import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from branch_panel import BranchPanel, BADGE_ROLE
from commit_info import read_commit_info
from commit_sidebar import render_basic, render_info
from git_reader import Commit, Repository, Worktree, read_repository
from test_commit_browser import git
from test_workspace import create_repo
from ui_helpers import application
from viewer import Window


class SidebarWorktreesTest(unittest.TestCase):
    def test_worktree_click_preserves_bottom_scroll(self):
        ids = [f'{i:040x}' for i in range(1, 24)]
        root = Path(tempfile.gettempdir())/'worktree-scroll'
        worktrees = [Worktree(str(root/f'checkout-{i:02}'), oid, detached=True) for i, oid in enumerate(ids)]
        repo = Repository(worktrees[0].path, {oid: Commit(oid, (), 'Tester', '', 'Commit') for oid in ids},
                          {}, branches_only=True, worktrees=worktrees, head_oid=ids[0])
        window = Window()
        window.resize(1600, 1000)
        try:
            with patch.object(window.details, 'show_commit'):
                window.repo = repo
                window.render()
                window.show()
                panel = window.branch_panel
                panel.tabs.setCurrentIndex(3)
                QTest.qWait(30)
                panel.parentWidget().setSizes([400, 400])
                QTest.qWait(30)
                for row in (21, 20, 21):
                    scrollbar = panel.list.verticalScrollBar()
                    scrollbar.setValue(scrollbar.maximum())
                    scroll = scrollbar.value()
                    item = next(panel.list.item(i) for i in range(panel.list.count())
                                if panel.list.item(i).text() == f'checkout-{row:02} — detached HEAD')
                    rect = panel.list.visualItemRect(item)
                    self.assertGreater(scroll, 0)
                    self.assertTrue(panel.list.viewport().rect().contains(rect))
                    QTest.mouseClick(panel.list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
                    QTest.qWait(30)
                    self.assertGreaterEqual(scrollbar.value(), scroll)
                    self.assertTrue(panel.list.viewport().rect().contains(panel.list.visualItemRect(item)))
                    self.assertTrue(window.nodes[ids[row]].isSelected())
        finally:
            window.close()
            application.processEvents()

    def test_badges_match_branch_refs_and_statuses(self):
        oid = '1'*40
        root = Path(tempfile.gettempdir())/'sidebar-worktrees'
        main = str(root/'main')
        linked = str(root/'linked')
        repo = Repository(main, {oid: Commit(oid, (), 'Tester', '', 'Commit')},
                          {oid: ['main', 'alias', 'feature', 'origin/main', 'gone']},
                          worktrees=[Worktree(main, oid, 'refs/heads/main', main=True),
                                     Worktree(linked, oid, 'refs/heads/feature', locked='in use'),
                                     Worktree(str(root/'gone'), oid, 'refs/heads/gone', prunable='missing directory'),
                                     Worktree(str(root/'empty'), '0'*40, 'refs/heads/empty')],
                          branch_refs={'origin/main': 'refs/remotes/origin/main'},
                          head_oid=oid, head_ref='refs/heads/main', tags={'release': oid})
        panel = BranchPanel()
        try:
            basic = render_basic(repo.commits[oid], repo.branches[oid], repo)
            self.assertIn('Checked out in 2 worktrees', basic)
            self.assertLess(basic.index(main), basic.index(linked))
            self.assertNotIn('missing directory', basic)
            panel.set_repository(repo)
            items = {panel.list.item(i).text(): panel.list.item(i) for i in range(panel.list.count())}
            self.assertEqual(items['main'].data(BADGE_ROLE), '[WT · here]')
            self.assertEqual(items['feature'].data(BADGE_ROLE), '[WT]')
            self.assertEqual(items['feature'].foreground().color().name(), '#c792ea')
            self.assertIn('Locked: in use', items['feature'].toolTip())
            self.assertIn(linked, items['feature'].toolTip())
            for name in ('alias', 'origin/main', 'gone', 'tag: release'):
                self.assertIsNone(items[name].data(BADGE_ROLE))
            panel.tabs.setCurrentIndex(3)
            visible = [item for item in items.values() if not item.isHidden()]
            self.assertEqual(len(visible), 4)
            self.assertEqual(visible[0].text(), 'main — main')
            unavailable = [item for item in visible if not item.flags() & Qt.ItemFlag.ItemIsEnabled]
            self.assertEqual(len(unavailable), 2)
            activations = []
            panel.branch_clicked.connect(lambda *args: activations.append(args))
            for item in unavailable:
                panel.activate(item)
            self.assertEqual(activations, [])
            panel.filter.setText(linked)
            self.assertEqual([item.text() for item in items.values() if not item.isHidden()], ['linked — feature'])
        finally:
            panel.close()

    def test_detached_worktree_navigation_and_prominent_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = create_repo(Path(directory)/'main')
            root = git(path, 'rev-parse', 'HEAD')
            git(path, 'branch', 'alias')
            linked = Path(directory)/'detached'
            git(path, 'worktree', 'add', '--detach', str(linked), root)
            git(linked, '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid',
                'commit', '--allow-empty', '-m', 'Detached worktree commit')
            detached = git(linked, 'rev-parse', 'HEAD')
            for options in ({'branches_only': True}, {}, {'all_branch_tips': True}, {'regular_history': True}):
                with self.subTest(options=options):
                    repo = read_repository(str(path), commit_limit=1, **options)
                    self.assertIn(detached, repo.commits)
                    window = Window()
                    try:
                        with patch.object(window.details, 'show_commit'):
                            window.repo = repo
                            window.render()
                            window.show()
                            QTest.qWait(30)
                            panel = window.branch_panel
                            panel.tabs.setCurrentIndex(3)
                            item = next(panel.list.item(i) for i in range(panel.list.count())
                                        if panel.list.item(i).text() == 'detached — detached HEAD')
                            panel.list.setCurrentItem(item)
                            rect = panel.list.visualItemRect(item)
                            QTest.mouseClick(panel.list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
                            QTest.qWait(30)
                            self.assertTrue(window.nodes[detached].isSelected())
                            self.assertTrue(panel.list.viewport().rect().contains(panel.list.visualItemRect(item)))
                            window.hidden_nodes.add(detached)
                            window.render()
                            panel.activate(item)
                            self.assertNotIn(detached, window.hidden_nodes)
                            self.assertTrue(window.nodes[detached].isSelected())
                    finally:
                        window.close()
                        application.processEvents()
            repo = read_repository(str(path))
            basic = render_basic(repo.commits[root], repo.branches[root], repo)
            self.assertLess(basic.index('Checked out in 1 worktree'), basic.index('Author:'))
            self.assertIn('[WT · here]', basic)
            html = render_info(read_commit_info(repo, root))
            self.assertLess(html.index('Checked out in 1 worktree'), html.index('References pointing here'))
            self.assertIn('[WT · here]', html.split('In worktree history')[0])
            self.assertNotIn('[WT]', html.split('In worktree history')[1])
            self.assertIn('detached', html.split('In worktree history')[1])
            html = render_info(read_commit_info(repo, detached))
            self.assertIn('Checked out in 1 worktree', html)
            self.assertIn('[WT]', html)
            self.assertNotIn('[WT · here]', html)

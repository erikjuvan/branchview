import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from branch_panel import BranchPanel
from git_reader import read_repository
from graph import build_graph
from viewer import Window
from test_workspace import create_repo
from test_commit_browser import git
from ui_helpers import application


class RefsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = create_repo(Path(self.temp.name)/'repo')
        self.root = git(self.path, 'rev-parse', 'HEAD')

    def commit(self, message):
        git(self.path, '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid',
            'commit', '--allow-empty', '-m', message)
        return git(self.path, 'rev-parse', 'HEAD')

    def visible(self, panel):
        return [panel.list.item(i) for i in range(panel.list.count()) if not panel.list.item(i).isHidden()]

    def test_tags_head_tabs_and_navigation_in_all_graph_modes(self):
        git(self.path, 'tag', 'light', self.root)
        git(self.path, '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid',
            'tag', '-a', 'release', '-m', 'Release', self.root)
        git(self.path, 'tag', 'tree-tag', 'HEAD^{tree}')
        self.commit('Branch tip')
        git(self.path, 'checkout', '--detach', self.root)
        head = self.commit('Detached tip')
        for options in ({'branches_only': True}, {}, {'all_branch_tips': True}, {'regular_history': True}):
            with self.subTest(options=options):
                repo = read_repository(str(self.path), commit_limit=1, **options)
                self.assertEqual(repo.head_oid, head)
                self.assertIsNone(repo.head_ref)
                self.assertEqual(repo.tags, {'light': self.root, 'release': self.root})
                graph = build_graph(repo)
                self.assertIn(head, graph.nodes)
                self.assertIn(self.root, graph.nodes)
                window = Window()
                try:
                    with patch.object(window.details, 'show_commit'):
                        window.repo = repo
                        window.render()
                        window.show()
                        QTest.qWait(30)
                        panel = window.branch_panel
                        self.assertEqual(panel.list.item(0).text(), 'HEAD (detached) · '+head[:8])
                        self.assertTrue(any(label.toPlainText() == 'HEAD (detached)' for label in window.labels))
                        self.assertTrue(any(label.toPlainText() == 'tag: release' for label in window.labels))
                        panel.tabs.setCurrentIndex(2)
                        self.assertEqual({item.text() for item in self.visible(panel)}, {'tag: light', 'tag: release'})
                        item = self.visible(panel)[0]
                        panel.activate(item)
                        self.assertTrue(window.nodes[self.root].isSelected())
                        panel.filter.setText('release')
                        self.assertEqual([item.text() for item in self.visible(panel)], ['tag: release'])
                        panel.filter.clear()
                        panel.tabs.setCurrentIndex(1)
                        self.assertEqual([item.text() for item in self.visible(panel)], ['main'])
                        panel.tabs.setCurrentIndex(0)
                        panel.activate(panel.list.item(0))
                        self.assertTrue(window.nodes[head].isSelected())
                finally:
                    window.close()
                    application.processEvents()

    def test_linked_worktree_head_is_the_opened_checkout(self):
        tip = self.commit('Main tip')
        linked = Path(self.temp.name)/'linked'
        git(self.path, 'worktree', 'add', '--detach', str(linked), self.root)
        main_repo = read_repository(str(self.path))
        linked_repo = read_repository(str(linked))
        self.assertEqual(main_repo.head_oid, tip)
        self.assertEqual(main_repo.head_ref, 'refs/heads/main')
        self.assertEqual(linked_repo.head_oid, self.root)
        self.assertIsNone(linked_repo.head_ref)
        window = Window()
        try:
            window.repo = main_repo
            window.render()
            branch = next(window.branch_panel.list.item(i) for i in range(window.branch_panel.list.count())
                          if window.branch_panel.list.item(i).text() == 'main [HEAD]')
            self.assertTrue(branch.font().bold())
            head_label = next(label for label in window.labels if label.toPlainText() == 'HEAD')
            self.assertEqual(head_label.parentItem().oid, tip)
            self.assertIn(str(self.path.resolve()), head_label.toolTip())
            git(self.path, 'checkout', '-b', 'alternative', self.root)
            window.repo = read_repository(str(self.path))
            window.render()
            self.assertEqual(window.branch_panel.list.item(0).text(), 'alternative [HEAD]')
            head_label = next(label for label in window.labels if label.toPlainText() == 'HEAD')
            self.assertEqual(head_label.parentItem().oid, self.root)
            branch = next(window.branch_panel.list.item(i) for i in range(window.branch_panel.list.count())
                          if window.branch_panel.list.item(i).text() == 'main')
            self.assertFalse(branch.font().bold())
        finally:
            window.close()

    def test_detached_head_without_branches_and_unborn_head(self):
        git(self.path, 'checkout', '--detach')
        git(self.path, 'branch', '-D', 'main')
        repo = read_repository(str(self.path), branches_only=True)
        self.assertEqual(repo.branches, {})
        self.assertEqual(build_graph(repo).nodes, {self.root})
        empty = Path(self.temp.name)/'empty'
        git(self.path, 'init', '-b', 'main', str(empty))
        repo = read_repository(str(empty))
        self.assertIsNone(repo.head_oid)
        self.assertEqual(repo.head_ref, 'refs/heads/main')
        self.assertEqual(build_graph(repo).nodes, set())
        panel = BranchPanel()
        self.addCleanup(panel.close)
        panel.set_repository(repo)
        self.assertEqual(panel.heading.text(), 'All refs (1)')
        self.assertEqual(panel.list.item(0).text(), 'HEAD → main (no commits yet)')
        self.assertFalse(panel.list.item(0).flags() & Qt.ItemFlag.ItemIsEnabled)
        activations = []
        panel.branch_clicked.connect(lambda *args: activations.append(args))
        panel.activate(panel.list.item(0))
        self.assertEqual(activations, [])

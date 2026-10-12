import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from viewer import Window
from branch_panel import BranchPanel
from git_reader import Commit, Repository
from test_workspace import create_repo
from test_commit_browser import git
from ui_helpers import application, wait_for_load


class BranchPanelTest(unittest.TestCase):
    def test_current_branch_is_pinned_once_and_keeps_branch_navigation(self):
        oid = '1'*40
        repo = Repository('synthetic', {}, {oid: ['alias', 'z-current', 'origin/z-current']},
                          branch_refs={'origin/z-current': 'refs/remotes/origin/z-current'},
                          head_oid=oid, head_ref='refs/heads/z-current', tags={'release': oid})
        panel = BranchPanel()
        self.addCleanup(panel.close)
        panel.set_repository(repo)
        current = panel.list.item(0)
        self.assertEqual(current.text(), 'z-current [HEAD]')
        self.assertEqual(current.data(Qt.ItemDataRole.UserRole+2), 'refs/heads/z-current')
        self.assertTrue(current.font().bold())
        self.assertEqual(current.foreground().color().name(), '#c792ea')
        self.assertEqual(panel.heading.text(), 'All refs (4)')
        activations = []
        panel.branch_clicked.connect(lambda *args: activations.append(args))
        panel.activate(current)
        self.assertEqual(activations, [('z-current', oid)])
        panel.list.setCurrentItem(current)
        panel.set_repository(replace(repo))
        self.assertEqual(panel.list.currentItem().text(), 'z-current [HEAD]')
        panel.tabs.setCurrentIndex(1)
        self.assertEqual(panel.heading.text(), 'Branches (3)')
        panel.filter.setText('HEAD')
        self.assertEqual([panel.list.item(i).text() for i in range(panel.list.count())
                          if not panel.list.item(i).isHidden()], ['z-current [HEAD]'])

    def test_detached_head_stays_separate_from_refs_at_the_same_commit(self):
        oid = '1'*40
        panel = BranchPanel()
        self.addCleanup(panel.close)
        panel.set_repository(Repository('synthetic', {}, {oid: ['main']}, head_oid=oid,
                                        tags={'release': oid}))
        self.assertEqual(panel.list.item(0).text(), 'HEAD (detached) · '+oid[:8])
        self.assertEqual(panel.heading.text(), 'All refs (3)')
        self.assertEqual(panel.list.item(1).text(), 'main')
        self.assertFalse(panel.list.item(1).font().bold())
        activations = []
        panel.branch_clicked.connect(lambda *args: activations.append(args))
        panel.activate(panel.list.item(0))
        self.assertEqual(activations, [('HEAD', oid)])
        panel.tabs.setCurrentIndex(1)
        self.assertTrue(panel.list.item(0).isHidden())

    def test_bottom_branch_click_keeps_viewport_during_shortcut_updates(self):
        for branches_only in (True, False):
            with self.subTest(branches_only=branches_only):
                self.check_bottom_branch_click(branches_only)

    def check_bottom_branch_click(self, branches_only):
        ids = [f'{i:040x}' for i in range(1, 24)]
        window = Window()
        window.resize(1600, 1000)
        window.repo = Repository('synthetic',
                                 {oid: Commit(oid, (ids[i-1],) if i else (), 'Tester', '', 'Commit')
                                  for i, oid in enumerate(ids)},
                                 {oid: [f'branch-{i:03}'] for i, oid in enumerate(ids)},
                                 branches_only=branches_only)
        try:
            with patch.object(window.details, 'show_commit'):
                window.render()
                window.show()
                QTest.qWait(30)
                panel = window.branch_panel
                panel.parentWidget().setSizes([400, 400])
                QTest.qWait(30)
                scrollbar = panel.list.verticalScrollBar()
                for row in (21, 20, 21):
                    scrollbar.setValue(scrollbar.maximum())
                    scroll = scrollbar.value()
                    item = panel.list.item(row)
                    rect = panel.list.visualItemRect(item)
                    self.assertGreater(scroll, 0)
                    self.assertTrue(panel.list.viewport().rect().contains(rect))
                    QTest.mouseClick(panel.list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
                    QTest.qWait(30)
                    self.assertGreaterEqual(scrollbar.value(), scroll)
                    self.assertTrue(panel.list.viewport().rect().contains(panel.list.visualItemRect(item)))
                    self.assertEqual(panel.list.currentItem(), item)
                    self.assertTrue(window.nodes[ids[row]].isSelected())
        finally:
            window.close()
            application.processEvents()

    def test_click_during_refresh_keeps_scrolled_branch_visible(self):
        repo = Repository('synthetic', {}, {'1'*40: [
            f'{prefix}-{i:03}' for prefix in ('aaa', 'topic') for i in range(100)]})
        for query in ('', 'topic'):
            with self.subTest(filter=query):
                panel = BranchPanel()
                panel.resize(350, 240)
                panel.set_repository(repo)
                panel.filter.setText(query)
                panel.branch_clicked.connect(lambda *_: panel.set_repository(replace(repo)))
                panel.show()
                try:
                    QTest.qWait(30)
                    scrollbar = panel.list.verticalScrollBar()
                    scrollbar.setValue(175 if not query else 75)
                    item = panel.list.item(179)
                    selected_name = item.text()
                    scroll = scrollbar.value()
                    rect = panel.list.visualItemRect(item)
                    self.assertGreater(scroll, 0)
                    self.assertTrue(panel.list.viewport().rect().contains(rect))
                    QTest.mouseClick(panel.list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
                    QTest.qWait(30)
                    self.assertEqual(scrollbar.value(), scroll)
                    self.assertEqual(panel.list.currentItem().text(), selected_name)
                    self.assertEqual(panel.filter.text(), query)
                    self.assertTrue(panel.list.viewport().rect().contains(
                        panel.list.visualItemRect(panel.list.currentItem())))
                finally:
                    panel.close()
                    application.processEvents()

    def test_remote_option_jump_reveals_collapsed_and_hidden_tip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = create_repo(Path(directory)/'repo')
            git(path, '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-m', 'Middle')
            middle = git(path, 'rev-parse', 'HEAD')
            git(path, 'branch', 'merged-old')
            git(path, '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-m', 'Tip')
            tip = git(path, 'rev-parse', 'HEAD')
            git(path, 'update-ref', 'refs/remotes/origin/main', tip)
            window = Window(str(path), presentation='terminal')
            window.show()
            try:
                wait_for_load(window)
                panel = window.branch_panel
                self.assertEqual({panel.list.item(i).text() for i in range(panel.list.count())
                                  if not panel.list.item(i).isHidden()}, {'main [HEAD]', 'merged-old'})
                self.assertNotIn(middle, window.nodes)
                item = next(panel.list.item(i) for i in range(panel.list.count()) if panel.list.item(i).text() == 'merged-old')
                panel.activate(item)
                self.assertTrue(window.nodes[middle].isSelected())
                self.assertLessEqual(window.view.transform().m11(), 1.5)
                bounds = window.nodes[middle].sceneBoundingRect()
                self.assertTrue(window.view.mapToScene(window.view.viewport().rect()).boundingRect().contains(bounds))
                window.hide_node(middle)
                panel.activate(item)
                self.assertNotIn(middle, window.hidden_nodes)
                self.assertTrue(window.nodes[middle].isSelected())
                window.remote.setChecked(True)
                wait_for_load(window)
                self.assertIn('origin/main', {panel.list.item(i).text() for i in range(panel.list.count())})
                panel.filter.setText('origin')
                self.assertEqual([panel.list.item(i).text() for i in range(panel.list.count()) if not panel.list.item(i).isHidden()], ['origin/main'])
                window.remote.setChecked(False)
                wait_for_load(window)
                panel.filter.clear()
                self.assertEqual(sum(not panel.list.item(i).isHidden() for i in range(panel.list.count())), 2)
            finally:
                window.close()
                application.processEvents()

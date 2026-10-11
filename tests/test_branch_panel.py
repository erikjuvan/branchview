import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from viewer import Window
from test_workspace import create_repo
from test_commit_browser import git
from ui_helpers import application, wait_for_load


class BranchPanelTest(unittest.TestCase):
    def test_remote_option_jump_reveals_collapsed_and_hidden_tip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = create_repo(Path(directory)/'repo')
            git(path, '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-m', 'Middle')
            middle = git(path, 'rev-parse', 'HEAD')
            git(path, 'branch', 'merged-old')
            git(path, '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-m', 'Tip')
            tip = git(path, 'rev-parse', 'HEAD')
            git(path, 'update-ref', 'refs/remotes/origin/main', tip)
            window = Window(str(path))
            window.show()
            try:
                wait_for_load(window)
                panel = window.branch_panel
                self.assertEqual({panel.list.item(i).text() for i in range(panel.list.count())}, {'main', 'merged-old'})
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
                self.assertEqual(panel.list.count(), 2)
            finally:
                window.close()
                application.processEvents()

import unittest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from git_reader import Commit, Repository
from search import search_commits
from viewer import Window
from ui_helpers import application


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.ids = [f'{i:040x}' for i in range(1, 5)]
        commits = {oid: Commit(oid, (self.ids[i-1],) if i else (), 'Tester', '',
                               'Draft search\n\nA special body' if i == 1 else f'Commit {i}')
                   for i, oid in enumerate(self.ids)}
        self.repo = Repository('synthetic', commits, {self.ids[-1]: ['Feature/Search', 'alias']})

    def test_hash_branch_full_message_and_result_limit(self):
        self.assertEqual(search_commits(self.repo, 'feature/SEARCH')[0], [self.ids[-1]])
        self.assertEqual(search_commits(self.repo, 'special body')[0], [self.ids[1]])
        self.assertEqual(search_commits(self.repo, self.ids[2])[0], [self.ids[2]])
        self.assertEqual(search_commits(self.repo, '')[0], [self.ids[-1]])
        self.assertEqual(search_commits(self.repo, 'missing'), ([], 0))
        self.assertEqual(search_commits(self.repo, 'Commit', limit=1)[1], 3)

    def test_shortcut_typing_and_jump_reveals_collapsed_hidden_commit(self):
        window = Window()
        self.addCleanup(window.close)
        window.repo = self.repo
        window.render()
        window.show()
        window.activateWindow()
        window.view.setFocus()
        self.app.processEvents()
        self.assertNotIn(self.ids[1], window.nodes)
        window.hidden_nodes.add(self.ids[1])
        QTest.keyClick(window.view, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        dialog = window.search_dialog
        self.assertTrue(dialog.isVisible())
        QTest.keyClicks(dialog.query, 'Draft search')
        self.assertEqual(dialog.query.text(), 'Draft search')
        QTest.keyClick(dialog.query, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertIn(self.ids[1], window.nodes)
        self.assertNotIn(self.ids[1], window.hidden_nodes)
        self.assertTrue(window.nodes[self.ids[1]].isSelected())
        self.assertFalse(dialog.isVisible())

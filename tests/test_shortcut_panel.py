import unittest
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from git_reader import Commit, Repository
from commit_info import CommitInfo
from viewer import Window
from ui_helpers import application


class ShortcutPanelTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or application
        self.window = Window()
        self.addCleanup(self.window.close)
        self.ids = [f'{i:040x}' for i in (1, 2, 3)]
        commits = {oid: Commit(oid, (self.ids[i-1],) if i else (), 'Tester', '', f'Commit {i}')
                   for i, oid in enumerate(self.ids)}
        repo = Repository('synthetic', commits, {self.ids[-1]: ['main']})
        self.window.repo = repo
        self.window.expanded.update(commits)
        self.window.render()
        self.window.details.reset_repository(repo)
        for oid, commit in commits.items():
            self.window.details.cache[oid] = CommitInfo(commit, '', 'Tester', '', '', '', [], ['main'], [], {}, [], [], [], '', [])

    def entries(self):
        return {key: action for key, action, _ in self.window.shortcuts_panel.entries}

    def test_context_changes_with_zero_one_two_and_many_selected_commits(self):
        window = self.window
        diff_key = window.diff_shortcut.key().toString(QKeySequence.SequenceFormat.NativeText)
        hide_key = window.hide_shortcut.key().toString(QKeySequence.SequenceFormat.NativeText)
        self.assertNotIn(diff_key, self.entries())
        self.assertNotIn(hide_key, self.entries())
        self.assertIn('Ctrl+click', self.entries())
        window.nodes[self.ids[0]].setSelected(True)
        self.assertIn('1 commit selected', window.shortcuts_panel.summary.text())
        self.assertIn('Diff selected commit', self.entries()[diff_key])
        self.assertIn(hide_key, self.entries())
        window.nodes[self.ids[1]].setSelected(True)
        self.assertIn('2 commits selected', window.shortcuts_panel.summary.text())
        self.assertIn('Compare', self.entries()[diff_key])
        window.nodes[self.ids[2]].setSelected(True)
        self.assertNotIn(diff_key, self.entries())
        self.assertIn(hide_key, self.entries())
        self.assertIn('one or two', window.shortcuts_panel.note.text())
        window.scene.clearSelection()
        self.assertNotIn(diff_key, self.entries())
        self.assertNotIn(hide_key, self.entries())

    def test_help_stays_fixed_when_commit_details_scroll_or_are_replaced(self):
        window = self.window
        window.show()
        window.nodes[self.ids[0]].setSelected(True)
        self.app.processEvents()
        panel = window.shortcuts_panel
        bounds, entries = panel.geometry(), list(panel.entries)
        window.details.setPlainText('Long commit details\n'*2000)
        self.app.processEvents()
        window.details.verticalScrollBar().setValue(window.details.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertEqual(panel.geometry(), bounds)
        self.assertEqual(panel.entries, entries)
        self.assertEqual(panel.geometry().top(), 0)
        self.assertGreaterEqual(window.details.geometry().top(), panel.geometry().bottom())
        window.details.show_commit(window.repo, self.ids[0])
        self.app.processEvents()
        self.assertEqual(panel.entries, entries)
        self.assertTrue(panel.isVisible())

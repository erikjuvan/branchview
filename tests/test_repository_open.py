import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu

from git_reader import Commit, Repository, Worktree
from repository_open import matching_worktrees, launch_checkout, RepositoryOpenPanel
from viewer import Window
from ui_helpers import application


class RepositoryOpenTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.main, self.linked = str(root/'main'), str(root/'linked')
        Path(self.main).mkdir()
        Path(self.linked).mkdir()
        self.ids = [str(i)*40 for i in (1, 2, 3)]
        self.trees = [Worktree(self.main, self.ids[2], 'refs/heads/main', main=True),
                      Worktree(self.linked, self.ids[1], 'refs/heads/feature')]
        self.repo = Repository(self.main,
                               {oid: Commit(oid, (self.ids[i-1],) if i else (), '', '', 'Commit')
                                for i, oid in enumerate(self.ids)},
                               {self.ids[2]: ['main'], self.ids[1]: ['feature']},
                               worktrees=self.trees, head_oid=self.ids[2], head_ref='refs/heads/main')

    def test_only_exact_checkouts_match(self):
        self.assertEqual(matching_worktrees(self.repo, {self.ids[1]}), [self.trees[1]])
        self.assertEqual(matching_worktrees(self.repo, {self.ids[0]}), [])
        self.assertEqual(matching_worktrees(self.repo, set()), [])
        self.assertEqual(matching_worktrees(self.repo, set(self.ids)), [])
        self.repo.worktrees += [Worktree('missing', self.ids[1], prunable='gone'),
                                Worktree('bare', self.ids[1], bare=True)]
        self.assertEqual(matching_worktrees(self.repo, {self.ids[1]}), [self.trees[1]])

    def test_buttons_target_current_repo_worktree_and_explicit_dropdown(self):
        panel = RepositoryOpenPanel()
        self.addCleanup(panel.close)
        self.assertFalse(panel.buttons['explorer'].isEnabled())
        with patch.object(panel, 'open_path') as opened:
            panel.set_context(self.repo, set())
            QTest.mouseClick(panel.buttons['explorer'], Qt.MouseButton.LeftButton)
            opened.assert_called_with('explorer', self.main)
            panel.set_context(self.repo, {self.ids[1]})
            self.assertIn('#c792ea', panel.buttons['vscode'].styleSheet())
            self.assertIn(self.linked, panel.buttons['vscode'].toolTip())
            panel.open_target('vscode')
            opened.assert_called_with('vscode', self.linked)
            panel.buttons['vscode'].menu().actions()[0].trigger()
            opened.assert_called_with('vscode', self.main)
            panel.set_context(self.repo, {self.ids[0]})
            self.assertEqual(panel.target.text(), 'Open repo: .')
            self.assertNotIn('#c792ea', panel.buttons['explorer'].styleSheet())
            panel.open_target('explorer')
            opened.assert_called_with('explorer', self.main)
            panel.set_context(self.repo, {self.ids[2]})
            self.assertEqual(panel.target.text(), 'Open repo: .')
            self.assertNotIn('#c792ea', panel.buttons['explorer'].styleSheet())
            other = self.linked+'/second'
            self.repo.worktrees.append(Worktree(other, self.ids[1], detached=True))
            panel.set_context(self.repo, {self.ids[1]})
            def choose_second():
                menu = panel.findChildren(QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly)[-1]
                menu.actions()[1].trigger()
                menu.close()
            QTimer.singleShot(0, choose_second)
            panel.open_target('explorer')
            opened.assert_called_with('explorer', other)
            self.repo.worktrees.pop()
            panel.set_context(self.repo, {self.ids[0]}, self.linked)
            panel.open_target('gitextensions')
            opened.assert_called_with('gitextensions', self.linked)
            panel.set_context(self.repo, set(self.ids))
            self.assertNotIn('#c792ea', panel.buttons['vscode'].styleSheet())

    def test_external_launch_arguments_and_missing_directory(self):
        with patch('repository_open.subprocess.Popen') as popen:
            launch_checkout('vscode', self.linked, 'Code.exe')
            self.assertEqual(popen.call_args.args[0], ['Code.exe', '--new-window', self.linked])
            launch_checkout('gitextensions', self.main, 'GitExtensions.exe')
            self.assertEqual(popen.call_args.args[0], ['GitExtensions.exe', 'browse', self.main])
        with patch('repository_open.QDesktopServices.openUrl', return_value=True) as open_url:
            launch_checkout('explorer', self.linked)
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), Path(self.linked).as_posix())
        with self.assertRaises(OSError):
            launch_checkout('explorer', self.main+'/missing')

    def test_graph_and_sidebar_selection_update_target(self):
        window = Window()
        self.addCleanup(window.close)
        with patch.object(window.details, 'show_commit'):
            window.repo = self.repo
            window.expanded.update(self.ids)
            window.render()
            window.nodes[self.ids[1]].setSelected(True)
            self.assertEqual(window.repository_open.matches, [self.trees[1]])
            window.scene.clearSelection()
            self.assertEqual(window.repository_open.matches, [])
            window.nodes[self.ids[0]].setSelected(True)
            self.assertEqual(window.repository_open.matches, [])
            self.assertEqual(window.repository_open.target.text(), 'Open repo: .')
            self.assertNotIn('#c792ea', window.repository_open.buttons['explorer'].styleSheet())
            window.branch_panel.tabs.setCurrentIndex(3)
            item = next(window.branch_panel.list.item(i) for i in range(window.branch_panel.list.count())
                        if window.branch_panel.list.item(i).data(Qt.ItemDataRole.UserRole+2) == 'worktree:'+self.linked)
            window.branch_panel.activate(item)
            self.assertEqual(window.repository_open.matches, [self.trees[1]])


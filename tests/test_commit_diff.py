import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QTextEdit

from git_reader import read_commit_diff, read_repository
from viewer import Window


class CommitDiffTest(unittest.TestCase):
    def test_divergent_commits_menu_and_direction(self):
        with tempfile.TemporaryDirectory() as path:
            def git(*args):
                return subprocess.check_output(
                    ['git', '-C', path, *args], text=True, stderr=subprocess.DEVNULL).strip()

            git('init', '-b', 'main')
            git('config', 'user.name', 'Tester')
            git('config', 'user.email', 'tester@example.invalid')
            file = Path(path) / 'example.txt'
            file.write_text('root\n')
            git('add', '.')
            git('commit', '-m', 'Root')
            root = git('rev-parse', 'HEAD')
            file.write_text('main\n')
            git('commit', '-am', 'Main change')
            main = git('rev-parse', 'HEAD')
            git('checkout', '-b', 'side', root)
            file.write_text('side\n')
            git('commit', '-am', 'Side change')
            side = git('rev-parse', 'HEAD')
            repo = read_repository(path)
            forward = read_commit_diff(repo, main, side)
            reverse = read_commit_diff(repo, side, main)
            self.assertIn('-main\n+side', forward)
            self.assertIn('-side\n+main', reverse)
            self.assertIn('example.txt |', forward)
            self.assertEqual(read_commit_diff(repo, main, main), 'No changes between these commits.')
            with self.assertRaises(ValueError):
                read_commit_diff(repo, 'invalid', side)

            app = QApplication.instance() or QApplication([])
            window = Window(path)
            self.addCleanup(window.close)
            self.assertEqual(len(window.node_menu(main).actions()), 1)
            window.nodes[main].setSelected(True)
            self.assertEqual(len(window.node_menu(main).actions()), 1)
            window.nodes[side].setSelected(True)
            menu = window.node_menu(main)
            action = next(a for a in menu.actions() if a.text() == 'Diff selected commits…')
            snapshots = []

            def inspect_dialog(dialog):
                text = dialog.findChild(QTextEdit)
                combo = dialog.findChild(QComboBox)
                snapshots.append((combo.currentData(), text.toPlainText()))
                combo.setCurrentIndex(1)
                snapshots.append((combo.currentData(), text.toPlainText()))
                return 0

            with patch.object(QDialog, 'exec', new=inspect_dialog):
                action.trigger()
                app.processEvents()
            self.assertEqual(len(snapshots), 2)
            for pair, text in snapshots:
                self.assertEqual(set(pair), {main, side})
                self.assertEqual(text, forward if pair == (main, side) else reverse)
            self.assertEqual(snapshots[0][0], tuple(reversed(snapshots[1][0])))
            self.assertEqual(len(window.scene.selectedItems()), 2)
            window.nodes[root].setSelected(True)
            self.assertEqual(len(window.node_menu(main).actions()), 1)

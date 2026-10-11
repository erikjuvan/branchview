import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog

from diff_viewer import DiffViewer, align_lines
from git_reader import Commit, Repository, ChangedFile, read_repository, read_changed_files, read_blob
from viewer import Window


class DiffViewerTest(unittest.TestCase):
    def test_submodule_and_line_limit_notices(self):
        app = QApplication.instance() or QApplication([])
        repo = Repository('synthetic', {'tip': Commit('tip', (), 'Tester', '', '')}, {'tip': ['main']})
        viewer = DiffViewer(repo)
        self.addCleanup(viewer.close)
        submodule = ChangedFile('M', 'module', 'module', '1'*40, '2'*40, '160000', '160000')
        with patch('diff_viewer.read_changed_files', return_value=[submodule]), patch('diff_viewer.read_blob') as blob:
            viewer.compare(None, 'tip')
            self.assertIn('Submodule', viewer.status.text())
            self.assertEqual(viewer.left.toPlainText(), '1'*40)
            self.assertEqual(viewer.right.toPlainText(), '2'*40)
            blob.assert_not_called()
        text = ChangedFile('M', 'large.txt', 'large.txt', '1'*40, '2'*40, '100644', '100644')
        with patch('diff_viewer.read_changed_files', return_value=[text]), patch('diff_viewer.read_blob', return_value=b'x\n'*20_001):
            viewer.compare(None, 'tip')
            self.assertIn('too many lines', viewer.status.text())
            self.assertEqual(viewer.left.toPlainText(), '')
            self.assertEqual(viewer.right.toPlainText(), '')

    def test_alignment_preserves_lines_and_newline_changes(self):
        rows = align_lines('one\nold\nthree\n', 'one\nnew\nextra\nthree\n')
        self.assertEqual([r.old_number for r in rows], [1, 2, None, 3])
        self.assertEqual([r.new_number for r in rows], [1, 2, 3, 4])
        self.assertEqual([r.changed for r in rows], [False, True, True, False])
        self.assertTrue(align_lines('same\n', 'same')[0].changed)
        self.assertEqual(align_lines('', ''), [])
        rows = align_lines('a\nb\nc\n', 'a\nc\n')
        self.assertIsNone(rows[1].new_number)
        self.assertEqual([r.old_text for r in rows if r.old_number is not None], ['a', 'b', 'c'])

    def test_real_files_rendering_root_and_scrolling(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as path:
            folder = Path(path)

            def git(*args):
                return subprocess.check_output(['git', '-C', path, *args], text=True,
                                               stderr=subprocess.DEVNULL).strip()

            def commit(message):
                git('add', '-A')
                git('commit', '-m', message)
                return git('rev-parse', 'HEAD')

            git('init', '-b', 'main')
            git('config', 'user.name', 'Tester')
            git('config', 'user.email', 'tester@example.invalid')
            original = ''.join(f'line {i}\n' for i in range(150))
            (folder/'edited.txt').write_text(original)
            (folder/'removed.txt').write_text('deleted\n')
            (folder/'old name.txt').write_text('renamed\n')
            root = commit('Initial files')
            changed = original.replace('line 5\n', 'changed\nextra\n')
            (folder/'edited.txt').write_text(changed)
            (folder/'removed.txt').unlink()
            git('mv', 'old name.txt', 'new ü name.txt')
            (folder/'added.txt').write_bytes(b'added without newline')
            (folder/'binary.bin').write_bytes(b'\x00\xff\x01')
            (folder/'empty.txt').write_bytes(b'')
            tip = commit('Changed files')
            repo = read_repository(path)
            changes = read_changed_files(repo, root, tip)
            by_path = {c.new_path: c for c in changes}
            self.assertEqual(by_path['removed.txt'].status, 'D')
            self.assertEqual(by_path['added.txt'].status, 'A')
            self.assertTrue(by_path['new ü name.txt'].status.startswith('R'))
            self.assertEqual(by_path['new ü name.txt'].old_path, 'old name.txt')
            self.assertEqual(read_blob(repo, by_path['added.txt'].old_blob), b'')
            with self.assertRaises(ValueError):
                read_blob(repo, by_path['edited.txt'].new_blob, limit=10)
            with self.assertRaises(ValueError):
                read_changed_files(repo, 'not-a-commit', tip)
            self.assertEqual(len(read_changed_files(repo, None, root)), 3)

            viewer = DiffViewer(repo)
            self.addCleanup(viewer.close)
            viewer.resize(1100, 500)
            viewer.show()
            viewer.compare(root, tip)
            app.processEvents()

            def select(path):
                index = next(i for i, c in enumerate(viewer.changes) if c.new_path == path)
                viewer.files.setCurrentRow(index)
                app.processEvents()

            select('edited.txt')
            self.assertEqual(viewer.left.numbers[6], None)
            self.assertEqual(viewer.right.numbers[6], 7)
            left_colors = viewer.left.extraSelections()
            right_colors = viewer.right.extraSelections()
            self.assertEqual(left_colors[0].format.background().color().name(), '#512d35')
            self.assertEqual(right_colors[0].format.background().color().name(), '#244b37')
            self.assertEqual(left_colors[1].format.background().color().name(), '#30343c')
            viewer.left.verticalScrollBar().setValue(50)
            self.assertEqual(viewer.right.verticalScrollBar().value(), 50)
            viewer.right.verticalScrollBar().setValue(80)
            self.assertEqual(viewer.left.verticalScrollBar().value(), 80)
            self.assertGreater(viewer.left.gutter.width(), 0)
            select('added.txt')
            self.assertEqual(viewer.left.numbers, [None])
            self.assertEqual(viewer.right.toPlainText(), 'added without newline')
            self.assertIn('no newline', viewer.status.text())
            select('removed.txt')
            self.assertEqual(viewer.left.toPlainText(), 'deleted')
            self.assertEqual(viewer.right.numbers, [None])
            select('binary.bin')
            self.assertIn('Binary', viewer.status.text())
            self.assertEqual(viewer.left.toPlainText(), '')
            self.assertEqual(viewer.right.toPlainText(), '')
            select('empty.txt')
            self.assertIn('+0', viewer.status.text())
            select('new ü name.txt')
            self.assertEqual(viewer.left.toPlainText(), 'renamed')
            self.assertEqual(viewer.right.toPlainText(), 'renamed')
            self.assertFalse(viewer.left.extraSelections())
            viewer.compare(tip, tip)
            self.assertEqual(viewer.files.count(), 0)
            self.assertIn('No changes', viewer.status.text())
            viewer.compare(root, tip)
            with patch('diff_viewer.read_blob', side_effect=RuntimeError('cannot read blob')):
                select('edited.txt')
            self.assertIn('cannot read blob', viewer.status.text())
            with patch('diff_viewer.read_changed_files', side_effect=subprocess.TimeoutExpired('git', 120)):
                viewer.compare(root, tip)
            self.assertIn('Cannot load comparison', viewer.status.text())
            self.assertEqual(viewer.files.count(), 0)

            window = Window(path)
            self.addCleanup(window.close)
            snapshots = []

            def inspect_dialog(dialog):
                diff = dialog.findChild(DiffViewer)
                snapshots.append((diff.source, diff.target, diff.files.count()))
                return 0

            with patch.object(QDialog, 'exec', new=inspect_dialog):
                window.show_diff(root)
                window.show_diff(tip)
            self.assertEqual(snapshots, [(None, root, 3), (root, tip, len(changes))])

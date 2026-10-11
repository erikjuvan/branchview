import subprocess
import tempfile
import unittest
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from commit_files import read_tree, preview_file
from commit_browser import CommitBrowser
from test_workspace import create_repo
from ui_helpers import application


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.DEVNULL).decode().strip()


def commit(path):
    git(path, 'add', '.')
    git(path, '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Files')
    return git(path, 'rev-parse', 'HEAD')


class CommitBrowserTest(unittest.TestCase):
    def test_historical_tree_preview_filter_and_pinned_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = create_repo(Path(directory)/'repo')
            (repo/'src').mkdir()
            (repo/'src'/'one.txt').write_text('old content\n', encoding='utf-8')
            (repo/'binary.dat').write_bytes(b'\0\1\2')
            oid = commit(repo)
            (repo/'src'/'one.txt').write_text('current content\n', encoding='utf-8')
            (repo/'untracked.txt').write_text('Untracked')
            files = read_tree(str(repo), oid)
            self.assertEqual({f.path for f in files}, {'src/one.txt', 'binary.dat'})
            entry = next(f for f in files if f.path.endswith('one.txt'))
            self.assertEqual(preview_file(str(repo), entry), 'old content\n')
            self.assertIn('Binary', preview_file(str(repo), files[0]))
            browser = CommitBrowser(str(repo), oid)
            browser.show()
            try:
                for _ in range(1000):
                    QTest.qWait(10)
                    if browser.tree_task.active is None:
                        break
                browser.filter.setText('one.txt')
                root = browser.tree.invisibleRootItem()
                src = next(root.child(i) for i in range(root.childCount()) if root.child(i).text(0) == 'src')
                browser.tree.setCurrentItem(src.child(0))
                for _ in range(1000):
                    QTest.qWait(10)
                    if browser.preview_task.active is None:
                        break
                self.assertEqual(browser.preview.toPlainText(), 'old content\n')
                self.assertEqual(browser.commit, oid)
                self.assertTrue(src.isExpanded())
                self.assertEqual((repo/'src'/'one.txt').read_text(), 'current content\n')
            finally:
                browser.close()
                application.processEvents()

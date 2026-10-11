import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from git_process import GitCancelled
from commit_files import read_tree
from commit_snapshot import export_snapshot, remove_snapshot, safe_file
from vscode_open import launch_vscode, SnapshotOpenDialog
from test_workspace import create_repo
from test_commit_browser import commit, git
from ui_helpers import application
from PySide6.QtTest import QTest


class SnapshotTest(unittest.TestCase):
    def test_exact_bytes_cache_preserves_edits_single_file_and_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = create_repo(root/'source')
            (repo/'.gitattributes').write_text('ignored.txt export-ignore\n*.dat -text\n')
            (repo/'ignored.txt').write_bytes(b'included despite export-ignore\n')
            raw = b'one\r\ntwo\0three\xff'+bytes(range(256))*9000
            (repo/'binary.dat').write_bytes(raw)
            oid = commit(repo)
            before = git(repo, 'status', '--porcelain')
            cache = root/'cache'
            snapshot = export_snapshot(str(repo), oid, cache_root=cache)
            self.assertEqual((snapshot.directory/'files'/'binary.dat').read_bytes(), raw)
            self.assertTrue((snapshot.directory/'files'/'ignored.txt').exists())
            self.assertFalse((snapshot.directory/'files'/'.git').exists())
            self.assertTrue(export_snapshot(str(repo), oid, cache_root=cache).reused)
            (snapshot.directory/'files'/'ignored.txt').write_text('Edited in editor')
            fresh = export_snapshot(str(repo), oid, cache_root=cache)
            self.assertNotEqual(snapshot.directory, fresh.directory)
            self.assertEqual((snapshot.directory/'files'/'ignored.txt').read_text(), 'Edited in editor')
            self.assertEqual((fresh.directory/'files'/'ignored.txt').read_bytes(), b'included despite export-ignore\n')
            entry = next(f for f in read_tree(str(repo), oid) if f.path == 'binary.dat')
            single = export_snapshot(str(repo), oid, entry=entry, cache_root=cache)
            self.assertEqual(single.file.read_bytes(), raw)
            self.assertEqual(len(list((single.directory/'files').iterdir())), 1)
            with patch('vscode_open.subprocess.Popen') as popen:
                launch_vscode('Code.exe', single)
            args = popen.call_args.args[0]
            self.assertEqual(args[:2], ['Code.exe', '--new-window'])
            self.assertEqual(args[-2:], ['--goto', str(single.file)])
            self.assertEqual(git(repo, 'status', '--porcelain'), before)
            remove_snapshot(single.directory, cache)
            self.assertFalse(single.directory.exists())
            with self.assertRaises(ValueError):
                remove_snapshot(repo, cache)

    def test_submodules_symlinks_lfs_and_cancellation_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = create_repo(root/'repo')
            (repo/'lfs.txt').write_bytes(b'version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 10\n')
            oid = commit(repo)
            # Write Git objects/index entries directly: no Windows symlink privilege needed.
            link = subprocess.check_output(['git', '-C', str(repo), 'hash-object', '-w', '--stdin'], input=b'../outside').decode().strip()
            git(repo, 'update-index', '--add', '--cacheinfo', f'120000,{link},link.txt')
            git(repo, 'update-index', '--add', '--cacheinfo', f'160000,{oid},submodule')
            git(repo, '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Links')
            oid = git(repo, 'rev-parse', 'HEAD')
            cache = root/'cache'
            snapshot = export_snapshot(str(repo), oid, cache_root=cache)
            self.assertEqual((snapshot.directory/'files'/'link.txt').read_bytes(), b'../outside')
            self.assertFalse((snapshot.directory/'files'/'link.txt').is_symlink())
            self.assertTrue((snapshot.directory/'files'/'submodule').is_dir())
            self.assertEqual(len(snapshot.notices), 3)
            event = Event()
            def progress(_):
                event.set()
            with self.assertRaises(GitCancelled):
                export_snapshot(str(repo), oid, event, progress, cache_root=root/'canceled')
            self.assertEqual(list((root/'canceled').rglob('.building-*')), [])
            self.assertEqual(list((root/'canceled').rglob('snapshot.json')), [])

    def test_unsafe_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ('../outside', '/absolute', '.git/config', '.GIT/config', 'folder/../../out', 'folder\\escape'):
                with self.assertRaises(ValueError):
                    safe_file(root, path)

    def test_export_ui_launches_and_cancels_without_touching_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = create_repo(root/'repo')
            oid = git(repo, 'rev-parse', 'HEAD')
            real_export = export_snapshot
            def export(*args, **kwargs):
                return real_export(*args, **kwargs, cache_root=root/'cache')
            with patch('vscode_open.find_vscode', return_value='Code.exe'), patch('vscode_open.export_snapshot', side_effect=export), patch('vscode_open.launch_vscode') as launch:
                dialog = SnapshotOpenDialog(str(repo), oid)
                dialog.show()
                for _ in range(1000):
                    QTest.qWait(10)
                    if launch.called:
                        break
                self.assertEqual(launch.call_count, 1)
                application.processEvents()

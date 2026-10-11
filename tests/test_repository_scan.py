import subprocess
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch, Mock
from types import SimpleNamespace
import os

from git_process import GitCancelled
from repository_scan import scan_repositories, RepositoryScanner, ScanResult
from workspace import WorkspaceWindow
from folder_open_dialog import FolderOpenDialog
from test_workspace import create_repo
from ui_helpers import application, wait_for_load
from PySide6.QtTest import QTest


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], stderr=subprocess.DEVNULL).decode().strip()


class RepositoryScanTest(unittest.TestCase):
    def test_depth_nested_repositories_empty_and_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            own = create_repo(root/'projects')
            immediate = create_repo(own/'one')
            nested = create_repo(immediate/'nested')
            deep = create_repo(own/'group'/'two')
            worktree = own/'linked'
            git(immediate, 'worktree', 'add', '-b', 'linked', str(worktree))
            shallow = scan_repositories(own)
            self.assertEqual(set(map(Path, shallow.repositories)), {own, immediate, worktree})
            full = scan_repositories(own, recursive=True)
            self.assertEqual(set(map(Path, full.repositories)), {own, immediate, nested, deep, worktree})
            self.assertEqual(full.errors, [])
            ordinary = own/'ordinary'
            ordinary.mkdir()
            self.assertEqual(scan_repositories(ordinary).repositories, [])

    def test_modern_old_form_and_uninitialized_submodules_are_pruned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = create_repo(root/'source')
            parent = create_repo(root/'projects'/'parent')
            git(parent, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(source), 'modern')
            modern = parent/'modern'
            create_repo(modern/'independent-inside-submodule')
            legacy = create_repo(parent/'legacy')
            oid = git(legacy, 'rev-parse', 'HEAD')
            git(parent, 'update-index', '--add', '--cacheinfo', f'160000,{oid},legacy')
            uninitialized = parent/'not-initialized'
            create_repo(uninitialized/'hidden')
            git(parent, 'update-index', '--add', '--cacheinfo', f'160000,{oid},not-initialized')
            independent = create_repo(parent/'independent')
            full = scan_repositories(root/'projects', recursive=True)
            self.assertEqual(set(map(Path, full.repositories)), {parent, independent})
            self.assertEqual(full.submodules, 3)
            self.assertEqual(full.errors, [])
            for excluded in (modern, legacy, legacy/'inside', uninitialized):
                excluded.mkdir(exist_ok=True)
                self.assertEqual(scan_repositories(excluded, recursive=True).repositories, [])

    def test_cancel_and_invalid_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = Event()
            event.set()
            with self.assertRaises(GitCancelled):
                scan_repositories(root, cancelled=event)
            (root/'.git').mkdir()
            result = scan_repositories(root)
            self.assertFalse(result.repositories)
            self.assertEqual(len(result.errors), 1)

    def test_bare_repository_and_git_metadata_pruning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = create_repo(root/'checkout')
            create_repo(checkout/'.git'/'should-not-open')
            bare = root/'archive.git'
            subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
            create_repo(bare/'objects'/'should-not-open')
            result = scan_repositories(root, recursive=True)
            self.assertEqual(set(map(Path, result.repositories)), {checkout, bare})

    def test_directory_reparse_points_are_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = create_repo(root/'good')
            create_repo(root/'junction')
            original_scandir = os.scandir

            class Entries:
                def __init__(self, path):
                    self.iterator = original_scandir(path)
                def __enter__(self):
                    entries = []
                    for entry in self.iterator:
                        if entry.name == 'junction':
                            substitute = Mock(wraps=entry)
                            substitute.name = entry.name
                            substitute.stat.return_value = SimpleNamespace(st_file_attributes=0x400)
                            entries.append(substitute)
                        else:
                            entries.append(entry)
                    return entries
                def __exit__(self, *_):
                    self.iterator.close()

            with patch('repository_scan.os.scandir', Entries):
                result = scan_repositories(root, recursive=True)
            self.assertEqual(list(map(Path, result.repositories)), [good])

    def test_scanner_cancellation_ignores_late_results(self):
        scanner = RepositoryScanner()
        received = []
        scanner.ready.connect(received.append)
        with tempfile.TemporaryDirectory() as directory:
            scanner.start(directory)
            scanner.cancel()
            for _ in range(100):
                QTest.qWait(10)
                if not scanner.jobs:
                    break
        self.assertFalse(received)
        self.assertFalse(scanner.jobs)

    def test_batch_open_and_repeat_preserve_tabs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = create_repo(root/'a')
            b = create_repo(root/'b')
            window = WorkspaceWindow()
            window.show()
            try:
                dialog = FolderOpenDialog(window)
                self.assertFalse(dialog.recursive.isChecked())
                window.open_folder(root)
                for _ in range(1500):
                    QTest.qWait(10)
                    if not window.cancel_scan_action.isEnabled():
                        break
                self.assertEqual(window.tabs.count(), 2)
                self.assertFalse(window.batch_pending)
                self.assertTrue(all(window.tabs.widget(i).repo for i in range(2)))
                page = window.tabs.widget(0)
                page.view.scale(2, 2)
                camera = page.view.transform()
                window.open_folder(root)
                for _ in range(1000):
                    QTest.qWait(10)
                    if not window.cancel_scan_action.isEnabled():
                        break
                self.assertEqual(window.tabs.count(), 2)
                self.assertEqual(page.view.transform(), camera)
                window.open_folder(root)
                window.cancel_batch()
                QTest.qWait(100)
                self.assertEqual(window.tabs.count(), 2)
                self.assertFalse(window.cancel_scan_action.isEnabled())
            finally:
                window.close()
                application.processEvents()

    def test_one_batch_error_summary_and_individual_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = create_repo(root/'good')
            missing = root/'missing'
            window = WorkspaceWindow()
            try:
                with patch('workspace.QMessageBox.warning') as warning:
                    window.scan_finished(ScanResult([str(good), str(missing)]))
                    for _ in range(1000):
                        QTest.qWait(10)
                        if not window.batch_pending and not window.batch_queue:
                            break
                    self.assertEqual(warning.call_count, 1)
                    self.assertIsNotNone(window.tabs.widget(0).repo)
                    self.assertIn('missing', warning.call_args.args[2])
                window.scan_finished(ScanResult([str(create_repo(root/'cancel'))]))
                page = window.tabs.widget(window.tabs.count()-1)
                with patch('workspace.QMessageBox.warning'):
                    page.cancel_load()
                self.assertFalse(window.batch_pending)
            finally:
                window.close()
                application.processEvents()

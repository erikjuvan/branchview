import subprocess
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtCore import QObject, QPoint
from shiboken6 import delete

from background_task import BackgroundTask
from repository_status import RepositoryStatus, parse_status, read_repository_status
from repository_status_panel import RepositoryStatusPanel
from workspace import WorkspaceWindow
from ui_helpers import application, wait_for_load


class RepositoryStatusLayoutTest(unittest.TestCase):
    def test_refresh_notice_does_not_move_sidebar_content(self):
        from viewer import Window

        window = Window()
        self.addCleanup(window.close)
        panel = window.repository_status
        status = RepositoryStatus(branch='main')
        with patch.object(panel.timer, 'start'):
            panel.refresh(str(Path.cwd()))
            panel.received(status)
            window.show()
            application.processEvents()
            bounds = panel.geometry()
            branch_position = window.branch_panel.mapTo(window.sidebar, QPoint())

            for _ in range(3):
                panel.refresh(str(Path.cwd()))
                application.processEvents()
                self.assertTrue(panel.notice.isVisible())
                self.assertEqual(panel.notice.text(), 'Refreshing…')
                self.assertEqual(panel.geometry(), bounds)
                self.assertEqual(window.branch_panel.mapTo(window.sidebar, QPoint()), branch_position)
                self.assertEqual(panel.notice.geometry().center().y(), panel.heading.geometry().center().y())
                self.assertGreater(panel.notice.geometry().left(), panel.heading.geometry().right())
                panel.received(status)
                application.processEvents()
                self.assertFalse(panel.notice.isVisible())
                self.assertEqual(panel.geometry(), bounds)
                self.assertEqual(window.branch_panel.mapTo(window.sidebar, QPoint()), branch_position)


class RepositoryStatusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'repo'
        self.path.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Tester')
        self.git('config', 'user.email', 'tester@example.invalid')

    def git(self, *args, path=None, check=True):
        return subprocess.run(['git', '-C', str(path or self.path), *args],
                              capture_output=True, check=check).stdout.decode().strip()

    def commit(self, message='Root'):
        self.git('add', '.')
        self.git('commit', '--allow-empty', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def wait_until(self, predicate):
        for _ in range(600):
            if predicate():
                return
            QTest.qWait(10)
        self.fail('Status did not complete')

    def test_unborn_counts_and_rename_paths(self):
        status = read_repository_status(str(self.path))
        self.assertEqual(status.branch, 'main')
        self.assertTrue(status.unborn)
        tracked = self.path / 'file with spaces.txt'
        tracked.write_text('initial\n')
        self.commit()
        tracked.write_text('staged\n')
        self.git('add', '.')
        tracked.write_text('unstaged\n')
        nested = self.path / 'new folder'
        nested.mkdir()
        (nested / 'one').write_text('one')
        (nested / 'two').write_text('two')
        status = read_repository_status(str(self.path))
        self.assertEqual((status.staged, status.unstaged, status.untracked), (1, 1, 2))
        self.commit('Edits')
        self.git('mv', tracked.name, 'renamed file.txt')
        status = read_repository_status(str(self.path))
        self.assertEqual((status.staged, status.unstaged, status.untracked), (1, 0, 0))

    def test_parser_skips_rename_source_and_handles_newlines(self):
        output = (b'# branch.head main\0# branch.oid abc\0'
                  b'2 R. N... 100644 100644 100644 a b R100 new\nname\0? source\0'
                  b'? actual\nfile\0u UU N... modes hashes path\0')
        status = parse_status(output)
        self.assertEqual((status.staged, status.untracked, status.conflicts), (1, 1, 1))

    def test_upstream_divergence_and_missing_upstream(self):
        self.commit()
        self.git('branch', 'upstream')
        self.git('branch', '--set-upstream-to=upstream')
        status = read_repository_status(str(self.path))
        self.assertEqual((status.upstream, status.ahead, status.behind), ('upstream', 0, 0))
        self.commit('Ahead')
        status = read_repository_status(str(self.path))
        self.assertEqual((status.ahead, status.behind), (1, 0))
        self.git('checkout', 'upstream')
        (self.path / 'other').write_text('other')
        self.commit('Behind')
        self.git('checkout', 'main')
        status = read_repository_status(str(self.path))
        self.assertEqual((status.ahead, status.behind), (1, 1))
        self.git('branch', '-D', 'upstream')
        status = read_repository_status(str(self.path))
        self.assertEqual(status.upstream, 'upstream')
        self.assertIsNone(status.ahead)
        self.assertIsNone(status.behind)

    def test_linked_detached_and_operation_metadata(self):
        oid = self.commit()
        linked = Path(self.temp.name) / 'linked tree'
        self.git('worktree', 'add', '--detach', str(linked))
        status = read_repository_status(str(linked))
        self.assertIsNone(status.branch)
        self.assertEqual(status.oid, oid)
        marker = Path(self.git('rev-parse', '--path-format=absolute', '--git-path', 'rebase-merge', path=linked))
        marker.mkdir()
        self.assertEqual(read_repository_status(str(linked)).operation, 'Rebase in progress')
        self.assertIsNone(read_repository_status(str(self.path)).operation)

    def test_real_merge_conflict(self):
        file = self.path / 'conflict.txt'
        file.write_text('base\n')
        self.commit()
        self.git('checkout', '-b', 'feature')
        file.write_text('feature\n')
        self.commit('Feature')
        self.git('checkout', 'main')
        file.write_text('main\n')
        self.commit('Main')
        self.git('merge', 'feature', check=False)
        status = read_repository_status(str(self.path))
        self.assertEqual(status.conflicts, 1)
        self.assertEqual((status.staged, status.unstaged), (0, 0))
        self.assertEqual(status.operation, 'Merge in progress')

    def test_bare_repository(self):
        bare = Path(self.temp.name) / 'bare'
        self.git('init', '--bare', str(bare))
        self.assertTrue(read_repository_status(str(bare)).bare)

    def test_panel_latest_request_and_error_retains_summary(self):
        panel = RepositoryStatusPanel()
        gate, started = Event(), Event()
        try:
            def reader(path, cancelled):
                name = Path(path).name
                if name == 'slow':
                    started.set()
                    gate.wait(4)
                return RepositoryStatus(branch=name)
            with patch('repository_status_panel.read_repository_status', side_effect=reader):
                panel.refresh('slow')
                self.wait_until(started.is_set)
                panel.refresh('new')
                self.wait_until(lambda: panel.summary is not None)
                self.assertEqual(panel.summary.branch, 'new')
                gate.set()
                self.wait_until(lambda: not panel.task.jobs)
                self.assertEqual(panel.summary.branch, 'new')
            with patch('repository_status_panel.read_repository_status', side_effect=RuntimeError('Unavailable')):
                panel.refresh('new')
                self.wait_until(lambda: 'Status unavailable' in panel.notice.text())
                self.assertEqual(panel.branch.text(), 'new')
                self.assertIn('Previous status shown', panel.notice.text())
        finally:
            gate.set()
            panel.shutdown()
            panel.close()

    def test_destroyed_owner_cancels_background_read(self):
        owner = QObject()
        task = BackgroundTask(owner)
        started, stopped = Event(), Event()
        flags = []
        def operation(cancelled, progress):
            flags.append(cancelled)
            started.set()
            cancelled.wait(3)
            stopped.set()
        task.start(operation)
        self.wait_until(started.is_set)
        delete(owner)
        self.assertTrue(flags[0].is_set())
        self.wait_until(stopped.is_set)

    def test_tab_return_refreshes_status_without_reloading_graph(self):
        self.commit()
        second = Path(self.temp.name) / 'second'
        self.git('worktree', 'add', '-b', 'second', str(second))
        window = WorkspaceWindow()
        try:
            first_page = window.open_repository(self.path)
            wait_for_load(first_page)
            self.wait_until(lambda: first_page.repository_status.summary is not None)
            second_page = window.open_repository(second)
            wait_for_load(second_page)
            (self.path / 'untracked').write_text('new')
            repo = first_page.repo
            window.tabs.setCurrentWidget(first_page)
            self.wait_until(lambda: first_page.repository_status.summary is not None
                            and first_page.repository_status.summary.untracked == 1)
            self.assertIs(first_page.repo, repo)
            self.assertIsNot(first_page.repository_status, second_page.repository_status)
        finally:
            window.close()

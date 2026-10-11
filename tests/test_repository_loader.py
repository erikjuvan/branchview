import unittest
from threading import Event, get_ident
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from git_reader import Commit, Repository
from graph import build_graph
from viewer import Window
from ui_helpers import wait_for_load


class RepositoryLoaderTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate):
        for _ in range(500):
            if predicate():
                return
            QTest.qWait(10)
        self.fail('Background job did not complete')

    def repo(self, path):
        oid = 'a'*40
        return Repository(path, {oid: Commit(oid, (), 'Tester', '', 'Root')}, {oid: ['main']})

    def test_responsive_cancel_and_latest_request_wins(self):
        window = Window()
        self.addCleanup(window.close)
        old = self.repo('old')
        window.repo = old
        window.loaded_options = {'remote': False, 'branches_only': False}
        window.render()
        gate, started, tick = Event(), Event(), Event()
        self.addCleanup(gate.set)
        gui = get_ident()
        threads = []

        def reader(path, **options):
            threads.append(get_ident())
            if path == 'slow':
                started.set()
                gate.wait(3)
            return self.repo(path)

        graph_threads = []
        def prepare(repo, **options):
            graph_threads.append(get_ident())
            return build_graph(repo, **options)

        with patch('repository_loader.read_repository', side_effect=reader), patch('repository_loader.build_graph', side_effect=prepare):
            window.load('slow')
            QTimer.singleShot(0, tick.set)
            self.wait_until(lambda: started.is_set() and tick.is_set())
            self.assertTrue(window.loading)
            self.assertIs(window.repo, old)
            self.assertTrue(window.cancel_action.isEnabled())
            window.cancel_action.trigger()
            self.assertFalse(window.loading)
            self.assertIs(window.repo, old)
            window.load('new')
            wait_for_load(window)
            self.assertEqual(window.repo.path, 'new')
            gate.set()
            self.wait_until(lambda: not window.loader.jobs)
            self.assertEqual(window.repo.path, 'new')
            self.assertTrue(all(thread != gui for thread in threads+graph_threads))
            self.assertFalse(window.cancel_action.isEnabled())

    def test_failure_keeps_existing_repository_and_restores_options(self):
        window = Window()
        self.addCleanup(window.close)
        old = self.repo('old')
        window.repo = old
        window.loaded_options = {'remote': False, 'branches_only': False}
        window.render()
        window.branches_only.blockSignals(True)
        window.branches_only.setChecked(True)
        window.branches_only.blockSignals(False)
        with patch('repository_loader.read_repository', side_effect=RuntimeError('Cannot read repository')), patch('viewer.QMessageBox.warning') as warning:
            window.load('bad')
            wait_for_load(window)
            warning.assert_called_once()
        self.assertIs(window.repo, old)
        self.assertFalse(window.branches_only.isChecked())
        self.assertFalse(window.cancel_action.isEnabled())

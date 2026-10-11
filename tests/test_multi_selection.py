import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from git_reader import Commit, Repository, Worktree
from commit_info import CommitInfo
from commit_sidebar import render_selection
from viewer import Window


class MultiSelectionTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.ids = [f'{i:040x}' for i in (1, 2, 3)]
        commits = {oid: Commit(oid, (self.ids[i-1],) if i else (), 'Tester', '2026-01-01', name)
                   for i, (oid, name) in enumerate(zip(self.ids, ['Root', '<b>Middle</b>', 'Tip']))}
        self.repo = Repository('/repo', commits, {self.ids[1]: ['feature'], self.ids[2]: ['main']},
                               worktrees=[Worktree('/repo', self.ids[2], 'refs/heads/main', main=True),
                                          Worktree('/linked tree', self.ids[1], 'refs/heads/feature')])

    def wait_until(self, predicate):
        for _ in range(500):
            if predicate():
                return
            QTest.qWait(10)
        self.fail('Background query did not complete')

    def info(self, oid):
        return CommitInfo(self.repo.commits[oid], '', 'Tester', '', '', '', [], ['main'], [], {}, [], [], [], '', [])

    def test_summary_includes_all_commits_worktrees_and_cached_shared_branches(self):
        cache = {oid: SimpleNamespace(branches=['main', 'feature'] if oid == self.ids[1] else ['main'])
                 for oid in self.ids[1:]}
        html = render_selection(self.repo, set(self.ids[1:]), cache)
        self.assertIn('2 commits selected', html)
        self.assertIn('&lt;b&gt;Middle&lt;/b&gt;', html)
        self.assertNotIn('<b>Middle</b>', html)
        self.assertIn('HEAD is selected', html)
        self.assertIn('1 selected ancestor in loaded history', html)
        self.assertIn('/linked tree', html)
        self.assertIn('Shared containing branches (cached)', html)
        self.assertIn('compare:', html)
        three = render_selection(self.repo, set(self.ids), {})
        self.assertIn('3 commits selected', three)
        self.assertNotIn('href="compare:', three)

    def test_stale_single_query_cannot_overwrite_multi_summary_and_links_work(self):
        window = Window()
        self.addCleanup(window.close)
        window.repo = self.repo
        window.expanded.update(self.ids)
        window.render()
        gate, started = Event(), Event()
        self.addCleanup(gate.set)

        def query(repo, oid, cancelled):
            if oid == self.ids[2]:
                started.set()
                gate.wait(3)
            return self.info(oid)

        with patch('commit_sidebar.read_commit_info', side_effect=query):
            window.nodes[self.ids[2]].setSelected(True)
            self.wait_until(started.is_set)
            window.nodes[self.ids[1]].setSelected(True)
            self.assertIn('2 commits selected', window.details.toPlainText())
            self.assertIn('<b>Middle</b>', window.details.toPlainText())
            self.assertIn('Tip', window.details.toPlainText())
            self.assertIsNone(window.details.active_oid)
            gate.set()
            self.wait_until(lambda: not window.details.jobs)
            self.assertIn('2 commits selected', window.details.toPlainText())
            with patch.object(window, 'show_commit_diff') as diff:
                window.open_detail_link(QUrl('compare:'+self.ids[2]+'/'+self.ids[1]))
                diff.assert_called_once_with(self.ids[2], self.ids[1])
            window.nodes[self.ids[0]].setSelected(True)
            self.assertIn('3 commits selected', window.details.toPlainText())
            window.open_detail_link(QUrl('commit:'+self.ids[1]))
            self.wait_until(lambda: self.ids[1] in window.details.cache)
            self.assertEqual(window.details.active_oid, self.ids[1])
            self.assertNotIn('commits selected', window.details.toPlainText())
            self.assertEqual(len(window.scene.selectedItems()), 1)

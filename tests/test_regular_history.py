import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from graph import build_graph, hide_nodes
from layout import regular_layout
from git_reader import read_repository
from viewer import Window
from test_workspace import create_repo
from test_commit_browser import git
from ui_helpers import application, wait_for_load


class RegularHistoryTest(unittest.TestCase):
    def test_date_order_rows_merge_lanes_default_and_mode_switching(self):
        with tempfile.TemporaryDirectory() as directory:
            path = create_repo(Path(directory)/'repo')
            root = git(path, 'rev-parse', 'HEAD')
            def commit(day, message, *args):
                env = {**os.environ, 'GIT_COMMITTER_DATE': f'2020-01-{day:02d}T12:00:00+00:00',
                       'GIT_AUTHOR_DATE': f'2020-01-{day:02d}T12:00:00+00:00'}
                subprocess.run(['git', '-C', str(path), '-c', 'user.name=Tester', '-c', 'user.email=test@example.invalid',
                                *(args or ('commit', '--allow-empty')), '-m', message], check=True, capture_output=True, env=env)
                return git(path, 'rev-parse', 'HEAD')
            old = commit(2, 'Old main commit')
            git(path, 'branch', 'old-main')
            git(path, 'checkout', '-b', 'side', root)
            commit(3, 'Side one')
            side = commit(4, 'Side two')
            git(path, 'checkout', 'main')
            commit(5, 'Main change')
            merge = commit(6, 'Merge side', 'merge', '--no-ff', 'side')
            repo = read_repository(str(path), regular_history=True)
            graph = build_graph(repo)
            expected = git(path, 'log', '--date-order', '--format=%H', '--branches').splitlines()
            self.assertEqual(graph.order, expected)
            positions = regular_layout(graph)
            self.assertEqual(len({y for x, y in positions.values()}), len(repo.commits))
            self.assertEqual([positions[oid][1] for oid in graph.order], list(range(0, len(graph.order)*40, 40)))
            self.assertTrue(all(positions[edge.child][1] < positions[edge.parent][1] for edge in graph.edges))
            self.assertTrue(all(not edge.hidden for edge in graph.edges))
            self.assertGreater(len({x for x, y in positions.values()}), 1)
            hidden = hide_nodes(graph, {old})
            self.assertNotIn(old, hidden.order)
            self.assertEqual(len(regular_layout(hidden)), len(repo.commits)-1)
            window = Window(str(path))
            window.show()
            try:
                wait_for_load(window)
                self.assertEqual(window.presentation.currentData(), 'regular')
                self.assertTrue(window.repo.regular_history)
                self.assertEqual(len(window.nodes), len(repo.commits))
                self.assertEqual(len({node.y() for node in window.nodes.values()}), len(repo.commits))
                self.assertTrue(any(label.toPlainText() == 'old-main' for label in window.labels))
                for mode in ('terminal', 'all', 'regular'):
                    window.presentation.setCurrentIndex(window.presentation.findData(mode))
                    wait_for_load(window)
                    self.assertEqual(window.repo.regular_history, mode == 'regular')
                    self.assertEqual(window.repo.all_branch_tips, mode == 'all')
                    if mode == 'all':
                        self.assertTrue(all(node.y() == 0 for node in window.nodes.values() if node.tip))
                window.hide_node(old)
                self.assertNotIn(old, window.nodes)
                self.assertEqual(len({node.y() for node in window.nodes.values()}), len(repo.commits)-1)
                window.show_hidden_nodes()
                self.assertIn(old, window.nodes)
            finally:
                window.close()
                application.processEvents()

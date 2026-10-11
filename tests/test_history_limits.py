import subprocess
import tempfile
import unittest
from PySide6.QtWidgets import QApplication

from git_reader import read_repository
from graph import build_graph
from viewer import Window
from ui_helpers import wait_for_load


class HistoryLimitTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = self.folder.name
        def git(*args):
            return subprocess.check_output(['git', '-C', self.path, *args], text=True,
                                           stderr=subprocess.DEVNULL).strip()
        self.git = git
        git('init', '-b', 'main')
        git('config', 'user.name', 'Tester')
        git('config', 'user.email', 'tester@example.invalid')
        self.ids = []
        for i in range(12):
            git('commit', '--allow-empty', '-m', f'Commit {i}')
            self.ids.append(git('rev-parse', 'HEAD'))
        git('branch', 'old', self.ids[0])

    def test_budget_retains_old_branch_tips_and_real_boundary_parents(self):
        repo = read_repository(self.path, commit_limit=3)
        self.assertEqual(set(repo.commits), {self.ids[0], *self.ids[-3:]})
        self.assertEqual(repo.commits[self.ids[-3]].parents, (self.ids[-4],))
        self.assertTrue(repo.history_limited)
        self.assertEqual(repo.commit_limit, 3)
        graph = build_graph(repo)
        self.assertIn(self.ids[-3], graph.nodes)
        self.assertIn(self.ids[0], graph.nodes)
        full = read_repository(self.path)
        self.assertFalse(full.history_limited)
        self.assertEqual(len(full.commits), 12)
        tips = read_repository(self.path, branches_only=True, commit_limit=1)
        self.assertEqual(set(tips.commits), {self.ids[0], self.ids[-1]})
        self.assertFalse(tips.history_limited)
        with self.assertRaises(ValueError):
            read_repository(self.path, commit_limit=0)

    def test_load_more_preserves_view_selection_expansion_and_positions(self):
        window = Window(self.path, history_limit=3)
        self.addCleanup(window.close)
        wait_for_load(window)
        window.show()
        self.app.processEvents()
        self.assertTrue(window.more_action.isEnabled())
        self.assertTrue(any(label.toPlainText() == 'Earlier history not loaded' for label in window.labels))
        self.assertIn('History limited', window.statusBar().currentMessage())
        window.expanded.add(self.ids[-2])
        window.render()
        window.nodes[self.ids[-1]].setPos(654, 370)
        window.nodes[self.ids[-1]].setSelected(True)
        window.view.scale(1.4, 1.4)
        window.view.centerOn(window.nodes[self.ids[-1]])
        transform = window.view.transform()
        center = window.view.mapToScene(window.view.viewport().rect().center())
        window.more_action.trigger()
        wait_for_load(window)
        self.assertEqual(len(window.repo.commits), 12)
        self.assertFalse(window.repo.history_limited)
        self.assertFalse(window.more_action.isEnabled())
        self.assertEqual(window.view.transform(), transform)
        new_center = window.view.mapToScene(window.view.viewport().rect().center())
        self.assertLess(abs(new_center.x()-center.x()), 3/transform.m11())
        self.assertLess(abs(new_center.y()-center.y()), 3/transform.m11())
        self.assertTrue(window.nodes[self.ids[-1]].isSelected())
        self.assertIn(self.ids[-2], window.expanded)
        self.assertEqual(window.nodes[self.ids[-1]].pos().x(), 654)
        self.assertFalse(any(label.toPlainText() == 'Earlier history not loaded' for label in window.labels))
        window.history_limit.setCurrentIndex(window.history_limit.findData(None))
        wait_for_load(window)
        self.assertIsNone(window.repo.commit_limit)
        window.branches_only.setChecked(True)
        wait_for_load(window)
        self.assertFalse(window.history_limit.isEnabled())
        self.assertFalse(window.more_action.isEnabled())

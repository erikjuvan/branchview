import subprocess
import tempfile
import unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication

from git_reader import read_repository, parse_worktrees
from commit_info import read_commit_info
from commit_sidebar import render_info
from graph import build_graph
from viewer import Window
from ui_helpers import wait_for_load


class WorktreeInfoTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.main = self.base/'main'
        self.linked = self.base/'linked tree'
        self.detached = self.base/'detached tree'
        self.main.mkdir()
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Tester')
        self.git('config', 'user.email', 'tester@example.invalid')
        self.root = self.commit('Root')
        self.git('checkout', '-b', 'feature')
        self.feature = self.commit('Feature')
        self.git('checkout', 'main')
        self.git('merge', '--ff-only', 'feature')
        self.tip = self.commit('Main continuation')
        self.git('branch', 'alias')
        self.git('worktree', 'add', str(self.linked), 'feature')
        self.git('worktree', 'lock', '--reason', 'in use', str(self.linked))
        self.git('worktree', 'add', '--detach', str(self.detached), self.root)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.main), *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def commit(self, message):
        self.git('commit', '--allow-empty', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def test_head_vs_ancestry_and_opened_linked_worktree(self):
        repo = read_repository(str(self.main))
        self.assertEqual(len(repo.worktrees), 3)
        graph = build_graph(repo)
        self.assertIn(self.feature, graph.nodes)
        self.assertNotIn(self.feature, graph.tips)
        feature = read_commit_info(repo, self.feature)
        matches = {Path(match.worktree.path).name: match for match in feature.worktrees}
        self.assertEqual(set(matches), {'main', 'linked tree'})
        self.assertEqual(matches['linked tree'].relation, 'HEAD is this commit')
        self.assertEqual(matches['linked tree'].worktree.locked, 'in use')
        self.assertIn('branch history', matches['main'].relation)
        self.assertTrue(matches['main'].opened)
        self.assertIn('Locked: in use', render_info(feature))
        root = read_commit_info(repo, self.root)
        detached = next(match for match in root.worktrees if match.worktree.detached)
        self.assertEqual(detached.relation, 'HEAD is this commit')
        subprocess.check_output(['git', '-C', str(self.detached), 'checkout', '--detach', self.tip],
                                stderr=subprocess.DEVNULL)
        updated = read_commit_info(repo, self.feature)
        detached = next(match for match in updated.worktrees if match.worktree.detached)
        self.assertEqual(detached.relation, 'Commit is an ancestor of detached HEAD')
        linked_repo = read_repository(str(self.linked), branches_only=True)
        info = read_commit_info(linked_repo, self.feature)
        self.assertTrue(next(match for match in info.worktrees if match.worktree.branch == 'refs/heads/feature').opened)
        self.assertFalse(next(match for match in info.worktrees if match.worktree.branch == 'refs/heads/main').opened)

    def test_graph_badges_colors_aliases_and_refresh(self):
        window = Window(str(self.main))
        self.addCleanup(window.close)
        wait_for_load(window)
        self.assertEqual(window.nodes[self.tip].brush().color().name(), '#c792ea')
        self.assertEqual(window.nodes[self.feature].brush().color().name(), '#c792ea')
        main_label = next(label for label in window.labels if label.toPlainText() == 'main [WT]')
        alias = next(label for label in window.labels if label.toPlainText() == 'alias')
        feature_label = next(label for label in window.labels if label.toPlainText() == 'feature [WT]')
        self.assertEqual(main_label.defaultTextColor().name(), '#c792ea')
        self.assertEqual(alias.defaultTextColor().name(), '#75baff')
        self.assertIn(str(self.linked).replace('\\', '/'), feature_label.toolTip().replace('\\', '/'))
        self.assertTrue(any(label.toPlainText() == 'Detached HEAD [WT]' for label in window.labels))
        window.nodes[self.tip].setSelected(True)
        self.assertEqual(window.nodes[self.tip].brush().color().name(), '#ffd166')
        self.assertEqual(main_label.defaultTextColor().name(), '#c792ea')
        window.scene.clearSelection()
        self.assertEqual(window.nodes[self.tip].brush().color().name(), '#c792ea')
        self.git('checkout', 'alias')
        window.refresh()
        wait_for_load(window)
        self.assertTrue(any(label.toPlainText() == 'alias [WT]' for label in window.labels))
        self.assertTrue(any(label.toPlainText() == 'main' and not label.worktree_badge for label in window.labels))

    def test_porcelain_parser_handles_nul_paths_lock_reasons_and_prunable(self):
        raw = (b'worktree /bare\0bare\0\0worktree /a path\nwith newline\0HEAD '+b'a'*40+
               b'\0branch refs/heads/feature\0locked line one\nline two\0\0worktree /gone\0HEAD '+b'b'*40+
               b'\0detached\0prunable missing directory\0\0')
        trees = parse_worktrees(raw)
        self.assertTrue(trees[0].main)
        self.assertTrue(trees[0].bare)
        self.assertFalse(trees[0].active)
        self.assertEqual(trees[1].path, '/a path\nwith newline')
        self.assertEqual(trees[1].locked, 'line one\nline two')
        self.assertTrue(trees[1].active)
        self.assertTrue(trees[2].detached)
        self.assertFalse(trees[2].active)

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog

from diff_viewer import DiffViewer
from git_reader import read_repository, read_changed_files
from graph import build_graph
from layout import branch_layout
from viewer import Window
from ui_helpers import wait_for_load


class BranchesOnlyTest(unittest.TestCase):
    def test_tip_loading_without_history_and_mode_switching(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as path:
            def git(*args):
                return subprocess.check_output(['git', '-C', path, *args], text=True,
                                               stderr=subprocess.DEVNULL).strip()

            def commit(message):
                git('commit', '--allow-empty', '-m', message)
                return git('rev-parse', 'HEAD')

            git('init', '-b', 'main')
            git('config', 'user.name', 'Tester')
            git('config', 'user.email', 'tester@example.invalid')
            (Path(path)/'file.txt').write_text('root content\n')
            git('add', '.')
            root = commit('Root')
            git('branch', 'old')
            intermediate = commit('Intermediate')
            fork = commit('Fork')
            git('checkout', '-b', 'side')
            side = commit('Side')
            git('checkout', 'main')
            parent = commit('Main change')
            git('merge', '--no-ff', 'side', '-m', 'Merge side')
            tip = git('rev-parse', 'HEAD')
            git('branch', 'alias')
            git('update-ref', 'refs/remotes/origin/main', intermediate)
            git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')

            with patch('git_reader.subprocess.run', wraps=subprocess.run) as run:
                repo = read_repository(path, branches_only=True)
            log_command = next(call.args[0] for call in run.call_args_list if 'log' in call.args[0])
            self.assertIn('--no-walk=sorted', log_command)
            self.assertNotIn('--topo-order', log_command)
            self.assertTrue(repo.branches_only)
            self.assertEqual(set(repo.commits), {root, side, tip})
            self.assertEqual(set(repo.branches[tip]), {'main', 'alias'})
            self.assertEqual(set(repo.commits[tip].parents), {parent, side})
            self.assertNotIn(parent, repo.commits)
            self.assertNotIn(fork, repo.commits)
            with patch('graph.terminal_tips', side_effect=AssertionError('Must not walk ancestry')):
                graph = build_graph(repo)
            self.assertEqual(graph.nodes, set(repo.branches))
            self.assertEqual(set(graph.tips), set(repo.branches))
            self.assertFalse(graph.edges)
            self.assertEqual(len(set(branch_layout(graph).values())), len(graph.nodes))
            self.assertEqual(read_changed_files(repo, parent, tip), [])
            remote = read_repository(path, remote=True, branches_only=True)
            self.assertEqual(set(remote.commits), {root, side, tip, intermediate})
            self.assertNotIn('origin/HEAD', [name for names in remote.branches.values() for name in names])

            window = Window(path, branches_only=True)
            wait_for_load(window)
            self.addCleanup(window.close)
            self.assertTrue(window.branches_only.isChecked())
            self.assertEqual(set(window.nodes), {root, side, tip})
            self.assertFalse(window.edge_items)
            self.assertIn('history not loaded', window.statusBar().currentMessage())
            self.assertIn('positions do not represent ancestry', window.details.toPlainText())
            self.assertEqual({label.node.oid for label in window.labels if label.toPlainText() == 'old'}, {root})
            window.nodes[tip].setPos(789, 456)
            window.branches_only.setChecked(False)
            wait_for_load(window)
            self.assertFalse(window.repo.branches_only)
            self.assertIn('History view', window.details.toPlainText())
            self.assertIn(parent, window.repo.commits)
            self.assertTrue(window.edge_items)
            window.nodes[tip].setPos(321, 654)
            window.branches_only.setChecked(True)
            wait_for_load(window)
            self.assertEqual((window.nodes[tip].pos().x(), window.nodes[tip].pos().y()), (789, 456))
            window.hide_node(root)
            window.refresh()
            wait_for_load(window)
            self.assertNotIn(root, window.nodes)
            window.rearrange_visible()
            self.assertNotIn(root, window.nodes)
            self.assertFalse(window.edge_items)
            window.show_hidden_nodes()
            self.assertIn(root, window.nodes)
            window.branches_only.setChecked(False)
            wait_for_load(window)
            self.assertEqual((window.nodes[tip].pos().x(), window.nodes[tip].pos().y()), (321, 654))
            window.branches_only.setChecked(True)
            wait_for_load(window)
            snapshots = []

            def inspect_dialog(dialog):
                diff = dialog.findChild(DiffViewer)
                snapshots.append((diff.source, diff.target, diff.files.count()))
                return 0

            with patch.object(QDialog, 'exec', new=inspect_dialog):
                window.show_diff(root)
                window.show_diff(tip)
                window.show_commit_diff(root, tip)
            self.assertEqual(snapshots, [(None, root, 1), (parent, tip, 0), (root, tip, 0)])
            with patch('repository_loader.read_repository', side_effect=RuntimeError('Load failed')), patch('viewer.QMessageBox.warning'):
                window.branches_only.setChecked(False)
                wait_for_load(window)
            self.assertTrue(window.branches_only.isChecked())
            self.assertTrue(window.repo.branches_only)

    def test_empty_repository_in_branch_mode(self):
        with tempfile.TemporaryDirectory() as path:
            subprocess.run(['git', 'init', path], check=True, capture_output=True)
            repo = read_repository(path, branches_only=True)
            self.assertEqual(build_graph(repo).nodes, set())
            self.assertEqual(branch_layout(build_graph(repo)), {})

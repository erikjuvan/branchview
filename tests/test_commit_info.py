import subprocess
import tempfile
import unittest
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import patch, MagicMock

from PySide6.QtCore import QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from commit_info import read_commit_info, InspectionCancelled, _inspection_bytes
from commit_sidebar import CommitSidebar, render_info
from git_reader import read_repository
from viewer import Window
from diff_viewer import DiffViewer


class CommitInfoTest(unittest.TestCase):
    def test_cancellation_stops_an_in_progress_git_command(self):
        event = Event()
        process = MagicMock()
        process.__enter__.return_value = process

        def communicate(timeout=None):
            if timeout is not None:
                event.set()
                raise subprocess.TimeoutExpired('git', timeout)
            return b'', b''

        process.communicate.side_effect = communicate
        with patch('commit_info.subprocess.Popen', return_value=process):
            with self.assertRaises(InspectionCancelled):
                _inspection_bytes(self.repo, ('log', '--all'), event)
        process.kill.assert_called_once()
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = self.directory.name
        self.folder = Path(self.path)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Integrator')
        self.git('config', 'user.email', 'integrator@example.invalid')
        (self.folder/'README.txt').write_text('Initial\n')
        self.git('add', '.')
        self.root = self.commit('Root')
        self.base = self.commit('Shared base')
        self.git('checkout', '-b', 'feature')
        (self.folder/'feature.txt').write_text('Feature\n')
        self.git('add', '.')
        self.feature = self.commit('<b>Feature & work</b>', '--author=Alice <alice@example.invalid>')
        self.git('checkout', 'main')
        self.main_change = self.commit('Main work')
        self.git('merge', '--no-ff', 'feature', '-m', 'Merge feature')
        self.merge = self.git('rev-parse', 'HEAD')
        self.git('tag', '-a', 'v1', '-m', 'First release')
        self.tip = self.commit('After integration')
        self.git('tag', 'v2')
        self.git('update-ref', 'refs/remotes/origin/main', self.tip)
        self.git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
        self.repo = read_repository(self.path, branches_only=True)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', self.path, *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def commit(self, message, *args):
        self.git('commit', '--allow-empty', '-m', message, *args)
        return self.git('rev-parse', 'HEAD')

    def wait_until(self, predicate):
        for _ in range(500):
            if predicate():
                return
            QTest.qWait(10)
        self.fail('Background details did not complete')

    def test_provenance_merge_metadata_refs_and_files(self):
        original_commits = set(self.repo.commits)
        info = read_commit_info(self.repo, self.feature)
        self.assertEqual(set(info.branches), {'feature', 'main', 'origin/main'})
        self.assertEqual(info.tip_refs, ['feature'])
        self.assertEqual(set(info.tags), {'v1', 'v2'})
        self.assertEqual(info.commit.author, 'Alice')
        self.assertEqual(info.author_email, 'alice@example.invalid')
        self.assertEqual(info.committer, 'Integrator')
        self.assertEqual(info.committer_email, 'integrator@example.invalid')
        self.assertEqual(info.parent_subjects[self.base], 'Shared base')
        self.assertEqual(dict(info.children), {self.merge: 'Merge feature'})
        entries = {entry.branch: entry for entry in info.integrations}
        self.assertEqual(entries['main'].merge, self.merge)
        self.assertEqual(entries['origin/main'].merge, self.merge)
        self.assertEqual(entries['feature'].kind, 'mainline')
        self.assertEqual(info.files[0].new_path, 'feature.txt')
        self.assertIn('1 insertion', info.statistics)
        self.assertEqual(set(self.repo.commits), original_commits)
        html = render_info(info)
        self.assertIn('&lt;b&gt;Feature &amp; work&lt;/b&gt;', html)
        self.assertNotIn('<b>Feature & work</b>', html)
        self.assertIn('original branch name', html)

        root = read_commit_info(self.repo, self.root)
        self.assertEqual(root.commit.parents, ())
        self.assertIn(self.base, dict(root.children))
        self.assertIn('README.txt', [change.new_path for change in root.files])
        merge = read_commit_info(self.repo, self.merge)
        self.assertEqual(merge.commit.parents, (self.main_change, self.feature))
        self.assertIn('Destination-side', render_info(merge))
        limited = read_commit_info(self.repo, self.feature, descendant_limit=1)
        self.assertTrue(any('limited' in warning for warning in limited.warnings))
        self.assertFalse(any(entry.kind == 'merge' for entry in limited.integrations))
        cancel = Event()
        cancel.set()
        with self.assertRaises(InspectionCancelled):
            read_commit_info(self.repo, self.feature, cancel)

    def test_async_cache_and_branch_only_parent_navigation(self):
        info = read_commit_info(self.repo, self.feature)
        sidebar = CommitSidebar()
        self.addCleanup(sidebar.cancel_pending)
        self.addCleanup(sidebar.close)
        gate, started = Event(), Event()
        self.addCleanup(gate.set)
        gui_thread = get_ident()
        threads = []

        def query(repo, oid, cancelled):
            threads.append(get_ident())
            started.set()
            gate.wait(3)
            return info

        with patch('commit_sidebar.read_commit_info', side_effect=query) as reader:
            sidebar.show_commit(self.repo, self.feature)
            self.assertIn('Loading relationships', sidebar.toPlainText())
            self.wait_until(started.is_set)
            self.assertNotEqual(threads[0], gui_thread)
            gate.set()
            self.wait_until(lambda: self.feature in sidebar.cache)
            self.assertIn('Contained in branches', sidebar.toPlainText())
            sidebar.show_commit(self.repo, self.feature)
            self.assertEqual(reader.call_count, 1)
            sidebar.reset_repository(self.repo)
            sidebar.show_commit(self.repo, self.feature)
            self.wait_until(lambda: self.feature in sidebar.cache)
            self.assertEqual(reader.call_count, 2)

        window = Window(self.path, branches_only=True)
        self.addCleanup(window.close)
        tips = set(window.repo.commits)
        window.open_detail_link(QUrl('commit:'+self.base))
        self.wait_until(lambda: self.base in window.details.cache)
        self.assertEqual(set(window.repo.commits), tips)
        self.assertEqual(set(window.nodes), tips)
        self.assertIn('Shared base', window.details.toPlainText())
        with patch.object(window, 'show_diff') as diff:
            window.open_detail_link(QUrl('diff:'+self.base+'?file=README.txt'))
        self.assertEqual(diff.call_args.args, (self.base,))
        self.assertIn(self.base, diff.call_args.kwargs['repo'].commits)
        self.assertEqual(diff.call_args.kwargs['file_path'], 'README.txt')
        paths = []

        def inspect_diff(dialog):
            diff = dialog.findChild(DiffViewer)
            paths.append(diff.changes[diff.files.currentRow()].new_path)
            return 0

        with patch.object(QDialog, 'exec', new=inspect_diff):
            window.open_detail_link(QUrl('diff:'+self.feature+'?file=feature.txt'))
        self.assertEqual(paths, ['feature.txt'])
        window.branches_only.setChecked(False)
        self.assertNotIn(self.main_change, window.nodes)
        window.open_detail_link(QUrl('commit:'+self.main_change))
        self.assertIn(self.main_change, window.nodes)
        self.assertTrue(window.nodes[self.main_change].isSelected())

    def test_stale_results_do_not_replace_new_selection(self):
        feature = read_commit_info(self.repo, self.feature)
        tip = read_commit_info(self.repo, self.tip)
        sidebar = CommitSidebar()
        self.addCleanup(sidebar.cancel_pending)
        self.addCleanup(sidebar.close)
        gate, started = Event(), Event()
        self.addCleanup(gate.set)

        def query(repo, oid, cancelled):
            if oid == self.feature:
                started.set()
                gate.wait(3)
                return feature
            return tip

        with patch('commit_sidebar.read_commit_info', side_effect=query):
            sidebar.show_commit(self.repo, self.feature)
            self.wait_until(started.is_set)
            sidebar.show_commit(self.repo, self.tip)
            self.wait_until(lambda: self.tip in sidebar.cache)
            gate.set()
            self.wait_until(lambda: not sidebar.jobs)
            self.assertEqual(sidebar.active_oid, self.tip)
            self.assertIn('After integration', sidebar.toPlainText())
            self.assertNotIn(self.feature, sidebar.cache)

    def test_shallow_boundary_retains_actual_parent_and_metadata(self):
        with tempfile.TemporaryDirectory() as target:
            subprocess.check_output(['git', 'clone', '--depth=1', '--no-local', self.path, target],
                                    stderr=subprocess.DEVNULL)
            repo = read_repository(target, branches_only=True)
            info = read_commit_info(repo, self.tip)
            self.assertEqual(info.commit.parents, (self.merge,))
            self.assertEqual(info.commit.author, 'Integrator')
            self.assertTrue(any('Shallow' in warning for warning in info.warnings))
            self.assertTrue(any('Cannot compare' in warning for warning in info.warnings))
            self.assertIn('Ordinary commit', render_info(info))

    def test_linear_descendants_and_rewritten_commits_are_distinguished(self):
        self.git('checkout', '-b', 'linear', self.feature)
        child = self.commit('Linear continuation')
        self.git('checkout', '-b', 'replayed', self.main_change)
        self.git('cherry-pick', self.feature)
        self.git('checkout', '-b', 'squashed', self.main_change)
        self.git('merge', '--squash', 'feature')
        self.commit('Squash feature')
        self.git('checkout', 'main')
        info = read_commit_info(self.repo, self.feature)
        self.assertIn('linear', info.branches)
        self.assertNotIn('replayed', info.branches)
        self.assertNotIn('squashed', info.branches)
        self.assertIn(child, dict(info.children))
        entry = next(entry for entry in info.integrations if entry.branch == 'linear')
        self.assertEqual(entry.kind, 'mainline')
        self.assertIsNone(entry.merge)

import unittest
from PySide6.QtGui import QColor
from git_reader import Commit, Repository, Worktree
from viewer import Window
from branch_colors import remote_name, remote_color
from ui_helpers import application


class BranchColorTest(unittest.TestCase):
    def test_remote_identity_palette_shared_tips_and_selection(self):
        ids = [f'{i:040x}' for i in (1, 2, 3, 4)]
        commits = {oid: Commit(oid, (), 'Tester', '', 'Commit') for oid in ids}
        repo = Repository('synthetic', commits,
                          {ids[0]: ['main', 'origin/main'], ids[1]: ['origin/topic'],
                           ids[2]: ['upstream/topic'], ids[3]: ['origin/local']}, branches_only=True,
                          branch_refs={'main': 'refs/heads/main', 'origin/main': 'refs/remotes/origin/main',
                                       'origin/topic': 'refs/remotes/origin/topic', 'upstream/topic': 'refs/remotes/upstream/topic',
                                       'origin/local': 'refs/heads/origin/local'}, remote_names=('origin', 'upstream', 'team/fork'))
        window = Window()
        try:
            window.repo = repo
            window.render()
            self.assertNotEqual(remote_color('origin'), remote_color('upstream'))
            self.assertNotEqual(remote_color('origin'), QColor('#75baff'))
            self.assertEqual(window.nodes[ids[0]].brush().color(), QColor('#75baff'))
            self.assertEqual(window.nodes[ids[1]].brush().color(), remote_color('origin'))
            self.assertEqual(window.nodes[ids[2]].brush().color(), remote_color('upstream'))
            self.assertEqual(window.nodes[ids[3]].brush().color(), QColor('#75baff'))
            label = next(label for label in window.labels if label.toPlainText() == 'origin/topic')
            # Block detail queries against the synthetic path; test highlights directly.
            window.scene.blockSignals(True)
            window.nodes[ids[1]].setSelected(True)
            window.update_selection_highlights()
            self.assertEqual(label.defaultTextColor(), remote_color('origin'))
            self.assertEqual(window.nodes[ids[1]].brush().color(), QColor('#ffd166'))
            window.scene.clearSelection()
            window.update_selection_highlights()
            self.assertEqual(window.nodes[ids[1]].brush().color(), remote_color('origin'))
            items = {window.branch_panel.list.item(i).text(): window.branch_panel.list.item(i) for i in range(window.branch_panel.list.count())}
            self.assertEqual(items['origin/main'].foreground().color(), remote_color('origin'))
            self.assertEqual(items['origin/local'].foreground().color(), QColor('#75baff'))
            repo.branch_refs['team/fork/topic'] = 'refs/remotes/team/fork/topic'
            self.assertEqual(remote_name(repo, 'team/fork/topic'), 'team/fork')
        finally:
            window.close()
            application.processEvents()

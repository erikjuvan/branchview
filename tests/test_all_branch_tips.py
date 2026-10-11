import subprocess
import tempfile
import unittest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from git_reader import read_repository
from graph import build_graph, hide_nodes
from layout import layout
from commit_info import read_commit_info
from commit_sidebar import render_info
from viewer import Window
from ui_helpers import wait_for_load


class AllBranchTipsTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = self.temp.name
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Tester')
        self.git('config', 'user.email', 'tester@example.invalid')
        self.root = self.commit('Root')
        self.base = self.commit('Shared base')
        self.git('branch', 'old', self.base)
        self.git('checkout', '-b', 'feature')
        self.linear = self.commit('Feature preparation')
        self.feature = self.commit('Feature finished')
        self.git('branch', 'feature-alias')
        self.git('checkout', 'main')
        self.main_change = self.commit('Main work')
        self.git('merge', '--no-ff', 'feature', '-m', 'Integrate feature')
        self.merge = self.git('rev-parse', 'HEAD')
        self.tip = self.commit('Continue main')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', self.path, *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def commit(self, message):
        self.git('commit', '--allow-empty', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def test_all_named_tips_are_roots_with_only_ancestry_and_merge_paths_retained(self):
        repo = read_repository(self.path, all_branch_tips=True)
        graph = build_graph(repo)
        positions = layout(graph)
        self.assertEqual({graph.commit_oid(tip) for tip in graph.tips}, set(repo.branches))
        self.assertEqual(len(graph.tips), 3)
        self.assertTrue(all(positions[tip][1] == 0 for tip in graph.tips))
        self.assertEqual(graph.commit_ids['tip:'+self.feature], self.feature)
        self.assertIn('tip:'+self.feature, graph.included_tips)
        self.assertFalse(any(edge.parent in graph.tips for edge in graph.edges))
        self.assertTrue(all(positions[edge.parent][1] > positions[edge.child][1] for edge in graph.edges))
        parents = {}
        for edge in graph.edges:
            parents.setdefault(edge.child, []).append(edge.parent)
            chain = (graph.commit_oid(edge.child), *edge.hidden, graph.commit_oid(edge.parent))
            for child, parent in zip(chain, chain[1:]):
                self.assertIn(parent, repo.commits[child].parents)
        ancestry, todo = set(), ['tip:'+self.feature]
        while todo:
            child = todo.pop()
            if child not in ancestry:
                ancestry.add(child)
                todo.extend(parents.get(child, []))
        self.assertNotIn(self.merge, ancestry)
        self.assertNotIn(self.tip, ancestry)
        expanded = build_graph(repo, set(repo.commits))
        self.assertEqual({edge.parent for edge in expanded.edges if edge.child == self.merge},
                         set(repo.commits[self.merge].parents))
        hidden = hide_nodes(graph, {self.feature})
        self.assertNotIn(self.feature, hidden.nodes)
        self.assertNotIn('tip:'+self.feature, hidden.nodes)
        self.assertTrue(any(self.feature in edge.hidden for edge in hidden.edges))
        limited = build_graph(read_repository(self.path, commit_limit=1, all_branch_tips=True))
        self.assertEqual(set(limited.tips), set(graph.tips))
        self.assertNotIn(self.feature, limited.nodes)
        self.assertIn('tip:'+self.feature, limited.nodes)

    def test_sidebar_identifies_real_merge_and_does_not_invent_one_for_mainline(self):
        repo = read_repository(self.path, all_branch_tips=True)
        feature = read_commit_info(repo, self.feature)
        self.assertEqual(feature.included_in, ['main'])
        html = render_info(feature)
        self.assertIn('Branch tip already included', html)
        self.assertIn('merged into its first-parent history', html)
        self.assertIn('commit:'+self.merge+'?history=1', html)
        old = read_commit_info(repo, self.base)
        self.assertIn('no introducing merge commit', render_info(old))
        self.assertFalse(any(entry.kind == 'merge' for entry in old.integrations))

    def test_gui_toggle_jump_independent_copies_hiding_and_flat_mode(self):
        window = Window(self.path, all_branch_tips=True)
        self.addCleanup(window.close)
        wait_for_load(window)
        alias = 'tip:'+self.feature
        self.assertEqual(window.nodes[self.feature].display_id, alias)
        self.assertIsNot(window.nodes[self.feature], window.display_nodes[self.feature])
        self.assertTrue(window.nodes[self.feature].tip)
        self.assertFalse(window.display_nodes[self.feature].tip)
        self.assertTrue(all(node.pos().y() == 0 for node in window.display_nodes.values() if node.tip))
        self.assertTrue(any(label.toPlainText() == 'feature' and label.included_tip for label in window.labels))
        copy = window.display_nodes[self.feature]
        copy_bounds = copy.sceneBoundingRect().united(copy.mapRectToScene(copy.childrenBoundingRect()))
        for edge, _, label in window.edge_items:
            if edge.child == self.merge and label is not None:
                self.assertFalse(label.sceneBoundingRect().intersects(copy_bounds))
        window.nodes[self.feature].setSelected(True)
        self.assertEqual(window.display_nodes[self.merge].brush().color().name(), '#59616e')
        window.open_detail_link(QUrl('commit:'+self.merge+'?history=1'))
        self.assertTrue(window.display_nodes[self.merge].isSelected())
        self.assertEqual(window.details.active_oid, self.merge)
        window.nodes[self.feature].setPos(650, 77)
        self.assertEqual(window.manual_positions[alias], (650, 77))
        self.assertNotEqual(window.display_nodes[self.feature].pos(), window.nodes[self.feature].pos())
        window.all_branch_tips.setChecked(False)
        wait_for_load(window)
        self.assertNotIn(alias, window.display_nodes)
        window.all_branch_tips.setChecked(True)
        wait_for_load(window)
        self.assertEqual(window.nodes[self.feature].pos().x(), 650)
        self.assertEqual(window.nodes[self.feature].pos().y(), 77)
        window.hide_node(self.feature)
        self.assertNotIn(alias, window.display_nodes)
        self.assertNotIn(self.feature, window.display_nodes)
        window.show_hidden_nodes()
        self.assertIn(alias, window.display_nodes)
        window.hide_node(self.tip)
        window.hide_node(self.merge)
        window.rearrange_visible()
        self.assertEqual(window.nodes[self.feature].pos().y(), 0)
        self.assertGreater(window.display_nodes[self.feature].pos().y(), 0)
        window.show_hidden_nodes()
        window.branches_only.setChecked(True)
        wait_for_load(window)
        self.assertFalse(window.all_branch_tips.isEnabled())
        self.assertFalse(window.edge_items)
        self.assertNotIn(alias, window.display_nodes)

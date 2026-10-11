import unittest

from PySide6.QtWidgets import QApplication

from git_reader import Commit, Repository
from viewer import Window


class SelectionHighlightTest(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        commits = {oid: Commit(oid, parents, 'Tester', '', 'Commit '+oid)
                   for oid, parents in [('root', ()), ('a', ('root',)), ('b', ('root',)),
                                        ('merge', ('a', 'b')), ('tip', ('merge',)),
                                        ('side', ('a',)), ('unrelated', ())]}
        self.window = Window()
        self.window.repo = Repository('synthetic', commits,
                                      {'tip': ['main'], 'side': ['feature'], 'unrelated': ['other']})
        self.window.render()
        self.addCleanup(self.window.close)

    def test_merge_ancestry_collapsed_edges_and_selection_union(self):
        window = self.window
        positions = {oid: node.pos() for oid, node in window.nodes.items()}
        bounds = window.scene.sceneRect()
        node_bounds = window.nodes['merge'].boundingRect()
        window.nodes['merge'].setSelected(True)
        self.assertEqual(window.nodes['merge'].brush().color().name(), '#ffd166')
        for oid in ('a', 'root'):
            self.assertEqual(window.nodes[oid].brush().color().name(), '#5ce0cc')
        for oid in ('tip', 'side', 'unrelated'):
            self.assertEqual(window.nodes[oid].brush().color().name(), '#59616e')
        for edge, item, label in window.edge_items:
            expected = '#5ce0cc' if edge.child in {'merge', 'a'} else '#454c56'
            self.assertEqual(item.pen().color().name(), expected)
            if 'b' in edge.hidden:
                self.assertEqual(label.defaultTextColor().name(), '#80ead9')
                self.assertEqual(label.opacity(), 1)
        self.assertEqual(window.nodes['merge'].boundingRect(), node_bounds)
        self.assertEqual(window.scene.sceneRect(), bounds)
        self.assertTrue(all(node.pos() == positions[oid] for oid, node in window.nodes.items()))

        window.nodes['side'].setSelected(True)
        self.assertEqual(window.nodes['side'].brush().color().name(), '#ffd166')
        side_labels = [label for label in window.labels if label.node.oid == 'side']
        self.assertTrue(all(label.defaultTextColor().name() == '#ffd166' for label in side_labels))
        self.assertTrue(any(label.toPlainText() == 'feature' for label in side_labels))
        self.assertEqual(window.nodes['tip'].brush().color().name(), '#59616e')
        self.assertEqual(window.nodes['root'].brush().color().name(), '#5ce0cc')

        window.scene.clearSelection()
        self.assertEqual(window.nodes['tip'].brush().color().name(), '#75baff')
        self.assertEqual(window.nodes['root'].brush().color().name(), '#b5bdc9')
        self.assertTrue(all(item.pen().color().name() == '#818b99' for _, item, _ in window.edge_items))
        self.assertTrue(all(label.opacity() == 1 for label in window.labels))
        window.nodes['tip'].setSelected(True)
        self.assertEqual(window.nodes['merge'].brush().color().name(), '#5ce0cc')

    def test_expansion_hiding_and_branch_mode(self):
        window = self.window
        window.expanded.add('b')
        window.render()
        window.nodes['merge'].setSelected(True)
        self.assertEqual(window.nodes['b'].brush().color().name(), '#5ce0cc')
        window.hide_node('a')
        window.nodes['merge'].setSelected(True)
        self.assertEqual(window.nodes['root'].brush().color().name(), '#5ce0cc')
        self.assertTrue(any('a' in edge.hidden and item.pen().color().name() == '#5ce0cc'
                            for edge, item, _ in window.edge_items))
        window.repo.branches_only = True
        window.hidden_nodes.clear()
        window.render()
        window.nodes['tip'].setSelected(True)
        self.assertFalse(window.parent_edges)
        self.assertFalse(window.edge_items)
        self.assertEqual(window.nodes['tip'].brush().color().name(), '#ffd166')
        self.assertEqual(window.nodes['side'].brush().color().name(), '#59616e')
        window.scene.clearSelection()
        self.assertEqual(window.nodes['side'].brush().color().name(), '#75baff')

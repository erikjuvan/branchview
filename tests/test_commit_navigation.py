import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from git_reader import Commit, Repository
from viewer import Window
from ui_helpers import application


class CommitNavigationTest(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.addCleanup(self.window.close)
        self.ids = [f'{i:040x}' for i in range(1, 5)]
        commits = {oid: Commit(oid, (self.ids[i-1],) if i else (), 'Tester', '', f'Commit {i}')
                   for i, oid in enumerate(self.ids)}
        self.window.repo = Repository('synthetic', commits, {self.ids[-1]: ['main']})
        self.window.render()
        # Navigation should update details without querying a synthetic Git path.
        self.details = patch.object(self.window.details, 'show_commit').start()
        self.addCleanup(patch.stopall)

    def selected(self):
        return {item.oid for item in self.window.scene.selectedItems() if hasattr(item, 'oid')}

    def test_shortcuts_reveal_immediate_hidden_relatives_and_keep_zoom(self):
        window = self.window
        window.show()
        window.activateWindow()
        window.view.setFocus()
        application.processEvents()
        window.nodes[self.ids[-1]].setSelected(True)
        window.hidden_nodes.add(self.ids[-2])
        zoom = window.view.transform().m11()
        QTest.keyClick(window.view, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.selected(), {self.ids[-2]})
        self.assertNotIn(self.ids[-2], window.hidden_nodes)
        self.assertEqual(window.view.transform().m11(), zoom)
        self.details.assert_called_with(window.repo, self.ids[-2])
        QTest.keyClick(window.view, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.selected(), {self.ids[-1]})

    def test_boundaries_and_ambiguous_selection_do_not_move(self):
        window = self.window
        window.nodes[self.ids[0]].setSelected(True)
        window.go_to_parent_commit()
        self.assertEqual(self.selected(), {self.ids[0]})
        window.nodes[self.ids[-1]].setSelected(True)
        window.go_to_child_commit()
        self.assertEqual(self.selected(), {self.ids[0], self.ids[-1]})
        window.scene.clearSelection()
        window.go_to_child_commit()
        self.assertEqual(self.selected(), set())
        window.nodes[self.ids[-1]].setSelected(True)
        window.go_to_child_commit()
        self.assertEqual(self.selected(), {self.ids[-1]})

    def test_merge_parents_and_branch_children_have_stable_order(self):
        window = self.window
        root, left, right, merge = self.ids
        window.repo.commits[right] = Commit(right, (root,), 'Tester', '', 'Right')
        window.repo.commits[merge] = Commit(merge, (left, right), 'Tester', '', 'Merge')
        window.render()
        window.nodes[merge].setSelected(True)
        window.go_to_parent_commit()
        self.assertEqual(self.selected(), {left})
        window.scene.clearSelection()
        window.nodes[root].setSelected(True)
        window.go_to_child_commit()
        self.assertEqual(self.selected(), {left})

    def test_missing_history_is_not_skipped(self):
        window = self.window
        del window.repo.commits[self.ids[1]]
        window.render()
        window.nodes[self.ids[2]].setSelected(True)
        window.go_to_parent_commit()
        self.assertEqual(self.selected(), {self.ids[2]})

    def test_help_and_context_menu_expose_navigation(self):
        window = self.window
        window.nodes[self.ids[-1]].setSelected(True)
        actions = [description for _, description, _ in window.shortcuts_panel.entries]
        self.assertIn('Go to child commit', actions)
        self.assertIn('Go to parent commit', actions)
        menu = window.node_menu(self.ids[-1])
        self.assertFalse(menu.actions()[0].isEnabled())
        self.assertTrue(menu.actions()[1].isEnabled())

    def test_all_branch_tips_selects_the_history_copy(self):
        window = self.window
        window.repo.all_branch_tips = True
        window.repo.branches[self.ids[1]] = ['feature']
        window.render()
        window.nodes[self.ids[-1]].setSelected(True)
        window.go_to_parent_commit()
        window.go_to_parent_commit()
        self.assertTrue(window.display_nodes[self.ids[1]].isSelected())
        self.assertFalse(window.display_nodes['tip:'+self.ids[1]].isSelected())

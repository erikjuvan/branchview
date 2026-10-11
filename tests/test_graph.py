import os
import subprocess
import tempfile
import unittest
from git_reader import read_repository
from graph import build_graph, terminal_tips
from layout import layout
from ui_helpers import wait_for_load

class GitGraphTest(unittest.TestCase):
    def test_real_git_merges_aliases_and_expansion(self):
        with tempfile.TemporaryDirectory() as path:
            def git(*args):
                return subprocess.check_output(['git','-C',path,*args],text=True,stderr=subprocess.DEVNULL).strip()
            git('init','-b','main')
            git('config','user.name','Tester')
            git('config','user.email','tester@example.invalid')
            def commit(message):
                git('commit','--allow-empty','-m',message)
                return git('rev-parse','HEAD')
            Path = __import__('pathlib').Path
            (Path(path)/'example.txt').write_text('initial\n')
            git('add', 'example.txt')
            root=commit('Root')
            git('branch','old')
            commit('Linear one'); commit('Linear two')
            fork=commit('Fork')
            git('checkout','-b','experiment')
            commit('Experiment one'); a=commit('Experiment two\n\nDetails')
            git('branch','alias')
            git('checkout','main')
            commit('Main one')
            git('checkout','-b','side')
            side=commit('Side')
            git('checkout','main')
            commit('Main two')
            git('merge','--no-ff','side','-m','Merge side')
            b=git('rev-parse','HEAD')
            repo=read_repository(path)
            from git_reader import read_diff
            self.assertIn('+initial', read_diff(repo, root, None))
            self.assertEqual(read_diff(repo, a, repo.commits[a].parents[0]), 'No changes relative to this parent.')
            self.assertEqual(set(terminal_tips(repo)),{a,b})
            self.assertEqual(set(repo.branches[a]),{'alias','experiment'})
            self.assertEqual(len(repo.commits[b].parents),2)
            self.assertIn('Details',repo.commits[a].message)
            graph=build_graph(repo)
            positions=layout(graph)
            self.assertTrue(all(positions[t][1]==0 for t in graph.tips))
            for e in graph.edges:
                self.assertGreater(positions[e.parent][1],positions[e.child][1])
                chain=(e.child,*e.hidden,e.parent)
                for child,parent in zip(chain,chain[1:]):
                    self.assertIn(parent,repo.commits[child].parents)
            hidden={o for e in graph.edges for o in e.hidden}
            self.assertEqual(graph.nodes|hidden,set(repo.commits))
            self.assertIn(root,graph.nodes)
            self.assertIn(fork,graph.nodes)
            expanded=build_graph(repo,hidden)
            self.assertFalse(any(e.hidden for e in expanded.edges))
            # Offscreen GUI smoke test, including selection and redraw.
            from PySide6.QtWidgets import QApplication
            from viewer import Window
            app=QApplication.instance() or QApplication([])
            window=Window(path)
            wait_for_load(window)
            window.show(); app.processEvents()
            self.assertEqual(len(window.repo.commits),len(repo.commits))
            window.expanded.update(hidden); window.render(); window.view.fit()
            node=window.nodes[a]
            node.setSelected(True); app.processEvents()
            self.assertIn(node.oid,window.details.toPlainText())
            self.assertTrue(all(label.scene() is window.scene for label in window.labels))
            old_path = next(item.path() for edge,item,label in window.edge_items if edge.child == node.oid or edge.parent == node.oid)
            oid = node.oid
            before_origin = window.view.mapToScene(0, 0)
            before_bounds = window.scene.sceneRect()
            node.setPos(650, 420)
            app.processEvents()
            self.assertEqual(window.scene.sceneRect(), before_bounds)
            self.assertEqual(window.view.mapToScene(0, 0), before_origin)
            from PySide6.QtCore import Qt
            self.assertEqual(node.cursor().shape(), Qt.CursorShape.ArrowCursor)
            self.assertTrue(all(label.cursor().shape() == Qt.CursorShape.ArrowCursor for label in window.labels))
            from PySide6.QtTest import QTest
            window.view.setFocus()
            QTest.keyClick(window.view, Qt.Key.Key_Space)
            app.processEvents()
            self.assertEqual(window.fit_shortcut.key().toString(), 'Space')
            self.assertEqual(window.manual_positions[oid], (650, 420))
            new_path = next(item.path() for edge,item,label in window.edge_items if edge.child == oid or edge.parent == oid)
            self.assertNotEqual(old_path, new_path)
            window.collapse()
            self.assertEqual(window.nodes[oid].pos().x(), 650)
            window.refresh()
            wait_for_load(window)
            self.assertEqual(window.nodes[oid].pos().y(), 420)
            self.assertEqual(window.scene.backgroundBrush().color().name(), '#292c31')
            window.grab().save('/workspace/scratch/1b60b907429c/theme_preview.png')
            from graph import hide_nodes
            hidden_graph = hide_nodes(build_graph(repo), {fork})
            self.assertNotIn(fork, hidden_graph.nodes)
            self.assertTrue(any(fork in e.hidden for e in hidden_graph.edges))
            window.hide_node(fork)
            self.assertNotIn(fork, window.nodes)
            window.rearrange_visible()
            self.assertNotIn(fork, window.nodes)
            self.assertEqual({act.text() for act in window.node_menu(a).actions()},
                             {'Hide node', 'Browse files at this commit…', 'Open commit in VS Code…'})
            self.assertEqual(window.view.dragMode(), window.view.DragMode.RubberBandDrag)
            window.show_hidden_nodes()
            self.assertIn(fork, window.nodes)
            # Label dragging moves the entire selected group.
            from PySide6.QtCore import QPointF, QTimer
            window.scene.clearSelection()
            window.nodes[a].setSelected(True)
            window.nodes[b].setSelected(True)
            label = next(l for l in window.labels if l.node.oid == a)
            origins = {o: window.nodes[o].pos() for o in (a,b)}
            class DragEvent:
                def __init__(self, point): self.point = point
                def button(self): return Qt.MouseButton.LeftButton
                def buttons(self): return Qt.MouseButton.LeftButton
                def modifiers(self): return Qt.KeyboardModifier.NoModifier
                def scenePos(self): return self.point
                def accept(self): pass
            label.mousePressEvent(DragEvent(QPointF(0,0)))
            label.mouseMoveEvent(DragEvent(QPointF(40,30)))
            for o in (a,b):
                self.assertEqual(window.nodes[o].pos(), origins[o] + QPointF(40,30))
            QTimer.singleShot(0, lambda: app.activeModalWidget().accept())
            window.show_diff(b)
            window.reset_layout()
            self.assertEqual(window.manual_positions, {})
            window.close()
    def test_empty_repo(self):
        with tempfile.TemporaryDirectory() as path:
            subprocess.run(['git','init',path],check=True,capture_output=True)
            repo=read_repository(path)
            self.assertEqual(build_graph(repo).nodes,set())

if __name__=='__main__':
    unittest.main()

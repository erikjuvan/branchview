import unittest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsScene, QToolBar
from viewer import View, Window
from git_reader import Commit, Repository
from PySide6.QtTest import QTest

class ZoomTest(unittest.TestCase):
    def test_top_shortcut_fits_tips_without_long_history(self):
        app = QApplication.instance() or QApplication([])
        window = Window()
        self.addCleanup(window.close)
        commits = {str(i): Commit(str(i), (str(i-1),) if i else (), 'Tester', '', f'Commit {i}')
                   for i in range(100)}
        commits['side'] = Commit('side', ('50',), 'Tester', '', 'Side tip')
        window.repo = Repository('synthetic', commits, {'99': ['main'], 'side': ['feature']})
        window.expanded.update(commits)
        window.render()
        window.show()
        window.activateWindow()
        window.view.setFocus()
        app.processEvents()
        window.view.fit()
        full_scale = window.view.transform().m11()
        positions = {oid: node.pos() for oid, node in window.nodes.items()}
        window.nodes['99'].setSelected(True)
        QTest.keyClick(window.view.viewport(), Qt.Key.Key_T)
        app.processEvents()
        self.assertGreater(window.view.transform().m11(), full_scale * 5)
        visible = window.view.mapToScene(window.view.viewport().rect()).boundingRect()
        for oid in ('99', 'side'):
            node = window.nodes[oid]
            self.assertTrue(visible.contains(node.sceneBoundingRect()))
            self.assertTrue(visible.contains(node.mapRectToScene(node.childrenBoundingRect())))
        self.assertFalse(visible.contains(window.nodes['0'].sceneBoundingRect()))
        self.assertTrue(window.nodes['99'].isSelected())
        self.assertTrue(all(node.pos() == positions[oid] for oid, node in window.nodes.items()))
        self.assertEqual(window.top_shortcut.key().toString(), 'T')
        action = next(action for action in window.findChildren(QToolBar)[0].actions()
                      if action.text() == 'Top commits')
        window.view.fit()
        action.trigger()
        self.assertGreater(window.view.transform().m11(), full_scale * 5)
        window.hide_node('99')
        window.hide_node('side')
        window.fit_top_commits()
        window.hidden_nodes.update(window.nodes)
        window.render()
        transform = window.view.transform()
        window.fit_top_commits()
        self.assertEqual(window.view.transform(), transform)

    def test_zoom_recovers_after_large_graph_fit(self):
        app = QApplication.instance() or QApplication([])
        scene = QGraphicsScene()
        scene.addRect(0, 0, 100000, 100000)
        view = View(scene)
        view.resize(800, 600)
        view.show()
        app.processEvents()
        view.fit()
        initial = view.transform().m11()
        self.assertLess(initial, .03)
        def wheel(delta):
            event = QWheelEvent(QPointF(100,100), QPointF(100,100), QPoint(),
                QPoint(0,delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False)
            view.wheelEvent(event)
        wheel(120)
        self.assertGreater(view.transform().m11(), initial)
        for _ in range(100):
            wheel(120)
        self.assertAlmostEqual(view.transform().m11(), 8)
        wheel(-120)
        self.assertLess(view.transform().m11(), 8)
        for _ in range(100):
            wheel(-120)
        self.assertAlmostEqual(view.transform().m11(), .03)
        before = view.transform().m11()
        wheel(0)
        self.assertEqual(view.transform().m11(), before)
        view.close()

import unittest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsScene
from viewer import View

class ZoomTest(unittest.TestCase):
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

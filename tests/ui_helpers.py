from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

# Keep one QApplication alive across tests while background jobs finish.
application = QApplication.instance() or QApplication([])


def wait_for_load(window):
    for _ in range(1000):
        if not window.loading:
            return
        QTest.qWait(10)
    raise AssertionError('Repository did not finish loading')

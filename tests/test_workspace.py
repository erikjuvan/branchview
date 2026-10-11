import subprocess
import tempfile
import unittest
from pathlib import Path

from PySide6.QtGui import QShortcut
from workspace import WorkspaceWindow
from ui_helpers import application, wait_for_load


def create_repo(path):
    path.mkdir(parents=True)
    subprocess.run(['git', 'init', '-b', 'main', str(path)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(path), '-c', 'user.name=Tester',
                    '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-m', 'Root'],
                   check=True, capture_output=True)
    return path


class WorkspaceTest(unittest.TestCase):
    def test_independent_tabs_deduplication_shortcuts_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = create_repo(root/'a')
            second = create_repo(root/'b')
            window = WorkspaceWindow()
            window.show()
            try:
                a = window.open_repository(first)
                wait_for_load(a)
                a.view.scale(1.7, 1.7)
                transform = a.view.transform()
                a.remote.setChecked(True)
                wait_for_load(a)
                a.view.setTransform(transform)
                oid = next(iter(a.nodes))
                a.nodes[oid].setSelected(True)
                b = window.open_repository(second)
                wait_for_load(b)
                self.assertEqual(window.tabs.count(), 2)
                self.assertFalse(b.remote.isChecked())
                self.assertTrue(all(not s.isEnabled() for s in a.findChildren(QShortcut)))
                self.assertTrue(b.diff_shortcut.isEnabled())
                child = first/'ordinary'
                child.mkdir()
                self.assertIs(window.open_repository(child), a)
                self.assertEqual(window.tabs.count(), 2)
                self.assertEqual(a.view.transform(), transform)
                self.assertTrue(a.nodes[oid].isSelected())
                self.assertTrue(a.diff_shortcut.isEnabled())
                window.close_tab(window.tabs.indexOf(a))
                self.assertEqual(window.tabs.count(), 1)
                self.assertIsNone(a.loader.active)
                self.assertTrue(b.diff_shortcut.isEnabled())
            finally:
                window.close()
                application.processEvents()

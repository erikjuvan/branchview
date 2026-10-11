"""Application shell with an independent viewer for every repository."""
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QTabWidget, QFileDialog, QToolBar

from git_process import run_git
from viewer import Window


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


class WorkspaceWindow(QMainWindow):
    def __init__(self, path=None, **options):
        super().__init__()
        self.options = options
        self.setWindowTitle('Git Branch Viewer')
        self.resize(1400, 900)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.activate_tab)
        self.setCentralWidget(self.tabs)
        toolbar = QToolBar('Repositories')
        self.addToolBar(toolbar)
        toolbar.addAction('Open…', self.open)
        self.open_shortcut = QShortcut(QKeySequence.StandardKey.Open, self)
        self.open_shortcut.activated.connect(self.open)
        self.close_shortcut = QShortcut(QKeySequence('Ctrl+W'), self)
        self.close_shortcut.activated.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        self.next_shortcut = QShortcut(QKeySequence('Ctrl+Tab'), self)
        self.next_shortcut.activated.connect(lambda: self.cycle_tab(1))
        self.previous_shortcut = QShortcut(QKeySequence('Ctrl+Shift+Tab'), self)
        self.previous_shortcut.activated.connect(lambda: self.cycle_tab(-1))
        self.statusBar().showMessage('Open a repository to get started')
        if path:
            self.open_repository(path)

    def open(self):
        path = QFileDialog.getExistingDirectory(self, 'Select Git repository')
        if path:
            self.open_repository(path)

    def open_repository(self, path):
        # Normalize subdirectory opens to the checkout root when possible.
        try:
            path = run_git(str(Path(path).resolve()), ['rev-parse', '--show-toplevel']).decode().strip()
        except RuntimeError:
            path = str(Path(path).resolve())
        key = path_key(path)
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            if page.repository_key == key:
                self.tabs.setCurrentIndex(index)
                return page
        page = Window(open_callback=self.open, **self.options)
        page.repository_key = key
        page.repository_path = path
        page.setWindowFlags(Qt.WindowType.Widget)
        index = self.tabs.addTab(page, Path(path).name or path)
        self.tabs.setTabToolTip(index, path)
        self.update_titles()
        self.tabs.setCurrentIndex(index)
        self.activate_tab(index)
        page.load(path)
        return page

    def update_titles(self):
        names = [Path(self.tabs.widget(i).repository_path).name for i in range(self.tabs.count())]
        for index, name in enumerate(names):
            path = self.tabs.widget(index).repository_path
            self.tabs.setTabText(index, path if names.count(name) > 1 else name or path)

    def activate_tab(self, index):
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            for shortcut in page.findChildren(QShortcut):
                shortcut.setEnabled(i == index)
            if i != index and page.search_dialog is not None:
                page.search_dialog.hide()
        page = self.tabs.widget(index)
        self.setWindowTitle(f'{page.repository_path} — Git Branch Viewer' if page else 'Git Branch Viewer')
        if page:
            page.view.setFocus()

    def cycle_tab(self, direction):
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex()+direction) % self.tabs.count())

    def close_tab(self, index):
        page = self.tabs.widget(index)
        if page is None:
            return
        page.shutdown()
        self.tabs.removeTab(index)
        page.deleteLater()
        self.update_titles()

    def closeEvent(self, event):
        for index in range(self.tabs.count()):
            self.tabs.widget(index).shutdown()
        super().closeEvent(event)

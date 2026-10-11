"""Application shell with an independent viewer for every repository."""
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QTabWidget, QToolBar, QDialog, QMessageBox

from git_process import run_git
from viewer import Window
from folder_open_dialog import FolderOpenDialog
from repository_scan import RepositoryScanner
from vscode_open import SnapshotCacheDialog


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


class WorkspaceWindow(QMainWindow):
    def __init__(self, path=None, recursive=False, **options):
        super().__init__()
        self.options = options
        self.setStyleSheet('QMainWindow, QTabWidget, QTabBar { background: #252526; color: #cccccc; } '
                           'QTabWidget::pane { border: 1px solid #3c3c3c; } '
                           'QTabBar::tab { background: #2d2d30; color: #969696; padding: 7px 14px; } '
                           'QTabBar::tab:selected { background: #1e1e1e; color: #cccccc; } '
                           'QToolBar, QStatusBar { background: #2d2d30; color: #cccccc; } '
                           'QToolBar { border: none; spacing: 4px; padding: 2px; } '
                           'QToolBar QLabel, QToolBar QCheckBox { color: #cccccc; background: transparent; } '
                           'QToolBar QCheckBox { spacing: 5px; padding: 2px; } '
                           'QToolBar QCheckBox::indicator { width: 12px; height: 12px; '
                           'border: 1px solid #8e98a6; background: #1e1e1e; } '
                           'QToolBar QCheckBox::indicator:checked { background: #007acc; border-color: #007acc; } '
                           'QToolButton { color: #cccccc; padding: 5px; border: none; border-radius: 4px; } '
                           'QToolButton:hover { background: #37373d; }')
        self.scanner = RepositoryScanner(self)
        self.scanner.progress.connect(lambda message: self.statusBar().showMessage(message))
        self.scanner.ready.connect(self.scan_finished)
        self.scanner.failed.connect(self.scan_failed)
        self.batch_serial = 0
        self.batch_pending = set()
        self.batch_queue = []
        self.batch_errors = []
        self.setWindowTitle('Git Branch Viewer')
        self.resize(1400, 900)
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.activate_tab)
        self.setCentralWidget(self.tabs)
        toolbar = QToolBar('Repositories')
        self.repository_toolbar = toolbar
        toolbar.setMovable(False)
        self.mounted_page = None
        self.addToolBar(toolbar)
        toolbar.addAction('Open…', self.open)
        toolbar.addAction('Snapshots…', self.manage_snapshots)
        self.cancel_scan_action = toolbar.addAction('Cancel batch open', self.cancel_batch)
        self.cancel_scan_action.setEnabled(False)
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
            self.open_folder(path, recursive)

    def open(self):
        dialog = FolderOpenDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.open_folder(dialog.path.text().strip(), dialog.recursive.isChecked())

    def manage_snapshots(self):
        SnapshotCacheDialog(self).exec()

    def open_folder(self, path, recursive=False):
        self.cancel_batch()
        self.cancel_scan_action.setEnabled(True)
        self.statusBar().showMessage(f'Scanning {path}…')
        self.scanner.start(path, recursive)

    def cancel_batch(self):
        self.scanner.cancel()
        self.batch_serial += 1
        self.batch_queue.clear()
        pending = list(self.batch_pending)
        self.batch_pending.clear()
        for page in pending:
            page.load_error_handler = None
            page.load_cancel_handler = None
            page.cancel_load()
        self.cancel_scan_action.setEnabled(False)
        self.statusBar().showMessage('Batch opening canceled; existing tabs retained')

    def scan_failed(self, error):
        self.cancel_scan_action.setEnabled(False)
        self.statusBar().showMessage('Folder scan failed')
        QMessageBox.warning(self, 'Cannot scan folder', error)

    def scan_finished(self, result):
        self.batch_errors = list(result.errors)
        self.batch_queue = list(result.repositories)
        self.batch_total = len(result.repositories)
        self.batch_submodules = result.submodules
        self.batch_focus = None
        self.open_next(self.batch_serial)

    def open_next(self, serial):
        if serial != self.batch_serial:
            return
        if self.batch_queue:
            path = self.batch_queue.pop(0)
            self.open_repository(path, batch=serial)
            QTimer.singleShot(0, lambda: self.open_next(serial))
        else:
            self.finish_batch(serial)

    def batch_done(self, page, serial, error=None):
        if serial != self.batch_serial or page not in self.batch_pending:
            return
        self.batch_pending.remove(page)
        page.load_error_handler = None
        page.load_cancel_handler = None
        if error:
            self.batch_errors.append(f'{page.repository_path}: {error}')
        self.finish_batch(serial)

    def finish_batch(self, serial):
        if serial != self.batch_serial or self.batch_queue or self.batch_pending:
            return
        self.cancel_scan_action.setEnabled(False)
        self.statusBar().showMessage(f'Found {self.batch_total} repositories · {self.batch_submodules} submodule folders skipped')
        if self.batch_errors:
            QMessageBox.warning(self, 'Some folders could not be opened', '\n\n'.join(self.batch_errors))
            self.batch_errors.clear()
        elif not self.batch_total:
            self.statusBar().showMessage('No independent Git repositories found in the selected scan scope')

    def open_repository(self, path, batch=None):
        # Normalize subdirectory opens to the checkout root when possible.
        if batch is None:
            try:
                path = run_git(str(Path(path).resolve()), ['rev-parse', '--show-toplevel']).decode().strip()
            except RuntimeError:
                path = str(Path(path).resolve())
        key = path_key(path)
        for index in range(self.tabs.count()):
            page = self.tabs.widget(index)
            if page.repository_key == key:
                if batch is None or self.batch_focus is None:
                    self.tabs.setCurrentIndex(index)
                    if batch is not None:
                        self.batch_focus = page
                return page
        page = Window(open_callback=self.open, **self.options)
        page.repository_key = key
        page.repository_path = path
        page.setWindowFlags(Qt.WindowType.Widget)
        # The active repository's controls belong above the tab strip.
        # Inactive toolbars stay owned by their page, preserving widget state.
        page.removeToolBarBreak(page.load_toolbar)
        for toolbar in (page.graph_toolbar, page.load_toolbar):
            page.removeToolBar(toolbar)
            toolbar.hide()
        index = self.tabs.addTab(page, Path(path).name or path)
        self.tabs.setTabToolTip(index, path)
        self.update_titles()
        if batch is None or self.batch_focus is None:
            self.tabs.setCurrentIndex(index)
            if batch is not None:
                self.batch_focus = page
        self.activate_tab(self.tabs.currentIndex())
        if batch is not None:
            self.batch_pending.add(page)
            page.load_error_handler = lambda error: None
            page.load_cancel_handler = lambda: self.batch_done(page, batch)
            page.loader.ready.connect(lambda *_: self.batch_done(page, batch))
            page.loader.failed.connect(lambda error: self.batch_done(page, batch, error))
        page.load(path)
        return page

    def update_titles(self):
        names = [Path(self.tabs.widget(i).repository_path).name for i in range(self.tabs.count())]
        for index, name in enumerate(names):
            path = self.tabs.widget(index).repository_path
            self.tabs.setTabText(index, path if names.count(name) > 1 else name or path)

    def activate_tab(self, index):
        if self.mounted_page is not None:
            self.removeToolBarBreak(self.mounted_page.load_toolbar)
            for toolbar in (self.mounted_page.graph_toolbar, self.mounted_page.load_toolbar):
                self.removeToolBar(toolbar)
                toolbar.setParent(self.mounted_page)
                toolbar.hide()
            self.mounted_page = None
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            for shortcut in page.findChildren(QShortcut):
                shortcut.setEnabled(i == index)
            if i != index and page.search_dialog is not None:
                page.search_dialog.hide()
        page = self.tabs.widget(index)
        self.setWindowTitle(f'{page.repository_path} — Git Branch Viewer' if page else 'Git Branch Viewer')
        if page:
            self.addToolBar(page.graph_toolbar)
            self.addToolBarBreak()
            self.addToolBar(page.load_toolbar)
            page.graph_toolbar.show()
            page.load_toolbar.show()
            self.mounted_page = page
            page.view.setFocus()

    def cycle_tab(self, direction):
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex()+direction) % self.tabs.count())

    def close_tab(self, index):
        page = self.tabs.widget(index)
        if page is None:
            return
        page.shutdown()
        if page in self.batch_pending:
            self.batch_done(page, self.batch_serial)
        self.tabs.removeTab(index)
        page.deleteLater()
        self.update_titles()

    def closeEvent(self, event):
        self.cancel_batch()
        for index in range(self.tabs.count()):
            self.tabs.widget(index).shutdown()
        super().closeEvent(event)

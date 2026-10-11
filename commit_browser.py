"""A commit-pinned file browser; tree and preview reads stay off the UI thread."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QPlainTextEdit)
from background_task import BackgroundTask
from commit_files import read_tree, preview_file


class CommitBrowser(QDialog):
    def __init__(self, repo_path, commit, parent=None):
        super().__init__(parent)
        self.repo_path, self.commit = repo_path, commit
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f'{Path(repo_path).name} @ {commit[:12]} — Files')
        self.resize(1050, 720)
        box = QVBoxLayout(self)
        heading = QLabel(f'{repo_path}\nCommit: {commit}\nTracked contents at this commit; current checkout is unchanged.')
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        box.addWidget(heading)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Filter files by path…')
        box.addWidget(self.filter)
        splitter = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Files'])
        splitter.addWidget(self.tree)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        splitter.addWidget(self.preview)
        splitter.setSizes([330, 720])
        box.addWidget(splitter, 1)
        self.status = QLabel('Reading commit tree…')
        box.addWidget(self.status)
        self.tree_task = BackgroundTask(self)
        self.preview_task = BackgroundTask(self)
        self.tree_task.ready.connect(self.populate)
        self.tree_task.failed.connect(self.status.setText)
        self.preview_task.ready.connect(self.preview.setPlainText)
        self.preview_task.failed.connect(self.preview.setPlainText)
        self.filter.textChanged.connect(self.apply_filter)
        self.tree.currentItemChanged.connect(self.select_file)
        self.tree_task.start(lambda cancelled, _: read_tree(repo_path, commit, cancelled))

    def populate(self, entries):
        self.tree.clear()
        folders = {'': self.tree.invisibleRootItem()}
        for entry in entries:
            parts = entry.path.split('/')
            for depth in range(1, len(parts)):
                key = '/'.join(parts[:depth])
                if key not in folders:
                    parent = folders['/'.join(parts[:depth-1])]
                    folders[key] = QTreeWidgetItem(parent, [parts[depth-1]])
            item = QTreeWidgetItem(folders['/'.join(parts[:-1])], [parts[-1]])
            item.setData(0, Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(0, entry.path+'\n'+('Submodule reference' if entry.kind == 'commit' else entry.mode))
        self.status.setText(f'{len(entries):,} tracked files · select a file to preview')
        self.apply_filter(self.filter.text())

    def apply_filter(self, query):
        query = query.casefold()
        def visit(item):
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry is not None:
                visible = query in entry.path.casefold()
            else:
                matches = [visit(item.child(i)) for i in range(item.childCount())]
                visible = any(matches)
                if query and visible:
                    item.setExpanded(True)
            item.setHidden(not visible)
            return visible
        root = self.tree.invisibleRootItem()
        for index in range(root.childCount()):
            visit(root.child(index))

    def select_file(self, item, previous):
        self.preview_task.cancel()
        entry = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        self.selected_file = entry
        if entry is None:
            self.preview.clear()
            return
        self.preview.setPlainText('Reading '+entry.path+'…')
        self.preview_task.start(lambda cancelled, _: preview_file(self.repo_path, entry, cancelled))

    def closeEvent(self, event):
        self.tree_task.cancel()
        self.preview_task.cancel()
        super().closeEvent(event)

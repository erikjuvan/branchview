"""Lightweight, selection-aware shortcut help window."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QGridLayout


class ShortcutPanel(QDialog):
    def __init__(self, window):
        super().__init__(window, Qt.WindowType.Tool | Qt.WindowType.CustomizeWindowHint |
                         Qt.WindowType.WindowTitleHint | Qt.WindowType.WindowCloseButtonHint)
        self.setObjectName('ShortcutPanel')
        self.setWindowTitle('Shortcuts')
        self.setModal(False)
        self.setStyleSheet('QDialog#ShortcutPanel { background: #252526; } '
                           'QLabel { background: transparent; }')
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(6)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 2, 0, 2)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(3)
        self.grid.setColumnStretch(1, 1)
        box.addLayout(self.grid)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color: #969696; font-size: 9pt;')
        box.addWidget(self.note)
        self.entries = []
        self.setFixedWidth(440)

    def toggle(self):
        if self.isVisible():
            self.close()
        else:
            self.update_context(self.parentWidget())
            self.show()
            self.raise_()
            self.activateWindow()

    def _resize_to_contents(self):
        self.layout().invalidate()
        height = self.layout().totalHeightForWidth(self.width())
        self.setFixedHeight(max(height, self.layout().totalSizeHint().height()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F1:
            if not event.isAutoRepeat():
                self.close()
            event.accept()
        else:
            super().keyPressEvent(event)

    def update_context(self, window):
        selected = {item.oid for item in window.scene.selectedItems() if hasattr(item, 'oid')}
        count = len(selected)
        entries = []
        def add(shortcut, action, tooltip=''):
            key = shortcut.key().toString(QKeySequence.SequenceFormat.NativeText)
            entries.append((key, action, tooltip))
        if window.repo and window.repo.commits:
            add(window.search_shortcut, 'Search branches, hashes, messages')
        if window.display_nodes:
            add(window.fit_shortcut, 'Fit the entire graph')
            add(window.top_shortcut, 'Jump to and fit top commits')
            add(window.rearrange_shortcut, 'Reset history layout' if window.repo and window.repo.regular_history and not window.repo.branches_only else 'Rearrange visible nodes')
            if count == 1:
                add(window.child_shortcut, 'Go to child commit', 'Reveals hidden commits. Uses the first child in loaded history order.')
                add(window.parent_shortcut, 'Go to parent commit', 'Reveals hidden commits. Uses the first loaded Git parent.')
                add(window.browse_shortcut, 'Browse files at selected commit')
                add(window.vscode_shortcut, 'Open selected commit in VS Code')
                add(window.diff_shortcut, 'Diff selected commit', 'Compare against a parent; roots use the empty tree. Merge commits offer a parent selector.')
            elif count == 2:
                add(window.diff_shortcut, 'Compare the two selected commits')
            if count:
                add(window.hide_shortcut, 'Hide selected commits', 'Requires focus in the graph. Hides every displayed copy of the selected commit(s).')
            entries.append(('Ctrl+click', 'Add/remove a commit from selection', 'Click a node or its label while holding Ctrl.'))
        summary = f'{count} commit'+('s' if count != 1 else '')+' selected' if count else 'No commits selected'
        if window.loading:
            summary += ' · loading repository'
        self.summary.setText(summary)
        if not entries:
            note = 'Graph shortcuts appear when commits are loaded.' if window.loading else 'Open a repository to enable graph shortcuts.'
        elif count > 2:
            note = 'Select one or two commits to use D. Delete requires graph focus.'
        elif count:
            note = 'Delete requires graph focus. Commit details are in the sidebar.'
        else:
            note = 'Select a commit to enable diff and hide shortcuts.'
        if getattr(window, 'open_callback', None) is not None:
            for key, action in [('Ctrl+O', 'Open repositories from folder'), ('Ctrl+W', 'Close current repository tab'),
                                ('Ctrl+Tab', 'Next repository tab'), ('Ctrl+Shift+Tab', 'Previous repository tab')]:
                entries.append((QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText), action, ''))
        entries.append(('F1', 'Show / hide shortcuts', 'Esc or the title-bar X also closes this window.'))
        self.note.setText(note + '\nF1 or Esc closes this window.')
        if entries == self.entries:
            self._resize_to_contents()
            return
        self.entries = entries
        # Reuse rows to avoid flicker while selection-aware help changes.
        for row, (key, action, tooltip) in enumerate(entries):
            cell = self.grid.itemAtPosition(row, 0)
            if cell is None:
                badge = QLabel()
                badge.setTextFormat(Qt.TextFormat.PlainText)
                badge.setStyleSheet('background: #333333; color: #ffd166; border-radius: 3px; padding: 1px 5px;')
                description = QLabel()
                description.setWordWrap(True)
                self.grid.addWidget(badge, row, 0, Qt.AlignmentFlag.AlignLeft)
                self.grid.addWidget(description, row, 1)
            else:
                badge = cell.widget()
                description = self.grid.itemAtPosition(row, 1).widget()
            badge.setText(key)
            description.setText(action)
            badge.setToolTip(tooltip)
            description.setToolTip(tooltip)
        while self.grid.count() > 2*len(entries):
            widget = self.grid.takeAt(self.grid.count()-1).widget()
            widget.hide()
            widget.deleteLater()
        self._resize_to_contents()

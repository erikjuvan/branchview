"""Selection-aware help that remains above the scrolling commit details."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QGridLayout, QSizePolicy


class ShortcutPanel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName('ShortcutPanel')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.setStyleSheet('QFrame#ShortcutPanel { background: #252526; border-bottom: 1px solid #3c3c3c; } '
                           'QLabel { background: transparent; }')
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(4)
        heading = QLabel('Available graph shortcuts')
        heading.setStyleSheet('font-weight: bold; color: #80ead9;')
        box.addWidget(heading)
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
            note = 'Delete requires graph focus. Commit details remain below.'
        else:
            note = 'Select a commit to enable diff and hide shortcuts.'
        if getattr(window, 'open_callback', None) is not None:
            for key, action in [('Ctrl+O', 'Open repositories from folder'), ('Ctrl+W', 'Close current repository tab'),
                                ('Ctrl+Tab', 'Next repository tab'), ('Ctrl+Shift+Tab', 'Previous repository tab')]:
                entries.append((QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText), action, ''))
        self.note.setText(note)
        if entries == self.entries:
            return
        self.entries = entries
        # Reuse rows so the panel never temporarily collapses while rebuilding.
        # That would enlarge the branch list and clamp its scrollbar upward.
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

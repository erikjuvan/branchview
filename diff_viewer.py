"""Read-only, aligned tree comparisons shared by both commit diff dialogs."""
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import zip_longest
from subprocess import TimeoutExpired

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QTextCursor, QTextFormat
from PySide6.QtWidgets import (QWidget, QPlainTextEdit, QTextEdit, QVBoxLayout,
                               QSplitter, QListWidget, QLabel, QPushButton, QDialog)
from git_reader import read_changed_files, read_blob


@dataclass(frozen=True)
class DiffRow:
    old_number: int | None
    old_text: str
    new_number: int | None
    new_text: str
    changed: bool


def align_lines(before: str, after: str) -> list[DiffRow]:
    # Compare visible content across Windows/Unix line endings, while retaining
    # the distinction between a final newline and no final newline.
    normalized = [text.replace('\r\n', '\n').replace('\r', '\n') for text in (before, after)]
    old, new = [text.splitlines(keepends=True) for text in normalized]
    rows = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new).get_opcodes():
        for i, j in zip_longest(range(i1, i2), range(j1, j2)):
            rows.append(DiffRow(i+1 if i is not None else None,
                                old[i].rstrip('\r\n') if i is not None else '',
                                j+1 if j is not None else None,
                                new[j].rstrip('\r\n') if j is not None else '', tag != 'equal'))
    return rows


def line_endings(text: str) -> str:
    styles = []
    if '\r\n' in text:
        styles.append('CRLF')
    remainder = text.replace('\r\n', '')
    if '\n' in remainder:
        styles.append('LF')
    if '\r' in remainder:
        styles.append('CR')
    return '/'.join(styles) or 'none'


class LineNumbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_numbers(event)


class DiffEditor(QPlainTextEdit):
    def __init__(self, color):
        super().__init__()
        self.numbers = []
        self.change_color = color
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.setStyleSheet('''
            QPlainTextEdit { background: #1e1e1e; color: #cccccc; border: none; }
            QScrollBar:vertical { background: #1e1e1e; width: 12px; margin: 0; }
            QScrollBar:horizontal { background: #1e1e1e; height: 12px; margin: 0; }
            QScrollBar::handle { background: #424242; border-radius: 4px; }
            QScrollBar::handle:hover { background: #4f4f4f; }
            QScrollBar::handle:vertical { min-height: 24px; }
            QScrollBar::handle:horizontal { min-width: 24px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
            QScrollBar::add-page, QScrollBar::sub-page { background: none; }
            QAbstractScrollArea::corner { background: #1e1e1e; }
        ''')
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.gutter = LineNumbers(self)
        self.blockCountChanged.connect(self.update_gutter_width)
        self.updateRequest.connect(self.update_gutter)
        self.update_gutter_width()

    def gutter_width(self):
        largest = max((n or 0 for n in self.numbers), default=0)
        return 18 + self.fontMetrics().horizontalAdvance('9') * max(3, len(str(largest)))

    def update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.gutter.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))

    def paint_numbers(self, event):
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor('#1e1e1e'))
        painter.setPen(QColor('#858585'))
        painter.setFont(self.font())
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        while block.isValid() and top <= event.rect().bottom():
            height = self.blockBoundingRect(block).height()
            index = block.blockNumber()
            if block.isVisible() and index < len(self.numbers) and self.numbers[index] is not None:
                painter.drawText(0, round(top), self.gutter.width()-8, round(height),
                                 Qt.AlignmentFlag.AlignRight, str(self.numbers[index]))
            top += height
            block = block.next()

    def set_rows(self, rows, side):
        self.numbers = [getattr(row, side+'_number') for row in rows]
        self.setPlainText('\n'.join(getattr(row, side+'_text') for row in rows))
        selections = []
        for index, row in enumerate(rows):
            if row.changed:
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(self.document().findBlockByNumber(index))
                color = self.change_color if self.numbers[index] is not None else '#252526'
                selection.format.setBackground(QColor(color))
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                selections.append(selection)
        self.setExtraSelections(selections)
        self.update_gutter_width()
        self.gutter.update()


class DiffViewer(QWidget):
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.changes = []
        self.source = self.target = None
        self._syncing = False
        self.exports = []
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        splitter = QSplitter()
        self.files = QListWidget()
        self.files.setMinimumWidth(150)
        splitter.addWidget(self.files)
        columns = QSplitter()
        self.left = DiffEditor('#512d35')
        self.right = DiffEditor('#244b37')
        self.old_title = QLabel()
        self.new_title = QLabel()
        self.open_before = QPushButton('Open before in VS Code')
        self.open_after = QPushButton('Open after in VS Code')
        self.open_before.setEnabled(False)
        self.open_after.setEnabled(False)
        self.open_before.clicked.connect(lambda: self.open_historical_file(True))
        self.open_after.clicked.connect(lambda: self.open_historical_file(False))
        for title, editor, button in [(self.old_title, self.left, self.open_before), (self.new_title, self.right, self.open_after)]:
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            panel = QWidget()
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(6, 6, 6, 0)
            layout.addWidget(title)
            layout.addWidget(button)
            layout.addWidget(editor, 1)
            columns.addWidget(panel)
        splitter.addWidget(columns)
        splitter.setSizes([230, 950])
        box.addWidget(splitter, 1)
        self.files.currentRowChanged.connect(self.show_file)
        for orientation in ('verticalScrollBar', 'horizontalScrollBar'):
            a, b = getattr(self.left, orientation)(), getattr(self.right, orientation)()
            a.valueChanged.connect(lambda value, other=b: self.sync_scroll(other, value))
            b.valueChanged.connect(lambda value, other=a: self.sync_scroll(other, value))

    def sync_scroll(self, other, value):
        if not self._syncing:
            self._syncing = True
            other.setValue(value)
            self._syncing = False

    def compare(self, source, target):
        self.source, self.target = source, target
        self.files.blockSignals(True)
        self.files.clear()
        self.changes = []
        self.open_before.setEnabled(False)
        self.open_after.setEnabled(False)
        self.left.set_rows([], 'old')
        self.right.set_rows([], 'new')
        self.old_title.setText('Before · ' + (source[:12] if source else 'empty tree'))
        self.new_title.setText('After · ' + target[:12])
        try:
            self.changes = read_changed_files(self.repo, source, target)
            for change in self.changes:
                path = (f'{change.old_path} → {change.new_path}' if change.old_path != change.new_path
                        else change.new_path)
                self.files.addItem(f'{change.status[0]}  {path}')
                self.files.item(self.files.count()-1).setToolTip(path)
            self.status.setText(f'{len(self.changes)} changed files · Red: removed · Green: added'
                                if self.changes else 'No changes between these commits.')
        except (RuntimeError, OSError, ValueError, TimeoutExpired) as exc:
            self.status.setText(f'Cannot load comparison: {exc}')
        finally:
            self.files.blockSignals(False)
        if self.changes:
            self.files.setCurrentRow(0)

    def show_file(self, index):
        if index < 0 or index >= len(self.changes):
            return
        change = self.changes[index]
        self.open_before.setEnabled(bool(self.source and change.old_blob.strip('0') and change.old_mode != '160000'))
        self.open_after.setEnabled(bool(change.new_blob.strip('0') and change.new_mode != '160000'))
        self.old_title.setText(f'Before · {self.source[:12] if self.source else "empty tree"}\n{change.old_path}')
        self.new_title.setText(f'After · {self.target[:12]}\n{change.new_path}')
        self.left.set_rows([], 'old')
        self.right.set_rows([], 'new')
        try:
            if '160000' in (change.old_mode, change.new_mode):
                self.status.setText('Submodule change · commit IDs shown below')
                rows = align_lines(change.old_blob+'\n' if change.old_blob.strip('0') else '',
                                   change.new_blob+'\n' if change.new_blob.strip('0') else '')
            else:
                old = read_blob(self.repo, change.old_blob)
                new = read_blob(self.repo, change.new_blob)
                if b'\0' in old or b'\0' in new:
                    self.status.setText('Binary file changed · text preview unavailable')
                    return
                before, after = old.decode('utf-8', errors='replace'), new.decode('utf-8', errors='replace')
                if max(before.count('\n'), after.count('\n')) > 20_000:
                    raise ValueError('File has too many lines for the text preview (limit: 20,000).')
                rows = align_lines(before, after)
                endings = []
                old_endings, new_endings = line_endings(before), line_endings(after)
                if old and new and old_endings != new_endings:
                    endings.append(f'Line endings: {old_endings} → {new_endings}')
                for label, data in [('Before', old), ('After', new)]:
                    if data and not data.endswith(b'\n'):
                        endings.append(f'{label}: no newline at end of file')
                added = sum(row.changed and row.new_number is not None for row in rows)
                removed = sum(row.changed and row.old_number is not None for row in rows)
                self.status.setText(f'{change.status} · +{added} / −{removed} lines · '
                                    f'mode {change.old_mode} → {change.new_mode}'
                                    + (' · ' + ' · '.join(endings) if endings else ''))
            self.left.set_rows(rows, 'old')
            self.right.set_rows(rows, 'new')
            first_change = next((i for i, row in enumerate(rows) if row.changed), 0)
            for editor in (self.left, self.right):
                editor.verticalScrollBar().setValue(max(0, first_change-3))
        except (RuntimeError, OSError, ValueError, TimeoutExpired) as exc:
            self.status.setText(f'Cannot preview file: {exc}')

    def open_historical_file(self, before):
        from commit_files import TreeFile
        from vscode_open import SnapshotOpenDialog
        index = self.files.currentRow()
        if index < 0 or index >= len(self.changes):
            return
        change = self.changes[index]
        oid = self.source if before else self.target
        path, blob, mode = ((change.old_path, change.old_blob, change.old_mode) if before else
                            (change.new_path, change.new_blob, change.new_mode))
        if not oid or not blob.strip('0') or mode == '160000':
            return
        dialog = SnapshotOpenDialog(self.repo.path, oid, self, TreeFile(path, blob, mode, 'blob'))
        self.exports.append(dialog)
        dialog.destroyed.connect(lambda: self.exports.remove(dialog) if dialog in self.exports else None)
        owner = self.window()
        if isinstance(owner, QDialog):
            owner.finished.connect(dialog.close)
        dialog.show()

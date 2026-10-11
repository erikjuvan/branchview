"""Persistent, per-checkout status with independent cancellable background reads."""
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QSizePolicy

from background_task import BackgroundTask
from repository_status import read_repository_status


class RepositoryStatusPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('RepositoryStatusPanel')
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.setStyleSheet('QFrame#RepositoryStatusPanel { border-bottom: 1px solid #3c3c3c; }')
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(4)
        self.heading = QLabel('Repository status')
        self.heading.setStyleSheet('font-weight: bold;')
        self.branch = QLabel('Open a repository')
        self.changes = QLabel()
        self.notice = QLabel()
        for label in (self.heading, self.branch, self.changes, self.notice):
            label.setWordWrap(True)
            # Branch names are repository data, never HTML.
            label.setTextFormat(Qt.TextFormat.PlainText)
            box.addWidget(label)
        self.notice.setStyleSheet('color: #969696; font-size: 9pt;')
        self.notice.hide()
        self.path = None
        self.summary = None
        self.pending = False
        self.closed = False
        self.task = BackgroundTask(self)
        self.task.ready.connect(self.received)
        self.task.failed.connect(self.failed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.start_read)
        self.setToolTip('Status of this checkout. Ahead/behind uses locally known upstream refs; no fetch is performed.\n'
                        'Counts are files. A file can have both staged and unstaged changes. Conflicts are counted separately.')

    def refresh(self, path):
        if self.closed or not path:
            return
        path = os.path.normcase(str(Path(path).expanduser().resolve()))
        if path != self.path:
            self.task.cancel()
            self.summary = None
            self.pending = False
            self.branch.setText('Reading checkout…')
            self.changes.clear()
        self.path = path
        self.notice.setToolTip('')
        self.notice.setText('Refreshing…' if self.summary else 'Reading status…')
        self.notice.show()
        self.timer.start()

    def start_read(self):
        if self.task.active is not None:
            self.pending = True
            return
        path = self.path
        self.task.start(lambda cancelled, progress: read_repository_status(path, cancelled))

    def received(self, status):
        self.summary = status
        if status.bare:
            branch, changes = 'Bare repository', 'No working tree'
        else:
            branch = status.branch or f'Detached HEAD · {status.oid[:8]}'
            if status.unborn:
                branch += ' · No commits yet'
            if status.upstream:
                branch += f' → {status.upstream}'
                if status.ahead is not None and status.behind is not None:
                    branch += f' · ↑{status.ahead} ↓{status.behind}' if status.ahead or status.behind else ' · Up to date'
                else:
                    branch += ' · Upstream unavailable'
            counts = [(status.conflicts, 'conflicts'), (status.staged, 'staged'),
                      (status.unstaged, 'unstaged'), (status.untracked, 'untracked')]
            changes = ' · '.join(f'{count} {label}' for count, label in counts if count) or 'Working tree clean'
            if status.operation:
                changes = status.operation + ' · ' + changes
        self.branch.setText(branch)
        self.changes.setText(changes)
        self.changes.setStyleSheet('color: #ffb86c;' if status.conflicts or status.operation else '')
        self.notice.hide()
        self.finish_read()

    def failed(self, error):
        self.notice.setText('Status unavailable' + (' · Previous status shown' if self.summary else ''))
        self.notice.setToolTip(error)
        self.notice.show()
        if self.summary is None:
            self.branch.setText('Status unavailable')
            self.changes.clear()
        self.finish_read()

    def finish_read(self):
        if self.pending or self.timer.isActive():
            self.pending = False
            self.notice.setText('Refreshing…')
            self.notice.show()
            self.timer.start()

    def shutdown(self):
        self.closed = True
        self.timer.stop()
        self.task.cancel()

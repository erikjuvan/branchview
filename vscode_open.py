"""VS Code discovery and asynchronous snapshot preparation UI."""
import os
import json
from pathlib import Path
import shutil
import subprocess

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog,
                               QDialogButtonBox, QListWidget, QListWidgetItem)
from PySide6.QtCore import Qt
from background_task import BackgroundTask
from commit_snapshot import export_snapshot, cache_directory, remove_snapshot


def find_vscode():
    settings = QSettings('GitBranchViewer', 'GitBranchViewer')
    saved = settings.value('vscode/executable', '')
    candidates = [saved] if saved else []
    for name in ('code', 'code-insiders'):
        command = shutil.which(name)
        if command:
            if os.name == 'nt' and Path(command).suffix.lower() in ('.cmd', '.bat'):
                candidates.extend([str(Path(command).parent.parent/'Code.exe'), str(Path(command).parent.parent/'Code - Insiders.exe')])
            else:
                candidates.append(command)
    if os.name == 'nt':
        for base in (os.environ.get('LOCALAPPDATA', '')+'/Programs', os.environ.get('ProgramFiles', '')):
            candidates.extend([str(Path(base)/'Microsoft VS Code'/'Code.exe'),
                               str(Path(base)/'Microsoft VS Code Insiders'/'Code - Insiders.exe')])
    return next((path for path in candidates if path and Path(path).is_file()), None)


def launch_vscode(executable, snapshot):
    args = [executable, '--new-window', str(snapshot.workspace)]
    if snapshot.file is not None:
        args.extend(['--goto', str(snapshot.file)])
    return subprocess.Popen(args, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


class SnapshotOpenDialog(QDialog):
    def __init__(self, repo_path, commit, parent=None, entry=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f'Open {Path(repo_path).name} @ {commit[:12]} in VS Code')
        self.resize(650, 190)
        box = QVBoxLayout(self)
        info = QLabel('Preparing a separate cached copy of tracked files.\n'
                      'Edits in VS Code affect that copy only. Your checkout stays unchanged.')
        info.setWordWrap(True)
        box.addWidget(info)
        self.status = QLabel('Preparing snapshot…')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        box.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self.close)
        box.addWidget(self.buttons)
        self.task = BackgroundTask(self)
        self.task.progress.connect(self.status.setText)
        self.task.failed.connect(self.failed)
        self.task.ready.connect(self.open_ready)
        self.executable = find_vscode()
        if self.executable is None:
            self.executable, _ = QFileDialog.getOpenFileName(parent, 'Locate VS Code executable', '',
                                                          'Executables (*.exe)' if os.name == 'nt' else 'All files (*)')
            if self.executable:
                QSettings('GitBranchViewer', 'GitBranchViewer').setValue('vscode/executable', self.executable)
        if self.executable:
            self.task.start(lambda cancelled, progress: export_snapshot(repo_path, commit, cancelled, progress, entry))
        else:
            self.failed('VS Code executable was not selected. Install VS Code or try again to choose its executable.')

    def failed(self, error):
        self.status.setText(error)
        self.buttons.setStandardButtons(QDialogButtonBox.StandardButton.Close)

    def open_ready(self, snapshot):
        try:
            launch_vscode(self.executable, snapshot)
        except OSError as exc:
            self.failed(str(exc))
            return
        if snapshot.notices:
            notes = list(snapshot.notices[:8])
            if len(snapshot.notices) > 8:
                notes.append(f'… {len(snapshot.notices)-8} more notices. Full details: {snapshot.directory / "ABOUT.txt"}')
            self.status.setText('Opened in VS Code.\n\n'+'\n'.join(notes))
            self.buttons.setStandardButtons(QDialogButtonBox.StandardButton.Close)
        else:
            self.close()

    def closeEvent(self, event):
        self.task.cancel()
        super().closeEvent(event)


class SnapshotCacheDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Cached commit snapshots')
        self.resize(850, 400)
        box = QVBoxLayout(self)
        label = QLabel('Snapshots remain after the app closes. Delete only copies you have finished using;\n'
                       'VS Code may still have them open. This also deletes any edits in those copies.')
        label.setWordWrap(True)
        box.addWidget(label)
        self.list = QListWidget()
        box.addWidget(self.list)
        for manifest in cache_directory().glob('*/*/*/snapshot.json'):
            try:
                metadata = json.loads(manifest.read_text(encoding='utf-8'))
                item = QListWidgetItem(f'{metadata["source"]} @ {metadata["commit"][:12]} · {metadata["scope"] or "whole commit"}')
                item.setData(Qt.ItemDataRole.UserRole, str(manifest.parent))
                item.setToolTip(str(manifest.parent))
                self.list.addItem(item)
            except (OSError, ValueError, KeyError):
                pass
        self.status = QLabel(f'{self.list.count()} cached snapshots')
        box.addWidget(self.status)
        delete = QPushButton('Delete selected snapshot')
        delete.clicked.connect(self.delete_selected)
        box.addWidget(delete)

    def delete_selected(self):
        item = self.list.currentItem()
        if item:
            try:
                remove_snapshot(item.data(Qt.ItemDataRole.UserRole))
                self.list.takeItem(self.list.row(item))
                self.status.setText(f'{self.list.count()} cached snapshots')
            except (OSError, ValueError) as exc:
                self.status.setText(str(exc))

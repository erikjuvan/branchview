"""Open live repository checkouts in external desktop applications."""
import os
from pathlib import Path
import shutil
import subprocess

from PySide6.QtCore import Qt, QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QToolButton, QMenu, QFileDialog, QMessageBox, QSizePolicy

from branch_panel import worktree_path
from vscode_open import find_vscode


PROGRAMS = {'explorer': 'Explorer', 'vscode': 'VS Code', 'gitextensions': 'Git Extensions'}


def matching_worktrees(repo, selected):
    """Only a checkout at the selected commit is an automatic target."""
    if not repo or len(selected) != 1:
        return []
    oid = next(iter(selected))
    return [wt for wt in repo.worktrees if wt.active and wt.head == oid]


def find_gitextensions():
    saved = QSettings('GitBranchViewer', 'GitBranchViewer').value('gitextensions/executable', '')
    candidates = [saved, shutil.which('GitExtensions.exe'), shutil.which('gitextensions')]
    if os.name == 'nt':
        for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            base = os.environ.get(key)
            if base:
                candidates.extend([str(Path(base)/'Git Extensions'/'GitExtensions.exe'),
                                   str(Path(base)/'GitExtensions'/'GitExtensions.exe'),
                                   str(Path(base)/'Programs'/'Git Extensions'/'GitExtensions.exe')])
    return next((path for path in candidates if path and Path(path).is_file()), None)


def launch_checkout(program, path, executable=None):
    directory = str(Path(path).resolve())
    if not Path(directory).is_dir():
        raise OSError('Checkout directory is unavailable: '+directory)
    if program == 'explorer':
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(directory)):
            raise OSError('Cannot open folder: '+directory)
        return
    args = ([executable, '--new-window', directory] if program == 'vscode' else
            [executable, 'browse', directory])
    return subprocess.Popen(args, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


class RepositoryOpenPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.repo = None
        self.selected = set()
        self.preferred_path = None
        self.matches = []
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 6)
        row.setSpacing(6)
        self.target = QLabel()
        self.target.setTextFormat(Qt.TextFormat.PlainText)
        self.target.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.target, 1)
        self.buttons = {}
        for program, title in PROGRAMS.items():
            button = QToolButton()
            button.setText(title)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            button.setMenu(QMenu(button))
            button.clicked.connect(lambda _=False, p=program: self.open_target(p))
            self.buttons[program] = button
            row.addWidget(button)
        self.set_context(None, set())

    def set_context(self, repo, selected, preferred_path=None):
        self.repo = repo
        self.selected = set(selected)
        self.preferred_path = preferred_path
        self.matches = matching_worktrees(repo, selected)
        explicit = next((wt for wt in repo.worktrees if wt.path == preferred_path
                         and wt.prunable is None and not wt.bare), None) if repo else None
        if explicit:
            self.matches = [explicit]
        path = self.matches[0].path if len(self.matches) == 1 else repo.path if repo else ''
        purple = bool(self.matches) and (len(self.matches) > 1 or
                                         Path(path).resolve() != Path(repo.path).resolve())
        caption = ('Choose worktree ('+str(len(self.matches))+')' if len(self.matches) > 1 else
                   ('Open worktree: ' if purple else 'Open repo: ')+worktree_path(repo.path, path)
                   if repo else 'Open repo')
        self.target.setText(caption)
        self.target.setToolTip('\n'.join(wt.path for wt in self.matches) if purple else path)
        self.target.setStyleSheet('color: '+('#c792ea' if purple else '#969696')+';')
        for program, button in self.buttons.items():
            button.setEnabled(repo is not None)
            button.setStyleSheet('QToolButton { color: '+('#c792ea' if purple else '#cccccc')+'; '
                                'background: #2d2d30; border: 1px solid #555555; border-radius: 4px; '
                                'padding: 4px 8px; padding-right: 27px; } '
                                'QToolButton:hover { background: #37373d; border-color: #777777; } '
                                'QToolButton:pressed { background: #094771; } '
                                'QToolButton:disabled { color: #808080; border-color: #3c3c3c; } '
                                'QToolButton::menu-button { subcontrol-origin: padding; '
                                'subcontrol-position: top right; width: 17px; '
                                'border-left: 1px solid #454545; '
                                'border-top-right-radius: 3px; border-bottom-right-radius: 3px; }')
            button.setToolTip(('Choose a matching worktree' if len(self.matches) > 1 else
                               'Open '+path)+' in '+PROGRAMS[program]+'\nArrow: choose current repo or another worktree')
            menu = button.menu()
            menu.clear()
            if repo:
                self.add_target(menu, 'Current repo · .', program, repo.path)
                for wt in sorted(repo.worktrees, key=lambda wt: wt.path.casefold()):
                    if wt.bare or wt.prunable is not None:
                        continue
                    branch = wt.branch.removeprefix('refs/heads/') if wt.branch else 'detached HEAD'
                    self.add_target(menu, branch+' · '+worktree_path(repo.path, wt.path), program, wt.path)

    def add_target(self, menu, text, program, path):
        action = menu.addAction(text)
        action.setToolTip(path)
        action.triggered.connect(lambda _=False: self.open_path(program, path))

    def open_target(self, program):
        if not self.repo:
            return
        if len(self.matches) > 1:
            menu = QMenu(self)
            for wt in self.matches:
                branch = wt.branch.removeprefix('refs/heads/') if wt.branch else 'detached HEAD'
                self.add_target(menu, branch+' · '+worktree_path(self.repo.path, wt.path), program, wt.path)
            button = self.buttons[program]
            menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
            menu.deleteLater()
            return
        self.open_path(program, self.matches[0].path if self.matches else self.repo.path)

    def open_path(self, program, path):
        executable = None
        if program != 'explorer':
            executable = find_vscode() if program == 'vscode' else find_gitextensions()
            if not executable:
                executable, _ = QFileDialog.getOpenFileName(self, 'Locate '+PROGRAMS[program]+' executable', '',
                                                           'Executables (*.exe)' if os.name == 'nt' else 'All files (*)')
                if not executable:
                    return
                QSettings('GitBranchViewer', 'GitBranchViewer').setValue(program+'/executable', executable)
        try:
            launch_checkout(program, path, executable)
        except OSError as exc:
            QMessageBox.warning(self, 'Cannot open '+PROGRAMS[program], str(exc))

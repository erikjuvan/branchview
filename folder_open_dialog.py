"""Choose a repository or containing folder and the discovery depth."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QCheckBox, QDialogButtonBox,
                               QFileDialog)


class FolderOpenDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Open repositories from folder')
        self.resize(620, 180)
        box = QVBoxLayout(self)
        box.addWidget(QLabel('Open a repository or a folder containing repositories.'))
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText('Folder path')
        row.addWidget(self.path)
        browse = QPushButton('Browse…')
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        box.addLayout(row)
        self.recursive = QCheckBox('Recursive: also scan deeper subfolders')
        box.addWidget(self.recursive)
        note = QLabel('Default: check this folder and its immediate subfolders.\n'
                      'Submodules are excluded. Existing tabs stay open.')
        note.setWordWrap(True)
        box.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        self.open_button = buttons.button(QDialogButtonBox.StandardButton.Open)
        self.open_button.setEnabled(False)
        self.path.textChanged.connect(lambda value: self.open_button.setEnabled(bool(value.strip())))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)

    def browse(self):
        path = QFileDialog.getExistingDirectory(self, 'Select repository or containing folder', self.path.text())
        if path:
            self.path.setText(path)

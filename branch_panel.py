"""A searchable list of the branch refs in the current repository snapshot."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem
from PySide6.QtGui import QColor
from branch_colors import remote_name, remote_color


class BranchPanel(QWidget):
    branch_clicked = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.repo = None
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(4)
        self.heading = QLabel('Branches (0)')
        box.addWidget(self.heading)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Filter branches…')
        self.filter.textChanged.connect(self.filter_branches)
        box.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setMinimumHeight(50)
        self.list.itemClicked.connect(self.activate)
        self.list.itemActivated.connect(self.activate)
        box.addWidget(self.list, 1)

    def set_repository(self, repo):
        if self.repo is repo:
            return
        self.repo = repo
        selected = self.list.currentItem()
        selected_name = selected.text() if selected else None
        self.list.clear()
        branches = [(name, oid, repo.branch_refs.get(name, 'refs/heads/'+name))
                    for oid, names in repo.branches.items() for name in names] if repo else []
        branches.sort(key=lambda entry: (entry[2].startswith('refs/remotes/'), entry[0].casefold()))
        for name, oid, ref in branches:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, (name, oid))
            item.setToolTip(f'{ref}\n{oid}')
            remote = remote_name(repo, name)
            item.setForeground(remote_color(remote) if remote is not None else QColor('#75baff'))
            if remote is not None:
                item.setToolTip(item.toolTip()+'\nRemote: '+remote)
            self.list.addItem(item)
            if name == selected_name:
                self.list.setCurrentItem(item)
        self.heading.setText(f'Branches ({len(branches):,})')
        self.heading.setToolTip('Local branches: blue. Remote branches: muted teal, with a stable shade per remote.\n'
                                'Checked-out worktree labels in the graph remain purple.')
        self.filter_branches(self.filter.text())

    def filter_branches(self, query):
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(query.casefold() not in item.text().casefold())

    def activate(self, item):
        name, oid = item.data(Qt.ItemDataRole.UserRole)
        self.branch_clicked.emit(name, oid)

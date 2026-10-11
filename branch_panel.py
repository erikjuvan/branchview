"""Searchable HEAD, branch and tag refs in the current repository snapshot."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QTabBar
from PySide6.QtGui import QColor
from branch_colors import remote_name, remote_color


class BranchList(QListWidget):
    def resizeEvent(self, event):
        current = self.currentItem()
        keep_visible = (current is not None and not current.isHidden()
                        and self.viewport().rect().intersects(self.visualItemRect(current)))
        super().resizeEvent(event)
        # Selection adds shortcut rows above this list. Keep a visible current
        # branch in view when those rows reduce the list's available height.
        if keep_visible and event.size().height() < event.oldSize().height():
            self.scrollToItem(current)


class BranchPanel(QWidget):
    branch_clicked = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.repo = None
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(4)
        self.heading = QLabel('All refs (0)')
        box.addWidget(self.heading)
        self.tabs = QTabBar()
        self.tabs.setStyleSheet('QTabBar::tab { background: #2d2d30; color: #cccccc; '
                               'border: 1px solid #3c3c3c; padding: 4px 10px; } '
                               'QTabBar::tab:selected { background: #094771; color: #ffffff; '
                               'border-bottom: 2px solid #75baff; } '
                               'QTabBar::tab:hover { background: #37373d; }')
        for title in ('All refs', 'Branches', 'Tags'):
            self.tabs.addTab(title)
        self.tabs.setExpanding(True)
        box.addWidget(self.tabs)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Filter refs…')
        self.filter.textChanged.connect(self.filter_branches)
        box.addWidget(self.filter)
        self.list = BranchList()
        self.list.setMinimumHeight(50)
        self.list.itemClicked.connect(self.activate)
        self.list.itemActivated.connect(self.activate)
        box.addWidget(self.list, 1)
        self.tabs.currentChanged.connect(lambda _: self.filter_branches(self.filter.text()))

    def set_repository(self, repo):
        if self.repo is repo:
            return
        self.repo = repo
        selected = self.list.currentItem()
        selected_ref = selected.data(Qt.ItemDataRole.UserRole+2) if selected else None
        vertical_scroll = self.list.verticalScrollBar().value()
        horizontal_scroll = self.list.horizontalScrollBar().value()
        selected_item = None
        self.list.clear()
        branches = [(name, oid, repo.branch_refs.get(name, 'refs/heads/'+name))
                    for oid, names in repo.branches.items() for name in names] if repo else []
        branches.sort(key=lambda entry: (entry[2].startswith('refs/remotes/'), entry[0].casefold()))
        entries = []
        if repo and repo.head_oid:
            location = repo.head_ref.removeprefix('refs/heads/') if repo.head_ref else 'detached'
            entries.append(('HEAD', repo.head_oid, 'HEAD', 'head', 'HEAD → '+location))
        entries.extend((name, oid, ref, 'branch', name) for name, oid, ref in branches)
        if repo:
            entries.extend((name, oid, 'refs/tags/'+name, 'tag', 'tag: '+name)
                           for name, oid in sorted(repo.tags.items(), key=lambda entry: entry[0].casefold()))
        for name, oid, ref, kind, label in entries:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, (name, oid))
            item.setData(Qt.ItemDataRole.UserRole+1, kind)
            item.setData(Qt.ItemDataRole.UserRole+2, ref)
            item.setToolTip(f'{ref}\n{oid}')
            remote = remote_name(repo, name) if kind == 'branch' else None
            color = '#c792ea' if kind == 'head' else '#d8ab65' if kind == 'tag' else '#75baff'
            item.setForeground(remote_color(remote) if remote is not None else QColor(color))
            if kind == 'head' or ref == repo.head_ref:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setToolTip(item.toolTip()+'\nCurrent checkout: '+repo.path)
            if remote is not None:
                item.setToolTip(item.toolTip()+'\nRemote: '+remote)
            self.list.addItem(item)
            if ref == selected_ref:
                selected_item = item
        self.heading.setToolTip('HEAD: current checkout, purple. Current branch: bold.\n'
                                'Local branches: blue. Remote branches: teal. Tags: gold.')
        self.filter_branches(self.filter.text())
        self.list.setCurrentItem(selected_item)
        # Rebuild the filtered layout before restoring the viewport. Restoring
        # selection while rows are still unfiltered can scroll it out of view.
        self.list.doItemsLayout()
        self.list.verticalScrollBar().setValue(vertical_scroll)
        self.list.horizontalScrollBar().setValue(horizontal_scroll)

    def filter_branches(self, query):
        category = (None, 'branch', 'tag')[self.tabs.currentIndex()]
        count = 0
        for index in range(self.list.count()):
            item = self.list.item(index)
            kind = item.data(Qt.ItemDataRole.UserRole+1)
            matches_category = category is None or kind == category
            count += matches_category
            search = item.text()
            item.setHidden(not matches_category or query.casefold() not in search.casefold())
        self.heading.setText(f'{self.tabs.tabText(self.tabs.currentIndex())} ({count:,})')

    def activate(self, item):
        name, oid = item.data(Qt.ItemDataRole.UserRole)
        self.branch_clicked.emit(name, oid)

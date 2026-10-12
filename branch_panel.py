"""Searchable refs and worktree checkouts in the current repository snapshot."""
from pathlib import Path
import os
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QRect, QPointF
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QTabBar, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication
from PySide6.QtGui import QColor, QPen, QFont, QFontMetrics
from branch_colors import remote_name, remote_color
from git_reader import opened_worktree
from theme import TAB_STYLESHEET


BADGE_ROLE = Qt.ItemDataRole.UserRole+3
SEARCH_ROLE = Qt.ItemDataRole.UserRole+4
PATH_ROLE = Qt.ItemDataRole.UserRole+5
DETAILS_ROLE = Qt.ItemDataRole.UserRole+6


def worktree_path(root, path):
    """Use relative paths, including siblings; different drives stay absolute."""
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:
        return Path(path).as_posix()


class WorktreeBadgeDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        badge = index.data(BADGE_ROLE)
        paths = index.data(PATH_ROLE) or []
        details = index.data(DETAILS_ROLE)
        if not badge and not paths:
            return super().paint(painter, option, index)
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        badge_width = styled.fontMetrics.horizontalAdvance(badge)+12 if badge else 0
        bracket_font = QFont(styled.font)
        bracket_font.setBold(False)
        bracket_font.setItalic(False)
        bracket_metrics = QFontMetrics(bracket_font)
        bracket_width = bracket_metrics.horizontalAdvance('[')+bracket_metrics.horizontalAdvance(']')
        path_font = QFont(bracket_font)
        path_font.setItalic(True)
        path_metrics = QFontMetrics(path_font)
        path = ', '.join(paths).replace('\n', ' ')
        path_width = min(path_metrics.horizontalAdvance(path)+bracket_width+12,
                         int(option.rect.width()*0.45),
                         max(0, option.rect.width()-badge_width-40)) if paths else 0
        width = badge_width+path_width+(6 if badge_width and path_width else 0)
        parts = [styled.text, *([details] if details else [])]
        styled.text = ' · '.join(part.replace('\n', ' ') for part in parts)
        styled.text = styled.fontMetrics.elidedText(styled.text, Qt.TextElideMode.ElideRight,
                                                   max(0, styled.rect.width()-width-12))
        style = styled.widget.style() if styled.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        painter.save()
        painter.setFont(styled.font)
        right = option.rect.right()-4
        if path_width:
            rect = QRect(right-path_width+1, option.rect.top()+2, path_width, option.rect.height()-4)
            painter.setFont(path_font)
            painter.setPen(QPen(QColor('#b5a1c4')))
            painter.setBrush(QColor('#3a2b48'))
            painter.drawRoundedRect(rect, 3, 3)
            path = path_metrics.elidedText(path, Qt.TextElideMode.ElideMiddle,
                                          max(0, path_width-bracket_width-12))
            text_width = path_metrics.horizontalAdvance(path)+bracket_width
            x = rect.left()+(rect.width()-text_width)/2
            baseline = rect.top()+(rect.height()-path_metrics.height())/2+path_metrics.ascent()
            painter.setFont(bracket_font)
            painter.drawText(QPointF(x, baseline), '[')
            x += bracket_metrics.horizontalAdvance('[')
            painter.setFont(path_font)
            painter.drawText(QPointF(x, baseline), path)
            x += path_metrics.horizontalAdvance(path)
            painter.setFont(bracket_font)
            painter.drawText(QPointF(x, baseline), ']')
            right -= path_width+6
        if badge:
            painter.setFont(styled.font)
            rect = QRect(right-badge_width+1, option.rect.top()+2, badge_width, option.rect.height()-4)
            active = badge.startswith('[WT')
            painter.setPen(QPen(QColor('#c792ea' if active else '#969696')))
            painter.setBrush(QColor('#3a2b48' if active else '#303030'))
            painter.drawRoundedRect(rect, 3, 3)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, badge)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        # Rows fit the sidebar; long labels and paths are elided by paint().
        return QSize(0, max(size.height(), option.fontMetrics.height()+8))


class BranchList(QListWidget):
    def resizeEvent(self, event):
        current = self.currentItem()
        keep_visible = (current is not None and not current.isHidden()
                        and self.viewport().rect().intersects(self.visualItemRect(current)))
        super().resizeEvent(event)
        # Selection adds shortcut rows above this list. Keep a visible current
        # branch in view when those rows reduce the list's available height.
        if keep_visible and event.size().height() < event.oldSize().height():
            target = current.data(Qt.ItemDataRole.UserRole)
            self.ensure_current_visible(target)
            # Qt finalizes scrollbar ranges after the viewport resize event.
            QTimer.singleShot(0, self, lambda: self.ensure_current_visible(target))

    def ensure_current_visible(self, target):
        current = self.currentItem()
        if current is not None and not current.isHidden() and current.data(Qt.ItemDataRole.UserRole) == target:
            rect = self.visualItemRect(current)
            viewport = self.viewport().rect()
            scrollbar = self.verticalScrollBar()
            unit = 1 if self.verticalScrollMode() == self.ScrollMode.ScrollPerPixel else max(1, rect.height())
            if rect.bottom() > viewport.bottom():
                steps = (rect.bottom()-viewport.bottom()+unit-1)//unit
                scrollbar.setValue(scrollbar.value()+steps)
            elif rect.top() < viewport.top():
                steps = (viewport.top()-rect.top()+unit-1)//unit
                scrollbar.setValue(scrollbar.value()-steps)


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
        self.tabs.setStyleSheet(TAB_STYLESHEET)
        for title in ('All refs', 'Branches', 'Tags', 'Worktrees'):
            self.tabs.addTab(title)
        self.tabs.setExpanding(True)
        box.addWidget(self.tabs)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Filter refs…')
        self.filter.textChanged.connect(self.filter_branches)
        box.addWidget(self.filter)
        self.list = BranchList()
        self.list.setItemDelegate(WorktreeBadgeDelegate(self.list))
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
        branches.sort(key=lambda entry: (entry[2] != repo.head_ref, entry[2].startswith('refs/remotes/'),
                                         entry[0].casefold()))
        entries = []
        if repo and (repo.head_oid or repo.head_ref) and not any(ref == repo.head_ref for _, _, ref in branches):
            if not repo.head_oid:
                label = 'HEAD → '+repo.head_ref.removeprefix('refs/heads/')+' (no commits yet)'
            elif not repo.head_ref:
                label = 'HEAD (detached) · '+repo.head_oid[:8]
            else:
                label = 'HEAD → '+repo.head_ref.removeprefix('refs/heads/')
            entries.append(('HEAD', repo.head_oid, 'HEAD', 'head', label))
        entries.extend((name, oid, ref, 'branch', name+' [HEAD]' if ref == repo.head_ref else name)
                       for name, oid, ref in branches)
        if repo:
            entries.extend((name, oid, 'refs/tags/'+name, 'tag', 'tag: '+name)
                           for name, oid in sorted(repo.tags.items(), key=lambda entry: entry[0].casefold()))
        opened = opened_worktree(repo.path, repo.worktrees) if repo else None
        worktree_entries = {}
        if repo:
            for wt in sorted(repo.worktrees, key=lambda wt: (wt != opened, wt.path.casefold())):
                folder = Path(wt.path).name or wt.path
                location = wt.branch.removeprefix('refs/heads/') if wt.branch else 'bare' if wt.bare else 'detached HEAD'
                ref = 'worktree:'+wt.path
                worktree_entries[ref] = wt
                label = (location+' [HEAD]' if wt == opened and wt.branch else location)
                if wt.detached:
                    label = 'HEAD (detached) · '+wt.head[:8]
                if not wt.active and not wt.bare and wt.prunable is None:
                    label += ' (no commits yet)'
                entries.append((folder, wt.head, ref, 'worktree', label))
        for name, oid, ref, kind, label in entries:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, (name, oid))
            item.setData(Qt.ItemDataRole.UserRole+1, kind)
            item.setData(Qt.ItemDataRole.UserRole+2, ref)
            item.setToolTip(f'{ref}\n{oid}' if oid else ref+'\nNo commits yet')
            if kind == 'head' and not oid:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            remote = remote_name(repo, name) if kind == 'branch' else None
            color = '#c792ea' if kind == 'head' or ref == repo.head_ref else '#d8ab65' if kind == 'tag' else '#75baff'
            item.setForeground(remote_color(remote) if remote is not None else QColor(color))
            if kind == 'head' or ref == repo.head_ref:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setToolTip(item.toolTip()+'\nCurrent checkout: '+repo.path)
            if remote is not None:
                item.setToolTip(item.toolTip()+'\nRemote: '+remote)
            trees = ([worktree_entries[ref]] if kind == 'worktree' else
                     [wt for wt in repo.worktrees if wt.branch == ref] if kind == 'branch' else
                     [opened] if kind == 'head' and opened else [])
            if trees:
                active = [wt for wt in trees if wt.active]
                wt = trees[0]
                badge = ('[WT · here]' if opened in active else '[WT]' if active else
                         '[prunable]' if wt.prunable is not None else '[bare]' if wt.bare else '[empty]')
                item.setData(BADGE_ROLE, badge)
                paths = [worktree_path(repo.path, wt.path) for wt in trees]
                item.setData(PATH_ROLE, paths)
                if active:
                    item.setForeground(QColor('#c792ea'))
                if kind == 'worktree' and wt == opened:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                for wt in trees:
                    status = 'Main worktree' if wt.main else 'Linked worktree'
                    if wt == opened:
                        status += ' · opened here'
                    if wt.locked is not None:
                        status += '\nLocked'+(': '+wt.locked if wt.locked else '')
                    if wt.prunable is not None:
                        status += '\nPrunable: '+wt.prunable
                    item.setToolTip(item.toolTip()+'\n'+status+'\n'+wt.path)
                if kind == 'worktree':
                    wt = trees[0]
                    details = ['Main worktree' if wt.main else 'Linked worktree']
                    if wt.locked is not None:
                        details.append('Locked'+(': '+wt.locked if wt.locked else ''))
                    if wt.prunable is not None:
                        details.append('Prunable'+(': '+wt.prunable if wt.prunable else ''))
                    item.setData(DETAILS_ROLE, ' · '.join(details))
                item.setData(SEARCH_ROLE, label+' '+' '.join(paths)+' '+ ' '.join(wt.path for wt in trees))
                if kind == 'worktree' and not active:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list.addItem(item)
            if ref == selected_ref:
                selected_item = item
        self.heading.setToolTip('HEAD and active worktrees: purple. [WT · here]: opened checkout. Current branch: bold.\n'
                                'Worktree paths are relative to the current project root (.); full paths are in tooltips.\n'
                                'Local branches: blue. Remote branches: teal. Tags: gold.')
        self.filter_branches(self.filter.text())
        self.list.setCurrentItem(selected_item)
        # Rebuild the filtered layout before restoring the viewport. Restoring
        # selection while rows are still unfiltered can scroll it out of view.
        self.list.doItemsLayout()
        self.list.verticalScrollBar().setValue(vertical_scroll)
        self.list.horizontalScrollBar().setValue(horizontal_scroll)

    def filter_branches(self, query):
        category = (None, 'branch', 'tag', 'worktree')[self.tabs.currentIndex()]
        self.filter.setPlaceholderText('Filter worktrees or paths…' if category == 'worktree' else
                                       'Filter refs…' if category == 'tag' else 'Filter refs or paths…')
        count = 0
        for index in range(self.list.count()):
            item = self.list.item(index)
            kind = item.data(Qt.ItemDataRole.UserRole+1)
            matches_category = kind != 'worktree' if category is None else kind == category
            count += matches_category
            search = item.data(SEARCH_ROLE) or item.text()
            item.setHidden(not matches_category or query.casefold() not in search.casefold())
        self.heading.setText(f'{self.tabs.tabText(self.tabs.currentIndex())} ({count:,})')

    def activate(self, item):
        if not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        name, oid = item.data(Qt.ItemDataRole.UserRole)
        self.branch_clicked.emit(name, oid)

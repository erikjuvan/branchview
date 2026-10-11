from PySide6.QtCore import Qt, QTimer, QEvent
from dataclasses import replace
from urllib.parse import urlsplit, parse_qs
import re
from collections import defaultdict
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import (QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsEllipseItem, QGraphicsItem, QFileDialog, QMessageBox, QToolBar,
    QCheckBox, QTextEdit, QSplitter, QGraphicsTextItem, QMenu, QDialog, QVBoxLayout, QComboBox, QLabel,
    QStyle, QStyleOptionGraphicsItem, QWidget)
from diff_viewer import DiffViewer
from commit_sidebar import CommitSidebar
from search import SearchDialog
from repository_loader import RepositoryLoader
from graph import build_graph, hide_nodes
from layout import layout, branch_layout, arrange_graph
from shortcut_panel import ShortcutPanel
from commit_browser import CommitBrowser
from vscode_open import SnapshotOpenDialog
from branch_panel import BranchPanel
from branch_colors import remote_name, remote_color
from repository_status_panel import RepositoryStatusPanel

class View(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.pan_position = event.position()
            event.accept()
        else:
            super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.MiddleButton and hasattr(self, 'pan_position'):
            delta = event.position() - self.pan_position
            self.pan_position = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            event.accept()
        else:
            super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        current = self.transform().m11()
        if delta > 0:
            target = min(current * 1.2, 8) if current < 8 else current
        elif delta < 0:
            target = max(current / 1.2, .03) if current > .03 else current
        else:
            target = current
        if current > 0 and target != current:
            self.scale(target / current, target / current)
        event.accept()
    def fit(self):
        self.fit_bounds(self.scene().itemsBoundingRect())
    def fit_bounds(self, bounds):
        # Bounds change only on explicit fit or redraw, never during a drag.
        self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-1000,-1000,1000,1000))
        self.fitInView(bounds.adjusted(-50,-50,50,50), Qt.AspectRatioMode.KeepAspectRatio)

class Node(QGraphicsEllipseItem):
    def __init__(self, oid, x, y, tip, window, display_id=None):
        super().__init__(-8,-8,16,16)
        self.oid = oid
        self.display_id = display_id or oid
        self.window = window
        self.tip = tip
        self.checked_out = any(wt.active and wt.head == oid for wt in window.repo.worktrees) if window.repo else False
        names = window.repo.branches.get(oid, []) if window.repo else []
        remotes = [remote_name(window.repo, name) for name in names]
        self.base_color = (remote_color(sorted(remotes)[0]) if remotes and all(remotes) else
                           QColor('#75baff' if tip else '#b5bdc9'))
        self.setPos(x,y)
        self.setBrush(self.base_color)
        self.setPen(QPen(QColor('#d5dce6'), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        if window.repo and window.repo.regular_history and not window.repo.branches_only:
            self.setRect(-5,-5,10,10)
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setZValue(2)
    def boundingRect(self):
        # Reserve room for the selection ring so selection never changes bounds.
        return self.rect().adjusted(-7, -7, 7, 7)
    def paint(self, painter, option, widget=None):
        option = QStyleOptionGraphicsItem(option)
        option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.save()
            pen = QPen(QColor('#ffd166'), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self.rect().adjusted(-5, -5, 5, 5))
            painter.restore()
    def highlight(self, ancestor, active):
        if self.isSelected():
            fill, border, width = '#ffd166', '#fff0c2', 3
        elif ancestor:
            fill, border, width = '#5ce0cc', '#b2fff1', 2
        elif self.checked_out:
            fill, border, width = '#c792ea', '#e2c4f7', 2
        elif active:
            fill, border, width = '#59616e', '#798391', 1
        else:
            fill, border, width = self.base_color, '#d5dce6', 1
        self.setBrush(QColor(fill))
        pen = QPen(QColor(border), width)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setZValue(4 if self.isSelected() else 2)
        self.update()
    def mouseDoubleClickEvent(self, event):
        self.window.show_diff(self.oid)
        event.accept()
    def contextMenuEvent(self, event):
        menu = self.window.node_menu(self.oid)
        menu.exec(event.screenPos())
        event.accept()
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.window.manual_positions[self.display_id] = (value.x(), value.y())
            self.window.update_edges()
        return super().itemChange(change, value)

class NodeLabel(QGraphicsTextItem):
    """Labels forward mouse interaction to the movable parent node."""
    def __init__(self, text, node):
        super().__init__(text, node)
        self.node = node
        self.base_color = QColor('#cccccc')
        self.worktree_badge = False
        self.remote_branch = False
        self.ref_badge = False
        self.included_tip = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
    def set_included_tip(self, included):
        self.prepareGeometryChange()
        self.included_tip = included
        self.update()
    def boundingRect(self):
        rect = super().boundingRect()
        return rect.adjusted(0, 0, 20, 0) if getattr(self, 'included_tip', False) else rect
    def paint(self, painter, option, widget=None):
        if self.node.isSelected() or self.ref_badge:
            painter.save()
            painter.setPen(QPen(self.defaultTextColor(), 1) if self.ref_badge else QPen(Qt.PenStyle.NoPen))
            painter.setBrush(QColor('#59471f' if self.node.isSelected() else '#35383e'))
            painter.drawRoundedRect(self.boundingRect(), 4, 4)
            painter.restore()
        super().paint(painter, option, widget)
        if self.included_tip:
            # Draw the inclusion icon directly; it must not depend on a font's
            # Unicode arrow coverage.
            painter.save()
            rect = super().boundingRect()
            x, y = rect.right()+4, rect.center().y()-4
            path = QPainterPath()
            path.moveTo(x, y-3)
            path.lineTo(x, y+2)
            path.quadTo(x, y+5, x+3, y+5)
            path.lineTo(x+11, y+5)
            path.moveTo(x+8, y+2)
            path.lineTo(x+11, y+5)
            path.lineTo(x+8, y+8)
            pen = QPen(self.defaultTextColor(), 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.restore()
    def mouseDoubleClickEvent(self, event):
        self.node.mouseDoubleClickEvent(event)
    def contextMenuEvent(self, event):
        self.node.contextMenuEvent(event)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.node.setSelected(not self.node.isSelected())
            elif not self.node.isSelected():
                self.node.window.scene.clearSelection()
                self.node.setSelected(True)
            self.drag_origin = event.scenePos()
            self.drag_nodes = {item: item.pos() for item in self.node.window.scene.selectedItems() if isinstance(item, Node)}
            event.accept()
        else:
            event.ignore()
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            if self.node.window.repo.regular_history and not self.node.window.repo.branches_only:
                event.accept()
                return
            delta = event.scenePos() - self.drag_origin
            for node, origin in self.drag_nodes.items():
                node.setPos(origin + delta)
            event.accept()
    def mouseReleaseEvent(self, event):
        event.accept()

class ChainLabel(QGraphicsTextItem):
    def __init__(self, hidden, window):
        super().__init__(f'{len(hidden)} commit'+('s' if len(hidden) != 1 else '')+' · double-click to expand')
        self.hidden, self.window = hidden, window
        self.setDefaultTextColor(QColor('#afb8c4'))
        self.setToolTip('\n'.join(window.repo.commits[o].message.split('\n')[0] for o in hidden[:15]))
    def mouseDoubleClickEvent(self, event):
        self.window.hidden_nodes.difference_update(self.hidden)
        self.window.expanded.update(self.hidden)
        self.window.render()
        event.accept()
    def mousePressEvent(self, event):
        self.window.details.setPlainText('\n\n'.join(
            f'{o}\n{self.window.repo.commits[o].message}' for o in self.hidden))
        event.accept()

class Window(QMainWindow):
    def __init__(self, path=None, branches_only=False, history_limit=500, all_branch_tips=False, open_callback=None, presentation='regular'):
        super().__init__()
        self.open_callback = open_callback
        self.repo = None
        self.expanded = set()
        self.hidden_nodes = set()
        self.positions_by_mode = {False: {}, True: {}, 'all_tips': {}, 'regular': {}}
        self.manual_positions = self.positions_by_mode[False]
        self.nodes = {}
        self.display_nodes = {}
        self.labels = []
        self.edge_items = []
        self.parent_edges = {}
        self.search_dialog = None
        self.loading = False
        self.pending_path = None
        self.loaded_options = None
        self.prepared = None
        self.preserve_view = False
        self.loader = RepositoryLoader(self)
        self.loader.ready.connect(self.apply_repository)
        self.loader.failed.connect(self.load_failed)
        self.loader.progress.connect(self.load_progress)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #252526; color: #cccccc; }
            QGraphicsView { background: #1e1e1e; border: 1px solid #3c3c3c; }
            QTextEdit { background: #252526; color: #cccccc; border: 1px solid #3c3c3c; }
            QToolBar { background: #252526; border: none; spacing: 6px; padding: 5px; }
            QToolButton { padding: 6px; border-radius: 4px; }
            QToolButton:hover { background: #37373d; }
            QCheckBox { padding: 4px; }
            QStatusBar { background: #252526; }
            QSplitter::handle { background: #3c3c3c; }
            QToolTip { background: #252526; color: #cccccc; border: 1px solid #454545; }
        """)
        self.setWindowTitle('Git Branch Viewer')
        self.resize(1200,800)
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QColor('#1e1e1e'))
        self.scene.selectionChanged.connect(self.inspect)
        self.view = View(self.scene)
        self.fit_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.fit_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.fit_shortcut.activated.connect(self.view.fit)
        self.top_shortcut = QShortcut(QKeySequence(Qt.Key.Key_T), self)
        self.top_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.top_shortcut.activated.connect(self.fit_top_commits)
        self.search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self.search_shortcut.activated.connect(self.open_search)
        self.hide_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.view)
        self.hide_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.hide_shortcut.activated.connect(self.hide_selected_nodes)
        self.rearrange_shortcut = QShortcut(QKeySequence(Qt.Key.Key_R), self)
        self.rearrange_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.rearrange_shortcut.activated.connect(self.rearrange_visible)
        self.diff_shortcut = QShortcut(QKeySequence(Qt.Key.Key_D), self)
        self.diff_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.diff_shortcut.activated.connect(self.diff_selected_nodes)
        self.browse_shortcut = QShortcut(QKeySequence(Qt.Key.Key_B), self)
        self.browse_shortcut.activated.connect(self.browse_selected_commit)
        self.vscode_shortcut = QShortcut(QKeySequence(Qt.Key.Key_V), self)
        self.vscode_shortcut.activated.connect(self.open_selected_in_vscode)
        self.commit_browsers = []
        self.snapshot_dialogs = []
        self.details = CommitSidebar()
        self.details.setReadOnly(True)
        self.details.anchorClicked.connect(self.open_detail_link)
        self.inspected_selection = set()
        self.details.setPlainText('Open a Git repository.\n\nCommit details and comparison summaries appear here.\n\nWheel: zoom\nLeft-drag background: select multiple\nMiddle-drag: pan\nDrag a node or its label: rearrange\nDouble-click a node: diff\nDouble-click a chain label: expand')
        self.shortcuts_panel = ShortcutPanel()
        self.sidebar = QWidget()
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        self.repository_status = RepositoryStatusPanel(self)
        sidebar_layout.addWidget(self.repository_status, 0, Qt.AlignmentFlag.AlignTop)
        sidebar_layout.addWidget(self.shortcuts_panel, 0, Qt.AlignmentFlag.AlignTop)
        self.branch_panel = BranchPanel()
        self.branch_panel.branch_clicked.connect(self.jump_to_branch)
        sidebar_content = QSplitter(Qt.Orientation.Vertical)
        sidebar_content.addWidget(self.branch_panel)
        sidebar_content.addWidget(self.details)
        sidebar_content.setChildrenCollapsible(False)
        sidebar_content.setSizes([190, 430])
        sidebar_layout.addWidget(sidebar_content, 1)
        splitter = QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(self.sidebar)
        splitter.setSizes([800,400])
        self.setCentralWidget(splitter)
        toolbar = QToolBar()
        self.graph_toolbar = toolbar
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for name, callback in [('Open…', self.open), ('Search…', self.open_search), ('Refresh', self.refresh),
                               ('Fit', self.view.fit), ('Top commits', self.fit_top_commits),
                               ('Rearrange visible nodes', self.rearrange_visible), ('Collapse all', self.collapse),
                               ('Show hidden nodes', self.show_hidden_nodes)]:
            if name == 'Open…' and self.open_callback is not None:
                continue
            action = toolbar.addAction(name, callback)
            if name == 'Collapse all':
                self.collapse_action = action
            elif name == 'Rearrange visible nodes':
                self.rearrange_action = action
        self.remote = QCheckBox('Include remote branches')
        self.remote.toggled.connect(self.refresh)
        self.branches_only = QCheckBox('Branches only')
        self.branches_only.setToolTip('Show all branch tips without loading ancestor history.')
        self.branches_only.setChecked(branches_only)
        self.branches_only.toggled.connect(self.refresh)
        self.addToolBarBreak()
        self.load_toolbar = QToolBar('Loading and history')
        self.load_toolbar.setMovable(False)
        self.addToolBar(self.load_toolbar)
        self.cancel_action = self.load_toolbar.addAction('Cancel load', self.cancel_load)
        self.cancel_action.setEnabled(False)
        self.load_toolbar.addWidget(QLabel('History:'))
        self.history_limit = QComboBox()
        for count in (500, 1000, 5000, 10000, None):
            self.history_limit.addItem(f'Latest {count:,}' if count else 'All history', count)
        if self.history_limit.findData(history_limit) < 0:
            self.history_limit.addItem(f'Latest {history_limit:,}', history_limit)
        self.history_limit.setCurrentIndex(self.history_limit.findData(history_limit))
        self.history_limit.setToolTip('Commit budget for history mode; all branch heads are always included.')
        self.history_limit.currentIndexChanged.connect(self.refresh)
        self.load_toolbar.addWidget(self.history_limit)
        self.more_action = self.load_toolbar.addAction('Load more ancestors', self.load_more)
        self.all_branch_tips = QCheckBox('All branch tips on top', self)
        self.all_branch_tips.setChecked(all_branch_tips or presentation == 'all')
        self.all_branch_tips.setToolTip('History mode: show every named tip on top with its ancestry. An arrow marks tips already included in another loaded branch.')
        self.all_branch_tips.toggled.connect(self.legacy_all_tips_changed)
        self.all_branch_tips.hide()
        self.load_toolbar.addWidget(QLabel('View:'))
        self.presentation = QComboBox()
        for title, key in [('Regular history', 'regular'), ('Terminal branches on top', 'terminal'), ('All branches on top', 'all')]:
            self.presentation.addItem(title, key)
        self.presentation.setCurrentIndex(self.presentation.findData('all' if all_branch_tips else presentation))
        self.presentation.setToolTip('Regular: one commit per row. Branch layouts: tips on top with compact ancestry.')
        self.presentation.currentIndexChanged.connect(self.change_presentation)
        self.load_toolbar.addWidget(self.presentation)
        self.load_toolbar.addSeparator()
        self.load_toolbar.addWidget(self.remote)
        self.load_toolbar.addWidget(self.branches_only)
        self.branches_only.toggled.connect(self.update_history_controls)
        self.update_history_controls()
        if path:
            self.load(path)
    def change_presentation(self, *_):
        self.all_branch_tips.blockSignals(True)
        self.all_branch_tips.setChecked(self.presentation.currentData() == 'all')
        self.all_branch_tips.blockSignals(False)
        self.refresh()
        self.update_history_controls()
    def legacy_all_tips_changed(self, checked):
        self.presentation.setCurrentIndex(self.presentation.findData('all' if checked else 'terminal'))
    def open(self):
        if self.open_callback is not None:
            self.open_callback()
            return
        path = QFileDialog.getExistingDirectory(self, 'Select Git repository')
        if path:
            self.load(path)
    def open_search(self):
        if self.search_dialog is None:
            self.search_dialog = SearchDialog(self)
        self.search_dialog.set_repository(self.repo)
        self.search_dialog.show()
        self.search_dialog.raise_()
        self.search_dialog.activateWindow()
        self.search_dialog.query.setFocus()
        self.search_dialog.query.selectAll()
    def load(self, path, preserve_view=False):
        self.preserve_view = preserve_view
        self.pending_path = path
        self.loading = True
        self.repository_status.refresh(path)
        self.cancel_action.setEnabled(True)
        self.statusBar().showMessage(f'Loading {path}…')
        self.update_history_controls()
        self.loader.start(path, remote=self.remote.isChecked(), branches_only=self.branches_only.isChecked(),
                          commit_limit=self.history_limit.currentData(),
                          all_branch_tips=self.presentation.currentData() == 'all' and not self.branches_only.isChecked(),
                          regular_history=self.presentation.currentData() == 'regular' and not self.branches_only.isChecked())
    def load_progress(self, phase):
        self.statusBar().showMessage(f'Loading {self.pending_path} · {phase}')
    def restore_load_options(self):
        if self.loaded_options:
            for widget, key in [(self.remote, 'remote'), (self.branches_only, 'branches_only'),
                                (self.all_branch_tips, 'all_branch_tips')]:
                widget.blockSignals(True)
                widget.setChecked(self.loaded_options.get(key, widget.isChecked()))
                widget.blockSignals(False)
            limit = self.loaded_options.get('commit_limit', self.history_limit.currentData())
            mode = getattr(self, 'loaded_presentation', None) or ('all' if self.loaded_options.get('all_branch_tips') else 'regular' if self.loaded_options.get('regular_history') else 'terminal')
            self.presentation.blockSignals(True)
            self.presentation.setCurrentIndex(self.presentation.findData(mode))
            self.presentation.blockSignals(False)
            self.history_limit.blockSignals(True)
            self.history_limit.setCurrentIndex(self.history_limit.findData(limit))
            self.history_limit.blockSignals(False)
        self.update_history_controls()
    def update_history_controls(self, *_):
        self.history_limit.setEnabled(not self.branches_only.isChecked())
        self.all_branch_tips.setEnabled(not self.branches_only.isChecked())
        self.presentation.setEnabled(not self.branches_only.isChecked())
        regular = self.presentation.currentData() == 'regular' and not self.branches_only.isChecked()
        self.collapse_action.setEnabled(not regular)
        self.rearrange_action.setText('Reset history layout' if regular else 'Rearrange visible nodes')
        self.more_action.setEnabled(bool(self.repo and self.repo.history_limited and not self.loading
                                        and not self.branches_only.isChecked()))
        self.shortcuts_panel.update_context(self)
    def load_more(self):
        if not self.repo or not self.repo.history_limited or self.loading or self.repo.branches_only:
            return
        limit = self.repo.commit_limit
        if limit is None:
            return
        new_limit = limit+max(500, limit)
        if self.history_limit.findData(new_limit) < 0:
            self.history_limit.addItem(f'Latest {new_limit:,}', new_limit)
        self.history_limit.blockSignals(True)
        self.history_limit.setCurrentIndex(self.history_limit.findData(new_limit))
        self.history_limit.blockSignals(False)
        self.load(self.repo.path, preserve_view=True)
    def cancel_load(self):
        self.loader.cancel()
        self.loading = False
        self.pending_path = None
        self.preserve_view = False
        self.cancel_action.setEnabled(False)
        self.restore_load_options()
        if self.repo:
            self.repository_status.refresh(self.repo.path)
        self.statusBar().showMessage('Load canceled · previous view retained' if self.repo else 'Load canceled · Open a repository to try again')
        handler = getattr(self, 'load_cancel_handler', None)
        if handler is not None:
            handler()
    def load_failed(self, error):
        self.loading = False
        self.pending_path = None
        self.preserve_view = False
        self.cancel_action.setEnabled(False)
        self.restore_load_options()
        if self.repo:
            self.repository_status.refresh(self.repo.path)
        self.statusBar().showMessage('Repository loading failed')
        handler = getattr(self, 'load_error_handler', None)
        if handler is not None:
            handler(error)
        else:
            QMessageBox.warning(self, 'Cannot open repository', error)
    def apply_repository(self, repo, graph, positions, options):
        keep_view = self.preserve_view and self.repo is not None and self.repo.path == repo.path
        if keep_view:
            transform = self.view.transform()
            center = self.view.mapToScene(self.view.viewport().rect().center())
            expanded = self.expanded.copy()
            selected = {item.display_id for item in self.scene.selectedItems() if isinstance(item, Node)}
        self.preserve_view = False
        self.loading = False
        self.pending_path = None
        self.cancel_action.setEnabled(False)
        self.loaded_options = options
        self.loaded_presentation = self.presentation.currentData()
        self.update_history_controls()
        self.prepared = (repo, graph, positions)
        if self.repo is None or self.repo.path != repo.path:
            for positions in self.positions_by_mode.values():
                positions.clear()
            self.hidden_nodes.clear()
        mode = True if repo.branches_only else 'regular' if repo.regular_history else 'all_tips' if repo.all_branch_tips else False
        self.manual_positions = self.positions_by_mode[mode]
        self.repo = repo
        if self.search_dialog is not None:
            self.search_dialog.set_repository(repo)
        self.details.reset_repository(repo)
        self.expanded.clear()
        if keep_view:
            self.expanded.update(expanded & repo.commits.keys())
        explanation = ('Branches only: ancestor history is not loaded.\n'
                       'Nodes are branch tips arranged in a grid; positions do not represent ancestry.'
                       if repo.branches_only else
                       'History view: all named branch tips start on top. An arrow marks tips included in another branch.\n'
                       'Each top entry shows only its ancestry; shared commits can also appear below receiving branches.'
                       if repo.all_branch_tips else
                       'Regular history: newest commits first, one row per commit. Parents remain below their children.'
                       if repo.regular_history else
                       'History view: vertical position represents ancestry, not time.')
        self.render()
        if repo.branches:
            self.details.setPlainText(explanation + '\n\nClick a commit to inspect its history and changes.')
        if keep_view:
            for oid in selected & self.display_nodes.keys():
                self.display_nodes[oid].setSelected(True)
            self.view.setTransform(transform)
            self.view.centerOn(center)
        else:
            self.fit_top_commits() if repo.regular_history and not repo.branches_only else self.view.fit()
        self.update_history_controls()
    def refresh(self, *_):
        path = self.pending_path if self.loading else self.repo.path if self.repo else getattr(self, 'repository_path', None)
        if path:
            self.load(path)
    def refresh_status(self):
        path = self.pending_path if self.loading else self.repo.path if self.repo else getattr(self, 'repository_path', None)
        self.repository_status.refresh(path)
    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and self.open_callback is None:
            if hasattr(self, 'repository_status'):
                self.refresh_status()
    def collapse(self):
        self.expanded.clear()
        self.render()
        self.fit_top_commits() if self.repo and self.repo.regular_history and not self.repo.branches_only else self.view.fit()
    def hide_node(self, oid):
        self._hide_nodes({oid})
    def hide_selected_nodes(self):
        self._hide_nodes({item.oid for item in self.scene.selectedItems() if isinstance(item, Node)})
    def _hide_nodes(self, oids):
        if not oids:
            return
        # Retain every visible position so hiding never rearranges other nodes.
        self.manual_positions.update({o: (n.pos().x(), n.pos().y()) for o,n in self.display_nodes.items()})
        self.hidden_nodes.update(oids)
        self.render()
    def show_hidden_nodes(self):
        self.hidden_nodes.clear()
        self.render()
    def node_menu(self, oid):
        menu = QMenu(self)
        browse = menu.addAction('Browse files at this commit…')
        browse.triggered.connect(lambda: QTimer.singleShot(0, lambda: self.browse_commit(oid)))
        vscode = menu.addAction('Open commit in VS Code…')
        vscode.triggered.connect(lambda: QTimer.singleShot(0, lambda: self.open_commit_in_vscode(oid)))
        action = menu.addAction('Hide node')
        action.triggered.connect(lambda: QTimer.singleShot(0, lambda: self.hide_node(oid)))
        selected = {item.oid for item in self.scene.selectedItems() if isinstance(item, Node)}
        if len(selected) == 2 and oid in selected:
            source, target = [o for o in reversed(self.repo.commits) if o in selected]
            action = menu.addAction('Diff selected commits…')
            action.triggered.connect(lambda: QTimer.singleShot(0, lambda: self.show_commit_diff(source, target)))
        return menu
    def browse_selected_commit(self):
        selected = {item.oid for item in self.scene.selectedItems() if isinstance(item, Node)}
        if len(selected) == 1:
            self.browse_commit(next(iter(selected)))
    def open_selected_in_vscode(self):
        selected = {item.oid for item in self.scene.selectedItems() if isinstance(item, Node)}
        if len(selected) == 1:
            self.open_commit_in_vscode(next(iter(selected)))
    def open_commit_in_vscode(self, oid):
        if self.repo:
            dialog = SnapshotOpenDialog(self.repo.path, oid, self)
            self.snapshot_dialogs.append(dialog)
            dialog.destroyed.connect(lambda: self.snapshot_dialogs.remove(dialog) if dialog in self.snapshot_dialogs else None)
            dialog.show()
    def browse_commit(self, oid):
        if not self.repo:
            return
        browser = CommitBrowser(self.repo.path, oid, self)
        self.commit_browsers.append(browser)
        browser.destroyed.connect(lambda: self.commit_browsers.remove(browser) if browser in self.commit_browsers else None)
        browser.show()
    def diff_selected_nodes(self):
        if not self.repo:
            return
        selected = {item.oid for item in self.scene.selectedItems() if isinstance(item, Node)}
        if len(selected) == 1:
            self.show_diff(next(iter(selected)))
        elif len(selected) == 2:
            source, target = [o for o in reversed(self.repo.commits) if o in selected]
            self.show_commit_diff(source, target)
    def show_commit_diff(self, source, target):
        dialog = QDialog(self)
        dialog.setWindowTitle('Diff between selected commits')
        dialog.resize(1250, 800)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel('Compare commit trees. Choose a direction to reverse additions and deletions.'))
        combo = QComboBox()
        for before, after in [(source, target), (target, source)]:
            combo.addItem(f'{before[:12]} → {after[:12]}', (before, after))
        box.addWidget(combo)
        summary = QLabel()
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setWordWrap(True)
        box.addWidget(summary)
        diff = DiffViewer(self.repo)
        box.addWidget(diff, 1)
        def refresh(*_):
            before, after = combo.currentData()
            descriptions = []
            for label, o in [('From', before), ('To', after)]:
                subject = self.repo.commits[o].message.split('\n')[0]
                descriptions.append(f'{label}: {o}\n{subject}')
            summary.setText('\n'.join(descriptions))
            diff.compare(before, after)
        combo.currentIndexChanged.connect(refresh)
        refresh()
        dialog.exec()
    def show_diff(self, oid, repo=None, file_path=None):
        repo = repo or self.repo
        info = self.details.cache.get(oid)
        if info is not None:
            repo = replace(repo, commits={**repo.commits, oid: info.commit})
        dialog = QDialog(self)
        dialog.setWindowTitle(f'Diff — {oid[:12]} against parent')
        dialog.resize(1250, 800)
        box = QVBoxLayout(dialog)
        box.addWidget(QLabel('Comparison uses the actual Git parent, including commits hidden in collapsed chains.'))
        combo = QComboBox()
        parents = repo.commits[oid].parents
        for index, parent in enumerate(parents):
            combo.addItem(f'Parent {index+1}: {parent}', parent)
        if not parents:
            combo.addItem('Empty tree (root commit)', None)
        box.addWidget(combo)
        diff = DiffViewer(repo)
        box.addWidget(diff, 1)
        def refresh(*_):
            diff.compare(combo.currentData(), oid)
            if file_path is not None:
                index = next((i for i, change in enumerate(diff.changes) if change.new_path == file_path), None)
                if index is not None:
                    diff.files.setCurrentRow(index)
        combo.currentIndexChanged.connect(refresh)
        refresh()
        dialog.exec()
    def rearrange_visible(self):
        if not self.repo:
            return
        graph = hide_nodes(build_graph(self.repo, self.expanded), self.hidden_nodes)
        # Hidden tip removal can expose new topmost nodes.
        if not self.repo.branches_only and not self.repo.all_branch_tips:
            graph.tips = sorted(graph.nodes - {e.parent for e in graph.edges})
        self.manual_positions.update(arrange_graph(self.repo, graph))
        self.render()
        self.fit_top_commits() if self.repo.regular_history and not self.repo.branches_only else self.view.fit()
    def fit_top_commits(self):
        top_nodes = (sorted(self.display_nodes.values(), key=lambda node: node.y())[:12]
                     if self.repo and self.repo.regular_history and not self.repo.branches_only else
                     [node for node in self.display_nodes.values() if node.tip])
        if not top_nodes:
            # If every branch tip is hidden, use the exposed topmost commits.
            parents = {oid for oids in self.parent_edges.values() for oid in oids}
            top_nodes = [node for oid, node in self.display_nodes.items() if oid not in parents]
        if not top_nodes:
            return
        bounds = top_nodes[0].sceneBoundingRect()
        for node in top_nodes:
            bounds = bounds.united(node.sceneBoundingRect())
            bounds = bounds.united(node.mapRectToScene(node.childrenBoundingRect()))
        self.view.fit_bounds(bounds)
        if self.repo and self.repo.regular_history and self.view.transform().m11() > 1.5:
            self.view.scale(1.5/self.view.transform().m11(), 1.5/self.view.transform().m11())
            self.view.centerOn(bounds.center())
    def jump_to_branch(self, name, oid):
        if not self.repo or name not in self.repo.branches.get(oid, []):
            return
        if oid not in self.nodes:
            self.expanded.add(oid)
        if oid in self.hidden_nodes or oid not in self.nodes:
            self.hidden_nodes.discard(oid)
            self.render()
        node = self.nodes.get(oid)
        if node is None:
            return
        self.scene.clearSelection()
        node.setSelected(True)
        bounds = node.sceneBoundingRect().united(node.mapRectToScene(node.childrenBoundingRect()))
        self.view.fit_bounds(bounds.adjusted(-120, -90, 120, 90))
        if self.view.transform().m11() > 1.5:
            self.view.scale(1.5/self.view.transform().m11(), 1.5/self.view.transform().m11())
        self.view.centerOn(bounds.center())
    def reset_layout(self):
        self.manual_positions.clear()
        self.render()
        self.view.fit()
    def update_edges(self):
        occupied, cells = [], defaultdict(list)
        def cell_keys(rect):
            for x in range(int(rect.left()//256), int(rect.right()//256)+1):
                for y in range(int(rect.top()//128), int(rect.bottom()//128)+1):
                    yield x, y
        def reserve(rect):
            index = len(occupied)
            occupied.append(rect)
            for key in cell_keys(rect):
                cells[key].append(index)
        for node in self.display_nodes.values():
            reserve(node.sceneBoundingRect().united(node.mapRectToScene(node.childrenBoundingRect())).adjusted(-4,-4,4,4))
        for edge, item, label in self.edge_items:
            child = self.display_nodes[edge.child].pos()
            parent = self.display_nodes[edge.parent].pos()
            x1,y1,x2,y2 = child.x(),child.y(),parent.x(),parent.y()
            path = QPainterPath()
            path.moveTo(x1,y1)
            if self.repo.regular_history and not self.repo.branches_only:
                bend = min(y1+20, (y1+y2)/2)
                path.cubicTo(x1,bend,x2,bend,x2,min(y1+40,y2))
                path.lineTo(x2,y2)
            else:
                path.cubicTo(x1,(y1+y2)/2,x2,(y1+y2)/2,x2,y2)
            item.setPath(path)
            if label is not None:
                middle_x, middle_y = (x1+x2)/2, (y1+y2)/2
                width = label.boundingRect().width()
                candidates = [(x, middle_y+dy) for dy in (-12, 16, -40, 44, -68, 72)
                              for x in (middle_x+12, middle_x-width-24)]
                def collisions(position):
                    rect = label.boundingRect().translated(*position)
                    nearby = {index for key in cell_keys(rect) for index in cells.get(key, ())}
                    return sum(rect.intersects(occupied[index]) for index in nearby)
                best, fewest = candidates[0], float('inf')
                for candidate in candidates:
                    count = collisions(candidate)
                    if count < fewest:
                        best, fewest = candidate, count
                    if count == 0:
                        break
                x, y = best
                label.setPos(x, y)
                reserve(label.sceneBoundingRect().adjusted(-4,-4,4,4))
    def render(self):
        self.branch_panel.set_repository(self.repo)
        self.details.cancel_pending()
        self.details.setPlainText('Select a commit to inspect its history and changes.')
        self.inspected_selection = set()
        self.scene.blockSignals(True)
        self.scene.clear()
        self.nodes = {}
        self.display_nodes = {}
        self.labels = []
        self.edge_items = []
        self.parent_edges = {}
        self.scene.blockSignals(False)
        if not self.repo:
            return
        if self.prepared is not None and self.prepared[0] is self.repo and not self.expanded:
            _, graph, automatic = self.prepared
            positions = dict(automatic)
        else:
            graph = build_graph(self.repo, self.expanded)
            positions = arrange_graph(self.repo, graph)
        graph = hide_nodes(graph, self.hidden_nodes)
        regular = self.repo.regular_history and not self.repo.branches_only
        if regular and self.hidden_nodes:
            positions = arrange_graph(self.repo, graph)
        positions = {oid: xy for oid,xy in positions.items() if oid in graph.nodes}
        if not regular:
            positions.update({oid: xy for oid, xy in self.manual_positions.items() if oid in graph.nodes})
        text_x = max((x for x, y in positions.values()), default=0)+32
        shared_copies = {graph.commit_oid(entry) for entry in graph.included_tips}
        for display_id,(x,y) in positions.items():
            oid = graph.commit_oid(display_id)
            commit = self.repo.commits[oid]
            node = Node(oid,x,y,display_id in graph.tips,self,display_id=display_id)
            self.display_nodes[display_id] = node
            if oid not in self.nodes or display_id in graph.tips:
                self.nodes[oid] = node
            context = ('\nBranch tip shown above; this commit also appears in shared ancestry.' if display_id != oid and oid in shared_copies else
                       '\nTop-row named branch tip.' if display_id != oid else
                       '\nThis commit is also shown as a branch tip above.' if oid in shared_copies else '')
            node.setToolTip(f'{oid}\n{commit.message}{context}'+('\nOne commit per history row' if regular else '\nDrag to move'))
            self.scene.addItem(node)
            label = NodeLabel(oid[:8]+' '+commit.message.split('\n')[0][:140 if regular else 25], node)
            self.labels.append(label)
            label.setDefaultTextColor(QColor('#cccccc'))
            label.setPos(12,-14)
            if self.repo.history_limited and any(p not in self.repo.commits for p in commit.parents) and not regular:
                boundary = NodeLabel('Earlier history not loaded', node)
                boundary.base_color = QColor('#d8ab65')
                boundary.setDefaultTextColor(boundary.base_color)
                boundary.setPos(12, 10)
                boundary.setToolTip('Use Load more ancestors or choose All history.')
                self.labels.append(boundary)
            if display_id == oid and oid in shared_copies:
                note = NodeLabel('Also shown as a branch tip above', node)
                note.base_color = QColor('#afb8c4')
                note.setDefaultTextColor(note.base_color)
                note.setPos(12, 28 if self.repo.history_limited and any(p not in self.repo.commits for p in commit.parents) else 10)
                self.labels.append(note)
            checkouts = [wt for wt in self.repo.worktrees if wt.active and wt.head == oid]
            if display_id in graph.tips or ((checkouts or oid in self.repo.branches) and not (self.repo.all_branch_tips and oid in shared_copies)):
                titles = []
                for name in self.repo.branches.get(oid, []):
                    trees = [wt for wt in checkouts if wt.branch == self.repo.branch_refs.get(name, 'refs/heads/'+name)]
                    included = display_id in graph.included_tips
                    title = NodeLabel(name+(' [WT]' if trees else ''), node)
                    title.set_included_tip(included)
                    title.worktree_badge = bool(trees)
                    remote = remote_name(self.repo, name)
                    title.remote_branch = remote is not None
                    title.ref_badge = regular
                    title.base_color = (QColor('#c792ea') if trees else remote_color(remote) if remote is not None else
                                        QColor('#d8ab65' if included else '#75baff'))
                    title.setDefaultTextColor(title.base_color)
                    tooltip = 'Tip is already included in another loaded branch’s history. Select it for merge/first-parent details.' if included else ''
                    if self.repo.all_branch_tips and self.repo.history_limited and not included:
                        tooltip = 'Inclusion may be outside the loaded history. Select this tip for full Git relationship details.'
                    if trees:
                        tooltip += '\nChecked out in worktree:\n'+'\n'.join(wt.path for wt in trees)
                    if remote is not None:
                        tooltip += '\nRemote: '+remote
                    title.setToolTip(tooltip.strip())
                    titles.append(title)
                detached = [wt for wt in checkouts if wt.detached]
                if detached:
                    title = NodeLabel('Detached HEAD [WT]', node)
                    title.worktree_badge = True
                    title.ref_badge = regular
                    title.base_color = QColor('#c792ea')
                    title.setDefaultTextColor(title.base_color)
                    title.setToolTip('\n'.join(wt.path for wt in detached))
                    titles.append(title)
                y = -15-sum(title.boundingRect().height() for title in titles)
                row_x = text_x-x
                for title in titles:
                    title.setPos(row_x if regular else -10, -14 if regular else y)
                    row_x += title.boundingRect().width()+8
                    y += title.boundingRect().height()
                    self.labels.append(title)
                if regular:
                    label.setPos(row_x, -14)
            elif regular:
                label.setPos(text_x-x, -14)
        for edge in graph.edges:
            self.parent_edges.setdefault(edge.child, []).append(edge.parent)
            item = self.scene.addPath(QPainterPath(),QPen(QColor('#818b99'),2))
            item.setZValue(-1)
            label = None
            if edge.hidden and not regular:
                label = ChainLabel(edge.hidden, self)
                self.scene.addItem(label)
            self.edge_items.append((edge,item,label))
        self.update_edges()
        self.update_selection_highlights()
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-1000,-1000,1000,1000))
        suffix = ' · Shallow history: ancestry is incomplete' if self.repo.shallow else ''
        if self.repo.history_limited:
            suffix += ' · History limited: ancestry may be incomplete'
        mode = ('branch tips · history not loaded' if self.repo.branches_only else
                'regular history · one commit per row' if self.repo.regular_history else
                'named branch tips · all on top' if self.repo.all_branch_tips else 'terminal tips')
        self.statusBar().showMessage(f'{self.repo.path} · {len(graph.nodes) if regular else len(graph.tips)} {mode} · {len(self.repo.commits)} loaded commits{suffix}')
        self.setWindowTitle(f'Git Branch Viewer — {self.repo.path}')
        if not graph.tips:
            self.details.setPlainText('No branch tips found. Empty repositories and detached commits without branch references are not displayed.')
        self.shortcuts_panel.update_context(self)
    def inspect(self):
        self.update_selection_highlights()
        self.shortcuts_panel.update_context(self)
        if not self.repo:
            return
        selected = {item.oid for item in self.scene.selectedItems() if isinstance(item, Node)}
        newly_selected = selected - self.inspected_selection
        self.inspected_selection = selected
        if len(selected) > 1:
            self.details.show_selection(self.repo, selected)
        elif selected:
            if newly_selected:
                oid = sorted(newly_selected)[0]
            elif self.details.active_oid in selected:
                oid = self.details.active_oid
            else:
                oid = sorted(selected)[0]
            self.details.show_commit(self.repo, oid)
        else:
            self.details.cancel_pending()
            self.details.setPlainText('Select a commit to inspect its history and changes.')
    def open_detail_link(self, url):
        parsed = urlsplit(url.toString())
        if parsed.scheme == 'compare':
            oids = parsed.path.split('/')
            if self.repo and len(oids) == 2 and all(re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', oid)
                                                   and oid in self.repo.commits for oid in oids):
                self.show_commit_diff(*oids)
            return
        oid = parsed.path
        if not self.repo or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', oid):
            return
        if parsed.scheme == 'commit':
            if oid in self.repo.commits and oid not in self.nodes:
                if not self.repo.branches_only:
                    self.expanded.add(oid)
                self.hidden_nodes.discard(oid)
                self.render()
            self.scene.clearSelection()
            if oid in self.nodes:
                node = self.display_nodes.get(oid, self.nodes[oid]) if parse_qs(parsed.query).get('history') == ['1'] else self.nodes[oid]
                node.setSelected(True)
                self.view.centerOn(node)
            else:
                self.details.show_commit(self.repo, oid)
        elif parsed.scheme == 'diff':
            info = self.details.cache.get(oid)
            if oid in self.repo.commits or info is not None:
                repo = self.repo if oid in self.repo.commits else replace(self.repo, commits={oid: info.commit})
                file_path = parse_qs(parsed.query).get('file', [None])[0]
                self.show_diff(oid, repo=repo, file_path=file_path)
    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
    def shutdown(self):
        self.loader.cancel()
        self.repository_status.shutdown()
        self.details.cancel_pending()
        if self.search_dialog is not None:
            self.search_dialog.close()
        for browser in list(self.commit_browsers):
            browser.close()
        for dialog in list(self.snapshot_dialogs):
            dialog.close()
    def update_selection_highlights(self):
        selected = {item.display_id for item in self.scene.selectedItems() if isinstance(item, Node)}
        ancestry = set()
        todo = list(selected)
        while todo:
            oid = todo.pop()
            if oid in ancestry:
                continue
            ancestry.add(oid)
            todo.extend(self.parent_edges.get(oid, ()))
        active = bool(selected)
        for oid, node in self.display_nodes.items():
            node.highlight(oid in ancestry, active)
        for label in self.labels:
            oid = label.node.display_id
            color = label.base_color if label.worktree_badge or label.remote_branch else QColor('#ffd166') if oid in selected else QColor('#80ead9') if oid in ancestry else label.base_color
            label.setDefaultTextColor(color)
            label.setOpacity(.6 if active and oid not in ancestry and not label.worktree_badge else 1)
            label.update()
        for edge, item, label in self.edge_items:
            highlighted = edge.child in ancestry
            color = '#5ce0cc' if highlighted else '#454c56' if active else '#818b99'
            pen = QPen(QColor(color), 3 if highlighted else 2)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setZValue(0 if highlighted else -1)
            if label is not None:
                label.setDefaultTextColor(QColor('#80ead9' if highlighted else '#afb8c4'))
                label.setOpacity(.6 if active and not highlighted else 1)

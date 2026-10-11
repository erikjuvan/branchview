from PySide6.QtCore import Qt, QTimer
from dataclasses import replace
from urllib.parse import urlsplit, parse_qs
import re
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import (QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsEllipseItem, QGraphicsItem, QFileDialog, QMessageBox, QToolBar,
    QCheckBox, QTextEdit, QSplitter, QGraphicsTextItem, QMenu, QDialog, QVBoxLayout, QComboBox, QLabel,
    QStyle, QStyleOptionGraphicsItem)
from diff_viewer import DiffViewer
from commit_sidebar import CommitSidebar
from search import SearchDialog
from repository_loader import RepositoryLoader
from graph import build_graph, hide_nodes
from layout import layout, branch_layout

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
    def __init__(self, oid, x, y, tip, window):
        super().__init__(-8,-8,16,16)
        self.oid = oid
        self.window = window
        self.tip = tip
        self.setPos(x,y)
        self.setBrush(QColor('#75baff' if tip else '#b5bdc9'))
        self.setPen(QPen(QColor('#d5dce6'), 1))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
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
        elif active:
            fill, border, width = '#59616e', '#798391', 1
        else:
            fill, border, width = ('#75baff' if self.tip else '#b5bdc9'), '#d5dce6', 1
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
            self.window.manual_positions[self.oid] = (value.x(), value.y())
            self.window.update_edges()
        return super().itemChange(change, value)

class NodeLabel(QGraphicsTextItem):
    """Labels forward mouse interaction to the movable parent node."""
    def __init__(self, text, node):
        super().__init__(text, node)
        self.node = node
        self.base_color = QColor('#e1e5eb')
        self.setCursor(Qt.CursorShape.ArrowCursor)
    def paint(self, painter, option, widget=None):
        if self.node.isSelected():
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#59471f'))
            painter.drawRoundedRect(self.boundingRect(), 4, 4)
            painter.restore()
        super().paint(painter, option, widget)
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
            delta = event.scenePos() - self.drag_origin
            for node, origin in self.drag_nodes.items():
                node.setPos(origin + delta)
            event.accept()
    def mouseReleaseEvent(self, event):
        event.accept()

class ChainLabel(QGraphicsTextItem):
    def __init__(self, hidden, window):
        super().__init__(f'{len(hidden)} commits · double-click to expand')
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
    def __init__(self, path=None, branches_only=False, history_limit=500):
        super().__init__()
        self.repo = None
        self.expanded = set()
        self.hidden_nodes = set()
        self.positions_by_mode = {False: {}, True: {}}
        self.manual_positions = self.positions_by_mode[False]
        self.nodes = {}
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
            QMainWindow, QWidget { background: #303238; color: #e1e5eb; }
            QGraphicsView { background: #292c31; border: 1px solid #484c54; }
            QTextEdit { background: #35383e; color: #e1e5eb; border: 1px solid #484c54; }
            QToolBar { background: #35383e; border: none; spacing: 6px; padding: 5px; }
            QToolButton { padding: 6px; border-radius: 4px; }
            QToolButton:hover { background: #4a4e56; }
            QCheckBox { padding: 4px; }
            QStatusBar { background: #35383e; }
            QSplitter::handle { background: #484c54; }
            QToolTip { background: #41464e; color: #f0f2f5; border: 1px solid #69717e; }
        """)
        self.setWindowTitle('Git Branch Viewer')
        self.resize(1200,800)
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QColor('#292c31'))
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
        self.details = CommitSidebar()
        self.details.setReadOnly(True)
        self.details.anchorClicked.connect(self.open_detail_link)
        self.inspected_selection = set()
        self.details.setPlainText('Open a Git repository.\n\nWheel: zoom\nDrag background: select multiple · middle-drag: pan\nDrag a node or its label: rearrange\nT: jump to and fit top commits\nR: rearrange visible nodes\nD: diff one or two selected commits\nDelete: hide selected nodes\nClick a commit: inspect\nDouble-click a chain label: expand\n\nVertical position represents ancestry, not time.')
        splitter = QSplitter()
        splitter.addWidget(self.view)
        splitter.addWidget(self.details)
        splitter.setSizes([800,400])
        self.setCentralWidget(splitter)
        toolbar = QToolBar()
        self.addToolBar(toolbar)
        for name, callback in [('Open…', self.open), ('Search…', self.open_search), ('Refresh', self.refresh),
                               ('Fit', self.view.fit), ('Top commits', self.fit_top_commits),
                               ('Rearrange visible nodes', self.rearrange_visible), ('Collapse all', self.collapse),
                               ('Show hidden nodes', self.show_hidden_nodes)]:
            toolbar.addAction(name, callback)
        self.remote = QCheckBox('Include remote branches')
        self.remote.toggled.connect(self.refresh)
        toolbar.addWidget(self.remote)
        self.branches_only = QCheckBox('Branches only')
        self.branches_only.setToolTip('Show all branch tips without loading ancestor history.')
        self.branches_only.setChecked(branches_only)
        self.branches_only.toggled.connect(self.refresh)
        toolbar.addWidget(self.branches_only)
        self.addToolBarBreak()
        self.load_toolbar = QToolBar('Loading and history')
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
        self.branches_only.toggled.connect(self.update_history_controls)
        self.update_history_controls()
        if path:
            self.load(path)
    def open(self):
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
        self.cancel_action.setEnabled(True)
        self.statusBar().showMessage(f'Loading {path}…')
        self.update_history_controls()
        self.loader.start(path, remote=self.remote.isChecked(), branches_only=self.branches_only.isChecked(),
                          commit_limit=self.history_limit.currentData())
    def load_progress(self, phase):
        self.statusBar().showMessage(f'Loading {self.pending_path} · {phase}')
    def restore_load_options(self):
        if self.loaded_options:
            for widget, key in [(self.remote, 'remote'), (self.branches_only, 'branches_only')]:
                widget.blockSignals(True)
                widget.setChecked(self.loaded_options[key])
                widget.blockSignals(False)
            limit = self.loaded_options.get('commit_limit', self.history_limit.currentData())
            self.history_limit.blockSignals(True)
            self.history_limit.setCurrentIndex(self.history_limit.findData(limit))
            self.history_limit.blockSignals(False)
        self.update_history_controls()
    def update_history_controls(self, *_):
        self.history_limit.setEnabled(not self.branches_only.isChecked())
        self.more_action.setEnabled(bool(self.repo and self.repo.history_limited and not self.loading
                                        and not self.branches_only.isChecked()))
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
        self.statusBar().showMessage('Load canceled · previous view retained' if self.repo else 'Load canceled · Open a repository to try again')
    def load_failed(self, error):
        self.loading = False
        self.pending_path = None
        self.preserve_view = False
        self.cancel_action.setEnabled(False)
        self.restore_load_options()
        self.statusBar().showMessage('Repository loading failed')
        QMessageBox.warning(self, 'Cannot open repository', error)
    def apply_repository(self, repo, graph, positions, options):
        keep_view = self.preserve_view and self.repo is not None and self.repo.path == repo.path
        if keep_view:
            transform = self.view.transform()
            center = self.view.mapToScene(self.view.viewport().rect().center())
            expanded = self.expanded.copy()
            selected = {item.oid for item in self.scene.selectedItems() if isinstance(item, Node)}
        self.preserve_view = False
        self.loading = False
        self.pending_path = None
        self.cancel_action.setEnabled(False)
        self.loaded_options = options
        self.update_history_controls()
        self.prepared = (repo, graph, positions)
        if self.repo is None or self.repo.path != repo.path:
            for positions in self.positions_by_mode.values():
                positions.clear()
            self.hidden_nodes.clear()
        self.manual_positions = self.positions_by_mode[repo.branches_only]
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
                       'History view: vertical position represents ancestry, not time.')
        self.render()
        if repo.branches:
            self.details.setPlainText(explanation + '\n\nClick a commit to inspect it.\n'
                                      'T: jump to and fit top commits\n'
                                      'D: diff one or two selected commits\n'
                                      'Delete: hide selected nodes\nR: rearrange visible nodes')
        if keep_view:
            for oid in selected & self.nodes.keys():
                self.nodes[oid].setSelected(True)
            self.view.setTransform(transform)
            self.view.centerOn(center)
        else:
            self.view.fit()
        self.update_history_controls()
    def refresh(self, *_):
        path = self.pending_path if self.loading else self.repo.path if self.repo else None
        if path:
            self.load(path)
    def collapse(self):
        self.expanded.clear()
        self.render()
        self.view.fit()
    def hide_node(self, oid):
        self._hide_nodes({oid})
    def hide_selected_nodes(self):
        self._hide_nodes({item.oid for item in self.scene.selectedItems() if isinstance(item, Node)})
    def _hide_nodes(self, oids):
        if not oids:
            return
        # Retain every visible position so hiding never rearranges other nodes.
        self.manual_positions.update({o: (n.pos().x(), n.pos().y()) for o,n in self.nodes.items()})
        self.hidden_nodes.update(oids)
        self.render()
    def show_hidden_nodes(self):
        self.hidden_nodes.clear()
        self.render()
    def node_menu(self, oid):
        menu = QMenu(self)
        action = menu.addAction('Hide node')
        action.triggered.connect(lambda: QTimer.singleShot(0, lambda: self.hide_node(oid)))
        selected = {item.oid for item in self.scene.selectedItems() if isinstance(item, Node)}
        if len(selected) == 2 and oid in selected:
            source, target = [o for o in reversed(self.repo.commits) if o in selected]
            action = menu.addAction('Diff selected commits…')
            action.triggered.connect(lambda: QTimer.singleShot(0, lambda: self.show_commit_diff(source, target)))
        return menu
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
        if not self.repo.branches_only:
            graph.tips = sorted(graph.nodes - {e.parent for e in graph.edges})
        arrange = branch_layout if self.repo.branches_only else layout
        self.manual_positions.update(arrange(graph))
        self.render()
        self.view.fit()
    def fit_top_commits(self):
        top_nodes = [node for node in self.nodes.values() if node.tip]
        if not top_nodes:
            # If every branch tip is hidden, use the exposed topmost commits.
            parents = {oid for oids in self.parent_edges.values() for oid in oids}
            top_nodes = [node for oid, node in self.nodes.items() if oid not in parents]
        if not top_nodes:
            return
        bounds = top_nodes[0].sceneBoundingRect()
        for node in top_nodes:
            bounds = bounds.united(node.sceneBoundingRect())
            bounds = bounds.united(node.mapRectToScene(node.childrenBoundingRect()))
        self.view.fit_bounds(bounds)
    def reset_layout(self):
        self.manual_positions.clear()
        self.render()
        self.view.fit()
    def update_edges(self):
        for edge, item, label in self.edge_items:
            child = self.nodes[edge.child].pos()
            parent = self.nodes[edge.parent].pos()
            x1,y1,x2,y2 = child.x(),child.y(),parent.x(),parent.y()
            path = QPainterPath()
            path.moveTo(x1,y1)
            path.cubicTo(x1,(y1+y2)/2,x2,(y1+y2)/2,x2,y2)
            item.setPath(path)
            if label is not None:
                label.setPos((x1+x2)/2+10,(y1+y2)/2-12)
    def render(self):
        self.details.cancel_pending()
        self.details.setPlainText('Select a commit to inspect its history and changes.')
        self.inspected_selection = set()
        self.scene.blockSignals(True)
        self.scene.clear()
        self.nodes = {}
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
            arrange = branch_layout if self.repo.branches_only else layout
            positions = arrange(graph)
        graph = hide_nodes(graph, self.hidden_nodes)
        positions = {oid: xy for oid,xy in positions.items() if oid in graph.nodes}
        positions.update({oid: xy for oid, xy in self.manual_positions.items() if oid in graph.nodes})
        for oid,(x,y) in positions.items():
            commit = self.repo.commits[oid]
            node = Node(oid,x,y,oid in graph.tips,self)
            self.nodes[oid] = node
            node.setToolTip(f'{oid}\n{commit.message}\nDrag to move')
            self.scene.addItem(node)
            label = NodeLabel(oid[:8]+' '+commit.message.split('\n')[0][:25], node)
            self.labels.append(label)
            label.setDefaultTextColor(QColor('#e1e5eb'))
            label.setPos(12,-14)
            if self.repo.history_limited and any(p not in self.repo.commits for p in commit.parents):
                boundary = NodeLabel('Earlier history not loaded', node)
                boundary.base_color = QColor('#d8ab65')
                boundary.setDefaultTextColor(boundary.base_color)
                boundary.setPos(12, 10)
                boundary.setToolTip('Use Load more ancestors or choose All history.')
                self.labels.append(boundary)
            if oid in graph.tips:
                names = NodeLabel('\n'.join(self.repo.branches[oid]),node)
                self.labels.append(names)
                names.base_color = QColor('#75baff')
                names.setDefaultTextColor(QColor('#75baff'))
                names.setPos(-10,-names.boundingRect().height()-15)
        for edge in graph.edges:
            self.parent_edges.setdefault(edge.child, []).append(edge.parent)
            item = self.scene.addPath(QPainterPath(),QPen(QColor('#818b99'),2))
            item.setZValue(-1)
            label = None
            if edge.hidden:
                label = ChainLabel(edge.hidden, self)
                self.scene.addItem(label)
            self.edge_items.append((edge,item,label))
        self.update_edges()
        self.update_selection_highlights()
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-1000,-1000,1000,1000))
        suffix = ' · Shallow history: ancestry is incomplete' if self.repo.shallow else ''
        if self.repo.history_limited:
            suffix += ' · History limited: ancestry may be incomplete'
        mode = 'branch tips · history not loaded' if self.repo.branches_only else 'terminal tips'
        self.statusBar().showMessage(f'{self.repo.path} · {len(graph.tips)} {mode} · {len(self.repo.commits)} loaded commits{suffix}')
        self.setWindowTitle(f'Git Branch Viewer — {self.repo.path}')
        if not graph.tips:
            self.details.setPlainText('No branch tips found. Empty repositories and detached commits without branch references are not displayed.')
    def inspect(self):
        self.update_selection_highlights()
        if not self.repo:
            return
        selected = {item.oid for item in self.scene.selectedItems() if isinstance(item, Node)}
        newly_selected = selected - self.inspected_selection
        self.inspected_selection = selected
        if selected:
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
                self.nodes[oid].setSelected(True)
                self.view.centerOn(self.nodes[oid])
            else:
                self.details.show_commit(self.repo, oid)
        elif parsed.scheme == 'diff':
            info = self.details.cache.get(oid)
            if oid in self.repo.commits or info is not None:
                repo = self.repo if oid in self.repo.commits else replace(self.repo, commits={oid: info.commit})
                file_path = parse_qs(parsed.query).get('file', [None])[0]
                self.show_diff(oid, repo=repo, file_path=file_path)
    def closeEvent(self, event):
        self.loader.cancel()
        self.details.cancel_pending()
        super().closeEvent(event)
    def update_selection_highlights(self):
        selected = {item.oid for item in self.scene.selectedItems() if isinstance(item, Node)}
        ancestry = set()
        todo = list(selected)
        while todo:
            oid = todo.pop()
            if oid in ancestry:
                continue
            ancestry.add(oid)
            todo.extend(self.parent_edges.get(oid, ()))
        active = bool(selected)
        for oid, node in self.nodes.items():
            node.highlight(oid in ancestry, active)
        for label in self.labels:
            oid = label.node.oid
            color = QColor('#ffd166') if oid in selected else QColor('#80ead9') if oid in ancestry else label.base_color
            label.setDefaultTextColor(color)
            label.setOpacity(.6 if active and oid not in ancestry else 1)
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

"""Search loaded commit metadata and jump without changing the repository."""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel


def search_commits(repo, query, limit=200):
    query = query.strip().casefold()
    matches = []
    for oid, commit in repo.commits.items():
        names = repo.branches.get(oid, [])
        if query and query in oid.casefold():
            rank = 0
        elif any(query in name.casefold() for name in names):
            rank = 1
        elif query and query in commit.message.casefold():
            rank = 2
        else:
            continue
        matches.append((rank, names[0] if names else '', oid))
    matches.sort()
    return [oid for _, _, oid in matches[:limit]], len(matches)


class SearchDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.repo = window.repo
        self.setWindowTitle('Find branch or commit')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(750, 500)
        box = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setPlaceholderText('Branch name, commit hash, or message…')
        self.query.setClearButtonEnabled(True)
        box.addWidget(self.query)
        self.status = QLabel()
        box.addWidget(self.status)
        self.results = QListWidget()
        box.addWidget(self.results)
        box.addWidget(QLabel('Enter or double-click to jump. Searches only loaded commits.'))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.update_results)
        self.query.textChanged.connect(lambda: self.timer.start())
        self.query.returnPressed.connect(self.jump)
        self.results.itemActivated.connect(self.jump)
        self.update_results()

    def set_repository(self, repo):
        self.repo = repo
        self.update_results()

    def update_results(self):
        self.results.clear()
        if self.repo is None:
            self.status.setText('Open a repository first.')
            return
        oids, count = search_commits(self.repo, self.query.text())
        for oid in oids:
            commit = self.repo.commits[oid]
            names = ', '.join(self.repo.branches.get(oid, []))
            subject = commit.message.split('\n')[0]
            item = QListWidgetItem(f'{names + " · " if names else ""}{oid[:12]}  {subject}')
            item.setData(Qt.ItemDataRole.UserRole, oid)
            item.setToolTip(commit.message)
            self.results.addItem(item)
        scope = 'branch tips only' if self.repo.branches_only else 'limited history' if self.repo.history_limited else 'loaded history'
        self.status.setText(f'{count} match' + ('es' if count != 1 else '')
                            + (f' · showing first {len(oids)}' if count > len(oids) else '') + ' · '+scope)
        if oids:
            self.results.setCurrentRow(0)

    def jump(self, *_):
        # Enter must use the current text, even before the debounce timer fires.
        if self.timer.isActive():
            self.timer.stop()
            self.update_results()
        item = self.results.currentItem()
        if item is not None and self.repo is self.window.repo:
            self.window.open_detail_link(QUrl('commit:'+item.data(Qt.ItemDataRole.UserRole)))
            self.accept()

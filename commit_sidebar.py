"""Rich commit details with cancellable background queries and a session cache."""
from collections import OrderedDict
from html import escape
from pathlib import Path
from threading import Event
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot, QUrl
from PySide6.QtWidgets import QTextBrowser, QWidget, QVBoxLayout, QTabBar, QStackedWidget

from commit_info import read_commit_info, InspectionCancelled
from commit_browser import CommitBrowser
from theme import TAB_STYLESHEET
from qt_jobs import emit_if_alive
from git_reader import opened_worktree


_pool = QThreadPool()
_pool.setMaxThreadCount(2)


def commit_link(oid, subject='', history=False):
    suffix = '?history=1' if history else ''
    return f'<a href="commit:{escape(oid, quote=True)}{suffix}">{escape(oid[:12])}</a> {escape(subject)}'


def section(title, body):
    return f'<h3>{escape(title)}</h3>{body}'

def worktree_html(wt, relation, opened=False, highlight=False):
    location = 'Main worktree' if wt.main else 'Linked worktree'
    if opened:
        location += ' · opened here'
    branch = wt.branch.removeprefix('refs/heads/') if wt.branch else 'detached HEAD'
    notes = []
    if wt.locked is not None:
        notes.append('Locked'+(': '+wt.locked if wt.locked else ''))
    if wt.prunable is not None:
        notes.append('Prunable'+(': '+wt.prunable if wt.prunable else ''))
    folder = Path(wt.path).name or wt.path
    badge = '<span style="color: #c792ea"><b>'+('[WT · here]' if opened else '[WT]')+'</b></span> ' if highlight else ''
    body = (f'<p>{badge}<b>{escape(branch)} — {escape(folder)}</b><br>{escape(location)}<br>{escape(wt.path)}<br>'
            f'{escape(relation)}<br>HEAD: '+commit_link(wt.head)
            +('<br>'+escape(' · '.join(notes)) if notes else '')+'</p>')
    return '<table width="100%" bgcolor="#302638" cellpadding="8"><tr><td>'+body+'</td></tr></table>' if highlight else body


def checkout_section(checkouts):
    if not checkouts:
        return '<p style="color: #969696">No active worktree is checked out at this commit.</p>'
    ordered = sorted(checkouts, key=lambda entry: (not entry[1], entry[0].path.casefold()))
    count = len(ordered)
    title = f'Checked out in {count} worktree'+('s' if count != 1 else '')
    return (f'<h3 style="color: #c792ea">{title}</h3>'
            + ''.join(worktree_html(wt, 'HEAD is this commit', opened, highlight=True) for wt, opened in ordered))


def list_html(items, limit=80):
    items = list(items)
    body = '<br>'.join(items[:limit]) or 'None found'
    if len(items) > limit:
        body += f'<br>… {len(items)-limit} more'
    return body


def render_basic(commit, branches, repo=None, category=None):
    subject = commit.message.split('\n')[0]
    body = f'<h2>{escape(subject)}</h2>'
    if repo is not None:
        opened = opened_worktree(repo.path, repo.worktrees)
        body += checkout_section([(wt, wt == opened) for wt in repo.worktrees if wt.active and wt.head == commit.oid])
    body += (f'<p>Commit: {escape(commit.oid)}<br>'
             f'Author: {escape(commit.author)}<br>Date: {escape(commit.date)}</p>'
             + section('Message', f'<pre style="white-space: pre-wrap">{escape(commit.message)}</pre>'))
    refs = (section('Branches pointing here', escape(', '.join(branches)) or 'None')
            + section('Parents', list_html(commit_link(p) for p in commit.parents) if commit.parents else 'Root commit'))
    return refs if category == 'References' else body if category == 'Commit' else body + refs


def render_info(info, category=None):
    c = info.commit
    subject = c.message.split('\n')[0]
    kind = 'Merge commit' if len(c.parents) > 1 else 'Root commit' if not c.parents else 'Ordinary commit'
    checkouts = [(match.worktree, match.opened) for match in info.worktrees
                 if match.worktree.active and match.worktree.head == c.oid]
    body = (f'<h2>{escape(subject)}</h2>'+checkout_section(checkouts)
            + f'<p>{kind}<br>Commit: {escape(c.oid)}</p>'
            f'<p>Author: {escape(c.author)} &lt;{escape(info.author_email)}&gt;<br>'
            f'Authored: {escape(c.date)}<br>'
            f'Committer: {escape(info.committer)} &lt;{escape(info.committer_email)}&gt;<br>'
            f'Committed: {escape(info.committer_date)}</p>')
    commit_body = body + section('Message', f'<pre style="white-space: pre-wrap">{escape(c.message)}</pre>')
    commit_body += section('Tree', escape(info.tree))
    body = section('References pointing here', list_html(escape(ref) for ref in info.tip_refs))
    named_tip = any(not ref.startswith('tag: ') for ref in info.tip_refs)
    if named_tip and info.included_in:
        entries = []
        for entry in info.integrations:
            if entry.branch not in info.included_in:
                continue
            if entry.kind == 'merge':
                entries.append(f'<b>{escape(entry.branch)}</b>: merged into its first-parent history via<br>'
                               + commit_link(entry.merge, entry.subject, history=True))
            elif entry.kind == 'mainline':
                entries.append(f'<b>{escape(entry.branch)}</b>: included on its first-parent history; no introducing merge commit')
            else:
                entries.append(f'<b>{escape(entry.branch)}</b>: tip is included; introducing merge could not be established')
        body += section('Branch tip already included', list_html(entries))
        body += '<p>Inclusion can result from a merge, fast-forward, or shared branch history. Branch names shown are current references.</p>'
    body += section('Contained in branches', list_html(escape(ref) for ref in info.branches))
    body += section('Contained in tags', list_html(escape(tag) for tag in info.tags))
    history = [match for match in info.worktrees if match.worktree.active and match.worktree.head != c.oid]
    body += section('In worktree history', ''.join(worktree_html(match.worktree, match.relation, match.opened)
                                                 for match in sorted(history, key=lambda m: (not m.opened, m.worktree.path.casefold())))
                    or 'No related worktree history found.')
    recorded = [match for match in info.worktrees if not match.worktree.active]
    if recorded:
        body += section('Recorded worktree checkouts', ''.join(worktree_html(match.worktree, match.relation, match.opened)
                                                               for match in recorded))
    parents = []
    for index, oid in enumerate(c.parents):
        role = ('Destination-side parent (first parent)' if index == 0 else f'Incoming parent {index}') if len(c.parents) > 1 else 'Parent'
        parents.append(f'{role}<br>{commit_link(oid, info.parent_subjects.get(oid, "Metadata unavailable"))}')
    body += section('Parents / merge roles', list_html(parents) if parents else 'Root commit: no parents')
    body += section('Direct children', list_html(commit_link(oid, subject) for oid, subject in info.children))
    entries = []
    for entry in info.integrations:
        branch = escape(entry.branch)
        if entry.kind == 'merge':
            entries.append(f'<b>{branch}</b>: introduced into its first-parent history by<br>'
                           + commit_link(entry.merge, entry.subject, history=True))
        elif entry.kind == 'mainline':
            entries.append(f'<b>{branch}</b>: commit is on its first-parent history')
        else:
            entries.append(f'<b>{branch}</b>: integration path could not be established')
    body += section('How it landed', list_html(entries))
    body += '<p>Branch names are current references. Git does not record the original branch name; '
    body += 'containment alone does not prove a merge. Squash merges and cherry-picks create different commit IDs.</p>'
    references_body = body
    label = 'Changes against first parent' if c.parents else 'Changes against empty tree'
    body = section(label, escape(info.statistics)+f'<br><a href="diff:{c.oid}">Open side-by-side diff</a>')
    body += '<p>'+list_html(f'{escape(change.status)} &nbsp; <a href="diff:{c.oid}?{escape(urlencode({"file": change.new_path}), quote=True)}">'
                            f'{escape(change.old_path+" → "+change.new_path if change.old_path != change.new_path else change.new_path)}</a>'
                            for change in info.files)+'</p>'
    warnings = section('History limitations', list_html(escape(warning) for warning in info.warnings)) if info.warnings else ''
    pages = {'Commit': commit_body, 'References': references_body, 'Diff': body}
    if category is not None:
        heading = f'<h2>{escape(subject)}</h2><p>Commit: {escape(c.oid)}</p>' if category != 'Commit' else ''
        if category == 'References':
            heading += checkout_section(checkouts)
        return heading + pages[category] + warnings
    return ''.join(pages.values()) + warnings


def render_selection(repo, selected, cache, category=None):
    oids = [oid for oid in reversed(repo.commits) if oid in selected]
    authors = sorted({repo.commits[oid].author for oid in oids})
    branches = sorted({name for oid in oids for name in repo.branches.get(oid, [])})
    author_label = 'author name' if len(authors) == 1 else 'author names'
    branch_label = 'branch reference' if len(branches) == 1 else 'branch references'
    body = (f'<h2>{len(oids)} commits selected</h2>'
            f'<p>{len(authors)} {author_label} · {len(branches)} {branch_label} pointing at selection</p>')
    heading = body
    if len(oids) == 2:
        source, target = oids
        body += f'<p><a href="compare:{source}/{target}">Compare {source[:12]} → {target[:12]}</a> (D)</p>'
    else:
        body += '<p>Select exactly two commits to compare them with D.</p>'
    diff_body = body
    body = section('Branches pointing at selection', list_html(escape(name) for name in branches))
    if oids and all(oid in cache for oid in oids):
        shared = set(cache[oids[0]].branches)
        for oid in oids[1:]:
            shared.intersection_update(cache[oid].branches)
        body += section('Shared containing branches (cached)', list_html(escape(name) for name in sorted(shared)))

    relationships = {oid: [] for oid in oids}
    tree_summaries = []
    opened = opened_worktree(repo.path, repo.worktrees)
    for wt in repo.worktrees:
        if not wt.active:
            continue
        reachable, todo = set(), [wt.head]
        while todo:
            oid = todo.pop()
            if oid in reachable:
                continue
            reachable.add(oid)
            commit = repo.commits.get(oid)
            if commit:
                todo.extend(commit.parents)
        matches = set(oids) & reachable
        if not matches:
            continue
        ancestors = len(matches)-int(wt.head in matches)
        description = []
        if wt.head in matches:
            description.append('HEAD is selected')
        if ancestors:
            description.append(f'{ancestors} selected ancestor'+('s' if ancestors != 1 else '')+' in loaded history')
        tree_summaries.append(worktree_html(wt, ' · '.join(description), wt == opened, highlight=wt.head in selected))
        for oid in matches:
            relationships[oid].append(('HEAD' if oid == wt.head else 'ancestor')+': '+wt.path)
    body += section('Worktrees related to selection', ''.join(tree_summaries) or 'No matches in loaded history.')
    body += '<p>Worktree ancestry in this summary uses loaded history; inspect a single commit for full Git queries.</p>'
    cards = []
    for oid in oids:
        c = repo.commits[oid]
        names = ', '.join(repo.branches.get(oid, [])) or 'None'
        card = ('<p>'+commit_link(oid, c.message.split('\n')[0])+f'<br>Branches pointing here: {escape(names)}'
                f'<br>Author: {escape(c.author)}<br>Date: {escape(c.date)}')
        if relationships[oid]:
            card += '<br>'+escape(' · '.join(relationships[oid]))
        cards.append(card+'</p>')
    commits_body = heading + section('Selected commits', list_html(cards))
    pages = {'Commit': commits_body, 'References': heading + body, 'Diff': diff_body}
    return pages[category] if category is not None else diff_body + body + section('Selected commits', list_html(cards))


class JobSignals(QObject):
    finished = Signal(object, object, object)


class InfoJob(QRunnable):
    def __init__(self, key, repo, oid):
        super().__init__()
        self.key, self.repo, self.oid = key, repo, oid
        self.cancelled = Event()
        self.signals = JobSignals()

    def run(self):
        info, error = None, None
        try:
            info = read_commit_info(self.repo, self.oid, self.cancelled)
        except InspectionCancelled:
            pass
        except Exception as exc:
            error = str(exc)
        emit_if_alive(self.signals, 'finished', self.key, info, error)


class CommitSidebar(QWidget):
    anchorClicked = Signal(QUrl)

    def __init__(self):
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 6, 8, 6)
        box.setSpacing(4)
        self.tabs = QTabBar()
        self.tabs.setStyleSheet(TAB_STYLESHEET)
        self.tabs.setExpanding(True)
        self.pages = QStackedWidget()
        self.browsers = {}
        for title in ('Commit', 'References', 'Diff', 'File tree'):
            self.tabs.addTab(title)
            browser = QTextBrowser()
            browser.setOpenLinks(False)
            browser.setOpenExternalLinks(False)
            browser.document().setDefaultStyleSheet('a { color: #80c7ff; } h2 { color: #ffd166; font-size: 14pt; } '
                                                   'h3 { color: #80ead9; margin-top: 16px; } pre { font-family: monospace; }')
            browser.anchorClicked.connect(self.anchorClicked.emit)
            self.browsers[title] = browser
            self.pages.addWidget(browser)
        box.addWidget(self.tabs)
        box.addWidget(self.pages, 1)
        self.tabs.currentChanged.connect(self.change_tab)
        self.file_browser = None
        self.repo = None
        self.cache = OrderedDict()
        self.jobs = {}
        self.active_oid = None
        self.generation = 0
        self.request_id = 0
        self.active_key = None
        self.context_note = ''

    def change_tab(self, index):
        browser = self.browsers[self.tabs.tabText(index)]
        scroll = browser.verticalScrollBar().value()
        self.pages.setCurrentIndex(index)
        self.ensure_file_browser()
        browser.verticalScrollBar().setValue(scroll)

    def clear_file_browser(self):
        if self.file_browser is not None:
            browser, self.file_browser = self.file_browser, None
            self.pages.removeWidget(browser)
            browser.close()
            browser.deleteLater()
            self.pages.insertWidget(3, self.browsers['File tree'])
            self.pages.setCurrentIndex(self.tabs.currentIndex())

    def ensure_file_browser(self):
        if self.tabs.currentIndex() != 3 or self.active_oid is None or self.file_browser is not None:
            return
        self.file_browser = CommitBrowser(self.repo.path, self.active_oid, self, embedded=True)
        self.pages.removeWidget(self.browsers['File tree'])
        self.pages.insertWidget(3, self.file_browser)
        self.pages.setCurrentIndex(3)

    def setPlainText(self, text):
        self.cancel_pending()
        for browser in self.browsers.values():
            browser.setPlainText(text)

    def toPlainText(self):
        if self.file_browser is not None and self.tabs.currentIndex() == 3:
            return self.file_browser.preview.toPlainText()
        return self.pages.currentWidget().toPlainText()

    def render_details(self, info=None, error=None, preserve_scroll=False):
        for title in ('Commit', 'References', 'Diff'):
            browser = self.browsers[title]
            scroll = browser.verticalScrollBar().value() if preserve_scroll else 0
            if info is not None:
                body = render_info(info, title)
            else:
                c = self.repo.commits.get(self.active_oid)
                body = render_basic(c, self.repo.branches.get(self.active_oid, []), self.repo, title) if c and title != 'Diff' else f'<p>Commit: {escape(self.active_oid)}</p>'
                body += (f'<p>Extended details unavailable: {escape(error)}</p>' if error else
                         '<p>Loading relationships and change summary…</p>')
            browser.setHtml(self.context_note + body)
            browser.verticalScrollBar().setValue(scroll)
        self.browsers['File tree'].setPlainText('Open this tab to browse tracked files at this commit.')
        self.ensure_file_browser()

    def closeEvent(self, event):
        self.cancel_pending()
        super().closeEvent(event)

    def reset_repository(self, repo):
        self.cancel_pending()
        self.repo = repo
        self.generation += 1
        self.cache.clear()

    def cancel_pending(self):
        for job in self.jobs.values():
            job.cancelled.set()
        self.active_oid = None
        self.clear_file_browser()

    def show_commit(self, repo, oid):
        if repo is not self.repo:
            self.reset_repository(repo)
        if self.active_oid == oid and self.active_key in self.jobs:
            return
        same_commit = self.active_oid == oid
        if not same_commit:
            self.cancel_pending()
        self.active_oid = oid
        self.request_id += 1
        key = (self.generation, oid, self.request_id)
        self.active_key = key
        self.context_note = ''
        if oid not in repo.commits:
            self.context_note = ('<p>This commit is outside the loaded graph. Switch to history mode to navigate its ancestry.</p>'
                                 if repo.branches_only else
                                 '<p>This commit is outside the loaded graph. Load more ancestors, choose All history, or include remote branches to place it in the graph.</p>')
        if oid in self.cache:
            self.cache.move_to_end(oid)
            self.render_details(self.cache[oid], preserve_scroll=same_commit)
            return
        self.render_details()
        job = InfoJob(key, repo, oid)
        job.signals.finished.connect(self.finished)
        self.jobs[key] = job
        _pool.start(job)

    def show_selection(self, repo, oids):
        if repo is not self.repo:
            self.reset_repository(repo)
        self.cancel_pending()
        for title in ('Commit', 'References', 'Diff'):
            self.browsers[title].setHtml(render_selection(repo, set(oids), self.cache, title))
        self.browsers['File tree'].setPlainText('Select a single commit to browse its file tree.')

    @Slot(object, object, object)
    def finished(self, key, info, error):
        job = self.jobs.pop(key, None)
        if job is None or job.cancelled.is_set() or key[0] != self.generation:
            return
        if info is not None:
            self.cache[key[1]] = info
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
        if key[1] != self.active_oid:
            return
        self.render_details(info, None if info else error or 'Unknown error', preserve_scroll=True)

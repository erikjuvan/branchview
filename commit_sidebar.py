"""Rich commit details with cancellable background queries and a session cache."""
from collections import OrderedDict
from html import escape
from threading import Event
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QTextBrowser

from commit_info import read_commit_info, InspectionCancelled
from qt_jobs import emit_if_alive


_pool = QThreadPool()
_pool.setMaxThreadCount(2)


def commit_link(oid, subject=''):
    return f'<a href="commit:{escape(oid, quote=True)}">{escape(oid[:12])}</a> {escape(subject)}'


def section(title, body):
    return f'<h3>{escape(title)}</h3>{body}'

def worktree_html(wt, relation, opened=False):
    location = 'Main worktree' if wt.main else 'Linked worktree'
    if opened:
        location += ' · opened here'
    branch = wt.branch.removeprefix('refs/heads/') if wt.branch else 'detached HEAD'
    notes = []
    if wt.locked is not None:
        notes.append('Locked'+(': '+wt.locked if wt.locked else ''))
    if wt.prunable is not None:
        notes.append('Prunable'+(': '+wt.prunable if wt.prunable else ''))
    return (f'<p><b>{escape(location)} · {escape(branch)}</b><br>{escape(wt.path)}<br>'
            f'{escape(relation)}'+('<br>'+escape(' · '.join(notes)) if notes else '')+'</p>')


def list_html(items, limit=80):
    items = list(items)
    body = '<br>'.join(items[:limit]) or 'None found'
    if len(items) > limit:
        body += f'<br>… {len(items)-limit} more'
    return body


def render_basic(commit, branches, repo=None):
    subject = commit.message.split('\n')[0]
    body = (f'<h2>{escape(subject)}</h2>'
            f'<p>Commit: {escape(commit.oid)}<br>'
            f'Branches pointing here: {escape(", ".join(branches)) or "None"}<br>'
            f'Author: {escape(commit.author)}<br>Date: {escape(commit.date)}</p>'
            + section('Parents', list_html(commit_link(p) for p in commit.parents) if commit.parents else 'Root commit')
            + section('Message', f'<pre style="white-space: pre-wrap">{escape(commit.message)}</pre>'))
    if repo is not None:
        heads = [wt for wt in repo.worktrees if wt.head == commit.oid and not wt.bare]
        body += section('Worktree HEAD checkouts', ''.join(worktree_html(wt, 'HEAD is this commit') for wt in heads)
                        or 'No worktree HEAD points here. Checking worktree ancestry…')
    return body


def render_info(info):
    c = info.commit
    subject = c.message.split('\n')[0]
    kind = 'Merge commit' if len(c.parents) > 1 else 'Root commit' if not c.parents else 'Ordinary commit'
    body = (f'<h2>{escape(subject)}</h2><p>{kind}<br>Commit: {escape(c.oid)}</p>'
            f'<p>Author: {escape(c.author)} &lt;{escape(info.author_email)}&gt;<br>'
            f'Authored: {escape(c.date)}<br>'
            f'Committer: {escape(info.committer)} &lt;{escape(info.committer_email)}&gt;<br>'
            f'Committed: {escape(info.committer_date)}</p>')
    body += section('References pointing here', list_html(escape(ref) for ref in info.tip_refs))
    body += section('Contained in branches', list_html(escape(ref) for ref in info.branches))
    body += section('Contained in tags', list_html(escape(tag) for tag in info.tags))
    body += section('Worktree checkouts and history', ''.join(worktree_html(match.worktree, match.relation, match.opened)
                                                            for match in info.worktrees)
                    or 'No matching worktree checkout or ancestry found in available history.')
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
                           + commit_link(entry.merge, entry.subject))
        elif entry.kind == 'mainline':
            entries.append(f'<b>{branch}</b>: commit is on its first-parent history')
        else:
            entries.append(f'<b>{branch}</b>: integration path could not be established')
    body += section('How it landed', list_html(entries))
    body += '<p>Branch names are current references. Git does not record the original branch name; '
    body += 'containment alone does not prove a merge. Squash merges and cherry-picks create different commit IDs.</p>'
    label = 'Changes against first parent' if c.parents else 'Changes against empty tree'
    body += section(label, escape(info.statistics)+f'<br><a href="diff:{c.oid}">Open side-by-side diff</a>')
    body += '<p>'+list_html(f'{escape(change.status)} &nbsp; <a href="diff:{c.oid}?{escape(urlencode({"file": change.new_path}), quote=True)}">'
                            f'{escape(change.old_path+" → "+change.new_path if change.old_path != change.new_path else change.new_path)}</a>'
                            for change in info.files)+'</p>'
    body += section('Message', f'<pre style="white-space: pre-wrap">{escape(c.message)}</pre>')
    body += section('Tree', escape(info.tree))
    if info.warnings:
        body += section('History limitations', list_html(escape(warning) for warning in info.warnings))
    return body


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


class CommitSidebar(QTextBrowser):
    def __init__(self):
        super().__init__()
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.document().setDefaultStyleSheet('a { color: #80c7ff; } h2 { color: #ffd166; font-size: 14pt; } '
                                            'h3 { color: #80ead9; margin-top: 16px; } pre { font-family: monospace; }')
        self.repo = None
        self.cache = OrderedDict()
        self.jobs = {}
        self.active_oid = None
        self.generation = 0
        self.request_id = 0
        self.active_key = None
        self.basic = ''

    def reset_repository(self, repo):
        self.cancel_pending()
        self.repo = repo
        self.generation += 1
        self.cache.clear()

    def cancel_pending(self):
        for job in self.jobs.values():
            job.cancelled.set()
        self.active_oid = None

    def show_commit(self, repo, oid):
        if repo is not self.repo:
            self.reset_repository(repo)
        if self.active_oid == oid and self.active_key in self.jobs:
            return
        self.cancel_pending()
        self.active_oid = oid
        self.request_id += 1
        key = (self.generation, oid, self.request_id)
        self.active_key = key
        if oid in self.cache:
            self.cache.move_to_end(oid)
            self.setHtml(render_info(self.cache[oid]))
            return
        c = repo.commits.get(oid)
        self.basic = render_basic(c, repo.branches.get(oid, []), repo) if c else f'<p>Commit: {escape(oid)}</p>'
        self.setHtml(self.basic+'<p>Loading relationships and change summary…</p>')
        job = InfoJob(key, repo, oid)
        job.signals.finished.connect(self.finished)
        self.jobs[key] = job
        _pool.start(job)

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
        scroll = self.verticalScrollBar().value()
        self.setHtml(render_info(info) if info else self.basic+f'<p>Extended details unavailable: {escape(error or "Unknown error")}</p>')
        self.verticalScrollBar().setValue(scroll)

"""Cancellable discovery of checkout roots, excluding registered submodules."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from git_process import run_git, GitCancelled
from qt_jobs import emit_if_alive


def canonical(path):
    return os.path.normcase(str(Path(path).resolve()))


@dataclass
class ScanResult:
    repositories: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    submodules: int = 0


def scan_repositories(folder, recursive=False, cancelled=None, progress=None):
    cancelled = cancelled or Event()
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'Not a directory: {root}')
    result = ScanResult()
    excluded = set()
    inspected = set()
    found = set()

    def git(path, *args):
        return run_git(str(path), list(args), cancelled=cancelled, timeout=15)

    def register_submodules(path):
        key = canonical(path)
        if key in inspected:
            return
        inspected.add(key)
        # The index identifies both current and old-form submodules, including
        # uninitialized ones. NUL records preserve spaces/newlines in paths.
        for record in git(path, 'ls-files', '--stage', '-z').split(b'\0'):
            if not record:
                continue
            metadata, name = record.split(b'\t', 1)
            if metadata.split()[0] == b'160000':
                excluded.add(canonical(Path(path)/os.fsdecode(name)))

    # Detect submodules even when the chosen folder is itself a submodule or
    # below one, and even when its .git directory uses the old embedded form.
    for ancestor in root.parents:
        if cancelled.is_set():
            raise GitCancelled()
        if (ancestor/'.git').exists():
            try:
                register_submodules(ancestor)
            except GitCancelled:
                raise
            except Exception as exc:
                result.errors.append(f'{ancestor}: {exc}')

    def excluded_path(path):
        return any(canonical(parent) in excluded for parent in (path, *path.parents))

    todo = [(root, 0)]
    visited = set()
    last_progress = 0
    while todo:
        if cancelled.is_set():
            raise GitCancelled()
        path, depth = todo.pop()
        key = canonical(path)
        if key in visited:
            continue
        visited.add(key)
        if excluded_path(path):
            result.submodules += 1
            continue
        if progress and monotonic()-last_progress >= .1:
            progress(f'Scanning {path} · {len(result.repositories)} repositories found')
            last_progress = monotonic()
        bare = (path/'HEAD').is_file() and (path/'objects').is_dir() and (path/'refs').is_dir()
        marker = (path/'.git').exists()
        if marker or bare:
            try:
                is_bare = git(path, 'rev-parse', '--is-bare-repository').strip() == b'true'
                if is_bare:
                    valid_root = canonical(os.fsdecode(git(path, 'rev-parse', '--absolute-git-dir')).strip()) == key
                else:
                    valid_root = canonical(os.fsdecode(git(path, 'rev-parse', '--show-toplevel')).strip()) == key
                if valid_root:
                    superproject = git(path, 'rev-parse', '--show-superproject-working-tree').strip()
                    if superproject:
                        result.submodules += 1
                        continue
                    if not is_bare:
                        register_submodules(path)
                    if key not in found:
                        result.repositories.append(str(path))
                        found.add(key)
                    if is_bare:
                        continue  # Its entire contents are Git metadata.
            except GitCancelled:
                raise
            except Exception as exc:
                result.errors.append(f'{path}: {exc}')
        if not recursive and depth >= 1:
            continue
        try:
            with os.scandir(path) as entries:
                children = []
                for entry in entries:
                    if cancelled.is_set():
                        raise GitCancelled()
                    if entry.name == '.git':
                        continue
                    # Reparse points include Windows directory junctions.
                    try:
                        attrs = getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0)
                        if entry.is_symlink() or attrs & 0x400:
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            children.append(Path(entry.path))
                    except OSError as exc:
                        result.errors.append(f'{entry.path}: {exc}')
            todo.extend((child, depth+1) for child in sorted(children, reverse=True))
        except OSError as exc:
            result.errors.append(f'{path}: {exc}')
    result.repositories.sort(key=str.casefold)
    return result


_pool = QThreadPool()
_pool.setMaxThreadCount(1)


class ScanSignals(QObject):
    progress = Signal(object, str)
    finished = Signal(object, object, object)


class ScanJob(QRunnable):
    def __init__(self, key, folder, recursive):
        super().__init__()
        self.key, self.folder, self.recursive = key, folder, recursive
        self.cancelled = Event()
        self.signals = ScanSignals()

    def run(self):
        result = error = None
        try:
            result = scan_repositories(self.folder, self.recursive, self.cancelled,
                                      lambda message: emit_if_alive(self.signals, 'progress', self.key, message))
        except GitCancelled:
            pass
        except Exception as exc:
            error = str(exc)
        emit_if_alive(self.signals, 'finished', self.key, result, error)


class RepositoryScanner(QObject):
    progress = Signal(str)
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.serial = 0
        self.active = None
        self.jobs = {}

    def start(self, folder, recursive=False):
        self.cancel()
        self.serial += 1
        job = ScanJob(self.serial, folder, recursive)
        self.active = job.key
        self.jobs[job.key] = job
        job.signals.progress.connect(self.report)
        job.signals.finished.connect(self.finished)
        _pool.start(job)

    def cancel(self):
        self.active = None
        for job in self.jobs.values():
            job.cancelled.set()

    def report(self, key, message):
        if key == self.active:
            self.progress.emit(message)

    def finished(self, key, result, error):
        job = self.jobs.pop(key, None)
        if job is None or key != self.active or job.cancelled.is_set():
            return
        self.active = None
        if error:
            self.failed.emit(error)
        elif result is not None:
            self.ready.emit(result)

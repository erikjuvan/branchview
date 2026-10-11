"""Cached tree/blob exports; no checkout, filters, or repository writes."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from threading import Event, Thread
import uuid
from time import monotonic

from PySide6.QtCore import QStandardPaths
from commit_files import read_tree
from git_process import GitCancelled


def cache_directory():
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation))/'GitBranchViewer'/'commit-snapshots'


def safe_file(root, name):
    parts = PurePosixPath(name).parts
    if not parts or PurePosixPath(name).is_absolute() or any(p in ('', '.', '..') or p.casefold() == '.git' for p in name.split('/')):
        raise ValueError(f'Cannot export path: {name}')
    if '\\' in name or '\0' in name:
        raise ValueError(f'Cannot export path: {name}')
    if os.name == 'nt':
        reserved = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
        if any(any(c in p for c in ':<>"|?*') or p.endswith((' ', '.')) or p.split('.')[0].upper() in reserved for p in parts):
            raise ValueError(f'Path cannot be represented on Windows: {name}')
    destination = root.joinpath(*parts)
    if not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes snapshot: {name}')
    return destination


@dataclass(frozen=True)
class Snapshot:
    directory: Path
    workspace: Path
    file: Path | None
    notices: tuple[str, ...]
    reused: bool = False


def _cached(directory, source, commit, scope):
    try:
        metadata = json.loads((directory/'snapshot.json').read_text(encoding='utf-8'))
        if (metadata['source'], metadata['commit'], metadata['scope']) != (source, commit, scope):
            return None
        expected = {entry['path'] for entry in metadata['files']}
        actual = {path.relative_to(directory/'files').as_posix() for path in (directory/'files').rglob('*') if path.is_file() or path.is_symlink()}
        if actual != expected:
            return None
        for entry in metadata['files']:
            path = safe_file(directory/'files', entry['path'])
            if path.is_symlink():
                return None
            stat = path.stat()
            if [stat.st_size, stat.st_mtime_ns] != entry['stat']:
                return None  # Preserve edits and prepare a fresh copy instead.
        workspace = directory/'snapshot.code-workspace'
        if not workspace.is_file():
            return None
        return Snapshot(directory, workspace, safe_file(directory/'files', scope) if scope else None,
                        tuple(metadata['notices']), True)
    except (ValueError, OSError, KeyError, TypeError):
        return None


def export_snapshot(repo_path, commit, cancelled=None, progress=None, entry=None, cache_root=None):
    cancelled = cancelled or Event()
    source = os.path.normcase(str(Path(repo_path).resolve()))
    identity = hashlib.sha256(source.encode()).hexdigest()[:20]
    scope = entry.path if entry else ''
    # Validate the hash even for single-file exports.
    entries = read_tree(repo_path, commit, cancelled, entry.path if entry else None)
    if entry:
        actual = next((item for item in entries if item.path == entry.path), None)
        if actual is None or actual.kind != 'blob':
            raise ValueError('Select a tracked file; submodules cannot be exported.')
        entries = [actual]
    base = (Path(cache_root) if cache_root else cache_directory())/identity/commit
    base.mkdir(parents=True, exist_ok=True)
    for candidate in base.iterdir():
        if cancelled.is_set():
            raise GitCancelled()
        if candidate.is_dir() and not candidate.name.startswith('.'):
            cached = _cached(candidate, source, commit, scope)
            if cached:
                return cached
    staging = base/('.building-'+uuid.uuid4().hex)
    staging.mkdir()
    files_root = staging/'files'
    files_root.mkdir()
    notices, file_metadata = [], []
    stop = Event()
    process = None
    destinations = set()
    last_progress = 0
    try:
        env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'}
        process = subprocess.Popen(['git', '--no-replace-objects', '-C', repo_path, 'cat-file', '--batch'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        def watch():
            while not stop.wait(.1):
                if cancelled.is_set():
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return
        watcher = Thread(target=watch, daemon=True)
        watcher.start()
        for index, item in enumerate(entries):
            if cancelled.is_set():
                raise GitCancelled()
            path = safe_file(files_root, item.path)
            key = os.path.normcase(str(path))
            if key in destinations:
                raise ValueError(f'File names collide on this filesystem: {item.path}')
            destinations.add(key)
            if item.kind == 'commit':
                path.mkdir(parents=True, exist_ok=True)
                notices.append(f'Submodule {item.path}: {item.oid} (contents not exported)')
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if progress and monotonic()-last_progress >= .1:
                progress(f'Exporting {index+1:,}/{len(entries):,} · {item.path}')
                last_progress = monotonic()
            process.stdin.write((item.oid+'\n').encode('ascii'))
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[1] != b'blob':
                raise ValueError(f'Cannot read blob for {item.path}')
            remaining = int(header[2])
            prefix = b''
            with path.open('wb') as output:
                while remaining:
                    if cancelled.is_set():
                        raise GitCancelled()
                    chunk = process.stdout.read(min(remaining, 1024*1024))
                    if not chunk:
                        raise ValueError(f'Incomplete blob for {item.path}')
                    if not prefix:
                        prefix = chunk[:200]
                    output.write(chunk)
                    remaining -= len(chunk)
            if process.stdout.read(1) != b'\n':
                raise ValueError('Invalid Git blob response')
            if item.mode == '120000':
                notices.append(f'Symlink {item.path}: exported as a text file containing its target')
            if prefix.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
                notices.append(f'Git LFS pointer {item.path}: external contents not fetched')
            if os.name != 'nt' and item.mode == '100755':
                path.chmod(0o755)
            stat = path.stat()
            file_metadata.append({'path': item.path, 'stat': [stat.st_size, stat.st_mtime_ns]})
        if cancelled.is_set():
            raise GitCancelled()
        workspace_data = {'folders': [{'path': 'files', 'name': f'{Path(repo_path).name} @ {commit[:12]}'}]}
        (staging/'snapshot.code-workspace').write_text(json.dumps(workspace_data, indent=2), encoding='utf-8')
        metadata = {'source': source, 'commit': commit, 'scope': scope, 'files': file_metadata, 'notices': notices}
        (staging/'snapshot.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        (staging/'ABOUT.txt').write_text(f'Exported from {repo_path}\nCommit: {commit}\n'
                                        'Edits affect this copy only. Source checkout is unchanged.\n'
                                        'Only tracked contents are exported.\n'+'\n'.join(notices), encoding='utf-8')
        final = base/uuid.uuid4().hex
        staging.rename(final)
        return Snapshot(final, final/'snapshot.code-workspace', safe_file(final/'files', scope) if scope else None, tuple(notices))
    except Exception:
        shutil.rmtree(staging)
        if cancelled.is_set():
            raise GitCancelled()
        raise
    finally:
        stop.set()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdin.close()
            process.stdout.close()


def remove_snapshot(directory, cache_root=None):
    root = (Path(cache_root) if cache_root else cache_directory()).resolve()
    directory = Path(directory).resolve()
    if not directory.is_relative_to(root) or len(directory.relative_to(root).parts) != 3:
        raise ValueError('Not a snapshot directory')
    shutil.rmtree(directory)

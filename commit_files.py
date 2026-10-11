"""Exact tracked tree entries and bounded historical file previews."""
from dataclasses import dataclass
import os
import re
from git_process import run_git


@dataclass(frozen=True)
class TreeFile:
    path: str
    oid: str
    mode: str
    kind: str


def read_tree(repo_path, commit, cancelled=None):
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit):
        raise ValueError('Expected a full commit hash')
    raw = run_git(repo_path, ['ls-tree', '-r', '-z', '--full-tree', commit], cancelled=cancelled)
    entries = []
    for record in raw.split(b'\0'):
        if record:
            metadata, path = record.split(b'\t', 1)
            mode, kind, oid = metadata.decode('ascii').split()
            entries.append(TreeFile(os.fsdecode(path), oid, mode, kind))
    return entries


def preview_file(repo_path, entry, cancelled=None):
    if entry.kind == 'commit':
        return f'Submodule reference: {entry.oid}\nSubmodule contents are not loaded.'
    size = int(run_git(repo_path, ['cat-file', '-s', entry.oid], cancelled=cancelled))
    if size > 2_000_000:
        return f'File size: {size:,} bytes. Text previews are limited to 2 MB.'
    data = run_git(repo_path, ['cat-file', 'blob', entry.oid], cancelled=cancelled)
    if b'\0' in data:
        return f'Binary file · {size:,} bytes'
    text = data.decode('utf-8-sig', errors='replace')
    if entry.mode == '120000':
        return 'Symbolic link target:\n'+text
    if data.startswith(b'version https://git-lfs.github.com/spec/v1\n'):
        return 'Git LFS pointer (external contents are not fetched):\n\n'+text
    return text

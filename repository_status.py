"""Read a checkout summary without reading patches or changing Git state."""
from dataclasses import dataclass, replace
from pathlib import Path

from git_process import run_git


@dataclass(frozen=True)
class RepositoryStatus:
    branch: str | None = None
    oid: str = ''
    unborn: bool = False
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    conflicts: int = 0
    operation: str | None = None
    bare: bool = False


def parse_status(output: bytes) -> RepositoryStatus:
    values = dict(staged=0, unstaged=0, untracked=0, conflicts=0)
    records = iter(output.split(b'\0'))
    for record in records:
        if record.startswith(b'# '):
            key, _, value = record[2:].partition(b' ')
            value = value.decode('utf-8', errors='replace')
            if key == b'branch.head':
                values['branch'] = None if value == '(detached)' else value
            elif key == b'branch.oid':
                values['unborn'] = value == '(initial)'
                values['oid'] = '' if value == '(initial)' else value
            elif key == b'branch.upstream':
                values['upstream'] = value
            elif key == b'branch.ab':
                ahead, behind = value.split()
                values['ahead'], values['behind'] = int(ahead[1:]), int(behind[1:])
        elif record.startswith((b'1 ', b'2 ')):
            fields = record.split(b' ', 3)
            xy, sub = fields[1:3]
            values['staged'] += xy[:1] != b'.'
            values['unstaged'] += xy[1:2] != b'.' or (sub.startswith(b'S') and sub[2:] != b'..')
            if record.startswith(b'2 '):
                # Renames/copies have a second NUL-separated path, not a record.
                next(records, None)
        elif record.startswith(b'u '):
            values['conflicts'] += 1
        elif record.startswith(b'? '):
            values['untracked'] += 1
    return RepositoryStatus(**values)


def read_repository_status(path: str, cancelled=None) -> RepositoryStatus:
    markers = ('rebase-merge', 'rebase-apply', 'MERGE_HEAD', 'CHERRY_PICK_HEAD',
               'REVERT_HEAD', 'sequencer', 'BISECT_START')
    args = ['rev-parse', '--is-bare-repository', '--path-format=absolute']
    for marker in markers:
        args.extend(['--git-path', marker])
    metadata = run_git(path, args, cancelled=cancelled, timeout=15).decode('utf-8', errors='replace').splitlines()
    if metadata[0] == 'true':
        return RepositoryStatus(bare=True)
    paths = dict(zip(markers, map(Path, metadata[1:])))
    operation = None
    if paths['rebase-merge'].exists():
        operation = 'Rebase in progress'
    elif paths['rebase-apply'].exists():
        operation = 'Apply in progress' if (paths['rebase-apply'] / 'applying').exists() else 'Rebase in progress'
    else:
        for marker, label in [('MERGE_HEAD', 'Merge'), ('CHERRY_PICK_HEAD', 'Cherry-pick'),
                              ('REVERT_HEAD', 'Revert'), ('sequencer', 'Sequence'), ('BISECT_START', 'Bisect')]:
            if paths[marker].exists():
                operation = label + ' in progress'
                break
    output = run_git(path, ['status', '--porcelain=v2', '--branch', '-z', '--untracked-files=all'],
                     cancelled=cancelled, timeout=20)
    return replace(parse_status(output), operation=operation)

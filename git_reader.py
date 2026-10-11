"""Read-only Git access. No shell commands or repository modifications."""
from dataclasses import dataclass, field
from pathlib import Path
import os
import subprocess
from git_process import run_git, GitCancelled

@dataclass(frozen=True)
class Commit:
    oid: str
    parents: tuple[str, ...]
    author: str
    date: str
    message: str

@dataclass(frozen=True)
class Worktree:
    path: str
    head: str = ''
    branch: str | None = None
    detached: bool = False
    bare: bool = False
    locked: str | None = None
    prunable: str | None = None
    main: bool = False

    @property
    def active(self):
        return not self.bare and self.prunable is None and bool(self.head.strip('0'))

def parse_worktrees(output: bytes) -> list[Worktree]:
    records, attributes = [], {}
    for item in [*output.split(b'\0'), b'']:
        if item:
            key, _, value = item.decode('utf-8', errors='replace').partition(' ')
            attributes[key] = value
        elif attributes:
            if 'worktree' in attributes:
                records.append(Worktree(attributes['worktree'], attributes.get('HEAD', ''),
                                        attributes.get('branch'), 'detached' in attributes,
                                        'bare' in attributes, attributes.get('locked'),
                                        attributes.get('prunable'), not records))
            attributes = {}
    return records

def read_worktrees(path: str, cancelled=None, git_runner=None) -> list[Worktree]:
    args = ('worktree', 'list', '--porcelain', '-z')
    output = git_runner(*args) if git_runner else run_git(path, args, cancelled=cancelled)
    return parse_worktrees(output)

def opened_worktree(path: str, worktrees: list[Worktree]) -> Worktree | None:
    opened = Path(path).resolve()
    candidates = [wt for wt in worktrees if opened.is_relative_to(Path(wt.path).resolve())]
    return max(candidates, key=lambda wt: len(wt.path), default=None)

@dataclass
class Repository:
    path: str
    commits: dict[str, Commit]
    branches: dict[str, list[str]]
    shallow: bool = False
    branches_only: bool = False
    commit_limit: int | None = None
    history_limited: bool = False
    worktrees: list[Worktree] = field(default_factory=list)
    branch_refs: dict[str, str] = field(default_factory=dict)

def read_repository(path: str, remote: bool = False, branches_only: bool = False,
                    cancelled=None, progress=None, commit_limit: int | None = None) -> Repository:
    if commit_limit is not None and commit_limit <= 0:
        raise ValueError('History limit must be positive or None for all history.')
    path = str(Path(path).expanduser().resolve())
    def git(*args, input_bytes=None):
        return run_git(path, args, cancelled=cancelled, input_bytes=input_bytes).decode('utf-8', errors='replace')
    def report(message):
        if progress:
            progress(message)
    report('Checking repository')
    git('rev-parse', '--git-dir')
    refs = ['refs/heads'] + (['refs/remotes'] if remote else [])
    branches = {}
    branch_refs = {}
    report('Reading branch references')
    for line in git('for-each-ref', '--format=%(objectname)%09%(refname:short)%09%(symref)%09%(refname)', *refs).splitlines():
        oid, name, symbolic, ref = line.split('\t')
        if not symbolic:
            branches.setdefault(oid, []).append(name)
            branch_refs[name] = ref
    commits = {}
    truncated = False
    if branches:
        # NUL fields avoid ambiguity from whitespace and multiline messages.
        ordering = ['--no-walk=sorted'] if branches_only else ['--topo-order']
        if commit_limit is not None and not branches_only:
            ordering.append(f'--max-count={commit_limit+1}')
        report('Reading branch tips' if branches_only else 'Reading commit history')
        output = git('log', *ordering, '--no-show-signature',
                     '--format=%H%x00%P%x00%an%x00%aI%x00%B%x00', '--stdin',
                     input_bytes=('\n'.join(branches)+'\n').encode())
        fields = output.split('\0')
        for i in range(0, len(fields)-1, 5):
            if cancelled is not None and cancelled.is_set():
                raise GitCancelled()
            oid, parents, author, date, message = fields[i:i+5]
            oid = oid.strip()
            if not branches_only and commit_limit is not None and len(commits) >= commit_limit:
                truncated = True
                break
            commits[oid] = Commit(oid, tuple(parents.split()), author, date, message.strip())
        # A global history budget must never remove an older branch head.
        missing_tips = set(branches)-commits.keys()
        if missing_tips:
            report('Reading remaining branch tips')
            tip_fields = git('log', '--no-walk=sorted', '--no-show-signature',
                             '--format=%H%x00%P%x00%an%x00%aI%x00%B%x00', '--stdin',
                             input_bytes=('\n'.join(sorted(missing_tips))+'\n').encode()).split('\0')
            for i in range(0, len(tip_fields)-1, 5):
                if cancelled is not None and cancelled.is_set():
                    raise GitCancelled()
                oid, parents, author, date, message = tip_fields[i:i+5]
                oid = oid.strip()
                commits[oid] = Commit(oid, tuple(parents.split()), author, date, message.strip())
    incomplete = truncated and any(p not in commits for c in commits.values() for p in c.parents)
    report('Reading worktree checkouts')
    worktrees = read_worktrees(path, cancelled=cancelled)
    return Repository(path, commits, branches, git('rev-parse', '--is-shallow-repository').strip() == 'true',
                      branches_only, commit_limit, incomplete, worktrees, branch_refs)

def read_diff(repo: Repository, oid: str, parent: str | None) -> str:
    """Compare a commit to an actual parent (or empty tree for a root)."""
    if oid not in repo.commits or (parent is not None and parent not in repo.commits[oid].parents):
        raise ValueError('Invalid commit or parent')
    flags = ['--no-ext-diff', '--no-textconv', '--no-color', '--stat', '--patch']
    args = (['diff', *flags, parent, oid, '--'] if parent else
            ['show', '--format=', '--root', *flags, oid, '--'])
    return _read_patch(repo, args) or 'No changes relative to this parent.'

def read_commit_diff(repo: Repository, source: str, target: str) -> str:
    """Compare the trees of any two loaded commits, from source to target."""
    if source not in repo.commits or target not in repo.commits:
        raise ValueError('Invalid comparison commit')
    args = ['diff', '--no-ext-diff', '--no-textconv', '--no-color', '--stat', '--patch',
            source, target, '--']
    return _read_patch(repo, args) or 'No changes between these commits.'

def _read_patch(repo: Repository, args: list[str]) -> str:
    common = ['git', '--no-replace-objects', '-C', repo.path]
    result = subprocess.run(common + args, capture_output=True, encoding='utf-8',
                            errors='replace', timeout=120, env={**os.environ, 'GIT_OPTIONAL_LOCKS':'0'})
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout

@dataclass(frozen=True)
class ChangedFile:
    status: str
    old_path: str
    new_path: str
    old_blob: str
    new_blob: str
    old_mode: str
    new_mode: str

def _git_bytes(repo: Repository, *args: str) -> bytes:
    result = subprocess.run(['git', '--no-replace-objects', '-C', repo.path, *args],
                            capture_output=True, timeout=120,
                            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'})
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace').strip())
    return result.stdout

def read_changed_files(repo: Repository, source: str | None, target: str, git_runner=None) -> list[ChangedFile]:
    """Read NUL-delimited tree changes, retaining blob IDs and rename paths."""
    if target not in repo.commits or (source is not None and source not in repo.commits
                                      and source not in repo.commits[target].parents):
        raise ValueError('Invalid comparison commit')
    flags = ['--raw', '-z', '--no-abbrev', '--no-ext-diff', '--no-textconv', '-M']
    args = (['diff', *flags, source, target, '--'] if source else
            ['diff-tree', '--root', '--no-commit-id', '-r', *flags, target, '--'])
    fields = (git_runner or _git_bytes)(repo, *args).split(b'\0')
    changes = []
    i = 0
    while i < len(fields) and fields[i]:
        old_mode, new_mode, old_blob, new_blob, status = fields[i].decode('ascii').split()
        old_path = fields[i+1].decode('utf-8', errors='replace')
        i += 2
        new_path = old_path
        if status[0] in 'RC':
            new_path = fields[i].decode('utf-8', errors='replace')
            i += 1
        changes.append(ChangedFile(status, old_path, new_path, old_blob, new_blob,
                                   old_mode.lstrip(':'), new_mode))
    return changes

def read_blob(repo: Repository, oid: str, limit: int = 2_000_000) -> bytes:
    """Load one blob on demand, with a bounded text-preview size."""
    if not oid.strip('0'):
        return b''
    size = int(_git_bytes(repo, 'cat-file', '-s', oid))
    if size > limit:
        raise ValueError('File is too large for the text preview (limit: 2 MB).')
    return _git_bytes(repo, 'cat-file', 'blob', oid)

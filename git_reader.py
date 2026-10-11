"""Read-only Git access. No shell commands or repository modifications."""
from dataclasses import dataclass
from pathlib import Path
import os
import subprocess

@dataclass(frozen=True)
class Commit:
    oid: str
    parents: tuple[str, ...]
    author: str
    date: str
    message: str

@dataclass
class Repository:
    path: str
    commits: dict[str, Commit]
    branches: dict[str, list[str]]
    shallow: bool = False

def read_repository(path: str, remote: bool = False) -> Repository:
    path = str(Path(path).expanduser().resolve())
    def git(*args):
        result = subprocess.run(['git', '--no-replace-objects', '-C', path, *args],
            capture_output=True, encoding='utf-8', errors='replace',
            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'}, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Git command failed')
        return result.stdout
    git('rev-parse', '--git-dir')
    refs = ['refs/heads'] + (['refs/remotes'] if remote else [])
    branches = {}
    for line in git('for-each-ref', '--format=%(objectname)%09%(refname:short)%09%(symref)', *refs).splitlines():
        oid, name, symbolic = line.split('\t')
        if not symbolic:
            branches.setdefault(oid, []).append(name)
    commits = {}
    if branches:
        # NUL fields avoid ambiguity from whitespace and multiline messages.
        result = subprocess.run(['git', '--no-replace-objects', '-C', path, 'log', '--topo-order',
            '--no-show-signature', '--format=%H%x00%P%x00%an%x00%aI%x00%B%x00', '--stdin'],
            input='\n'.join(branches)+'\n', capture_output=True, encoding='utf-8', errors='replace',
            env={**os.environ, 'GIT_OPTIONAL_LOCKS':'0'}, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        fields = result.stdout.split('\0')
        for i in range(0, len(fields)-1, 5):
            oid, parents, author, date, message = fields[i:i+5]
            oid = oid.strip()
            commits[oid] = Commit(oid, tuple(parents.split()), author, date, message.strip())
    return Repository(path, commits, branches, git('rev-parse', '--is-shallow-repository').strip() == 'true')

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

def read_changed_files(repo: Repository, source: str | None, target: str) -> list[ChangedFile]:
    """Read NUL-delimited tree changes, retaining blob IDs and rename paths."""
    if target not in repo.commits or (source is not None and source not in repo.commits
                                      and source not in repo.commits[target].parents):
        raise ValueError('Invalid comparison commit')
    flags = ['--raw', '-z', '--no-abbrev', '--no-ext-diff', '--no-textconv', '-M']
    args = (['diff', *flags, source, target, '--'] if source else
            ['diff-tree', '--root', '--no-commit-id', '-r', *flags, target, '--'])
    fields = _git_bytes(repo, *args).split(b'\0')
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

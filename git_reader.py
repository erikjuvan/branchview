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
    common = ['git', '--no-replace-objects', '-C', repo.path]
    flags = ['--no-ext-diff', '--no-textconv', '--no-color', '--stat', '--patch']
    args = (['diff', *flags, parent, oid, '--'] if parent else
            ['show', '--format=', '--root', *flags, oid, '--'])
    result = subprocess.run(common + args, capture_output=True, encoding='utf-8',
                            errors='replace', timeout=120, env={**os.environ, 'GIT_OPTIONAL_LOCKS':'0'})
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout or 'No changes relative to this parent.'

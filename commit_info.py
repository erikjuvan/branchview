"""On-demand commit provenance derived from locally available Git history."""
from dataclasses import dataclass, replace, field
import re
from threading import Event

from git_reader import Commit, Repository, ChangedFile, Worktree, read_changed_files, read_worktrees, opened_worktree
from git_process import run_git, GitCancelled as InspectionCancelled


def _inspection_bytes(repo, args, cancelled):
    return run_git(repo.path, args, cancelled=cancelled)


@dataclass(frozen=True)
class Integration:
    branch: str
    merge: str | None
    subject: str
    kind: str

@dataclass(frozen=True)
class WorktreeMatch:
    worktree: Worktree
    relation: str
    opened: bool = False


@dataclass
class CommitInfo:
    commit: Commit
    author_email: str
    committer: str
    committer_email: str
    committer_date: str
    tree: str
    tip_refs: list[str]
    branches: list[str]
    tags: list[str]
    parent_subjects: dict[str, str]
    children: list[tuple[str, str]]
    integrations: list[Integration]
    files: list[ChangedFile]
    statistics: str
    warnings: list[str]
    worktrees: list[WorktreeMatch] = field(default_factory=list)


def read_commit_info(repo: Repository, oid: str, cancelled: Event | None = None,
                     descendant_limit: int = 50_000) -> CommitInfo:
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', oid):
        raise ValueError('Commit details require a full Git object ID.')

    def check():
        if cancelled is not None and cancelled.is_set():
            raise InspectionCancelled()

    def git_bytes(*args):
        check()
        result = _inspection_bytes(repo, args, cancelled)
        check()
        return result

    def git(*args):
        return git_bytes(*args).decode('utf-8', errors='replace')

    fields = git('show', '--no-patch', '--no-show-signature',
                 '--format=%H%x00%P%x00%T%x00%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B%x00',
                 oid, '--').split('\0')
    sha, parents, tree, author, email, date, committer, committer_email, committed, message = fields[:10]
    # Pretty-format parent lists can be simplified at shallow boundaries. Read
    # actual parent headers so an incomplete checkout is not presented as a root.
    header = git('cat-file', 'commit', oid).split('\n\n', 1)[0]
    parents = ' '.join(line.removeprefix('parent ') for line in header.splitlines() if line.startswith('parent '))
    commit = Commit(sha, tuple(parents.split()), author, date, message.strip())
    warnings = []
    if repo.shallow:
        warnings.append('Shallow repository: relationships are limited to the available history.')
    refs = git('for-each-ref', '--contains='+oid,
               '--format=%(refname)%09%(objectname)%09%(*objectname)%09%(symref)',
               'refs/heads', 'refs/remotes', 'refs/tags')
    branches, tags, tips = [], [], []
    branch_tips = []
    containing_refs = set()
    for line in refs.splitlines():
        ref, object_id, peeled, symbolic = line.split('\t')
        if symbolic:
            continue
        name = ref.removeprefix('refs/heads/').removeprefix('refs/remotes/').removeprefix('refs/tags/')
        is_tag = ref.startswith('refs/tags/')
        if object_id == oid or peeled == oid:
            tips.append(('tag: ' if is_tag else '') + name)
        if is_tag:
            tags.append(name)
        else:
            branches.append(name)
            containing_refs.add(ref)
            branch_tips.append((name, object_id))

    worktree_matches = []
    worktrees = read_worktrees(repo.path, git_runner=git_bytes)
    opened = opened_worktree(repo.path, worktrees)
    for wt in worktrees:
        check()
        if wt.bare or not wt.head.strip('0'):
            continue
        if wt.head == oid:
            relation = 'Recorded HEAD is this commit (prunable worktree)' if wt.prunable is not None else 'HEAD is this commit'
        elif not wt.active:
            continue
        elif wt.branch:
            if wt.branch not in containing_refs:
                continue
            relation = 'Commit is in the checked-out branch history'
        else:
            try:
                if git('rev-list', '--max-count=1', oid, '--not', wt.head, '--').strip():
                    continue
            except RuntimeError:
                warnings.append(f'Could not inspect detached worktree history: {wt.path}')
                continue
            relation = 'Commit is an ancestor of detached HEAD'
        worktree_matches.append(WorktreeMatch(wt, relation, wt == opened))

    parent_subjects = {}
    if commit.parents:
        try:
            values = git('show', '--no-patch', '--no-show-signature', '--format=%H%x00%s%x00',
                         *commit.parents, '--').split('\0')
            for i in range(0, len(values)-1, 2):
                parent_subjects[values[i].strip()] = values[i+1]
        except RuntimeError:
            warnings.append('Some parent metadata is unavailable in this checkout.')

    # All reachable descendants, before any first-parent filtering. This lets us
    # find where each branch's first-parent chain first acquired this commit.
    values = git('log', '--all', '--ancestry-path', '^'+oid,
                 f'--max-count={descendant_limit}', '--no-show-signature',
                 '--format=%H%x00%P%x00%s%x00', '--').split('\0')
    descendants = {}
    for i in range(0, len(values)-1, 3):
        check()
        child, child_parents, subject = values[i:i+3]
        descendants[child.strip()] = (tuple(child_parents.split()), subject)
    truncated = len(descendants) >= descendant_limit
    if truncated:
        warnings.append(f'Descendant search limited to {descendant_limit:,} commits; children and integration results may be incomplete.')
    children = sorted((child, subject) for child, (ps, subject) in descendants.items() if oid in ps)
    integrations = []
    for branch, tip in branch_tips:
        check()
        cursor = tip
        seen = set()
        while cursor != oid and cursor in descendants and cursor not in seen:
            seen.add(cursor)
            ps, subject = descendants[cursor]
            if not ps:
                break
            if ps[0] != oid and ps[0] not in descendants:
                if len(ps) > 1 and not truncated:
                    integrations.append(Integration(branch, cursor, subject, 'merge'))
                else:
                    integrations.append(Integration(branch, None, '', 'unknown'))
                break
            cursor = ps[0]
        else:
            kind = 'mainline' if cursor == oid else 'unknown'
            integrations.append(Integration(branch, None, '', kind))

    working_repo = replace(repo, commits={oid: commit})
    check()
    files, statistics = [], 'Change summary unavailable.'
    try:
        files = read_changed_files(working_repo, commit.parents[0] if commit.parents else None, oid,
                                   git_runner=lambda _, *args: git_bytes(*args))
        check()
        flags = ['--no-ext-diff', '--no-textconv', '--no-color', '--shortstat']
        statistics = (git('diff', *flags, commit.parents[0], oid, '--') if commit.parents else
                      git('diff-tree', '--root', '--no-commit-id', '-r', *flags, oid, '--')).strip()
    except RuntimeError as exc:
        warnings.append('Cannot compare against the parent: '+str(exc))
    return CommitInfo(commit, email, committer, committer_email, committed, tree,
                      tips, branches, tags, parent_subjects, children, integrations,
                      files, statistics or 'No file changes relative to this parent.', warnings, worktree_matches)

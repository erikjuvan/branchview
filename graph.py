"""Terminal-tip filtering and lossless contraction of linear ancestry."""
from dataclasses import dataclass
from git_reader import Repository
from git_process import GitCancelled

def check_cancelled(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise GitCancelled()

@dataclass(frozen=True)
class Edge:
    child: str
    parent: str
    hidden: tuple[str, ...]

@dataclass
class Graph:
    nodes: set[str]
    tips: list[str]
    edges: list[Edge]

def terminal_tips(repo: Repository, cancelled=None) -> list[str]:
    ancestors = set()
    for tip in repo.branches:
        check_cancelled(cancelled)
        todo = list(repo.commits[tip].parents)
        visited = set()
        while todo:
            check_cancelled(cancelled)
            oid = todo.pop()
            if oid in visited or oid not in repo.commits:
                continue
            visited.add(oid)
            todo.extend(repo.commits[oid].parents)
        ancestors.update(visited)
    return sorted(set(repo.branches)-ancestors, key=lambda oid: repo.branches[oid][0])

def build_graph(repo: Repository, expanded: set[str] | None = None, cancelled=None) -> Graph:
    check_cancelled(cancelled)
    if repo.branches_only:
        tips = sorted(repo.branches, key=lambda oid: repo.branches[oid][0])
        return Graph(set(tips), tips, [])
    tips = terminal_tips(repo, cancelled=cancelled)
    reachable = set()
    todo = tips.copy()
    while todo:
        check_cancelled(cancelled)
        oid = todo.pop()
        if oid in reachable or oid not in repo.commits:
            continue
        reachable.add(oid)
        todo.extend(repo.commits[oid].parents)
    children = {oid: [] for oid in reachable}
    for oid in reachable:
        check_cancelled(cancelled)
        for parent in repo.commits[oid].parents:
            if parent in reachable:
                children[parent].append(oid)
    keep = set(tips) | (set(expanded or ()) & reachable)
    for oid in reachable:
        check_cancelled(cancelled)
        parents = [p for p in repo.commits[oid].parents if p in reachable]
        if len(parents) != 1 or len(repo.commits[oid].parents) != 1 or len(children[oid]) != 1:
            keep.add(oid)
    edges = []
    for oid in sorted(keep):
        check_cancelled(cancelled)
        for parent in repo.commits[oid].parents:
            if parent not in reachable:
                continue
            hidden = []
            while parent not in keep:
                hidden.append(parent)
                parent = repo.commits[parent].parents[0]
            edges.append(Edge(oid, parent, tuple(hidden)))
    return Graph(keep, tips, edges)

def hide_nodes(graph: Graph, hidden: set[str]) -> Graph:
    """Bypass hidden nodes, preserving each surviving ancestry path."""
    nodes = graph.nodes - hidden
    edges = list(graph.edges)
    for oid in sorted(graph.nodes & hidden):
        incoming = [e for e in edges if e.parent == oid]
        outgoing = [e for e in edges if e.child == oid]
        edges = [e for e in edges if e.parent != oid and e.child != oid]
        for before in incoming:
            for after in outgoing:
                edges.append(Edge(before.child, after.parent,
                                  before.hidden + (oid,) + after.hidden))
    return Graph(nodes, [tip for tip in graph.tips if tip in nodes], list(dict.fromkeys(edges)))

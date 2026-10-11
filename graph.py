"""Terminal-tip filtering and lossless contraction of linear ancestry."""
from dataclasses import dataclass
from git_reader import Repository

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

def terminal_tips(repo: Repository) -> list[str]:
    ancestors = set()
    for tip in repo.branches:
        todo = list(repo.commits[tip].parents)
        visited = set()
        while todo:
            oid = todo.pop()
            if oid in visited or oid not in repo.commits:
                continue
            visited.add(oid)
            todo.extend(repo.commits[oid].parents)
        ancestors.update(visited)
    return sorted(set(repo.branches)-ancestors, key=lambda oid: repo.branches[oid][0])

def build_graph(repo: Repository, expanded: set[str] | None = None) -> Graph:
    tips = terminal_tips(repo)
    reachable = set()
    todo = tips.copy()
    while todo:
        oid = todo.pop()
        if oid in reachable or oid not in repo.commits:
            continue
        reachable.add(oid)
        todo.extend(repo.commits[oid].parents)
    children = {oid: [] for oid in reachable}
    for oid in reachable:
        for parent in repo.commits[oid].parents:
            if parent in reachable:
                children[parent].append(oid)
    keep = set(tips) | (set(expanded or ()) & reachable)
    for oid in reachable:
        parents = [p for p in repo.commits[oid].parents if p in reachable]
        if len(parents) != 1 or len(children[oid]) != 1:
            keep.add(oid)
    edges = []
    for oid in sorted(keep):
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

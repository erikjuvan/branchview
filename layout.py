"""Topological depth, with every terminal tip exactly on the top row."""
from collections import defaultdict, deque
from math import ceil, sqrt
from graph import Graph, check_cancelled

def branch_layout(graph: Graph, cancelled=None) -> dict[str, tuple[float, float]]:
    """Arrange branch tips in a compact grid for repositories with many refs."""
    columns = max(1, min(5, ceil(sqrt(len(graph.tips)))))
    positions = {}
    for index, oid in enumerate(graph.tips):
        check_cancelled(cancelled)
        positions[oid] = ((index % columns)*400, (index // columns)*150)
    return positions

def layout(graph: Graph, cancelled=None) -> dict[str, tuple[float, float]]:
    parents = defaultdict(list)
    pending = {oid: 0 for oid in graph.nodes}
    for edge in graph.edges:
        check_cancelled(cancelled)
        parents[edge.child].append(edge.parent)
        pending[edge.parent] += 1
    depth = {oid: 0 for oid in graph.nodes}
    lanes = {tip: {i} for i, tip in enumerate(graph.tips)}
    queue = deque(graph.tips)
    while queue:
        check_cancelled(cancelled)
        child = queue.popleft()
        for parent in parents[child]:
            depth[parent] = max(depth[parent], depth[child]+1)
            lanes.setdefault(parent, set()).update(lanes.get(child, set()))
            pending[parent] -= 1
            if pending[parent] == 0:
                queue.append(parent)
    rows = defaultdict(list)
    for oid in graph.nodes:
        rows[depth[oid]].append(oid)
    positions = {}
    for row, nodes in rows.items():
        check_cancelled(cancelled)
        desired = lambda oid: sum(lanes.get(oid, {0}))/len(lanes.get(oid, {0}))*300
        previous = -float('inf')
        for oid in sorted(nodes, key=lambda oid: (desired(oid), oid)):
            x = max(desired(oid), previous+220)
            positions[oid] = (x, row*110)
            previous = x
    return positions

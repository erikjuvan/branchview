# Git Branch Viewer

Python 3.10+ desktop application. Requires Git on PATH and PySide6.

## Run

Extract the ZIP, open a terminal inside `git_branch_viewer`, then:

```sh
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py /path/to/repository
```

Alternatively run `python main.py` and use Open. On Arch Linux, installing
`pyside6` with the system package manager is another option.

## Controls

- Wheel: zoom around cursor. Left-drag blank background: select multiple nodes. Middle-drag: pan.
- Ctrl-click adds/removes a node from selection. Drag selected nodes or their
  labels to move the selected group.
- Dark gray theme throughout the window and graph.
- Drag any commit node or its label to organize the graph freely. Edges and
  collapsed-chain labels follow automatically; the view stays fixed during dragging. Branch tip names move with nodes.
- Manual positions survive expansion, collapse, and refresh within the same
  repository during the session. They are not saved after closing the app.
- Right-click a node or its label → Hide node. Connections bypass it.
  Press Delete while the graph has focus to hide all selected nodes.
  Show hidden nodes restores them; expanding a chain also reveals its hidden nodes.
  Hidden state lasts for the session and is retained on refresh.
- R or Rearrange visible nodes: automatically lay out only the visible graph.
- Double-click a node or its label to view its patch and diff statistics against
  its actual Git parent. Merge commits provide a parent selector. Root commits
  compare against the empty tree.
- Select exactly two nodes, then right-click either node or its label and choose
  Diff selected commits to compare their trees. The dialog lets you reverse the direction.
- Both diff dialogs show a changed-file list and side-by-side file contents with
  original line numbers, red removed lines, green added lines, aligned spacer rows,
  and synchronized scrolling. File contents load when selected. Binary files show
  a notice; submodules show commit IDs. Text previews are limited to 2 MB and
  20,000 lines per file, and non-UTF-8 text uses replacement characters.
- Space or Fit: fit entire graph. Click a commit: metadata and full message.
- Click a collapsed-chain label: inspect hidden commits.
- Double-click a chain label: expand it. Collapse all restores compact view.
- Refresh reloads branch references and history, resetting expansion.
- Local branches by default; optionally include remote-tracking branches.

## Graph meaning

In the automatic layout, all terminal tip commits occupy the top row. Manual
dragging allows arbitrary positions. A terminal tip is not a strict
ancestor of another selected branch tip. Multiple branch names sharing a tip
are grouped. Branch labels whose tips are ancestors of another tip are hidden
from the top row; their names remain available when that commit is inspected.
Both merge parents are retained. Shared ancestors are drawn once. Linear
chains are collapsed; roots, merges, junctions, and terminal tips remain.
Vertical spacing represents ancestry depth, not dates or elapsed time.
Disconnected histories remain separate. Shallow repositories show a warning:
terminal detection can only use available history.

The application only reads Git data. It does not fetch, checkout, merge, or
write repository files. Uncommitted changes, tags, and detached-only commits
are outside the scope of this first version. Loading is synchronous; intended
for small repositories with roughly ten branches. Layout is deterministic,
but merge edges can cross and long labels can overlap in complicated histories.

## Verification

```sh
python -m unittest discover -s tests -v
```

Qt documentation: https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QGraphicsView.html

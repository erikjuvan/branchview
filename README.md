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

For large repositories, start with `python main.py --branches-only /path/to/repository`
to avoid loading history on the first open.
History mode defaults to a 500-commit budget. Use `--max-commits 5000` for a
larger initial budget or `--max-commits 0` for all history.

## Controls

- The fixed top section of the right sidebar lists available graph shortcuts.
  It updates with the selection: D diffs one commit or compares two; Delete is
  shown for any selection and requires graph focus. With three or more commits,
  the panel explains how to enable D. Commit details scroll independently below.

- Ctrl+F or Search: find loaded commits by hash, full message, or branch name.
  Enter or double-click jumps to the result, revealing collapsed or hidden nodes.
  With an empty query, show branch tips. Branch-only mode searches only tip metadata.

- Wheel: zoom around cursor. Left-drag blank background: select multiple nodes. Middle-drag: pan.
- Ctrl-click adds/removes a node from selection. Drag selected nodes or their
  labels to move the selected group.
- Multiple selections show a combined sidebar summary: selection count, branch
  references, individual commit links/authors/dates, and worktree relationships
  proven by loaded history. Two selections include a comparison link and D hint.
  Cached details also show shared containing branches when available. Selecting
  one commit restores full details; unfinished single-commit queries cannot
  replace a multi-selection summary.
- Selected nodes have gold rings and gold label backgrounds. Their visible parent
  ancestry, including both merge parents and collapsed chains, is highlighted in
  turquoise; unrelated paths are dimmed. Multiple selections highlight the union
  of their ancestry. Branch-only mode highlights selections without loading history.
- Dark gray theme throughout the window and graph.
- Checked-out branch labels are purple and marked [WT], with worktree paths in
  their tooltips. Worktree HEAD nodes are purple when not selected or highlighted
  as ancestors. Checked-out branch heads remain visible even inside collapsed
  history. Detached worktree HEADs are marked when present in the loaded graph.
  The sidebar distinguishes HEAD checkouts from commits contained in worktree
  branch history, and shows paths, main/linked status, locks, and prunable records.
  Refresh updates worktree colors and cached details. No worktrees are modified.
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
- D: with one selected node, show its diff against its parent; with two selected
  nodes, compare those commits. With no selection or more than two nodes, do nothing.
- Both diff dialogs show a changed-file list and side-by-side file contents with
  original line numbers, red removed lines, green added lines, aligned spacer rows,
  and synchronized scrolling. File contents load when selected. Binary files show
  a notice; submodules show commit IDs. Text previews are limited to 2 MB and
  20,000 lines per file, and non-UTF-8 text uses replacement characters.
  Line-ending styles (CRLF/LF/CR) are normalized for line matching; conversions
  are reported above the diff. Missing final newlines remain highlighted changes.
- Space or Fit: fit entire graph. Click a commit: metadata and full message.
- The sidebar loads extended details in the background: author and committer
  identities/dates, references pointing here, all locally known containing branches
  and tags, direct children, parent subjects and merge roles, integration merges
  on current branches' first-parent paths, and changed files/statistics against
  the first parent (or empty tree for roots). Parent, child, and integration links
  navigate to commits; file links open side-by-side diffs. In branch-only mode,
  inspecting an ancestor does not load the graph's full history. Results are cached
  until Refresh. Searches are limited to 50,000 descendants and report incomplete
  or shallow history. Git does not store original branch names; current containing
  branches do not establish the branch where a commit was created. Squash merges
  and cherry-picks have different commit IDs and are not attributed as exact matches.
- T or Top commits: jump to and fit the visible branch tips and their labels,
  excluding ancestor history from the fit. If all tips are hidden, fit the exposed
  topmost commits. In branch-only mode, fit all visible branch tips.
- Click a collapsed-chain label: inspect hidden commits.
- Double-click a chain label: expand it. Collapse all restores compact view.
- Refresh reloads branch references and history, resetting expansion.
- Repository loading and initial graph calculation run in the background. The
  status bar shows the current phase. Cancel load keeps the previous view; a new
  Open or display-option change supersedes any unfinished load.
- History: choose a commit budget or All history. Every branch head is retained,
  so the loaded count can exceed the budget. Load more ancestors increases the
  budget while retaining zoom, pan, selection, expansion, and manual positions.
  Boundary labels and the status bar identify missing history; ancestry and
  terminal-tip filtering are approximate until the missing history is loaded.
- Local branches by default; optionally include remote-tracking branches.
- Branches only: show every branch tip in a compact grid, with no ancestor nodes
  or ancestry edges. This also includes branches pointing to ancestors of other
  branch tips. Names sharing a commit are grouped. Git loads only tip metadata;
  parent diffs and comparisons between two tips remain available. Turn it off to
  load the full history. Manual layouts are retained separately for each mode.
  Two-tip diffs initially follow Git's commit-date order; the dialog lets you
  reverse their direction.
- All branch tips on top (history mode): keep every named tip on the top row,
  including tips already contained in another included branch. Each top entry
  shows only parent ancestry. An ancestral tip also appears as a shared-history
  copy below receiving branches, preserving real merge paths without connecting
  descendants to the top entry. ↪ marks proven inclusion in loaded history;
  inclusion may come from a merge, fast-forward, or shared history. The sidebar
  identifies introducing merges where available and provides clickable hashes
  that jump to the merge in the receiving history. For commits outside loaded
  history, links open their details and explain how to load them into the graph.
  Same-tip names remain grouped; remote references follow Include remote branches.
  With limited history, an unmarked tip may still be included beyond the graph
  budget; sidebar queries inspect available Git history independently. Hiding a
  commit hides both displayed copies; selecting both copies still counts as one
  distinct commit. Manual layouts are retained separately. CLI: `--all-branch-tips`.

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
are outside the scope of this first version. History mode loads a bounded slice
by default. Branch-only mode avoids history traversal. Layout is deterministic,
but merge edges can cross and long labels can overlap in complicated histories.

## Verification

```sh
python -m unittest discover -s tests -v
```

Qt documentation: https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QGraphicsView.html

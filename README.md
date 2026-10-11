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

Open accepts a repository or a folder containing repositories and adds one tab
per checkout. By default it checks the selected folder and its immediate child
folders. Enable **Recursive** in the Open dialog (or pass `--recursive` on the
command line) to search all descendant folders. Submodules and their contents
are excluded, including older embedded submodules. Independent nested repositories
and linked worktrees are included; Git metadata and directory links/junctions
are not traversed. Scanning runs in the background; Cancel batch open stops the
scan, queued opens and unfinished batch loads while retaining existing tabs.
Load failures are summarized once; other repositories still open normally.

```sh
python main.py /path/to/projects
python main.py --recursive /path/to/projects
```

For large repositories, start with `python main.py --branches-only /path/to/repository`
to avoid loading history on the first open.
History mode defaults to a 500-commit budget. Use `--max-commits 5000` for a
larger initial budget or `--max-commits 0` for all history.

## Controls

- **View** selects three history presentations. **Regular history** is the default:
  newest commits first, one commit per row with compact connecting lanes and
  inline branch labels. Committer dates order independent histories, with parents
  kept below children even when clocks disagree. Rows are equally spaced, not
  proportional to elapsed time. Every loaded commit is shown without contraction.
  **Terminal branches on top** retains the compact ancestry layout; **All branches
  on top** extends it with every named tip at the top. **Branches only** remains
  a separate option for a no-history tip grid. Regular history opens at the most
  recent rows; T returns there and Space fits everything. Regular rows are fixed;
  manual node arrangements remain available in the other presentations.
  CLI: `--presentation regular|terminal|all`; `--all-branch-tips` still selects all.

- The right sidebar has **All refs**, **Branches**, and **Tags** tabs with a shared
  name filter. All refs pins **HEAD** first, showing the current branch or detached
  state for the checkout open in this repository tab. The current branch is bold;
  HEAD is purple and tags are gold. Remote branches follow **Include remote branches**.
  Click a ref (or select it and press Enter) to reveal its commit and zoom to a
  readable view. Hidden or collapsed commits are revealed. The graph marks the
  current checkout with **HEAD** and shows tag names beside their commits.
  Drag the divider between the list and commit details to adjust their heights.
- Remote branch labels and remote-only branch nodes use muted green/teal shades,
  with a stable shade for each remote. The sidebar uses the same colors. Local
  branches retain blue; worktree labels retain purple. Remote label colors remain
  visible during selection, while nodes and ancestry use the existing highlights.
  Commits shared by local and remote tips retain local node styling, with each
  remote label individually colored. Hover a remote label for its remote name.

- B with one commit selected, or right-click → Browse files at this commit,
  opens a commit-pinned file tree with path filtering and background text previews.
  It shows all tracked files, including unchanged ones. The checkout is untouched.
  Binary/large files, symlinks and Git LFS pointers have descriptive previews;
  submodules appear as references without loading their contents.
- V with one commit selected, or right-click → Open commit in VS Code, exports
  all tracked files to a separate cached snapshot and opens a named VS Code
  workspace. The file browser also opens individual historical files in VS Code.
  Exports run in the background and can be canceled. Unmodified snapshots are
  reused; edited copies are retained and subsequent opens prepare a fresh copy.
  Snapshots persist after closing the app. Use **Snapshots…** to delete copies you
  have finished using, including any edits made in those copies. Source Git
  repositories, worktrees and uncommitted files are never changed. No VS Code
  extension is needed; the app detects VS Code or lets you choose its executable.
  Submodule contents and external LFS objects are not fetched. Symlinks are
  exported as text files containing their targets, with a notice. Git archive
  export attributes and checkout filters are not applied: regular files retain
  their exact committed bytes.
  The diff viewer has **Open before/after in VS Code** buttons for the selected
  changed file; deleted or added files only enable the side that exists.

- Repositories open in independent, closable, movable tabs. Each tab retains its
  graph, selection, camera, sidebar and display options. Opening the same checkout
  again selects its existing tab. Ctrl+O opens, Ctrl+W closes the current tab,
  and Ctrl+Tab / Ctrl+Shift+Tab switch tabs. Graph shortcuts affect the active tab.

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
- Local branches, HEAD and commit tags by default; optionally include remote-tracking branches.
  Annotated tags resolve to their commits. Tags of trees or blobs are omitted.
  HEAD and tag commits remain loaded even when outside the history budget.
- Branches only: show every branch tip in a compact grid, with no ancestor nodes
  or ancestry edges, plus HEAD and tag commits. This also includes branches pointing to ancestors of other
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

Regular history shows every loaded commit on a separate row. Independent
histories are ordered by commit date while parent commits remain below children;
the lane lines express ancestry, and row spacing does not express elapsed time.
The initial view fits the newest rows. Branch refs stay beside their actual commit.

In the terminal-branches layout, all terminal tip commits occupy the top row. Manual
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
write repository files. Uncommitted changes are outside the scope of this viewer.
Detached HEAD commits and commit tags are included. History mode loads a bounded slice
by default. Branch-only mode avoids history traversal. Layout is deterministic,
but merge edges can cross and long labels can overlap in complicated histories.

## Verification

```sh
python -m unittest discover -s tests -v
```

Qt documentation: https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QGraphicsView.html

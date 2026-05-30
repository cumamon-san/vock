---
title: HTML Coverage Report — Single-Page App with Sidebar Navigation
date: 2026-05-30
status: approved
---

## Overview

Redesign `report/html.py` to produce a single HTML file with sidebar navigation and full file display. Each source file is shown in its entirety with covered lines highlighted. Files are rendered on demand via JavaScript to keep initial load fast.

Scope: `report/html.py` only. `report/btf.py` is unchanged.

---

## Architecture

### Data Layer (Python)

`generate()` builds a single data dictionary and serializes it as JSON into a `<script>` tag:

```python
data = {
    "files": ["kernel/sched/core.c", ...],        # sorted list of file paths
    "covered": {"kernel/sched/core.c": [123, 124, ...]},  # covered line numbers (1-based)
    "lines": {"kernel/sched/core.c": ["...", ...] | null}  # all lines, or null if file not found
}
```

- `filter_kw` is applied in Python when building `data` (same behaviour as today).
- Parameters `before` and `after` are accepted but ignored — files are shown in full.
- Function signature `generate(cov, kernel_src, before, after, output_path, filter_kw)` is preserved unchanged.

### Presentation Layer (HTML/CSS)

Two-column flex layout:

```
┌──────────────┬────────────────────────────────────┐
│  Sidebar     │  Content                           │
│  (250px)     │  (flex: 1)                         │
│              │                                    │
│ [filter...] │  kernel/sched/core.c  42 lines     │
│              │  ──────────────────────────────    │
│ sched/core.c │  <pre>                             │
│ net/socket.c │    1 |  #include <linux/...>       │
│ ...          │  123 >  sched_init();   ← covered  │
│              │  </pre>                            │
└──────────────┴────────────────────────────────────┘
```

- Dark theme preserved (background `#1e1e1e`, same CSS classes `.cov`, `.ctx`, `.ln`).
- Sidebar is fixed-height with `overflow-y: scroll`.
- Active file in sidebar is highlighted.
- Covered line count shown next to each filename in the sidebar.

### Behaviour Layer (JavaScript, ~50 lines)

**On page load:**
1. Populate sidebar `<ul>` from `DATA.files`.
2. Select and render the first file.

**`renderFile(path)`:**
1. Check render cache; return cached HTML if present.
2. If `DATA.lines[path]` is `null`, render `(file not found)` message.
3. Otherwise iterate `DATA.lines[path]`, wrap each line in `<span class="cov">` or `<span class="ctx">`, prepend line number.
4. Insert result into `<pre id="content">`.
5. Store result in cache object.

**Sidebar filter:**
- `<input oninput>` filters `<li>` elements by `textContent` match, toggling `display`.

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| File not found on disk | `DATA.lines[path] = null`; JS shows `(file not found)` |
| No files covered (empty report) | Sidebar empty, content area shows "No files covered" |
| `filter_kw` set | Applied in Python at data-build time; JS sees already-filtered file list |
| `before` / `after` parameters | Accepted, silently ignored |

---

## Out of Scope

- `report/btf.py` — no changes.
- Any other report modes (`terminal.py`, `resolve.py`).
- Pagination or virtual scrolling within a file.

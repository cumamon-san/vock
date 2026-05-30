---
title: Uncovered Lines Highlighting in HTML Coverage Report
date: 2026-05-30
status: approved
---

## Overview

Add a third line state to the HTML coverage report: **instrumented but not executed** (miss lines). These are kernel source lines for which KCOV placed a tracing point, but which were never reached during the traced run. The set of all instrumented lines is derived from ELF relocation entries in vmlinux, matching the approach used by syzkaller's `syz-cover`.

Scope: `report/elf.py` (new), `report/html.py`, `output.py`.

---

## Architecture

### New module: `report/elf.py`

Parses vmlinux using `pyelftools` to discover all KCOV-instrumented program counters:

1. Open vmlinux as ELF.
2. Locate the symbol index of `__sanitizer_cov_trace_pc` in the symbol table.
3. Scan all `SHT_RELA` sections; collect relocations referencing that symbol index.
4. Compute the PC of each instrumented point: `pc = relocation.offset` (adjusted for module base).
5. Return as a list of hex strings `["0x...", ...]`.

If `pyelftools` is not installed, raises `ImportError` — caller handles gracefully.

### Changes to `output.py`

After KASLR detection and before `generate_html()`, two new steps are inserted:

```
instrumented_addrs = elf.get_instrumented_pcs(args.vmlinux)
instrumented_lines = run_addr2line(args.vmlinux, instrumented_addrs)
instrumented_cov   = aggregate(instrumented_lines, args.kernel_src)
```

Both steps are guarded:
- If vmlinux is unavailable: skip, pass `instrumented=None` to `generate_html()`.
- If `pyelftools` is not installed: catch `ImportError`, print a warning, pass `instrumented=None`.

### Changes to `report/html.py`

**Function signature** (backward-compatible):
```python
def generate(cov, kernel_src, before, after, output_path,
             filter_kw=None, instrumented=None)
```

**JSON `DATA` structure** — new key added:
```python
{
  "files":        [...],
  "covered":      {path: [sorted ints]},
  "lines":        {path: [...] | null},
  "instrumented": {path: [sorted ints]}   # {} if unavailable
}
```

`filter_kw` is applied to both `cov` and `instrumented` equally at Python build time.

---

## Visual Presentation

Three line states:

| State | Class | Marker | Background | Text colour |
|---|---|---|---|---|
| Covered (executed) | `.cov` | `>` | `#1e3a1e` | `#4ec9b0` (teal) |
| Miss (instrumented, not hit) | `.miss` | `!` | `#3a1e1e` | `#f48771` (orange-red) |
| Context (not instrumented) | `.ctx` | `\|` | none | `#808080` (grey) |

JS rendering in `renderFile()`:
```javascript
var covSet  = new Set(DATA.covered[path]      || []);
var instSet = new Set(DATA.instrumented[path] || []);
var cls  = covSet.has(ln) ? 'cov'  : (instSet.has(ln) ? 'miss' : 'ctx');
var mark = covSet.has(ln) ? '&gt;' : (instSet.has(ln) ? '!'    : '|');
```

**Sidebar statistics** — denominator uses instrumented count when available, falls back to total source lines:
```javascript
var inst = DATA.instrumented[path];
var tot  = inst && inst.length ? inst.length
         : (DATA.lines[path] ? DATA.lines[path].length : 0);
// displays: "42 / 180 (23%)"
```

---

## Edge Cases

| Scenario | Behaviour |
|---|---|
| vmlinux missing or not specified | `instrumented=None` → `DATA.instrumented={}` → no miss highlighting, stats unchanged |
| `pyelftools` not installed | `ImportError` caught in `output.py`; warning printed; report generated without miss data |
| File in `instrumented` but absent from `cov` | All its instrumented lines render as `.miss` — correct |
| Line in `covered` but not in `instrumented` | Rendered as `.cov` — covered takes precedence over addr2line discrepancies |
| `filter_kw` set | Applied to both `cov` and `instrumented` in Python; excluded files absent from both |
| Large vmlinux | ELF relocation scan may take a few seconds; progress note printed to stdout |

---

## Out of Scope

- `report/btf.py` — no changes.
- `report/terminal.py` — no changes.
- aarch64 / other architectures: relocation type for `__sanitizer_cov_trace_pc` calls may differ; initial implementation targets x86_64. Support for other architectures can be added later.

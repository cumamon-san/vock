# HTML Coverage Report SPA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `report/html.py` to produce a single HTML file with sidebar navigation, JSON-embedded data, and full file display rendered on demand via JavaScript.

**Architecture:** `generate()` builds a Python dict (`files`, `covered`, `lines`) and serialises it as JSON into a `<script>` tag. A ~50-line JS block reads this data, populates the sidebar, and renders the selected file on demand with caching. The function signature is preserved unchanged; parameters `before`/`after` are accepted and silently ignored.

**Tech Stack:** Python 3 stdlib (`json`, `pathlib`), vanilla JavaScript (no frameworks), pytest for unit tests.

---

### Task 1: Write failing unit tests

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_html_report.py`

- [ ] **Step 1: Create test files**

Create `tests/__init__.py` (empty):
```
```

Create `tests/test_html_report.py`:
```python
import json
import os
import tempfile
import pytest
from report.html import generate


def _parse_data(html: str) -> dict:
    """Extract and parse the DATA JSON object from generated HTML."""
    marker = "const DATA="
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end].rstrip("; \n"))


def test_data_json_structure():
    """generate() embeds JSON with files, covered, lines keys."""
    with tempfile.TemporaryDirectory() as src:
        fpath = "kernel/sched/core.c"
        os.makedirs(os.path.join(src, "kernel/sched"))
        with open(os.path.join(src, fpath), "w") as f:
            f.write("line one\nline two\nline three\n")

        output = os.path.join(src, "out.html")
        generate({"kernel/sched/core.c": {2}}, src, 4, 4, output)

        data = _parse_data(open(output).read())
        assert data["files"] == ["kernel/sched/core.c"]
        assert data["covered"]["kernel/sched/core.c"] == [2]
        assert data["lines"]["kernel/sched/core.c"] == ["line one", "line two", "line three"]


def test_missing_file_produces_null():
    """Files not found on disk are represented as null in JSON."""
    with tempfile.TemporaryDirectory() as src:
        output = os.path.join(src, "out.html")
        generate({"kernel/missing.c": {5}}, src, 4, 4, output)

        data = _parse_data(open(output).read())
        assert data["lines"]["kernel/missing.c"] is None


def test_filter_kw_excludes_files():
    """filter_kw is applied in Python; excluded files absent from DATA."""
    with tempfile.TemporaryDirectory() as src:
        os.makedirs(os.path.join(src, "kernel/sched"))
        os.makedirs(os.path.join(src, "net"))
        open(os.path.join(src, "kernel/sched/core.c"), "w").write("a\n")
        open(os.path.join(src, "net/socket.c"), "w").write("b\n")

        output = os.path.join(src, "out.html")
        generate(
            {"kernel/sched/core.c": {1}, "net/socket.c": {1}},
            src, 4, 4, output, filter_kw="sched"
        )

        data = _parse_data(open(output).read())
        assert data["files"] == ["kernel/sched/core.c"]
        assert "net/socket.c" not in data["files"]


def test_empty_cov_shows_message():
    """Empty coverage dict produces 'No files covered' message in HTML."""
    with tempfile.TemporaryDirectory() as src:
        output = os.path.join(src, "out.html")
        generate({}, src, 4, 4, output)

        content = open(output).read()
        assert "No files covered" in content


def test_html_contains_sidebar_and_js():
    """Output contains sidebar elements and renderFile JS function."""
    with tempfile.TemporaryDirectory() as src:
        output = os.path.join(src, "out.html")
        generate({}, src, 4, 4, output)

        content = open(output).read()
        assert "file-list" in content
        assert "renderFile" in content
        assert 'id="filter"' in content
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
cd /home/lehich/vock && python3 -m pytest tests/test_html_report.py -v
```

Expected: 5 tests FAILED (current `generate()` produces old snippet-based HTML, not JSON).

---

### Task 2: Rewrite `report/html.py`

**Files:**
- Modify: `report/html.py` (full rewrite)

- [ ] **Step 3: Replace the entire content of `report/html.py`**

```python
"""Generate coverage.html from resolved source coverage."""
import json
from pathlib import Path


def generate(cov: dict[str, set[int]], kernel_src: str,
             before: int, after: int, output_path: str, filter_kw: str = None):
    """Write coverage.html with sidebar navigation and full file display."""
    src_root = Path(kernel_src)

    files = []
    covered = {}
    lines = {}

    for fpath, cov_lines in sorted(cov.items()):
        if filter_kw and filter_kw not in fpath:
            continue
        files.append(fpath)
        covered[fpath] = sorted(cov_lines)
        full = src_root / fpath
        try:
            lines[fpath] = full.read_text(errors="ignore").splitlines()
        except FileNotFoundError:
            lines[fpath] = None

    data_json = json.dumps(
        {"files": files, "covered": covered, "lines": lines},
        ensure_ascii=False
    )

    total_files = len(files)
    total_lines = sum(len(v) for v in covered.values())
    no_files_msg = "" if files else '<span class="ctx">No files covered</span>'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>vock coverage</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: monospace; background: #1e1e1e; color: #d4d4d4; display: flex; flex-direction: column; height: 100vh; }}
header {{ padding: 10px 20px; background: #252526; border-bottom: 1px solid #3c3c3c; flex-shrink: 0; }}
h1 {{ color: #569cd6; display: inline; font-size: 1.1em; }}
.summary {{ color: #9cdcfe; margin-left: 1em; }}
.main {{ display: flex; flex: 1; overflow: hidden; }}
#sidebar {{ width: 280px; flex-shrink: 0; background: #252526; border-right: 1px solid #3c3c3c; display: flex; flex-direction: column; }}
#filter {{ width: 100%; padding: 8px 10px; background: #3c3c3c; border: none; color: #d4d4d4; font-family: monospace; font-size: 0.85em; outline: none; flex-shrink: 0; }}
#filter::placeholder {{ color: #858585; }}
#file-list {{ list-style: none; overflow-y: auto; flex: 1; }}
#file-list li {{ padding: 5px 10px; cursor: pointer; font-size: 0.8em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #ce9178; }}
#file-list li:hover {{ background: #2a2d2e; }}
#file-list li.active {{ background: #094771; color: #d4d4d4; }}
#file-list .count {{ color: #858585; margin-left: 0.4em; }}
#content-area {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; }}
#file-header {{ padding: 8px 16px; background: #1e1e1e; border-bottom: 1px solid #3c3c3c; color: #dcdcaa; font-size: 0.9em; flex-shrink: 0; }}
#content {{ overflow: auto; flex: 1; }}
pre {{ padding: 10px 16px; }}
.cov {{ background: #1e3a1e; color: #4ec9b0; display: block; }}
.ctx {{ color: #808080; display: block; }}
.ln {{ color: #858585; display: inline-block; width: 5em; text-align: right; margin-right: 1em; user-select: none; }}
</style></head>
<body>
<header>
  <h1>vock kernel coverage report</h1>
  <span class="summary">{total_files} files &mdash; {total_lines} covered lines</span>
</header>
<div class="main">
  <div id="sidebar">
    <input id="filter" placeholder="filter files..." />
    <ul id="file-list"></ul>
  </div>
  <div id="content-area">
    <div id="file-header"></div>
    <div id="content"><pre>{no_files_msg}</pre></div>
  </div>
</div>
<script>
const DATA={data_json};
const cache={{}};
function renderFile(path){{
  document.querySelectorAll('#file-list li').forEach(function(li){{
    li.classList.toggle('active', li.dataset.path===path);
  }});
  var header=document.getElementById('file-header');
  var content=document.getElementById('content');
  var covSet=new Set(DATA.covered[path]||[]);
  header.textContent=path+' ('+covSet.size+' covered lines)';
  if(cache[path]!==undefined){{content.innerHTML=cache[path];return;}}
  var fileLines=DATA.lines[path];
  if(fileLines===null){{
    cache[path]='<pre><span class="ctx">(file not found)</span></pre>';
    content.innerHTML=cache[path];return;
  }}
  var html='<pre>';
  fileLines.forEach(function(line,i){{
    var ln=i+1;
    var esc=line.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    var cls=covSet.has(ln)?'cov':'ctx';
    var mark=covSet.has(ln)?'&gt;':'|';
    html+='<span class="'+cls+'"><span class="ln">'+ln+'</span> '+mark+' '+esc+'</span>\\n';
  }});
  html+='</pre>';
  cache[path]=html;
  content.innerHTML=html;
}}
document.addEventListener('DOMContentLoaded',function(){{
  var list=document.getElementById('file-list');
  DATA.files.forEach(function(path){{
    var li=document.createElement('li');
    var count=(DATA.covered[path]||[]).length;
    li.dataset.path=path;
    li.title=path;
    li.innerHTML=path.split('/').pop()+' <span class="count">('+count+')</span>';
    li.onclick=function(){{renderFile(path);}};
    list.appendChild(li);
  }});
  document.getElementById('filter').addEventListener('input',function(){{
    var q=this.value.toLowerCase();
    list.querySelectorAll('li').forEach(function(li){{
      li.style.display=li.title.toLowerCase().includes(q)?'':'none';
    }});
  }});
  if(DATA.files.length)renderFile(DATA.files[0]);
}});
</script>
</body></html>"""

    with open(output_path, "w") as f:
        f.write(html)
```

- [ ] **Step 4: Run tests — verify they all pass**

```bash
cd /home/lehich/vock && python3 -m pytest tests/test_html_report.py -v
```

Expected output:
```
tests/test_html_report.py::test_data_json_structure PASSED
tests/test_html_report.py::test_missing_file_produces_null PASSED
tests/test_html_report.py::test_filter_kw_excludes_files PASSED
tests/test_html_report.py::test_empty_cov_shows_message PASSED
tests/test_html_report.py::test_html_contains_sidebar_and_js PASSED
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py tests/test_html_report.py report/html.py
git commit -m "feat: rewrite HTML coverage report as SPA with sidebar navigation"
```

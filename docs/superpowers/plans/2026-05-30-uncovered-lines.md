# Uncovered Lines Highlighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third line state (`.miss` = instrumented but not executed) to the HTML coverage report by scanning ELF relocations in vmlinux for `__sanitizer_cov_trace_pc` call sites.

**Architecture:** New `report/elf.py` uses `pyelftools` to scan vmlinux `SHT_RELA` sections for relocations targeting `__sanitizer_cov_trace_pc`, returning a list of hex PC addresses. `output.py` resolves those PCs via `addr2line` and passes the result to `generate()`. `html.py` embeds them as `DATA.instrumented`, renders miss lines with class `.miss` / marker `!`, and uses instrumented counts as stats denominator.

**Tech Stack:** Python 3, pyelftools 0.32+, pytest.

---

## File Structure

| File | Change |
|---|---|
| `report/elf.py` | **Create** — ELF relocation scanner |
| `tests/test_elf.py` | **Create** — unit tests for elf.py |
| `report/html.py` | **Modify** — `instrumented` param, `.miss` CSS, updated JS |
| `output.py` | **Modify** — integrate elf.py with graceful fallback |
| `tests/test_html_report.py` | **Modify** — new tests for miss rendering and instrumented stats |

---

### Task 1: `report/elf.py` — ELF relocation scanner

**Files:**
- Create: `tests/test_elf.py`
- Create: `report/elf.py`

- [ ] **Step 1: Create `tests/test_elf.py` with failing tests**

```python
import os
import struct
import tempfile
import pytest
from report.elf import get_instrumented_pcs


def _build_test_elf(pc_offset=0xffffffff81001234):
    """Build a minimal x86_64 ELF64 with one __sanitizer_cov_trace_pc RELA entry."""
    # Symbol string table: offset 0 = "", offset 1 = symbol name
    strtab = b'\x00__sanitizer_cov_trace_pc\x00'   # 26 bytes

    # Section name string table
    # offsets: .strtab=1, .shstrtab=9, .symtab=19, .rela.text=27
    shstrtab = b'\x00.strtab\x00.shstrtab\x00.symtab\x00.rela.text\x00'  # 38 bytes
    shstr_idx = {'.strtab': 1, '.shstrtab': 9, '.symtab': 19, '.rela.text': 27}

    # Symbol table: NULL entry + __sanitizer_cov_trace_pc (SHN_UNDEF, GLOBAL FUNC)
    sym0 = struct.pack('<IBBHQQ', 0, 0, 0, 0, 0, 0)
    sym1 = struct.pack('<IBBHQQ', 1, (1 << 4) | 2, 0, 0, 0, 0)  # bind=GLOBAL, type=FUNC
    symtab = sym0 + sym1  # 48 bytes

    # RELA entry: offset=pc_offset, sym_idx=1, type=R_X86_64_PLT32=4, addend=-4
    r_info = (1 << 32) | 4
    rela = struct.pack('<QQq', pc_offset, r_info, -4)  # 24 bytes

    # File layout
    strtab_off   = 64                               # after ELF header
    shstrtab_off = strtab_off + len(strtab)         # 64+26 = 90
    symtab_off   = shstrtab_off + len(shstrtab)     # 90+38 = 128
    rela_off     = symtab_off + len(symtab)         # 128+48 = 176
    shdrs_off    = rela_off + len(rela)             # 176+24 = 200

    # Section headers: 0=NULL 1=.strtab 2=.shstrtab 3=.symtab 4=.rela.text
    SHT_NULL, SHT_STRTAB, SHT_SYMTAB, SHT_RELA = 0, 3, 2, 4

    def shdr(name, type_, offset, size, link, info, entsize):
        return struct.pack('<IIQQQQIIQQ',
                           name, type_, 0, 0, offset, size, link, info, 8, entsize)

    shdrs = (
        shdr(0,                        SHT_NULL,   0,           0,            0, 0,  0) +
        shdr(shstr_idx['.strtab'],     SHT_STRTAB, strtab_off,  len(strtab),  0, 0,  0) +
        shdr(shstr_idx['.shstrtab'],   SHT_STRTAB, shstrtab_off,len(shstrtab),0, 0,  0) +
        shdr(shstr_idx['.symtab'],     SHT_SYMTAB, symtab_off,  len(symtab),  1, 1, 24) +
        shdr(shstr_idx['.rela.text'],  SHT_RELA,   rela_off,    len(rela),    3, 0, 24)
    )

    # ELF64 header
    e_ident = b'\x7fELF\x02\x01\x01\x00' + b'\x00' * 8
    elf_hdr = e_ident + struct.pack('<HHIQQQIHHHHHH',
        2, 62, 1, 0, 0, shdrs_off, 0, 64, 0, 0, 64, 5, 2)

    data = bytearray(shdrs_off + len(shdrs))
    data[0:64]                                   = elf_hdr
    data[strtab_off:strtab_off+len(strtab)]      = strtab
    data[shstrtab_off:shstrtab_off+len(shstrtab)]= shstrtab
    data[symtab_off:symtab_off+len(symtab)]      = symtab
    data[rela_off:rela_off+len(rela)]            = rela
    data[shdrs_off:]                             = shdrs
    return bytes(data)


def test_finds_kcov_relocation():
    """get_instrumented_pcs returns the offset of the KCOV RELA entry."""
    pc = 0xffffffff81001234
    elf_data = _build_test_elf(pc)
    with tempfile.NamedTemporaryFile(suffix='.elf', delete=False) as f:
        f.write(elf_data)
        tmp = f.name
    try:
        result = get_instrumented_pcs(tmp)
    finally:
        os.unlink(tmp)
    assert result == [hex(pc)]


def test_no_kcov_symbol_returns_empty():
    """ELF without __sanitizer_cov_trace_pc returns empty list."""
    # Build ELF with a different symbol name (no KCOV)
    strtab = b'\x00other_function\x00'
    shstrtab = b'\x00.strtab\x00.shstrtab\x00.symtab\x00'
    shstr_idx = {'.strtab': 1, '.shstrtab': 9, '.symtab': 19}
    sym0 = struct.pack('<IBBHQQ', 0, 0, 0, 0, 0, 0)
    sym1 = struct.pack('<IBBHQQ', 1, (1 << 4) | 2, 0, 0, 0, 0)
    symtab = sym0 + sym1
    strtab_off = 64
    shstrtab_off = strtab_off + len(strtab)
    symtab_off = shstrtab_off + len(shstrtab)
    shdrs_off = symtab_off + len(symtab)
    SHT_NULL, SHT_STRTAB, SHT_SYMTAB = 0, 3, 2
    def shdr(name, type_, offset, size, link, info, entsize):
        return struct.pack('<IIQQQQIIQQ', name, type_, 0, 0, offset, size, link, info, 8, entsize)
    shdrs = (
        shdr(0,                       SHT_NULL,   0,            0,             0, 0,  0) +
        shdr(shstr_idx['.strtab'],    SHT_STRTAB, strtab_off,   len(strtab),   0, 0,  0) +
        shdr(shstr_idx['.shstrtab'],  SHT_STRTAB, shstrtab_off, len(shstrtab), 0, 0,  0) +
        shdr(shstr_idx['.symtab'],    SHT_SYMTAB, symtab_off,   len(symtab),   1, 1, 24)
    )
    e_ident = b'\x7fELF\x02\x01\x01\x00' + b'\x00' * 8
    elf_hdr = e_ident + struct.pack('<HHIQQQIHHHHHH',
        2, 62, 1, 0, 0, shdrs_off, 0, 64, 0, 0, 64, 4, 2)
    data = bytearray(shdrs_off + len(shdrs))
    data[0:64] = elf_hdr
    data[strtab_off:strtab_off+len(strtab)] = strtab
    data[shstrtab_off:shstrtab_off+len(shstrtab)] = shstrtab
    data[symtab_off:symtab_off+len(symtab)] = symtab
    data[shdrs_off:] = shdrs
    with tempfile.NamedTemporaryFile(suffix='.elf', delete=False) as f:
        f.write(bytes(data))
        tmp = f.name
    try:
        result = get_instrumented_pcs(tmp)
    finally:
        os.unlink(tmp)
    assert result == []


def test_missing_file_raises():
    """Missing vmlinux raises OSError."""
    with pytest.raises(OSError):
        get_instrumented_pcs('/nonexistent/vmlinux')
```

- [ ] **Step 2: Run tests — verify they all fail**

```bash
cd /home/lehich/vock && python3 -m pytest tests/test_elf.py -v
```

Expected: 3 tests FAILED (module `report.elf` does not exist).

- [ ] **Step 3: Create `report/elf.py`**

```python
"""Discover KCOV-instrumented PCs from vmlinux ELF relocations."""
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.elf.relocation import RelocationSection

_TRACE_PC_NAMES = frozenset({
    '__sanitizer_cov_trace_pc',
    '____sanitizer_cov_trace_pc_veneer',  # ARM64 veneer
})


def get_instrumented_pcs(vmlinux_path):
    """Return hex addresses of all KCOV-instrumented PCs in vmlinux.

    Scans SHT_RELA sections for relocations targeting __sanitizer_cov_trace_pc,
    matching the approach used by syzkaller's syz-cover tool.
    """
    with open(vmlinux_path, 'rb') as f:
        elf = ELFFile(f)

        symtab = elf.get_section_by_name('.symtab')
        if symtab is None or not isinstance(symtab, SymbolTableSection):
            return []

        trace_indices = {
            i for i, sym in enumerate(symtab.iter_symbols())
            if sym.name in _TRACE_PC_NAMES
        }
        if not trace_indices:
            return []

        pcs = []
        for section in elf.iter_sections():
            if isinstance(section, RelocationSection) and section.is_RELA():
                for rel in section.iter_relocations():
                    if rel['r_info_sym'] in trace_indices:
                        pcs.append(hex(rel['r_offset']))
        return pcs
```

- [ ] **Step 4: Run tests — verify they all pass**

```bash
cd /home/lehich/vock && python3 -m pytest tests/test_elf.py -v
```

Expected:
```
tests/test_elf.py::test_finds_kcov_relocation PASSED
tests/test_elf.py::test_no_kcov_symbol_returns_empty PASSED
tests/test_elf.py::test_missing_file_raises PASSED
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add report/elf.py tests/test_elf.py
git commit -m "feat: add ELF relocation scanner for KCOV-instrumented PCs"
```

---

### Task 2: `report/html.py` — miss rendering and instrumented stats

**Files:**
- Modify: `report/html.py`
- Modify: `tests/test_html_report.py`

- [ ] **Step 6: Add failing tests to `tests/test_html_report.py`**

Append to the end of `tests/test_html_report.py`:

```python
def test_instrumented_key_in_data_json():
    """DATA.instrumented contains sorted instrumented line numbers when provided."""
    with tempfile.TemporaryDirectory() as src:
        fpath = "kernel/sched/core.c"
        os.makedirs(os.path.join(src, "kernel/sched"))
        with open(os.path.join(src, fpath), "w") as f:
            f.write("line one\nline two\nline three\nline four\n")

        output = os.path.join(src, "out.html")
        generate({"kernel/sched/core.c": {2}}, src, 4, 4, output,
                 instrumented={"kernel/sched/core.c": {2, 3}})

        data = _parse_data(open(output).read())
        assert data["instrumented"]["kernel/sched/core.c"] == [2, 3]


def test_no_instrumented_gives_empty_dict():
    """DATA.instrumented is {} when instrumented=None."""
    with tempfile.TemporaryDirectory() as src:
        output = os.path.join(src, "out.html")
        generate({}, src, 4, 4, output)

        data = _parse_data(open(output).read())
        assert data["instrumented"] == {}


def test_miss_css_class_present():
    """.miss CSS class is defined in HTML output."""
    with tempfile.TemporaryDirectory() as src:
        output = os.path.join(src, "out.html")
        generate({}, src, 4, 4, output)
        assert ".miss" in open(output).read()


def test_filter_kw_applied_to_instrumented():
    """filter_kw excludes files from DATA.instrumented as well as DATA.covered."""
    with tempfile.TemporaryDirectory() as src:
        os.makedirs(os.path.join(src, "kernel/sched"))
        os.makedirs(os.path.join(src, "net"))
        open(os.path.join(src, "kernel/sched/core.c"), "w").write("a\n")
        open(os.path.join(src, "net/socket.c"), "w").write("b\n")

        output = os.path.join(src, "out.html")
        generate(
            {"kernel/sched/core.c": {1}, "net/socket.c": {1}},
            src, 4, 4, output,
            filter_kw="sched",
            instrumented={"kernel/sched/core.c": {1, 2}, "net/socket.c": {1, 2}},
        )

        data = _parse_data(open(output).read())
        assert "net/socket.c" not in data["instrumented"]
        assert "kernel/sched/core.c" in data["instrumented"]
```

- [ ] **Step 7: Run new tests — verify they fail**

```bash
cd /home/lehich/vock && python3 -m pytest tests/test_html_report.py::test_instrumented_key_in_data_json tests/test_html_report.py::test_no_instrumented_gives_empty_dict tests/test_html_report.py::test_miss_css_class_present tests/test_html_report.py::test_filter_kw_applied_to_instrumented -v
```

Expected: 4 tests FAILED (`generate()` has no `instrumented` parameter, `DATA.instrumented` key absent, `.miss` class absent).

- [ ] **Step 8: Rewrite `report/html.py`**

Replace the entire file with:

```python
"""Generate coverage.html from resolved source coverage."""
import json
from pathlib import Path


def generate(cov: dict[str, set[int]], kernel_src: str,
             before: int, after: int, output_path: str,
             filter_kw: str = None, instrumented: dict[str, set[int]] = None):
    """Write coverage.html with sidebar navigation and full file display."""
    src_root = Path(kernel_src)

    files = []
    covered = {}
    lines = {}
    inst = {}

    for fpath, cov_lines in sorted(cov.items()):
        if filter_kw and filter_kw not in fpath:
            continue
        files.append(fpath)
        covered[fpath] = sorted(cov_lines)
        full = src_root / fpath
        try:
            lines[fpath] = full.read_text(errors="ignore").splitlines()
        except OSError:
            lines[fpath] = None
        if instrumented and fpath in instrumented:
            inst[fpath] = sorted(instrumented[fpath])

    data_json = json.dumps(
        {"files": files, "covered": covered, "lines": lines, "instrumented": inst},
        ensure_ascii=False
    ).replace("</", "<\\/")

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
#file-list {{ list-style: none; overflow-y: auto; flex: 1; font-size: 0.8em; }}
#file-list ul {{ list-style: none; padding-left: 12px; }}
#file-list li {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
#file-list li.file {{ padding: 3px 10px; cursor: pointer; color: #ce9178; }}
#file-list li.file:hover {{ background: #2a2d2e; }}
#file-list li.file.active {{ background: #094771; color: #d4d4d4; }}
#file-list li.dir {{ padding: 3px 6px; cursor: pointer; color: #569cd6; user-select: none; }}
#file-list li.dir:hover {{ background: #2a2d2e; }}
.dir-toggle {{ display: inline-block; width: 1em; font-size: 0.75em; color: #858585; }}
.count {{ color: #858585; margin-left: 0.4em; }}
#content-area {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; }}
#file-header {{ padding: 8px 16px; background: #1e1e1e; border-bottom: 1px solid #3c3c3c; color: #dcdcaa; font-size: 0.9em; flex-shrink: 0; }}
#content {{ overflow: auto; flex: 1; }}
pre {{ padding: 10px 16px; }}
.cov {{ background: #1e3a1e; color: #4ec9b0; display: block; }}
.miss {{ background: #3a1e1e; color: #f48771; display: block; }}
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
  document.querySelectorAll('#file-list li.file').forEach(function(li){{
    li.classList.toggle('active',li.dataset.path===path);
  }});
  var header=document.getElementById('file-header');
  var content=document.getElementById('content');
  var covSet=new Set(DATA.covered[path]||[]);
  var instSet=new Set(DATA.instrumented[path]||[]);
  header.textContent=path+' ('+covSet.size+' covered lines)';
  if(cache[path]!==undefined){{content.innerHTML=cache[path];return;}}
  var fileLines=DATA.lines[path];
  if(fileLines===null){{
    cache[path]='<pre><span class="ctx">(file not found)</span></pre>';
    content.innerHTML=cache[path];return;
  }}
  var buf='<pre>';
  fileLines.forEach(function(line,i){{
    var ln=i+1;
    var esc=line.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    var cls=covSet.has(ln)?'cov':(instSet.has(ln)?'miss':'ctx');
    var mark=covSet.has(ln)?'&gt;':(instSet.has(ln)?'!':'|');
    buf+='<span class="'+cls+'"><span class="ln">'+ln+'</span> '+mark+' '+esc+'</span>\\n';
  }});
  buf+='</pre>';
  cache[path]=buf;
  content.innerHTML=buf;
}}
function fmt(cov,tot){{
  if(tot===0)return cov+' / 0';
  return cov+' / '+tot+' ('+Math.round(cov/tot*100)+'%)';
}}
function buildTree(files){{
  var root={{}};
  files.forEach(function(path){{
    var parts=path.split('/'),node=root;
    for(var i=0;i<parts.length-1;i++){{if(!node[parts[i]])node[parts[i]]={{}};node=node[parts[i]];}}
    node[parts[parts.length-1]]=null;
  }});
  return root;
}}
function renderTreeNode(node,prefix,ul){{
  var keys=Object.keys(node).sort();
  var dirs=[],files=[];
  keys.forEach(function(k){{(node[k]===null?files:dirs).push(k);}});
  var sumCov=0,sumTot=0;
  dirs.forEach(function(dir){{
    var li=document.createElement('li');li.className='dir';
    var tog=document.createElement('span');tog.className='dir-toggle';tog.textContent='▶';
    var lbl=document.createElement('span');lbl.className='dir-name';lbl.textContent=' '+dir;
    var sub=document.createElement('ul');sub.style.display='none';
    function toggle(){{var open=sub.style.display!=='none';sub.style.display=open?'none':'';tog.textContent=open?'▶':'▼';}}
    tog.onclick=toggle;lbl.onclick=toggle;
    li.appendChild(tog);li.appendChild(lbl);li.appendChild(sub);ul.appendChild(li);
    var s=renderTreeNode(node[dir],prefix+dir+'/',sub);
    sumCov+=s.cov;sumTot+=s.tot;
    var cnt=document.createElement('span');cnt.className='count';cnt.textContent=' '+fmt(s.cov,s.tot);
    li.appendChild(cnt);
  }});
  files.forEach(function(file){{
    var path=prefix+file;
    var cov=(DATA.covered[path]||[]).length;
    var instArr=DATA.instrumented[path];
    var tot=instArr&&instArr.length?instArr.length:(DATA.lines[path]?DATA.lines[path].length:0);
    sumCov+=cov;sumTot+=tot;
    var li=document.createElement('li');li.className='file';li.dataset.path=path;li.title=path;
    var name=document.createTextNode(file+' ');
    var cnt=document.createElement('span');cnt.className='count';cnt.textContent=fmt(cov,tot);
    li.appendChild(name);li.appendChild(cnt);
    li.onclick=function(){{renderFile(path);}};
    ul.appendChild(li);
  }});
  return {{cov:sumCov,tot:sumTot}};
}}
function applyFilter(q){{
  var files=document.querySelectorAll('#file-list li.file');
  var dirs=document.querySelectorAll('#file-list li.dir');
  if(!q){{
    files.forEach(function(li){{li.style.display='';}});
    dirs.forEach(function(li){{
      li.style.display='';
      var sub=li.querySelector(':scope>ul'),tog=li.querySelector(':scope>.dir-toggle');
      if(sub)sub.style.display='none';if(tog)tog.textContent='▶';
    }});
    return;
  }}
  dirs.forEach(function(li){{
    var sub=li.querySelector(':scope>ul'),tog=li.querySelector(':scope>.dir-toggle');
    if(sub)sub.style.display='';if(tog)tog.textContent='▼';
  }});
  files.forEach(function(li){{li.style.display=li.title.toLowerCase().includes(q)?'':'none';}});
  Array.from(dirs).reverse().forEach(function(li){{
    var sub=li.querySelector(':scope>ul');if(!sub)return;
    var vis=Array.from(sub.children).some(function(c){{return c.style.display!=='none';}});
    li.style.display=vis?'':'none';
  }});
}}
document.addEventListener('DOMContentLoaded',function(){{
  var list=document.getElementById('file-list');
  if(DATA.files.length){{renderTreeNode(buildTree(DATA.files),'',list);renderFile(DATA.files[0]);}}
  document.getElementById('filter').addEventListener('input',function(){{applyFilter(this.value.toLowerCase());}});
}});
</script>
</body></html>"""

    with open(output_path, "w") as f:
        f.write(html)
```

- [ ] **Step 9: Run all tests — verify they all pass**

```bash
cd /home/lehich/vock && python3 -m pytest tests/test_html_report.py tests/test_elf.py -v
```

Expected: all 11 tests PASSED (7 existing + 4 new).

- [ ] **Step 10: Commit**

```bash
git add report/html.py tests/test_html_report.py
git commit -m "feat: add miss line highlighting and instrumented stats to HTML report"
```

---

### Task 3: `output.py` — integrate ELF scanner

**Files:**
- Modify: `output.py`

- [ ] **Step 11: Update `output.py`**

Replace the lines between `# Resolve addresses` and `generate_html(...)` with:

Find this block (lines 107–115):
```python
    # Resolve addresses
    lines = run_addr2line(args.vmlinux, addrs)
    cov = aggregate(lines, args.kernel_src)
    if not cov:
        if not args.quiet:
            print("\033[93mno source lines resolved\033[0m")
        return

    generate_html(cov, args.kernel_src, args.B, args.A, args.output, args.filter)
```

Replace with:
```python
    # Resolve addresses
    lines = run_addr2line(args.vmlinux, addrs)
    cov = aggregate(lines, args.kernel_src)
    if not cov:
        if not args.quiet:
            print("\033[93mno source lines resolved\033[0m")
        return

    # Discover instrumented PCs from vmlinux ELF (optional: requires pyelftools)
    instrumented_cov = None
    if path.isfile(args.vmlinux):
        try:
            from report.elf import get_instrumented_pcs
            if not args.quiet:
                print("  Scanning vmlinux for instrumented PCs...")
            inst_addrs = get_instrumented_pcs(args.vmlinux)
            inst_lines = run_addr2line(args.vmlinux, inst_addrs)
            instrumented_cov = aggregate(inst_lines, args.kernel_src)
        except ImportError:
            if not args.quiet:
                print("\033[93m  pyelftools not installed; miss highlighting disabled\033[0m")
        except Exception as e:
            if not args.quiet:
                print(f"\033[93m  ELF scan failed ({e}); miss highlighting disabled\033[0m")

    generate_html(cov, args.kernel_src, args.B, args.A, args.output, args.filter,
                  instrumented_cov)
```

- [ ] **Step 12: Run all tests — verify no regressions**

```bash
cd /home/lehich/vock && python3 -m pytest tests/ -v
```

Expected: all 11 tests PASSED.

- [ ] **Step 13: Commit**

```bash
git add output.py
git commit -m "feat: integrate ELF instrumented-PC scanner into output.py pipeline"
```

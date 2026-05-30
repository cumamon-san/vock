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
        except OSError:
            lines[fpath] = None

    data_json = json.dumps(
        {"files": files, "covered": covered, "lines": lines},
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
#file-list {{ list-style: none; overflow-y: auto; flex: 1; }}
#file-list ul {{ list-style: none; padding-left: 12px; }}
#file-list li {{ font-size: 0.8em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
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
    var cls=covSet.has(ln)?'cov':'ctx';
    var mark=covSet.has(ln)?'&gt;':'|';
    buf+='<span class="'+cls+'"><span class="ln">'+ln+'</span> '+mark+' '+esc+'</span>\\n';
  }});
  buf+='</pre>';
  cache[path]=buf;
  content.innerHTML=buf;
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
  dirs.forEach(function(dir){{
    var li=document.createElement('li');li.className='dir';
    var tog=document.createElement('span');tog.className='dir-toggle';tog.textContent='▶';
    var lbl=document.createElement('span');lbl.className='dir-name';lbl.textContent=' '+dir;
    var sub=document.createElement('ul');sub.style.display='none';
    function toggle(){{var open=sub.style.display!=='none';sub.style.display=open?'none':'';tog.textContent=open?'▶':'▼';}}
    tog.onclick=toggle;lbl.onclick=toggle;
    li.appendChild(tog);li.appendChild(lbl);li.appendChild(sub);ul.appendChild(li);
    renderTreeNode(node[dir],prefix+dir+'/',sub);
  }});
  files.forEach(function(file){{
    var path=prefix+file;
    var count=(DATA.covered[path]||[]).length;
    var li=document.createElement('li');li.className='file';li.dataset.path=path;li.title=path;
    var name=document.createTextNode(file+' ');
    var cnt=document.createElement('span');cnt.className='count';cnt.textContent='('+count+')';
    li.appendChild(name);li.appendChild(cnt);
    li.onclick=function(){{renderFile(path);}};
    ul.appendChild(li);
  }});
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

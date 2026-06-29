"""Publish the group posting registry to the EstateBoard web dashboard.

Writes two files into the EstateBoard repo's docs/ (served at estateboard.pages.dev):
  - groups.json : the registry data (from data/group_registry.json)
  - groups.html : a self-contained viewer (Tabulator table) — WHERE we post,
                  membership, post counts, last posted, status.

Then commits, pushes, and deploys to Cloudflare Pages so the page is live at
  https://estateboard.pages.dev/groups.html

Best-effort: if EstateBoard is absent or the registry is missing, it logs and
returns cleanly. Never raises.

Usage:
    python scripts/sync_groups_web.py
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

log = logging.getLogger("sync_groups_web")

DEFAULT_EB_ROOT = Path(r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard")
REGISTRY_JSON = ROOT / "data" / "group_registry.json"

GROUPS_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>投稿先グループ管理 — FB物件配信</title>
<link href="https://unpkg.com/tabulator-tables@6.3.0/dist/css/tabulator.min.css" rel="stylesheet" />
<script src="https://unpkg.com/tabulator-tables@6.3.0/dist/js/tabulator.min.js"></script>
<style>
  body { margin:0; background:#f1f5f9; color:#0f172a;
    font-family:"Segoe UI","Hiragino Kaku Gothic ProN","Yu Gothic UI",Meiryo,system-ui,sans-serif; font-size:13px; }
  header { background:linear-gradient(120deg,#0f172a 0%,#134e4a 100%); color:#fff; padding:18px 22px; }
  header h1 { margin:0 0 4px; font-size:18px; }
  header .sub { opacity:.8; font-size:12px; }
  .cards { display:flex; gap:12px; padding:16px 22px 0; flex-wrap:wrap; }
  .card { background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:12px 16px; min-width:120px;
    box-shadow:0 1px 2px rgba(15,23,42,.06); }
  .card .n { font-size:22px; font-weight:700; }
  .card .l { color:#64748b; font-size:11px; }
  .wrap { padding:16px 22px 40px; }
  #t { background:#fff; border-radius:12px; box-shadow:0 8px 24px rgba(15,23,42,.08); }
  .pill { padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }
  .active { background:#dcfce7; color:#166534; }
  .registered { background:#fef9c3; color:#854d0e; }
  .candidate { background:#e2e8f0; color:#475569; }
  a { color:#0d9488; text-decoration:none; }
  a:hover { text-decoration:underline; }
</style>
</head>
<body>
<header>
  <h1>📮 投稿先グループ管理</h1>
  <div class="sub">どのFacebookグループに物件を配信しているかの記録。active=配信中 / registered=保留 / candidate=所属済みの追加候補。</div>
</header>
<div class="cards" id="cards"></div>
<div class="wrap"><div id="t"></div></div>
<script>
function pill(s){ return `<span class="pill ${s}">${s}</span>`; }
fetch('groups.json?_='+Date.now()).then(r=>r.json()).then(d=>{
  const rows = d.groups||[];
  const by = s => rows.filter(r=>r.status===s).length;
  document.getElementById('cards').innerHTML = [
    ['配信中(active)', by('active')],
    ['保留(registered)', by('registered')],
    ['追加候補(candidate)', by('candidate')],
    ['投稿確認 合計', rows.reduce((a,r)=>a+(r.posts_verified||0),0)],
  ].map(([l,n])=>`<div class="card"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
  new Tabulator('#t', {
    data: rows, layout:'fitColumns', height:'70vh', pagination:false,
    initialSort:[{column:'status',dir:'asc'},{column:'posts_verified',dir:'desc'}],
    columns:[
      {title:'状態', field:'status', width:120, formatter:c=>pill(c.getValue())},
      {title:'グループ名', field:'name', minWidth:240, formatter:c=>{
        const u=c.getRow().getData().url; return u?`<a href="${u}" target="_blank">${c.getValue()||''}</a>`:(c.getValue()||''); }},
      {title:'カテゴリ', field:'category', width:150},
      {title:'順序', field:'selection_order', width:110},
      {title:'所属', field:'member', width:70, hozAlign:'center', formatter:c=>c.getValue()?'✓':''},
      {title:'投稿確認', field:'posts_verified', width:100, hozAlign:'right'},
      {title:'試行', field:'posts_attempted', width:80, hozAlign:'right'},
      {title:'最終投稿', field:'last_posted_at', width:120, formatter:c=>(c.getValue()||'').slice(0,10)},
    ],
  });
  document.querySelector('header .sub').innerHTML += ` ｜ 更新: ${(d.updated_at||'').slice(0,16).replace('T',' ')}`;
});
</script>
</body>
</html>
"""


def _git(eb_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(eb_root), capture_output=True, text=True, timeout=60, check=False)


def sync_groups_web(eb_root: Path | None = None) -> dict:
    eb = Path(eb_root) if eb_root else DEFAULT_EB_ROOT
    if not eb.exists():
        log.warning("EstateBoard repo not found: %s", eb)
        return {"skipped": True}
    if not REGISTRY_JSON.exists():
        log.warning("registry not found; run build_group_registry first")
        return {"skipped": True}

    docs = eb / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "groups.json").write_text(REGISTRY_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    (docs / "groups.html").write_text(GROUPS_HTML, encoding="utf-8")

    rels = ["docs/groups.json", "docs/groups.html"]
    pushed = False
    try:
        status = _git(eb, "status", "--porcelain", *rels)
        if status.stdout.strip():
            _git(eb, "add", *rels)
            _git(eb, "commit", "-m", "data: update FB group posting registry page")
            push = _git(eb, "push")
            if push.returncode != 0:
                log.warning("push failed: %s", (push.stderr or push.stdout)[:200])
            pushed = True
            _wrangler_deploy(eb)
    except Exception as exc:  # noqa: BLE001 - never crash the pipeline
        log.warning("groups web sync git step skipped: %s: %s", type(exc).__name__, exc)
    return {"skipped": False, "pushed": pushed, "url": "https://estateboard.pages.dev/groups.html"}


def _wrangler_deploy(eb: Path) -> bool:
    try:
        cp = subprocess.run(
            ["npx", "wrangler", "pages", "deploy", "docs", "--project-name=estateboard", "--commit-dirty=true"],
            cwd=str(eb), capture_output=True, text=True, timeout=600, shell=True, check=False,
        )
        return cp.returncode == 0
    except Exception as exc:  # noqa: BLE001
        log.warning("wrangler deploy skipped: %s: %s", type(exc).__name__, exc)
        return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    result = sync_groups_web()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

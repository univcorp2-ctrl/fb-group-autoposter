"""Publish a live Facebook-posting status page to the EstateBoard site.

Writes docs/fb-status.json + docs/fb-status.html into the EstateBoard repo and
deploys with wrangler (same path as groups.html, which is known to deploy), so
the page is live at https://estateboard.pages.dev/fb-status.html

Shows: is posting actually running (extension polling, pause switch, session),
recent posts with their text preview / permalink / quality score, today's
counts, next scheduled runs, and red alerts when something is stuck.
Best-effort; never raises. Only public post data is published (no secrets).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sync_groups_web import DEFAULT_EB_ROOT, _wrangler_deploy  # noqa: E402

log = logging.getLogger("sync_fb_status_web")
JST = timezone(timedelta(hours=9))
BRIDGE = "http://127.0.0.1:8766/health"


def _bridge() -> dict:
    try:
        with urllib.request.urlopen(BRIDGE, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"bridge unreachable: {type(exc).__name__}"}


def _db_path() -> Path:
    import os
    return Path(os.getenv("DB_PATH", str(ROOT / "data" / "jobs.db")))


def _recent(conn: sqlite3.Connection, limit: int = 40) -> list[dict]:
    from src.post_quality import evaluate
    groups = {}
    try:
        from config import load_groups
        groups = {str(g["id"]): g.get("name", "") for g in load_groups()}
    except Exception:  # noqa: BLE001
        pass
    rows = conn.execute(
        """
        SELECT t.group_id, t.status, t.posted_at, t.permalink, t.last_error, t.body,
               j.property_id, j.updated_at, j.payload_json
        FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
        WHERE t.status IN ('posted','uncertain','failed','skipped')
          AND COALESCE(t.posted_at, j.updated_at) >= ?
        ORDER BY COALESCE(t.posted_at, j.updated_at) DESC LIMIT ?
        """,
        ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(), limit),
    ).fetchall()
    out = []
    for r in rows:
        try:
            title = json.loads(r["payload_json"] or "{}").get("title", "")
        except Exception:  # noqa: BLE001
            title = ""
        body = r["body"] or ""
        q = evaluate(body)
        out.append({
            "at": r["posted_at"] or r["updated_at"],
            "group": groups.get(str(r["group_id"]), str(r["group_id"])),
            "group_url": f"https://www.facebook.com/groups/{r['group_id']}",
            "property_id": r["property_id"],
            "title": title,
            "status": r["status"],
            "permalink": r["permalink"],
            "error": (r["last_error"] or "")[:160],
            "quality": q.score,
            "quality_ok": q.passes,
            "preview": "\n".join(body.split("\n")[:4]),
        })
    return out


def _schedule() -> list[dict]:
    try:
        cp = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-ScheduledTask -TaskName 'FBAutoposter-*' | ? { $_.TaskName -match 'Morning|Midday|Afternoon|Evening|DailyGuarantee' } | "
             "% { $i = $_ | Get-ScheduledTaskInfo; [pscustomobject]@{name=$_.TaskName; state=[string]$_.State; "
             "next=$i.NextRunTime.ToString('s'); last=$i.LastRunTime.ToString('s'); result=$i.LastTaskResult} } | ConvertTo-Json"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        data = json.loads(cp.stdout or "[]")
        return data if isinstance(data, list) else [data]
    except Exception:  # noqa: BLE001
        return []


def build_status() -> dict:
    bridge = _bridge()
    now = datetime.now(timezone.utc)
    start_jst = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    with sqlite3.connect(_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        recent = _recent(conn)
        today = {r["status"]: r["n"] for r in conn.execute(
            """SELECT t.status, COUNT(*) n FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
               WHERE COALESCE(t.posted_at, j.updated_at) >= ? GROUP BY t.status""", (start_jst,))}
        last_live = conn.execute(
            "SELECT MAX(posted_at) m FROM job_targets WHERE status IN ('posted','uncertain')").fetchone()["m"]
    alerts = []
    if not bridge.get("ok"):
        alerts.append("拡張ブリッジ停止（127.0.0.1:8766に応答なし）")
    elif not bridge.get("extension_polling"):
        alerts.append(f"Chrome拡張がポーリングしていません（{bridge.get('extension_poll_age_seconds')}秒）→ 拡張の再読み込みが必要")
    if bridge.get("posting_paused"):
        alerts.append("投稿は一時停止中（data/PAUSE_POSTING）")
    if last_live:
        hours = (now - datetime.fromisoformat(last_live)).total_seconds() / 3600
        if hours > 30:
            alerts.append(f"最終投稿から{hours:.0f}時間経過")
    return {
        "updated_at": now.isoformat(),
        "bridge": {k: bridge.get(k) for k in (
            "ok", "extension_polling", "extension_poll_age_seconds", "extension_version",
            "posting_paused", "pending_tasks", "active_lease", "error")},
        "today": today,
        "last_post_at": last_live,
        "alerts": alerts,
        "schedule": _schedule(),
        "recent": recent,
    }


STATUS_HTML = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>FB投稿ステータス</title>
<style>
:root{--bg:#f1f5f9;--card:#fff;--ink:#0f172a;--mute:#64748b;--ok:#166534;--okb:#dcfce7;--ng:#991b1b;--ngb:#fee2e2;--wa:#854d0e;--wab:#fef9c3}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 "Hiragino Kaku Gothic ProN","Yu Gothic UI",Meiryo,system-ui,sans-serif}
header{background:linear-gradient(120deg,#0f172a,#134e4a);color:#fff;padding:16px}
h1{margin:0;font-size:18px} .sub{opacity:.8;font-size:12px}
main{max-width:960px;margin:0 auto;padding:12px 16px 40px}
.alert{background:var(--ngb);color:var(--ng);border-radius:10px;padding:10px 12px;margin:8px 0;font-weight:600}
.okline{background:var(--okb);color:var(--ok);border-radius:10px;padding:10px 12px;margin:8px 0;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:12px 0}
.card{background:var(--card);border-radius:12px;padding:10px 12px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card .n{font-size:22px;font-weight:700}.card .l{color:var(--mute);font-size:11px}
.post{background:var(--card);border-radius:12px;padding:12px;margin:10px 0;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.meta{font-size:12px;color:var(--mute)} pre{white-space:pre-wrap;font:13px/1.5 inherit;margin:6px 0 0;background:#f8fafc;padding:8px;border-radius:8px}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:700;margin-right:6px}
.posted{background:var(--okb);color:var(--ok)}.uncertain{background:var(--wab);color:var(--wa)}.failed,.skipped{background:var(--ngb);color:var(--ng)}
a{color:#0d9488} table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;font-size:12px}
td,th{padding:6px 8px;border-bottom:1px solid #e2e8f0;text-align:left}
</style></head><body>
<header><h1>📮 Facebook物件投稿ステータス</h1><div class="sub" id="upd"></div></header>
<main><div id="alerts"></div><div class="cards" id="cards"></div>
<h3>次回の定期投稿</h3><table id="sched"></table>
<h3>直近の投稿（7日）</h3><div id="posts"></div></main>
<script>
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const jst=s=>s?new Date(s).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'-';
fetch('fb-status.json?_='+Date.now()).then(r=>r.json()).then(d=>{
 document.getElementById('upd').textContent='更新: '+jst(d.updated_at)+'（PCから約30分ごとに自動更新）';
 document.getElementById('alerts').innerHTML=(d.alerts||[]).length?d.alerts.map(a=>`<div class="alert">⚠️ ${esc(a)}</div>`).join(''):'<div class="okline">✅ 投稿システム正常稼働中</div>';
 const t=d.today||{}, b=d.bridge||{};
 document.getElementById('cards').innerHTML=[['本日 投稿',(t.posted||0)+(t.uncertain||0)],['本日 品質NGで保留',t.skipped||0],['本日 失敗',t.failed||0],['拡張ポーリング',b.extension_polling?'OK':'停止'],['拡張バージョン',b.extension_version||'-'],['最終投稿',jst(d.last_post_at)]].map(([l,n])=>`<div class="card"><div class="n">${esc(n)}</div><div class="l">${l}</div></div>`).join('');
 document.getElementById('sched').innerHTML='<tr><th>タスク</th><th>次回</th><th>前回</th></tr>'+(d.schedule||[]).sort((a,b)=>(a.next||'').localeCompare(b.next||'')).map(s=>`<tr><td>${esc(s.name.replace('FBAutoposter-',''))}</td><td>${esc((s.next||'').replace('T',' ').slice(5,16))}</td><td>${esc((s.last||'').replace('T',' ').slice(5,16))}</td></tr>`).join('');
 document.getElementById('posts').innerHTML=(d.recent||[]).map(p=>`<div class="post"><span class="pill ${esc(p.status)}">${esc(p.status)}</span><b>${esc(p.title||p.property_id)}</b><div class="meta">${jst(p.at)} ｜ <a href="${esc(p.group_url)}" target="_blank" rel="noopener">${esc(p.group)}</a> ｜ 品質 ${esc(p.quality)}/10 ${p.permalink?`｜ <a href="${esc(p.permalink)}" target="_blank" rel="noopener">投稿を開く</a>`:''} ${p.error&&p.status!=='posted'?'｜ '+esc(p.error):''}</div><pre>${esc(p.preview)}</pre></div>`).join('')||'<p>直近7日の投稿はありません</p>';
});
</script></body></html>
"""


def sync_fb_status_web(eb_root: Path | None = None, deploy: bool = True) -> dict:
    eb = Path(eb_root) if eb_root else DEFAULT_EB_ROOT
    status = build_status()
    local = ROOT / "logs" / "fb-status.json"
    local.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    if not eb.exists():
        return {"skipped": True, "alerts": status["alerts"]}
    docs = eb / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "fb-status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    (docs / "fb-status.html").write_text(STATUS_HTML, encoding="utf-8")
    deployed = _wrangler_deploy(eb) if deploy else False
    return {"deployed": deployed, "alerts": status["alerts"], "url": "https://estateboard.pages.dev/fb-status.html"}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(json.dumps(sync_fb_status_web(deploy="--no-deploy" not in sys.argv), ensure_ascii=False))


if __name__ == "__main__":
    main()

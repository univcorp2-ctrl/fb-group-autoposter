"""Generate FB post DRAFTS for Daiwa House listings and save them to Notion.

The supplier company name is NEVER shown — each listing is positioned as a
"超大手有名企業ブランド" property (brand masked via src.group_rules.mask_brands).
Drafts are written locally (data/daiwa_drafts.json) and upserted into a Notion
database so they can be reviewed/approved before posting.

Run:
    python scripts/daiwa_drafts.py            # generate + save to Notion (if configured)
    python scripts/daiwa_drafts.py --no-notion
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups  # noqa: E402
from src.daiwa_adapter import daiwa_to_property  # noqa: E402
from src.generator import generate_variants  # noqa: E402
from src.group_rules import mask_brands  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402

log = logging.getLogger("daiwa_drafts")

DEFAULT_SOURCE = Path(r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard\docs\data_daiwa.json")
LOCAL_OUT = ROOT / "data" / "daiwa_drafts.json"
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _draft_group() -> dict:
    """A group config used only to render the draft body (signature/links/limits
    matching a real post). Falls back to a sane default if groups.yaml is empty."""
    try:
        groups = load_groups()
        if groups:
            g = dict(groups[0])
            g["name"] = "下書き"
            return g
    except Exception as exc:  # noqa: BLE001
        log.warning("could not load groups for draft signature: %s", exc)
    return {"id": "draft", "name": "下書き", "post_url": "https://www.facebook.com/groups/0",
            "tone": "プロフェッショナル", "max_chars": 1200, "active_hours": [0, 24],
            "allow_links": False, "allow_images": True, "forbidden": ["保証", "絶対", "確実"], "signature": ""}


def build_drafts(source: Path, settings: Settings) -> list[dict]:
    if not source.exists():
        log.warning("Daiwa source not found: %s", source)
        return []
    data = json.loads(source.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else []
    group = _draft_group()
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y-%m-%d")
    drafts: list[dict] = []
    for it in items:
        prop = daiwa_to_property(it)
        body = generate_variants(prop, [group], settings).variants[0]["body"]
        body = mask_brands(body)  # final safety: never leak the brand
        drafts.append(
            {
                "property_id": prop["property_id"],
                "title": prop["title"],
                "kind": prop.get("_kind", ""),
                "price_man": prop.get("_price_man"),
                "yield": prop.get("_yield"),
                "grade": prop.get("_grade", ""),
                "nokori_man": prop.get("_nokori_man"),
                "location": prop["location"],
                "body": body,
                "created": today,
            }
        )
    return drafts


def _notion_props(d: dict) -> dict:
    props: dict = {
        "物件名": {"title": [{"text": {"content": d["title"][:200]}}]},
        "物件ID": {"rich_text": [{"text": {"content": d["property_id"]}}]},
        "種別": {"rich_text": [{"text": {"content": d["kind"]}}]},
        "所在地": {"rich_text": [{"text": {"content": d["location"][:200]}}]},
        "投稿本文(下書き)": {"rich_text": [{"text": {"content": d["body"][:2000]}}]},
        "ステータス": {"select": {"name": "下書き"}},
        "作成日": {"date": {"start": d["created"]}},
    }
    if d.get("price_man"):
        props["価格(万円)"] = {"number": round(d["price_man"])}
    if d.get("yield"):
        props["利回り(%)"] = {"number": float(d["yield"])}
    if d.get("grade") in ("A", "B", "C", "D"):
        props["仕入れ判定"] = {"select": {"name": d["grade"]}}
    if d.get("nokori_man") is not None:
        props["手残り(万円/年)"] = {"number": round(d["nokori_man"])}
    return props


def push_to_notion(drafts: list[dict], token: str, db_id: str) -> dict:
    """Create a Notion page per draft that does not already exist (by 物件ID)."""
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
               "Content-Type": "application/json"}
    created = skipped = 0
    for d in drafts:
        try:
            q = requests.post(
                f"{NOTION_API}/databases/{db_id}/query",
                headers=headers,
                json={"filter": {"property": "物件ID", "rich_text": {"equals": d["property_id"]}}, "page_size": 1},
                timeout=30,
            )
            q.raise_for_status()
            if q.json().get("results"):
                skipped += 1
                continue
            r = requests.post(
                f"{NOTION_API}/pages",
                headers=headers,
                json={"parent": {"database_id": db_id}, "properties": _notion_props(d)},
                timeout=30,
            )
            r.raise_for_status()
            created += 1
        except requests.RequestException as exc:
            log.warning("Notion push failed for %s: %s", d["property_id"], exc)
    return {"created": created, "skipped": skipped}


def main() -> None:
    setup_logging()
    settings = Settings.load()
    source = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else DEFAULT_SOURCE
    drafts = build_drafts(source, settings)
    LOCAL_OUT.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_OUT.write_text(
        json.dumps({"generated_at": datetime.now(UTC).isoformat(), "drafts": drafts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("generated %d Daiwa drafts -> %s", len(drafts), LOCAL_OUT)

    summary = {"drafts": len(drafts), "notion": None}
    token = settings.notion_token
    db_id = os.getenv("NOTION_DRAFTS_DATABASE_ID", "")
    if "--no-notion" not in sys.argv and token and db_id and drafts:
        summary["notion"] = push_to_notion(drafts, token, db_id)
    elif not (token and db_id):
        log.info("Notion drafts DB not configured (NOTION_TOKEN / NOTION_DRAFTS_DATABASE_ID); local only")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

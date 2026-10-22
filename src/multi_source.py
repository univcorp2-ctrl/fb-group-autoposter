from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _items(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        rows = data.get("items", [])
        return rows if isinstance(rows, list) else []
    return data if isinstance(data, list) else []


def _key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item.get("_source_kind") or "estateboard"), str(item.get("propertyId") or item.get("id") or "")


def build_posting_source(
    estateboard_source: str | Path,
    gmail_source: str | Path | None,
    out_path: str | Path,
) -> dict[str, Any]:
    eb = _items(estateboard_source)
    gm = _items(gmail_source)
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in [*eb, *gm]:
        if not isinstance(item, dict):
            continue
        k = _key(item)
        if not k[1] or k in seen:
            continue
        seen.add(k)
        merged.append(item)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source": "estateboard+gmail_broker_ok", "count": len(merged), "items": merged}
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if out.exists() and out.read_bytes() == tmp.read_bytes():
        # Windows may keep the source open for a concurrent read. If the fresh
        # snapshot is byte-identical, no destructive replacement is needed.
        tmp.unlink()
    else:
        for attempt in range(4):
            try:
                tmp.replace(out)
                break
            except PermissionError:
                if attempt == 3:
                    raise  # Changed source must never silently stay stale.
                time.sleep(0.5 * (attempt + 1))
    return {"estateboard": len(eb), "gmail": len(gm), "combined": len(merged), "out": str(out)}

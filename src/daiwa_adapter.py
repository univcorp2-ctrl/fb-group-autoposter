"""Adapt Daiwa House dashboard rows (EstateBoard docs/data_daiwa.json) into the
autoposter's property dict — with the supplier brand masked.

The brand name (大和ハウス) lives only in metadata (提供元/取込ファイル), never in
the property name, but we mask everything defensively and POSITION each listing
as a "超大手有名企業ブランド" property (a credibility signal) without naming the
company.
"""

from __future__ import annotations

from typing import Any

from src.estateboard_adapter import format_price_yen
from src.group_rules import BRAND_MASK, mask_brands

# The label we lead Daiwa drafts with — the selling point is "from a major,
# famous corporate brand", stated generically.
BRAND_POSITION = f"{BRAND_MASK}の物件"


def _num(value: Any) -> float | None:
    try:
        f = float(str(value).replace(",", "").strip())
        return f if f != 0 else None
    except (TypeError, ValueError):
        return None


def _s(value: Any) -> str:
    return mask_brands(str(value or "").strip())


def daiwa_to_property(item: dict[str, Any]) -> dict[str, Any]:
    """Map one data_daiwa.json row to the autoposter property dict."""
    man = _num(item.get("価格(万円)"))
    price = format_price_yen(man * 10_000) if man else "記載なし"
    y = _num(item.get("表面利回り(%)"))
    structure = _s(item.get("構造"))
    age = item.get("築年数")
    age_str = str(age).strip()
    age_label = "新築" if age_str == "0" else (f"築{age_str}年" if age_str not in ("", "None") else "")
    structure_full = structure
    if structure and age_label:
        base = structure if "造" in structure else f"{structure}造"
        structure_full = f"{base} {age_label}"

    highlights = [BRAND_POSITION]
    kind = _s(item.get("種別"))
    if kind:
        highlights.append(kind)
    if structure:
        highlights.append(structure)
    nokori = _num(item.get("手残り(万円/年)"))
    if nokori and nokori > 0:
        highlights.append(f"手残り年{round(nokori)}万円")

    return {
        "property_id": "daiwa-" + str(item.get("ID") or "?"),
        "title": _s(item.get("物件名")) or "（名称未設定）",
        "price": price,
        "yield_pct": f"{y:g}%" if y else "記載なし",
        "location": _s(item.get("所在地")),
        "access": _s(item.get("最寄駅")),
        "structure": structure_full,
        "land_area": _s(item.get("土地面積(㎡)")),
        "building_area": "",
        "year_built": age_label,
        "highlights": highlights,
        "url": "",
        "images": [],
        "raw_text": "",
        # Carried for the Notion draft DB (not used in the post body).
        "_grade": _s(item.get("仕入れ判定")),
        "_nokori_man": nokori,
        "_price_man": man,
        "_yield": y,
        "_kind": kind,
    }

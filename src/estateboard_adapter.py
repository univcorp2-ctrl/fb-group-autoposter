"""EstateBoard received-property export -> fb-group-autoposter property dicts.

Source: EstateBoard `output/received/properties.json` (flattened dot-keyed items).
Only `property.allowBrokerSharing == TRUE` items are eligible (仲介回しOK).
"""

from __future__ import annotations

from typing import Any

PROPERTY_TYPE_JA: dict[str, str] = {
    "WHOLE_BUILDING_MANSION": "一棟マンション",
    "WHOLE_BUILDING_APARTMENT": "一棟アパート",
    "WHOLE_BUILDING_NORMAL": "一棟ビル",
    "BUILDING_OTHER": "一棟その他",
    "LAND_NORMAL": "土地",
    "LAND_OTHER": "土地その他",
    "CONDOMINIUM_MANSION_RESIDENTIAL": "区分マンション（住居）",
    "CONDOMINIUM_MANSION_INVESTMENT": "区分マンション（投資用）",
    "CONDOMINIUM_STORE_OFFICE": "区分（店舗・事務所）",
    "CONDOMINIUM_OTHER": "区分その他",
    "HOUSE_RESIDENTIAL": "戸建（住居）",
    "HOUSE_INVESTMENT": "戸建（投資用）",
    "HOUSE_COMBINED_RENTAL": "戸建（併用賃貸）",
    "HOUSE_LODGING": "戸建（宿泊）",
    "FACILITY_COMMERCIAL": "商業施設",
    "FACILITY_HOSPITAL_NURSING": "医療・介護施設",
    "FACILITY_WAREHOUSE_FACTORY": "倉庫・工場",
    "HOTEL": "ホテル",
    "RESORT_PROPERTY": "リゾート物件",
}

STRUCTURE_JA: dict[str, str] = {
    "REINFORCED_CONCRETE": "RC造",
    "STEEL_REINFORCED_CONCRETE": "SRC造",
    "HEAVY_WEIGHT_STEEL": "重量鉄骨造",
    "LIGHT_WEIGHT_STEEL": "軽量鉄骨造",
    "WOOD": "木造",
    "OTHER": "その他構造",
}

_MISSING = "記載なし"


def _get(item: dict[str, Any], key: str) -> Any:
    """Read a `property.*` value from a flattened or nested EstateBoard item."""
    if f"property.{key}" in item:
        return item[f"property.{key}"]
    prop = item.get("property")
    if isinstance(prop, dict):
        return prop.get(key)
    return None


def is_broker_ok(item: dict[str, Any]) -> bool:
    return str(_get(item, "allowBrokerSharing")).upper() == "TRUE"


def is_postable(item: dict[str, Any]) -> bool:
    """Broker-OK, published, not deleted, and has a price."""
    return (
        is_broker_ok(item)
        and item.get("publicationStatus") == "PUBLISHED"
        and not item.get("deletedAt")
        and bool(_get(item, "price"))
    )


def format_price_yen(value: Any) -> str:
    try:
        yen = int(float(value))
    except (TypeError, ValueError):
        return _MISSING
    if yen <= 0:
        return _MISSING
    oku, man = divmod(yen, 100_000_000)
    man //= 10_000
    if oku and man:
        return f"{oku}億{man:,}万円"
    if oku:
        return f"{oku}億円"
    return f"{man:,}万円"


def format_yield(value: Any) -> str:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return _MISSING
    if pct <= 0:
        return _MISSING
    return f"{pct:.2f}%"


def format_area(value: Any) -> str:
    try:
        sqm = float(value)
    except (TypeError, ValueError):
        return _MISSING
    if sqm <= 0:
        return _MISSING
    return f"{sqm:g}㎡"


def build_location(item: dict[str, Any]) -> str:
    parts = [
        _get(item, "prefectureLabel"),
        _get(item, "cityLabel"),
        _get(item, "restAddress"),
    ]
    joined = "".join(str(p) for p in parts if p)
    return joined or _MISSING


def build_access(item: dict[str, Any]) -> str:
    lines: list[str] = []
    for idx in (1, 2, 3):
        station = _get(item, f"nearestStation{idx}")
        if not station:
            continue
        distance = _get(item, f"distanceFromNearestStation{idx}")
        if distance:
            lines.append(f"{station} 徒歩{distance}分")
        else:
            lines.append(str(station))
    return " / ".join(lines) if lines else _MISSING


def build_structure(item: dict[str, Any]) -> str:
    code = str(_get(item, "buildingStructureType") or "")
    structure = STRUCTURE_JA.get(code, "")
    floors_above = _get(item, "floorsAboveGround")
    floors_below = _get(item, "floorsBelowGround")
    suffix = ""
    if floors_above:
        suffix = f"{floors_above}階建"
        if floors_below:
            suffix = f"地下{floors_below}階付 {suffix}"
    text = " ".join(p for p in (structure, suffix) if p)
    return text or _MISSING


def build_year_built(item: dict[str, Any]) -> str:
    year = _get(item, "constructionDateYear")
    if not year:
        return _MISSING
    month = _get(item, "constructionDateMonth")
    return f"{year}年{month}月" if month else f"{year}年"


def build_highlights(item: dict[str, Any]) -> list[str]:
    highlights: list[str] = []
    ptype = PROPERTY_TYPE_JA.get(str(_get(item, "propertyType") or ""))
    if ptype:
        highlights.append(ptype)
    structure = STRUCTURE_JA.get(str(_get(item, "buildingStructureType") or ""))
    if structure:
        highlights.append(structure)
    try:
        dist = float(_get(item, "distanceFromNearestStation1"))
        if 0 < dist <= 10:
            highlights.append("駅近")
    except (TypeError, ValueError):
        pass
    if str(_get(item, "ownershipType")) == "FREEHOLD":
        highlights.append("所有権")
    commission = str(_get(item, "commissionAllocation") or "")
    if "分かれ" in commission:
        highlights.append("分かれ")
    return highlights


def to_property(item: dict[str, Any]) -> dict[str, Any]:
    """Map one EstateBoard item to a fb-group-autoposter property dict."""
    return {
        "property_id": f"eb-{item.get('propertyId') or item.get('id')}",
        "title": str(_get(item, "label") or item.get("label") or _MISSING),
        "price": format_price_yen(_get(item, "price")),
        "yield_pct": format_yield(_get(item, "yieldAssumedFullOccupancy")),
        "location": build_location(item),
        "access": build_access(item),
        "structure": build_structure(item),
        "land_area": format_area(_get(item, "landAreaSqm")),
        "building_area": format_area(_get(item, "buildingAreaSqm")),
        "year_built": build_year_built(item),
        "highlights": build_highlights(item),
        "url": str(item.get("detail_url") or ""),
        "images": [],
        "raw_text": str(_get(item, "catchphrase") or _get(item, "note") or ""),
    }


def _raw_float(value: Any, *, default: float) -> float:
    """Parse a raw numeric field; `default` (e.g. +inf/-inf) when missing/invalid."""
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _sort_eligible(eligible: list[dict[str, Any]], order: str) -> list[dict[str, Any]]:
    """Order eligible items by the requested strategy.

    - "newest"     : createdAt descending (default, back-compat)
    - "price_asc"  : cheapest first (missing price -> +inf, sinks to the end)
    - "price_desc" : most expensive first (missing price -> -inf, sinks to end)
    - "yield_desc" : highest yield first (missing yield -> -inf, sinks to end)
    """
    if order == "price_asc":
        return sorted(eligible, key=lambda it: _raw_float(_get(it, "price"), default=float("inf")))
    if order == "price_desc":
        return sorted(
            eligible, key=lambda it: _raw_float(_get(it, "price"), default=float("-inf")), reverse=True
        )
    if order == "yield_desc":
        return sorted(
            eligible,
            key=lambda it: _raw_float(_get(it, "yieldAssumedFullOccupancy"), default=float("-inf")),
            reverse=True,
        )
    # "newest" (default) and any unknown order fall back to createdAt desc.
    return sorted(eligible, key=lambda it: str(it.get("createdAt") or ""), reverse=True)


def select_postable(
    items: list[dict[str, Any]],
    *,
    limit: int | None = None,
    exclude_ids: set[str] | None = None,
    order: str = "newest",
) -> list[dict[str, Any]]:
    """Ordered postable (broker-OK) properties, mapped to property dicts.

    `exclude_ids` filters out property_ids already posted so each daily run
    picks a fresh listing. `order` controls the selection strategy so each
    group can pick its OWN next property by its OWN configured order. The
    default ("newest") keeps the original behavior for back-compat.
    """
    exclude = exclude_ids or set()
    eligible = [it for it in items if is_postable(it)]
    eligible = _sort_eligible(eligible, order)
    mapped: list[dict[str, Any]] = []
    for it in eligible:
        prop = to_property(it)
        if prop["property_id"] in exclude:
            continue
        mapped.append(prop)
        if limit is not None and len(mapped) >= limit:
            break
    return mapped

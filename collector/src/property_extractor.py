"""Extract structured property data from a Facebook group post's text (役割3 core).

Pure functions, no I/O — fully unit-testable. Japanese real-estate posts in FB
groups are free-form, so we parse defensively with regex and return whatever we
can confidently find. `extract_property` returns None when the text does not look
like a property listing at all (so non-property chatter is dropped).

This module has NO dependency on the other roles — it is a standalone text parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The 47 prefectures, used to anchor a location match.
_PREFECTURES = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)

# Property-type keywords -> normalized label.
_TYPE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("一棟マンション", "一棟マンション"),
    ("一棟アパート", "一棟アパート"),
    ("一棟ビル", "一棟ビル"),
    ("区分マンション", "区分マンション"),
    ("区分", "区分"),
    ("戸建", "戸建"),
    ("テラスハウス", "戸建"),
    ("アパート", "一棟アパート"),
    ("マンション", "マンション"),
    ("土地", "土地"),
    ("ビル", "一棟ビル"),
    ("店舗", "店舗"),
    ("事務所", "事務所"),
    ("倉庫", "倉庫"),
    ("ホテル", "ホテル"),
)

# Signals that the text is a property listing at all.
_PROPERTY_SIGNALS = ("利回り", "万円", "億円", "物件", "売", "投資", "区分", "一棟", "土地", "築")

_YIELD_RE = re.compile(r"(?:表面)?利回り[:：\s]*([0-9]+(?:\.[0-9]+)?)\s*[%％]")
_YIELD_FALLBACK_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*[%％]")
_STATION_RE = re.compile(r"([^\s、。/]+?(?:駅|停))\s*(?:徒歩|歩)?\s*([0-9]+)\s*分")
_YEAR_BUILT_RE = re.compile(r"築\s*([0-9]+)\s*年|((?:19|20)[0-9]{2})\s*年\s*築|(新築)")
_AREA_RE = re.compile(r"(土地|建物|専有)[^0-9]{0,4}([0-9]+(?:\.[0-9]+)?)\s*(?:㎡|平米|m2|m²)")
# Price: an 億 part and/or a 万 part; a trailing 円 is optional ("4500万" counts).
# At least one of the two unit groups must be present (enforced in parse_price_yen).
_PRICE_RE = re.compile(
    r"(?:([0-9]+(?:\.[0-9]+)?)\s*億)?\s*(?:([0-9][0-9,]*(?:\.[0-9]+)?)\s*万)?\s*円?"
)


@dataclass(frozen=True)
class ExtractedProperty:
    price_yen: int | None = None
    yield_pct: float | None = None
    prefecture: str | None = None
    location: str | None = None
    property_type: str | None = None
    station_access: str | None = None
    year_built: str | None = None
    areas: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "price_yen": self.price_yen,
            "yield_pct": self.yield_pct,
            "prefecture": self.prefecture,
            "location": self.location,
            "property_type": self.property_type,
            "station_access": self.station_access,
            "year_built": self.year_built,
            "areas": dict(self.areas),
        }


def parse_price_yen(text: str) -> int | None:
    """Parse the first plausible price expression to an integer yen value.

    Handles "1億2000万円", "1億円", "3,980万円", "3980万". Returns None if no
    price-like token with a 億/万 unit is present.
    """
    for m in _PRICE_RE.finditer(text):
        oku, man = m.group(1), m.group(2)
        if not oku and not man:
            continue
        total = 0.0
        if oku:
            total += float(oku) * 100_000_000
        if man:
            total += float(man.replace(",", "")) * 10_000
        if total > 0:
            return int(total)
    return None


def parse_yield_pct(text: str) -> float | None:
    m = _YIELD_RE.search(text)
    if m:
        return float(m.group(1))
    # Fallback: a lone percentage near a yield-ish context is risky, so only use
    # it when the text mentions 利回り somewhere.
    if "利回" in text:
        m2 = _YIELD_FALLBACK_RE.search(text)
        if m2:
            return float(m2.group(1))
    return None


def parse_location(text: str) -> tuple[str | None, str | None]:
    """Return (prefecture, location-string). Location includes the city/ward
    following the prefecture when present."""
    for pref in _PREFECTURES:
        idx = text.find(pref)
        if idx == -1:
            continue
        tail = text[idx + len(pref): idx + len(pref) + 20]
        m = re.match(r"([^\s、。\n/]{0,12}?[市区町村郡])", tail)
        city = m.group(1) if m else ""
        return pref, f"{pref}{city}"
    return None, None


def parse_property_type(text: str) -> str | None:
    for keyword, label in _TYPE_KEYWORDS:
        if keyword in text:
            return label
    return None


def parse_station(text: str) -> str | None:
    m = _STATION_RE.search(text)
    if m:
        return f"{m.group(1)} 徒歩{m.group(2)}分"
    return None


def parse_year_built(text: str) -> str | None:
    m = _YEAR_BUILT_RE.search(text)
    if not m:
        return None
    if m.group(3):
        return "新築"
    if m.group(1):
        return f"築{m.group(1)}年"
    if m.group(2):
        return f"{m.group(2)}年築"
    return None


def parse_areas(text: str) -> dict[str, float]:
    areas: dict[str, float] = {}
    for kind, value in _AREA_RE.findall(text):
        try:
            areas.setdefault(kind, float(value))
        except ValueError:
            continue
    return areas


def looks_like_property(text: str) -> bool:
    """A cheap gate: does this post look like a property listing at all?"""
    hits = sum(1 for s in _PROPERTY_SIGNALS if s in text)
    return hits >= 2


def extract_property(text: str) -> ExtractedProperty | None:
    """Extract a property from post text, or None if it is not a listing.

    Requires at least a price OR a yield to be considered a real listing — a post
    that only says "物件募集中" with no numbers is not stored.
    """
    if not text or not looks_like_property(text):
        return None
    price = parse_price_yen(text)
    yield_pct = parse_yield_pct(text)
    if price is None and yield_pct is None:
        return None
    pref, location = parse_location(text)
    return ExtractedProperty(
        price_yen=price,
        yield_pct=yield_pct,
        prefecture=pref,
        location=location,
        property_type=parse_property_type(text),
        station_access=parse_station(text),
        year_built=parse_year_built(text),
        areas=parse_areas(text),
    )

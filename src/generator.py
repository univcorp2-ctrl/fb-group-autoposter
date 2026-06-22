from __future__ import annotations

import hashlib
import json
import logging
import random
import re
from dataclasses import dataclass
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from src.group_rules import apply_group_rules

log = logging.getLogger(__name__)


@dataclass
class GeneratedBatch:
    variants: list[dict[str, Any]]
    degraded: bool


def _stable_seed(property_id: str, group_id: str) -> int:
    digest = hashlib.sha256(f"{property_id}:{group_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


_HASHTAG_TYPE_BASES = {
    "一棟マンション", "一棟アパート", "一棟ビル", "区分マンション",
    "戸建", "商業施設", "ホテル", "土地", "倉庫・工場", "医療・介護施設",
}
_AREA_RE = re.compile(r"(東京都|北海道|京都府|大阪府|.{2,3}?県)(.+?[市区町村])")


def build_hashtags(property_data: dict[str, Any]) -> list[str]:
    """Derive a small set of relevant hashtags from a property dict."""
    tags = ["#不動産投資", "#収益物件", "#投資用不動産"]
    for highlight in property_data.get("highlights") or []:
        base = str(highlight).split("（")[0]
        if base in _HASHTAG_TYPE_BASES:
            tags.append("#" + base)
    match = _AREA_RE.search(str(property_data.get("location", "")))
    if match:
        tags.append("#" + match.group(1))
        tags.append("#" + match.group(2))
    seen: set[str] = set()
    ordered: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            ordered.append(tag)
    return ordered[:6]


_FORBIDDEN_PITCH_WORDS = ("保証", "絶対", "確実")
PITCH_PREFIX = "🔑 推しポイント："
_WALK_RE = re.compile(r"徒歩\s*(\d+)\s*分")


def _parse_yield(value: Any) -> float | None:
    """Parse a yield like '8.5%' or 8.5 into a float, or None."""
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def build_pitch(property_data: dict[str, Any]) -> str:
    """A short, factual one-line buyer-merit (推しポイント). No fabrication.

    Collects up to 3 merits from available fields (yield, 駅徒歩, structure,
    所有権/分かれ, area), prefixes 🔑 推しポイント：, and ends with a soft
    benefit phrase. Never uses forbidden words; kept to ~60 chars.
    """
    merits: list[str] = []

    y = _parse_yield(property_data.get("yield_pct"))
    if y is not None and y > 0:
        merits.append(f"高利回り{y:g}%" if y >= 8 else f"利回り{y:g}%")

    access = str(property_data.get("access", "") or "")
    walk = _WALK_RE.search(access)
    highlights = [str(h) for h in (property_data.get("highlights") or [])]
    if walk:
        merits.append(f"駅徒歩{walk.group(1)}分")
    elif "駅近" in highlights or "駅近" in access:
        merits.append("駅近")

    structure = str(property_data.get("structure", "") or "")
    if "SRC造" in structure or "SRC造" in highlights:
        merits.append("SRC造で資産性◎")
    elif "RC造" in structure or "RC造" in highlights:
        merits.append("RC造で資産性◎")

    if "所有権" in highlights:
        merits.append("所有権")
    if "分かれ" in highlights:
        merits.append("分かれ")

    location = str(property_data.get("location", "") or "")
    if not merits and location:
        merits.append(f"{location[:8]}エリア")

    selected = merits[:3]
    benefit = "長期保有・利回り重視の方に。"
    core = "／".join(selected) if selected else "投資検討に好適"
    pitch = f"{PITCH_PREFIX}{core}　{benefit}"
    # Defensive: never emit a forbidden word even if a field smuggled one in.
    for word in _FORBIDDEN_PITCH_WORDS:
        pitch = pitch.replace(word, "")
    return pitch


def fallback_body(property_data: dict[str, Any], group: dict[str, Any], *, revision_instruction: str = "") -> str:
    property_id = property_data.get("property_id", "unknown")
    rng = random.Random(_stable_seed(property_id, group["id"]))
    openings = [
        "収益物件のご紹介です。",
        "物件情報を共有します。",
        "不動産投資向けの案件です。",
        "以下、物件概要です。",
    ]
    if "カジュアル" in str(group.get("tone", "")):
        openings += ["気になる物件が出ました。", "投資用物件の共有です😊"]
    highlights = property_data.get("highlights") or []
    lines = [
        rng.choice(openings),
        "",
        f"🏢 {property_data.get('title', '記載なし')}",
        f"💰 価格：{property_data.get('price', '記載なし')}",
        f"📈 利回り：{property_data.get('yield_pct', '記載なし')}",
        f"📍 所在地：{property_data.get('location', '記載なし')}",
        f"🚃 交通：{property_data.get('access', '記載なし')}",
        f"🏗 構造：{property_data.get('structure', '記載なし')}",
        f"📐 土地：{property_data.get('land_area', '記載なし')}／建物：{property_data.get('building_area', '記載なし')}",
        f"🗓 築年：{property_data.get('year_built', '記載なし')}",
    ]
    # 推しポイント (mandatory buyer-merit). Placed near the top so the group
    # rules' max_chars truncation never cuts it (it sits well before the
    # contact/hashtags block that may be trimmed on long bodies).
    lines += ["", build_pitch(property_data)]
    if highlights:
        bullet = " / ".join(str(x) for x in highlights)
        lines += ["", f"✨ {bullet}"]
    contact = str(group.get("contact", "") or "").strip()
    if contact:
        lines += ["", contact]
    hashtags = build_hashtags(property_data)
    if hashtags:
        lines += ["", " ".join(hashtags)]
    if property_data.get("url") and group.get("allow_links", True):
        lines += ["", f"詳細：{property_data['url']}"]
    if revision_instruction:
        lines += ["", f"修正反映メモ：{revision_instruction}"]
    return apply_group_rules("\n".join(lines), group).body


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def _call_claude(settings: Any, property_data: dict[str, Any], group: dict[str, Any], revision_instruction: str = "") -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    pitch = build_pitch(property_data)
    prompt = f"""
あなたは不動産Facebookグループ向け投稿文面を作る編集者です。
以下の物件情報を、指定グループ向けの投稿本文にしてください。

厳守:
- 価格、利回り、面積、所在地、物件名などの数値・固有名詞は絶対に改変しない。
- 誇大表現は禁止。禁止語は使わない。
- group.allow_links=false の場合はURLを入れない。
- max_chars以内。
- 本文の上部に「{PITCH_PREFIX}…」で始まる短い推しポイントの行をちょうど1行入れる
  （事実ベース・誇張なし）。下記 pitch をそのまま使ってよい。
- 返答は本文のみ。前置き不要。

pitch:
{pitch}

property_data:
{json.dumps(property_data, ensure_ascii=False, indent=2)}

group:
{json.dumps(group, ensure_ascii=False, indent=2)}

revision_instruction:
{revision_instruction}
"""
    resp = client.messages.create(
        model=settings.claude_model,
        max_tokens=1600,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    chunks = []
    for item in resp.content:
        text = getattr(item, "text", "")
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _inject_pitch(body: str, pitch: str) -> str:
    """Insert the pitch line near the top of the body (after the price line if
    found, else after the first line) so truncation never removes it."""
    lines = body.split("\n")
    anchor = 0
    for i, line in enumerate(lines):
        if "価格" in line or "💰" in line:
            anchor = i + 1
            break
    else:
        anchor = 1 if lines else 0
    lines[anchor:anchor] = ["", pitch]
    return "\n".join(lines)


def generate_variants(
    property_data: dict[str, Any],
    groups: list[dict[str, Any]],
    settings: Any,
    *,
    revision_instruction: str = "",
) -> GeneratedBatch:
    variants: list[dict[str, Any]] = []
    degraded = False
    for group in groups:
        body = ""
        if getattr(settings, "anthropic_api_key", ""):
            try:
                body = _call_claude(settings, property_data, group, revision_instruction)
            except Exception as exc:
                log.warning("claude generation failed for group %s: %s", group.get("id"), exc)
                degraded = True
        else:
            degraded = True
        if not body:
            body = fallback_body(property_data, group, revision_instruction=revision_instruction)
        body = apply_group_rules(body, group).body
        # Guarantee the 推しポイント line is present regardless of Claude/fallback.
        # Inject it near the top (before any contact/hashtags block) so the
        # group rules' max_chars truncation never cuts it, then re-apply rules.
        if "推しポイント" not in body:
            body = _inject_pitch(body, build_pitch(property_data))
            body = apply_group_rules(body, group).body
        seed = _stable_seed(property_data.get("property_id", "unknown"), group["id"])
        variants.append(
            {
                "group_id": group["id"],
                "body": body,
                "images": property_data.get("images", []),
                "char_count": len(body),
                "variation_seed": seed,
            }
        )
    return GeneratedBatch(variants=variants, degraded=degraded)

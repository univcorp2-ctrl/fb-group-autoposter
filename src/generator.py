from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from src.group_rules import apply_group_rules


@dataclass
class GeneratedBatch:
    variants: list[dict[str, Any]]
    degraded: bool


def _stable_seed(property_id: str, group_id: str) -> int:
    digest = hashlib.sha256(f"{property_id}:{group_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


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
        f"物件名：{property_data.get('title', '記載なし')}",
        f"価格：{property_data.get('price', '記載なし')}",
        f"利回り：{property_data.get('yield_pct', '記載なし')}",
        f"所在地：{property_data.get('location', '記載なし')}",
        f"交通：{property_data.get('access', '記載なし')}",
        f"構造：{property_data.get('structure', '記載なし')}",
        f"土地面積：{property_data.get('land_area', '記載なし')}",
        f"建物面積：{property_data.get('building_area', '記載なし')}",
        f"築年：{property_data.get('year_built', '記載なし')}",
    ]
    if highlights:
        bullet = " / ".join(str(x) for x in highlights)
        lines += ["", f"ポイント：{bullet}"]
    if property_data.get("url"):
        lines += ["", f"詳細：{property_data['url']}"]
    if revision_instruction:
        lines += ["", f"修正反映メモ：{revision_instruction}"]
    return apply_group_rules("\n".join(lines), group)


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def _call_claude(settings: Any, property_data: dict[str, Any], group: dict[str, Any], revision_instruction: str = "") -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    prompt = f"""
あなたは不動産Facebookグループ向け投稿文面を作る編集者です。
以下の物件情報を、指定グループ向けの投稿本文にしてください。

厳守:
- 価格、利回り、面積、所在地、物件名などの数値・固有名詞は絶対に改変しない。
- 誇大表現は禁止。禁止語は使わない。
- group.allow_links=false の場合はURLを入れない。
- max_chars以内。
- 返答は本文のみ。前置き不要。

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
            except Exception:
                degraded = True
        else:
            degraded = True
        if not body:
            body = fallback_body(property_data, group, revision_instruction=revision_instruction)
        body = apply_group_rules(body, group)
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

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ClickAt:
    x: float
    y: float
    reason: str = ""


async def heal_locate(page: Any, intent: str, settings: Any) -> ClickAt | None:
    if not getattr(settings, "anthropic_api_key", ""):
        return None
    shot = await page.screenshot(full_page=False)
    prompt = f"""このFacebookグループページのスクリーンショットでUI要素を特定してください。
目的の要素: {intent}
返答は厳密にJSONのみ: {{"found": true/false, "bbox": [x,y,w,h], "reason": "..."}}
要素が無ければ found:false。前置き・マークダウン禁止。"""
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.claude_vision_model,
            max_tokens=400,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.b64encode(shot).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = "".join(getattr(item, "text", "") for item in resp.content)
        data = json.loads(text)
        if data.get("found") and isinstance(data.get("bbox"), list) and len(data["bbox"]) == 4:
            x, y, w, h = data["bbox"]
            return ClickAt(x + w / 2, y + h / 2, data.get("reason", ""))
    except Exception as exc:
        log.warning("vision heal failed: %s", exc)
    return None

"""Optional OpenAI Codex CLI provider for Facebook post copy.

Codex is only used for text generation. Playwright remains responsible for the
logged-in browser session. Any CLI error falls back to the repository's
fact-preserving deterministic generator so posting is not blocked.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.generator import (
    INVEST_PREFIX,
    GeneratedBatch,
    _inject_pitch,
    _stable_seed,
    build_investment_pitch,
    build_pitch,
    fallback_body,
)
from src.group_rules import apply_group_rules

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


def build_codex_prompt(
    property_data: dict[str, Any], group: dict[str, Any], revision_instruction: str = ""
) -> str:
    return f"""不動産Facebookグループ向け投稿本文だけを日本語で出力してください。
事実・数値・固有名詞を改変しない。誇大表現、保証、絶対、確実は禁止。
グループ規則を守り、URL禁止ならURLを含めない。前置きやMarkdownコードフェンスは不要。
推しポイント行と投資シミュレーションは入力内容を維持してください。

property_data:
{json.dumps(property_data, ensure_ascii=False, indent=2)}

group:
{json.dumps(group, ensure_ascii=False, indent=2)}

revision_instruction:
{revision_instruction}
"""


def _call_codex(prompt: str, timeout_seconds: int = 120) -> str:
    executable = shutil.which(os.getenv("CODEX_CLI", "codex"))
    if not executable:
        raise FileNotFoundError("Codex CLI was not found on PATH")
    output_path = Path(tempfile.mkstemp(prefix="fb-codex-", suffix=".txt")[1])
    try:
        command = [
            executable,
            "exec",
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
            "-",
        ]
        subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=ROOT,
            timeout=timeout_seconds,
            check=True,
        )
        return output_path.read_text(encoding="utf-8").strip()
    finally:
        output_path.unlink(missing_ok=True)


def generate_variants_with_codex(
    property_data: dict[str, Any],
    groups: list[dict[str, Any]],
    settings: Any,
    *,
    revision_instruction: str = "",
) -> GeneratedBatch:
    variants: list[dict[str, Any]] = []
    degraded = False
    timeout = int(os.getenv("CODEX_TIMEOUT_SECONDS", "120"))
    for group in groups:
        body = ""
        try:
            body = _call_codex(build_codex_prompt(property_data, group, revision_instruction), timeout)
<<<<<<< HEAD
        except Exception as exc:
=======
        except Exception as exc:  # noqa: BLE001 - fallback is deliberate
>>>>>>> origin/main
            log.warning("Codex generation failed for group %s: %s", group.get("id"), exc)
            degraded = True
        if not body:
            body = fallback_body(property_data, group, revision_instruction=revision_instruction)
        body = apply_group_rules(body, group).body
        if "推しポイント" not in body:
            body = _inject_pitch(body, build_pitch(property_data))
            body = apply_group_rules(body, group).body
        invest = build_investment_pitch(property_data)
        if invest and INVEST_PREFIX not in body:
            body = apply_group_rules(f"{body.rstrip()}\n\n{invest}", group).body
        variants.append(
            {
                "group_id": group["id"],
                "body": body,
                "images": property_data.get("images", []),
                "char_count": len(body),
                "variation_seed": _stable_seed(
                    property_data.get("property_id", "unknown"), group["id"]
                ),
            }
        )
    return GeneratedBatch(variants=variants, degraded=degraded)

"""Generate a polite Japanese reply draft for an inbound 1:1 Messenger message.

Two layers:
  - build_template_draft(): deterministic, no network. Always available.
  - build_draft(): tries Claude (if ANTHROPIC_API_KEY) for a tailored reply, then
    falls back to the template. Claude is best-effort — any failure degrades to
    the template, never crashes.

A draft is a SUGGESTION saved for human review. It is never auto-sent.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_DISCLAIMER = "（※この返信は下書きです。送信前に内容をご確認ください）"


def _first_name(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return "お問い合わせ"
    # Use the family-name-ish leading token for a natural 〇〇さん.
    return n.split()[0].split("　")[0]


def build_template_draft(name: str, last_message: str, *, line_url: str = "", community_url: str = "") -> str:
    """Deterministic, safe fallback draft. No external calls."""
    greeting = f"{_first_name(name)}さん、はじめまして。お問い合わせありがとうございます。"
    body = (
        "ご連絡いただいた件、よろしければもう少し詳しくお伺いできればと思います。"
        "ご希望のエリアや予算感、投資/居住などの目的を教えていただけますか？"
    )
    links: list[str] = []
    if line_url:
        links.append(f"・公式LINE（こちらが一番スムーズです）→ {line_url}")
    if community_url:
        links.append(f"・コミュニティ → {community_url}")
    parts = [greeting, "", body]
    if links:
        parts += ["", "詳しいご案内は下記からもどうぞ：", *links]
    return "\n".join(parts).strip()


def _build_claude_prompt(name: str, last_message: str, line_url: str, community_url: str) -> str:
    return (
        "あなたは不動産仲介の丁寧な担当者です。"
        "Facebook Messenger に届いた1対1のお問い合わせに対する、"
        "自然で礼儀正しい日本語の返信文の下書きを作ってください。\n"
        "条件:\n"
        "- 200文字程度、敬語、押し付けがましくない\n"
        "- 相手の質問に具体的に触れつつ、ヒアリング(エリア/予算/目的)を1つ促す\n"
        f"- 末尾に案内: 公式LINE {line_url} とコミュニティ {community_url}（URLがある場合のみ）\n"
        "- 会社名や個人情報は書かない\n\n"
        f"相手の表示名: {name}\n"
        f"相手の最新メッセージ: {last_message}\n\n"
        "返信下書きのみを出力してください。"
    )


def _claude_draft(
    name: str, last_message: str, line_url: str, community_url: str, api_key: str, model: str
) -> str | None:
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": _build_claude_prompt(name, last_message, line_url, community_url)}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 - degrade to template, never crash
        log.warning("claude draft failed, using template: %s: %s", type(exc).__name__, exc)
        return None


def build_draft(
    name: str,
    last_message: str,
    *,
    line_url: str = "",
    community_url: str = "",
    api_key: str = "",
    model: str = "claude-sonnet-4-6",
) -> str:
    """Best reply draft available: Claude if configured, else the template.

    The returned text always ends with a draft disclaimer so it is never mistaken
    for an auto-sent message.
    """
    draft: str | None = None
    if api_key:
        draft = _claude_draft(name, last_message, line_url, community_url, api_key, model)
    if not draft:
        draft = build_template_draft(name, last_message, line_url=line_url, community_url=community_url)
    return f"{draft}\n\n{_DISCLAIMER}"

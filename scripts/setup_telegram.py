"""One-shot Telegram wiring: discover chat_id, write .env, send a test message.

Why this exists: notifications (post success/failure, session-recovery alerts,
new-group discovery) only fire when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are
set. The token is a secret that must come from @BotFather — it cannot be
generated here — but everything else is automated.

Operator steps:
  1. In Telegram, message @BotFather -> /newbot -> copy the bot token.
  2. Open your new bot and send it any message (e.g. "hi"). This is what lets
     us auto-discover your chat_id.
  3. Run:  python scripts/setup_telegram.py <BOT_TOKEN>
     (or set TELEGRAM_BOT_TOKEN in the environment and run with no argument)

The script calls getUpdates to find the chat_id of the most recent message,
writes both values into .env (preserving every other line), and sends a
confirming test message so you immediately see it works.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def discover_chat_id(token: str) -> str | None:
    """Return the chat_id of the most recent update, or None if none found."""
    resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
    resp.raise_for_status()
    results = resp.json().get("result", [])
    for update in reversed(results):  # newest first
        for key in ("message", "edited_message", "channel_post", "my_chat_member"):
            obj = update.get(key)
            if obj and obj.get("chat", {}).get("id") is not None:
                return str(obj["chat"]["id"])
        cb = update.get("callback_query")
        if cb and cb.get("message", {}).get("chat", {}).get("id") is not None:
            return str(cb["message"]["chat"]["id"])
    return None


def upsert_env(path: Path, values: dict[str, str]) -> None:
    """Set each KEY=value in the .env, preserving all other lines/ordering."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    for key, val in remaining.items():
        out.append(f"{key}={val}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def send_test(token: str, chat_id: str) -> bool:
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": "✅ FB自動投稿ボットのTelegram通知を設定しました。\n"
            "今後は投稿の成否・セッション切れ・新規グループ候補をここに通知します。",
        },
        timeout=20,
    )
    return resp.ok


def main() -> int:
    token = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        print("ERROR: bot token required. Usage: python scripts/setup_telegram.py <BOT_TOKEN>")
        print("Get one from @BotFather (/newbot), then message your bot once before running.")
        return 2

    try:
        chat_id = discover_chat_id(token)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        print(f"ERROR: Telegram rejected the token (HTTP {code}). Double-check the token from @BotFather.")
        return 1
    except requests.RequestException as exc:
        print(f"ERROR: could not reach Telegram: {type(exc).__name__}")
        return 1

    if not chat_id:
        print("No chat_id found. Open your bot in Telegram, send it any message, then re-run this.")
        return 1

    upsert_env(ENV_PATH, {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id})
    print(f"Wrote TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (chat_id={chat_id}) to {ENV_PATH}")

    if send_test(token, chat_id):
        print("Sent a test message — check your Telegram. Setup complete.")
        return 0
    print("Saved config, but the test message failed to send. Verify the bot is not blocked.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

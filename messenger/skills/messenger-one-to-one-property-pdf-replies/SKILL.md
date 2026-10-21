---
name: messenger-one-to-one-property-pdf-replies
description: Silent autonomous Messenger replies only to new verified one-to-one property PDF requests; never groups or UI popups.
---

# Messenger 1対1の物件資料自動返信スキル

## 正本と稼働
- Repository: `fb-group-autoposter/messenger`; keep GitHub and Google Drive as permanent sources, Windows C: only a runtime worktree.
- `FBAutoposter-MessengerDrafts` uses **hidden pythonw.exe**, polls every **1 minute** after each run. `FBAutoposter-MessengerWatchdog` uses **hidden pythonw.exe** every 5 minutes to restart only a stopped Ready task.
- Keep authenticated Chrome Default profile `C:\AI-Agent\chrome-profile-authenticated` attached via CDP to **background target**; never raise the user interface or open a foreground tab.
- LINE jobs remain windowless `wscript.exe //B //Nologo`.

## Mandatory safety barriers
1. **NEVER send to a group.** Inbox `is_group is False`, `one_to_one_verified is True`, `participant_count == 1` as an integer, and exact recipient/thread ID; independently verify the *opened thread's* accessibility header using `src/direct_thread_guard.py`. Ambiguity means no send.
2. Only **new one-to-one requests for property materials**: 資料/図面/概要書/レントロール/PDF/パンフ/物件概要. No general greetings/marketing.
3. Never send historical messages or replay ambiguous outcomes: store the baseline hashed inbox previews and durable per-message send ledger.
4. Low-cost drafts are never enough: require high-end reviewer approval tied to the exact inbound text and real conversation history.
5. Match EstateBoard property ID, explicitly approved Drive PDF file ID and SHA-256, verify immediately before send; never attach arbitrary PDFs.
6. Never overwrite a human's unsent text. Mark **sent** only on actual Messenger evidence for text **and PDF**, not task status or passing tests.
7. Never start visible Chrome, PowerShell, or a new user-facing tab. No ChatGPT-scheduled tasks, CLI agent mode changes, or paid API fallback without approval.

## Verification and operations
`python -m pytest messenger/tests -q`; inspect `messenger/data/draft_daemon_status.json`, `messenger/data/auto_reply_status.json`, private Drive `messenger_watchdog_status.json`. Inspect Task Scheduler `FBAutoposter-MessengerDrafts`, `FBAutoposter-MessengerWatchdog`, `FBAutoposter-MessengerChrome` (Hidden=true). Avoid stopping a worker mid-send. If the review provider hits a quota, leave the message pending; do not bypass quality review.

Acceptance: new verified 1:1 PDF request → background inbox read → matching EstateBoard property → verified Drive PDF → cheap draft → senior review → exact-recipient/group guard → one send with PDF → Messenger text+attachment proof → durable status/Drive sync. Never claim completion without a verified new delivered example.

Save all work and redacted diagnostics in GitHub + Drive; do not publish .env, private message content, or PDFs. Any unresolved obstacle gets a copy-ready, reproducible handoff report.

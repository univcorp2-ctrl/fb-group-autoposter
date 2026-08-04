# Messenger Automatic Composer Draft Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Place safe reply drafts into eligible Facebook Messenger 1:1 composers automatically while making programmatic sending impossible and preserving every uncertain or human-authored state for review.

**Architecture:** A read-only deterministic scanner produces an inbound-message fingerprint. A durable SQLite state machine records intent before any composer mutation, a local gateway produces a bounded draft, and a dedicated no-send writer performs exact pre/write/post checks. Telegram and local audit delivery use an independent outbox. Two default-off gates plus account trust authorization protect the live writer.

**Tech Stack:** Python 3.11, Playwright, SQLite, JSON, pytest, Ruff, hidden Windows Task Scheduler.

---

**Spec:** `docs/superpowers/specs/2026-08-03-facebook-posting-messenger-recovery-design.md`

**Prerequisites:** Complete posting recovery Tasks 1-4 and Telegram recovery Tasks 1-6.
Do not enable a live Messenger writer while Facebook reports an unfamiliar device or
until account trust has been explicitly authorized in a familiar browser.

## Existing code preserved

Keep `messenger/src/drafter.py` template wording and Anthropic fallback behavior until the
gateway task replaces only the provider boundary. Keep the existing session/profile and
human typing delay. Replace the JSON fingerprint store additively: import it once into
SQLite, retain the JSON files as read-only migration evidence, and never overwrite a
non-empty human composer.

## File map

- Create `messenger/src/models.py`: strict inbox, classification, draft, intent, and run-result models.
- Create `messenger/src/state_db.py`: additive SQLite state, migrations, leases, and recovery states.
- Modify `messenger/src/store.py`: legacy JSON import adapter only.
- Modify `messenger/src/scraper.py`: deterministic 1:1 thread/message snapshot.
- Modify `messenger/src/classifier.py`: high-confidence eligibility and stable exclusions.
- Create `messenger/src/ai_gateway.py`: shared Phase 1 gateway adapter for Messenger drafting.
- Modify `messenger/src/drafter.py`: gateway call plus deterministic validation/fallback.
- Replace `messenger/src/fb_draft_writer.py`: guarded no-send composer placement state machine.
- Create `messenger/src/outbox.py`: downstream audit/Telegram delivery events.
- Modify `messenger/src/notifier.py`: Telegram destination handler only.
- Rewrite `messenger/scripts/run_once.py`: operational orchestration and terminal result.
- Create `messenger/scripts/authorize_account_trust.py`: local explicit trust authorization/revocation.
- Create `messenger/scripts/reconcile_delivery.py`: downstream-only worker.
- Create `messenger/scripts/launch_hidden.ps1` and `.vbs` only if the repository-level launcher cannot safely dispatch Messenger commands; prefer reuse.
- Modify `scripts/install_windows_tasks.ps1`, `messenger/.env.example`, `messenger/README_ja.md`, `README.md`, and `README_ja.md`.
- Add focused tests under `messenger/tests/` and repository launcher contract tests.

### Task 1: Define strict Messenger models and terminal outcomes

**Files:**
- Create: `messenger/src/models.py`
- Create: `messenger/src/run_result.py`
- Create: `messenger/tests/test_models.py`
- Create: `messenger/tests/test_run_result.py`

- [ ] **Step 1: Write failing strict-model tests**

Define and test versioned models for thread snapshot, inbound message, classification,
draft generation, placement intent, placement evidence, and terminal result. Reject
unknown fields, invalid URLs, and missing stable thread/message identity. Snapshot models
must retain group/room, blank-text, and attachment evidence so the classifier can persist
their exact exclusion reasons; those observations are rejected only as placement intents.

- [ ] **Step 2: Write failing exit-contract tests**

Use outcomes and exits:

| Exit | Outcome | Examples |
| ---: | --- | --- |
| 0 | `completed` | scan completed and every eligible draft reached a durable terminal state |
| 0 | `no_action` | no eligible inbound text |
| 20 | `preflight_blocked` | gates off, trust absent, login needed, recovery-required no-write |
| 30 | `risk_stopped` | checkpoint, CAPTCHA, unfamiliar device, unknown DOM, or other account risk |
| 40 | `placement_ambiguous` | interruption after `write_started` or unverifiable composer mutation |
| 50 | `delivery_pending` | composer truth is durable but Telegram delivery is pending or ambiguous |
| 60 | `internal_error` | unexpected internal failure |

Assert atomic `latest.json` plus immutable run history, token redaction, and no message
content in terminal summaries.

- [ ] **Step 3: Verify failures**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_models.py messenger/tests/test_run_result.py -v
```

- [ ] **Step 4: Implement and pass tests**

Use immutable dataclasses or equivalent strict parsers. Put sanitized evidence references,
hashes, and counts in results; keep full draft text only in the private durable store.

- [ ] **Step 5: Commit**

```powershell
git add messenger/src/models.py messenger/src/run_result.py messenger/tests/test_models.py messenger/tests/test_run_result.py
git commit -m "feat: define Messenger recovery contracts"
```

### Task 2: Add the durable intent and recovery state machine

**Files:**
- Create: `messenger/src/state_db.py`
- Modify: `messenger/src/store.py`
- Create: `messenger/tests/test_state_db.py`
- Create: `messenger/tests/test_legacy_state_import.py`

- [ ] **Step 1: Write failing schema and transition tests**

Create a unique key on `(thread_id, inbound_message_fingerprint)`. Cover migration,
idempotent import, concurrent lease denial, lease expiry before write, and allowed states:

```text
observed -> classified -> drafted -> intent_recorded -> write_started
write_started -> placed_not_sent | placement_ambiguous
intent_recorded on interrupted recovery -> recovery_required_no_write
```

Terminal exclusions include `existing_composer_draft`, `group_or_room`,
`attachment_or_photo`, `acknowledgement_only`, `low_confidence`, `identity_or_contract`,
`payment`, `pii`, `login_required`, `account_trust_blocked`, and `challenge_detected`.
No automatic transition leaves `placement_ambiguous` or `recovery_required_no_write`.

- [ ] **Step 2: Verify failures**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_state_db.py messenger/tests/test_legacy_state_import.py -v
```

- [ ] **Step 3: Implement additive SQLite storage**

Store private message/draft text separately from run summaries. Each transition is an
atomic compare-and-set with timestamps, run ID, lease owner, reason, and hashes. On first
startup import `threads_state.json` and `drafts_archive.jsonl` without modifying them;
write an import marker and source hashes.

- [ ] **Step 4: Pass tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_state_db.py messenger/tests/test_legacy_state_import.py -v
git add messenger/src/state_db.py messenger/src/store.py messenger/tests/test_state_db.py messenger/tests/test_legacy_state_import.py
git commit -m "feat: persist Messenger placement intents"
```

### Task 3: Make inbox scanning and eligibility deterministic

**Files:**
- Modify: `messenger/src/scraper.py`
- Modify: `messenger/src/classifier.py`
- Create: `messenger/tests/fixtures/inbox_one_to_one.html`
- Create: `messenger/tests/fixtures/inbox_group_and_room.html`
- Create: `messenger/tests/fixtures/thread_text_and_attachment.html`
- Modify: `messenger/tests/test_scraper.py`
- Modify: `messenger/tests/test_classifier.py`
- Create: `messenger/tests/test_inbound_fingerprint.py`

- [ ] **Step 1: Write failing deterministic snapshot tests**

Require stable thread ID from the canonical Messenger URL and stable inbound message ID
when exposed by the DOM. If no message ID exists, fingerprint normalized sender role,
timestamp marker, exact text hash, and nearest stable DOM identity. A changing inbox
preview alone is not sufficient proof of a new inbound message.

- [ ] **Step 2: Write failing exclusion tests**

Test 1:1 versus group/room using multiple independent signals, self-sent last messages,
unread but acknowledgement-only text, photos/files/stickers/voice/call events, empty or
truncated text, ambiguous sender direction, login/checkpoint pages, and risky topics.
Only high-confidence 1:1 plain inbound text can be `eligible`. The classifier requires
affirmative 1:1 evidence; merely finding zero group indicators produces `low_confidence`.

- [ ] **Step 3: Verify failures**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_scraper.py messenger/tests/test_classifier.py messenger/tests/test_inbound_fingerprint.py -v
```

- [ ] **Step 4: Implement bounded deterministic scanning**

Enumerate a fixed maximum of visible inbox rows, open candidates sequentially, and capture
only the bounded recent message window needed to establish direction and type. Zero or
conflicting group signals produce `low_confidence`, not eligible. Preserve the existing
human dwell and single persistent browser session.

- [ ] **Step 5: Pass tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_scraper.py messenger/tests/test_classifier.py messenger/tests/test_inbound_fingerprint.py -v
git add messenger/src/scraper.py messenger/src/classifier.py messenger/tests/fixtures messenger/tests/test_scraper.py messenger/tests/test_classifier.py messenger/tests/test_inbound_fingerprint.py
git commit -m "fix: classify Messenger conversations deterministically"
```

### Task 4: Route draft generation through the Phase 1 AI gateway

**Files:**
- Create: `messenger/src/ai_gateway.py`
- Modify: `messenger/src/drafter.py`
- Modify: `messenger/config.py`
- Modify: `messenger/.env.example`
- Create: `messenger/tests/test_ai_gateway.py`
- Modify: `messenger/tests/test_drafter.py`

- [ ] **Step 1: Write failing provider-contract tests**

Support the deterministic template, the existing Anthropic API path, one
OpenAI-compatible HTTP profile, and one allowlisted JSON CLI runner capable of selecting
`claude`, `codex`, or `gemini`. Test strict JSON schema, hard timeout, output cap,
`shell=False`, `CREATE_NO_WINDOW`, allowlisted executable/arguments/environment, isolated
working directory, token redaction, and template fallback/stop. GLM and a local LLM use
the OpenAI-compatible profile. Provider-native adapters are Phase 2.

- [ ] **Step 2: Write failing draft-safety tests**

The model receives the minimum private text required for the selected provider profile.
Validate maximum length, no fabricated property facts, no promises, no payment/identity
instructions, no request for sensitive data, and mandatory human-review disclaimer.
Validation failure falls back to the conservative template or stops before intent.

- [ ] **Step 3: Verify failures**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_ai_gateway.py messenger/tests/test_drafter.py -v
```

- [ ] **Step 4: Implement one gateway boundary**

Reuse repository `src/ai_gateway` primitives when their import boundary is stable; keep a
thin Messenger adapter rather than duplicating subprocess or profile validation. AI may
return draft text only. It receives no page, locator, cookie, action, or Facebook control.

- [ ] **Step 5: Pass tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_ai_gateway.py messenger/tests/test_drafter.py tests/ai_gateway -v
git add messenger/src/ai_gateway.py messenger/src/drafter.py messenger/config.py messenger/.env.example messenger/tests/test_ai_gateway.py messenger/tests/test_drafter.py
git commit -m "feat: switch Messenger drafting providers safely"
```

### Task 5: Replace the writer with a provable no-send placement state machine

**Files:**
- Modify: `messenger/src/fb_draft_writer.py`
- Create: `messenger/src/no_send_guard.py`
- Create: `messenger/tests/fixtures/thread_empty_composer.html`
- Create: `messenger/tests/fixtures/thread_existing_composer.html`
- Create: `messenger/tests/fixtures/thread_after_placement.html`
- Create: `messenger/tests/test_no_send_guard.py`
- Create: `messenger/tests/test_draft_placement.py`
- Create: `messenger/tests/test_static_no_send.py`

- [ ] **Step 1: Write the static no-send test first**

Scan all executable Messenger Python/PowerShell/VBS sources and fail on Send-button
locators, message-send Graph/API calls, keyboard Enter/Return in writer code, form submit,
generic coordinate clicks, or any helper capable of sending. Maintain a narrowly reviewed
allowlist for benign literal documentation strings only.

- [ ] **Step 2: Write synthetic browser placement tests**

Cover empty composer success, non-empty composer exclusion without mutation, multiple or
missing composer candidates, stale inbound fingerprint, new outbound message before
write, challenge/login/account-trust change, crash before `write_started`, crash after
`write_started`, partial typing, exact readback mismatch, and successful placement.

- [ ] **Step 3: Define pre/write/post evidence**

Before mutation require: both gates on, fresh account trust, matching URL/thread/message
fingerprint, empty composer, unchanged sent-message count/outbound fingerprint, one visible
composer, and durable `intent_recorded`. Immediately before the first character, commit
`write_started`. After typing, require exact normalized composer text plus unchanged
sent-message count/outbound fingerprint before committing `placed_not_sent`.

- [ ] **Step 4: Verify failures**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_static_no_send.py messenger/tests/test_no_send_guard.py messenger/tests/test_draft_placement.py -v
```

- [ ] **Step 5: Implement the dedicated writer**

The writer exposes only `place_draft_no_send(intent_id)`. It must not accept arbitrary
locators or a page-wide click callback. Preserve human-prefix typing delays. Any exception
after `write_started` commits `placement_ambiguous`/40; it never clears or retries the
composer. Recovery of `intent_recorded` without proof of zero write becomes
`recovery_required_no_write`/20.

- [ ] **Step 6: Pass focused tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_static_no_send.py messenger/tests/test_no_send_guard.py messenger/tests/test_draft_placement.py -v
git add messenger/src/fb_draft_writer.py messenger/src/no_send_guard.py messenger/tests/fixtures messenger/tests/test_static_no_send.py messenger/tests/test_no_send_guard.py messenger/tests/test_draft_placement.py
git commit -m "feat: place Messenger drafts without sending"
```

### Task 6: Add account trust, default-off gates, and orchestration

**Files:**
- Modify: `messenger/config.py`
- Create: `messenger/src/account_trust.py`
- Create: `messenger/scripts/authorize_account_trust.py`
- Rewrite: `messenger/scripts/run_once.py`
- Create: `messenger/tests/test_account_trust.py`
- Create: `messenger/tests/test_run_once.py`
- Modify: `messenger/tests/test_scraper.py`

- [ ] **Step 1: Write failing gate and revocation tests**

Require both `MESSENGER_AUTO_DRAFT_ENABLED=true` and
`MESSENGER_COMPOSER_WRITE_ENABLED=true`; both default false. Account trust binds an
operator authorization timestamp, maximum 30-day expiry, browser-profile fingerprint,
and security-state fingerprint. Revoke immediately on login challenge, checkpoint,
unfamiliar-device UI, fingerprint change, or operator command.

- [ ] **Step 2: Write failing orchestration tests**

Test bounded scan counts, one placement per run, independent per-item exclusions,
idempotent rerun, lease contention, terminal exit precedence, no live writer construction
when gates/trust fail, and no message content in summary logs. A Telegram exception must
not change placement truth.

- [ ] **Step 3: Verify failures**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_account_trust.py messenger/tests/test_run_once.py messenger/tests/test_scraper.py -v
```

- [ ] **Step 4: Implement fail-closed orchestration**

Run order: validate config -> recover interrupted states -> validate session/trust ->
scan -> snapshot -> classify -> draft -> record intent -> place at most one -> enqueue
audit events -> finalize result. A scan-only command never imports the writer. Authorization
records local evidence only and never changes Facebook security settings.

- [ ] **Step 5: Pass tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_account_trust.py messenger/tests/test_run_once.py messenger/tests/test_scraper.py -v
git add messenger/config.py messenger/src/account_trust.py messenger/scripts/authorize_account_trust.py messenger/scripts/run_once.py messenger/tests/test_account_trust.py messenger/tests/test_run_once.py messenger/tests/test_scraper.py
git commit -m "feat: gate Messenger draft placement"
```

### Task 7: Add durable audit delivery and hidden scheduling

**Files:**
- Create: `messenger/src/outbox.py`
- Modify: `messenger/src/notifier.py`
- Create: `messenger/scripts/reconcile_delivery.py`
- Modify: `scripts/install_windows_tasks.ps1`
- Create: `messenger/tests/test_outbox.py`
- Create: `messenger/tests/test_delivery_reconciliation.py`
- Modify: `tests/test_hidden_launcher.py`

- [ ] **Step 1: Write failing outbox tests**

Cover stable event keys, leases, delivered/retryable/ambiguous delivery, crash recovery,
and atomic placement-finalization plus event production. Events include sanitized thread
label, classification, placement state, run ID, and review instruction; they exclude
credentials and full private messages unless the explicitly configured private Telegram
destination requires the generated draft.

- [ ] **Step 2: Write the no-Facebook reconciliation test**

Fail the test if `playwright`, Messenger session, scraper, or writer is imported or
constructed. The worker may read outbox rows and call destination handlers only. Never
automatically resend `delivery_ambiguous`.

- [ ] **Step 3: Implement and verify**

Prefer the repository-level outbox/Telegram transport through a narrow adapter. Schedule
scan and reconciliation as separate hidden allowlisted commands. Posting and Messenger
tasks use `MultipleInstances=IgnoreNew`, real exit propagation, and install disabled.

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests/test_outbox.py messenger/tests/test_delivery_reconciliation.py tests/test_hidden_launcher.py -v
```

- [ ] **Step 4: Commit**

```powershell
git add messenger/src/outbox.py messenger/src/notifier.py messenger/scripts/reconcile_delivery.py scripts/install_windows_tasks.ps1 messenger/tests/test_outbox.py messenger/tests/test_delivery_reconciliation.py tests/test_hidden_launcher.py
git commit -m "feat: audit Messenger drafts in the background"
```

### Task 8: Verify offline, then run the guarded live canary

**Files:**
- Modify: `messenger/README_ja.md`
- Modify: `README.md`
- Modify: `README_ja.md`
- Modify: `docs/recovery-runbook.md`

- [ ] **Step 1: Run the complete offline gate**

```powershell
.venv\Scripts\python.exe -m pytest messenger/tests -q
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
git diff --check
```

Require zero static no-send violations and all legacy Messenger tests green.

- [ ] **Step 2: Document provider and operational switching**

Document `template`, Claude, Codex, Gemini, GLM/OpenAI-compatible, and local LLM profile
selection, synthetic `test`, atomic `set`, previous-profile rollback, background/no-console
behavior, account-trust authorization/revocation, state inspection, and how to disable the
placement gate immediately. State prominently that the system cannot send messages.

- [ ] **Step 3: Clear manual prerequisites**

The operator confirms Facebook security/2FA in the familiar browser and authorizes account
trust. Run scan-only mode first and review classifications/drafts. Any unfamiliar-device,
checkpoint, login, or fingerprint-change evidence revokes trust and stops here.

- [ ] **Step 4: Approve one exact placement canary**

Show the operator the exact conversation identity, inbound fingerprint, generated draft,
and exclusion/risk assessment. Require explicit approval for that exact intent. Do not ask
for or authorize sending.

- [ ] **Step 5: Place and verify exactly one draft**

Enable both gates only for the canary lease. Require `placed_not_sent`, exact composer
readback, unchanged sent-message count/outbound fingerprint, a durable audit row, and a
Telegram delivery result. The operator visually confirms the draft remains unsent in the
composer. Disable the placement gate after the canary review.

- [ ] **Step 6: Stage background operation**

Require seven successful scans across at least three days, at least one human-verified
`placed_not_sent`, zero `placement_ambiguous`, zero risk events, and zero send-invariant
changes before raising from one to at most three placements per run. Keep ambiguous and
recovery-required items manual forever.

- [ ] **Step 7: Commit documentation evidence**

```powershell
git add messenger/README_ja.md README.md README_ja.md docs/recovery-runbook.md
git commit -m "docs: operationalize no-send Messenger drafts"
```

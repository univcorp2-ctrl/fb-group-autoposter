# Telegram Delivery Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver autoposter notifications reliably through the configured General bot, preserve the shared webhook, and make every sent, ambiguous, failed, or acknowledged event auditable without causing another Facebook submission.

**Architecture:** A read-only credential probe validates the ignored `.env` against the operator-owned workbook without exposing values. A Telegram transport separates outbound `sendMessage` from inbound update mode, while a durable SQLite outbox and downstream-only reconciliation worker make delivery idempotent.

**Tech Stack:** Python 3.11, requests, openpyxl, SQLite, Telegram Bot API, pytest, Ruff, hidden Windows Task Scheduler launcher.

---

**Spec:** `docs/superpowers/specs/2026-07-23-daiwa-facebook-delivery-design.md`

**Prerequisite:** Complete runtime Tasks 1–6 in
`docs/superpowers/plans/2026-07-16-runtime-safety-recovery.md`. Reuse, do not duplicate,
the durable run/attempt/circuit APIs already implemented.

## Supersession and milestone map

This plan and `2026-07-31-daiwa-estateboard-canary.md` are the implementation successors
to `2026-07-16-estateboard-telegram-delivery.md`. Preserve the inherited safety behavior,
but do not execute its tasks separately:

| Inherited delivery task | Successor |
| --- | --- |
| Task 1 outbox | this plan Tasks 3–4 |
| Task 2 v1 overlay | canary plan Task 1, superseded by v2 |
| Task 3 EstateBoard join | canary plan Task 2 |
| Task 4 web readback | canary plan Task 3 |
| Task 5 Telegram outbox | this plan Tasks 1–5 |
| Task 6 reconciliation | this plan Task 6 plus canary Task 3 EstateBoard handler |
| Task 7 verification/docs | this plan Task 7 plus canary Tasks 3 and 7 |

The integration manifest `delivery` milestone is satisfied only when this entire plan and
canary Tasks 1–3 have immutable passing commit SHAs. No v1 writer is implemented first.

## File map

- Create `src/telegram_config_probe.py`: safe workbook/`.env` comparison.
- Create `src/telegram_transport.py`: outbound Bot API and webhook-mode detection.
- Create `src/outbox.py`: delivery event leases and terminal states.
- Modify `src/queue_db.py`: additive outbox tables.
- Modify `src/approval.py`: message composition and transport delegation.
- Modify `src/poster.py`: replace every direct alert/send path with outbox production.
- Modify `scripts/approval_listener.py`: fail closed when webhook mode owns callbacks.
- Modify `scripts/ingest_daiwa.py`: produce DAIWA ingestion delivery events.
- Create `scripts/check_telegram_delivery.py`: no-secret health command.
- Create `scripts/reconcile_delivery.py`: downstream-only worker.
- Modify hidden launcher/task installation files after tests.
- Add focused tests and update documentation.

### Task 1: Add a no-secret credential/configuration probe

**Files:**
- Create: `src/telegram_config_probe.py`
- Create: `scripts/check_telegram_delivery.py`
- Test: `tests/test_telegram_config_probe.py`

- [ ] **Step 1: Write failing tests**

Create a fixture workbook with `Telegrams!A2` and a BotFather-style message in
`Telegrams!B8`. Test exact match, missing sheet/cell, malformed embedded token, mismatch,
and sanitized output. Assert the token/chat never occur in JSON, logs, or exceptions.

- [ ] **Step 2: Verify failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_telegram_config_probe.py -v
```

- [ ] **Step 3: Implement targeted read-only extraction**

Expose:

```python
def compare_telegram_config(
    workbook_path: Path,
    env_path: Path,
) -> TelegramConfigCheck:
    ...
```

Read only `Telegrams!A2` and `Telegrams!B8` with `openpyxl` read-only/data-only mode.
Extract the embedded token in memory. Return only booleans, credential role
`General bot`, and safe reason codes.

The script defaults the workbook to
`G:\マイドライブ\AI_Agents\Private\API_AWS_DB.xlsx` and `.env` to the repository root.
It never writes either file.

- [ ] **Step 4: Pass tests**

Run Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/telegram_config_probe.py scripts/check_telegram_delivery.py tests/test_telegram_config_probe.py
git commit -m "feat: verify Telegram config without exposing secrets"
```

### Task 2: Separate outbound transport from inbound update mode

**Files:**
- Create: `src/telegram_transport.py`
- Modify: `src/approval.py`
- Test: `tests/test_telegram_transport.py`
- Modify: `tests/test_approval_security.py`

- [ ] **Step 1: Write failing transport tests**

Test:

- `getMe`, `getChat`, and `getWebhookInfo` health classification;
- active webhook does not block outbound `sendMessage`;
- active webhook prohibits `getUpdates`;
- token redaction from HTTP errors;
- successful sends return Telegram `message_id`;
- timeout after request submission becomes `delivery_ambiguous`; and
- deterministic safe failure codes.

- [ ] **Step 2: Verify failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_telegram_transport.py tests/test_approval_security.py -v
```

- [ ] **Step 3: Implement transport**

Expose:

```python
class TelegramTransport:
    def probe(self) -> TelegramProbe: ...
    def send_message(self, text: str, reply_markup: dict | None = None) -> TelegramSendResult: ...
    def inbound_mode(self) -> Literal["webhook", "polling", "disabled", "unknown"]: ...
```

Keep the existing webhook unchanged. Do not call `setWebhook` or `deleteWebhook`.
`TelegramApproval` composes messages but delegates HTTP to the transport.

- [ ] **Step 4: Pass tests and existing approval tests**

Run Step 2 plus:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_persistent_alerts.py -v
```

- [ ] **Step 5: Commit**

```powershell
git add src/telegram_transport.py src/approval.py tests/test_telegram_transport.py tests/test_approval_security.py tests/test_persistent_alerts.py
git commit -m "fix: separate Telegram send and callback modes"
```

### Task 3: Add the durable delivery outbox

**Files:**
- Create: `src/outbox.py`
- Modify: `src/queue_db.py`
- Test: `tests/test_outbox.py`

- [ ] **Step 1: Write failing outbox tests**

Cover unique event keys, pending leases, lease expiry, delivered/failed/ambiguous states,
crash recovery, and atomic producer finalization.

- [ ] **Step 2: Verify failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_outbox.py -v
```

- [ ] **Step 3: Add additive schema and APIs**

Use one `delivery_outbox` table with:

```text
event_id, event_key UNIQUE, destination, event_type, origin_run_id,
attempt_id, subject_id, payload_json, state, lease_owner, lease_expires_at,
attempt_count, remote_message_id, created_at, updated_at, last_error
```

Payloads contain rendered message text but never token/chat ID. Producers enqueue in the
same transaction that finalizes the corresponding attempt/run state.

- [ ] **Step 4: Pass outbox and DB tests**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_outbox.py tests/test_submission_attempts.py tests/test_circuits.py -v
```

- [ ] **Step 5: Commit**

```powershell
git add src/outbox.py src/queue_db.py tests/test_outbox.py
git commit -m "feat: add durable downstream delivery outbox"
```

### Task 4: Route notifications through the outbox

**Files:**
- Modify: `src/approval.py`
- Modify: `src/outbox.py`
- Modify: `src/poster.py`
- Modify: `src/post_verify.py`
- Modify: `scripts/verify_posts.py`
- Modify: `scripts/run_daily.py`
- Modify: `scripts/ingest_daiwa.py`
- Test: `tests/test_telegram_outbox.py`

- [ ] **Step 1: Write failing event tests**

Cover DAIWA ingestion success/failure, preview, verified post, uncertainty, challenge,
recovery, daily completion, and EstateBoard delivery notices. Require stable event keys
and Japanese property/community/permalink content where applicable. Assert the ingestion
terminal state and its outbox event commit atomically.

- [ ] **Step 2: Verify failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_telegram_outbox.py -v
```

- [ ] **Step 3: Replace direct sends with event production**

No Facebook producer, including `src/poster.py`, calls `sendMessage` or `alert` directly.
Inject an event producer instead of a network notifier. Enqueue:

```text
telegram:<attempt_id>:verified
telegram:<attempt_id>:uncertain
telegram:<run_id>:environment:<reason>
telegram:<run_id>:summary
```

Preserve existing message wording where possible. A verified message must include property
name, community name, and HTTPS permalink.

- [ ] **Step 4: Pass tests**

Run Step 2 and persistent alert tests. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/approval.py src/outbox.py src/poster.py src/post_verify.py scripts/verify_posts.py scripts/run_daily.py scripts/ingest_daiwa.py tests/test_telegram_outbox.py
git commit -m "feat: enqueue Telegram delivery events"
```

### Task 5: Make callbacks fail closed under the shared webhook

**Files:**
- Modify: `scripts/approval_listener.py`
- Modify: `src/approval.py`
- Modify: `src/operational_cli.py`
- Test: `tests/test_approval_listener_mode.py`
- Test: `tests/test_daiwa_publication_approval_cli.py`

- [ ] **Step 1: Write failing mode tests**

Assert active webhook returns reason `telegram_webhook_owns_callbacks`, does not call
`getUpdates`, and exits successfully with zero handled callbacks. Unknown mode must alert
and fail closed. Test the operational CLI can record an exact DAIWA publication
authorization by invoking the Task 3 source-plan API with property ID, row fingerprint,
literal `TRUE`, authorizer, and availability timestamp.

- [ ] **Step 2: Implement mode gate**

Polling is permitted only when `getWebhookInfo.url` is empty. Do not clear the existing
Worker webhook. Add operational CLI command `authorize-daiwa-publication` that delegates
to `daiwa_store.authorize_publication`; do not duplicate authorization logic. Canary
approval uses this command until a separately reviewed Worker callback route exists.

- [ ] **Step 3: Pass tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_approval_listener_mode.py tests/test_daiwa_publication_approval_cli.py tests/test_persistent_alerts.py -v
git add scripts/approval_listener.py src/approval.py src/operational_cli.py tests/test_approval_listener_mode.py tests/test_daiwa_publication_approval_cli.py
git commit -m "fix: prevent polling against Telegram webhook"
```

### Task 6: Add downstream-only reconciliation

**Files:**
- Create: `scripts/reconcile_delivery.py`
- Modify: `src/outbox.py`
- Modify: `src/run_result.py`
- Test: `tests/test_delivery_reconciliation.py`

- [ ] **Step 1: Write failing reconciliation tests**

Use a fake `FacebookPoster` that raises if imported or constructed. Test delivered, retryable
pre-send failure, ambiguous timeout, operator-confirmed resend, origin-run linkage, and a
destination-handler registry that can later accept the EstateBoard handler without
importing Facebook.

- [ ] **Step 2: Verify failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_delivery_reconciliation.py -v
```

- [ ] **Step 3: Implement bounded worker**

Claim at most 20 events for 60 seconds. Dispatch by destination through a registered
handler interface. This plan registers the Telegram handler; the canary plan registers
EstateBoard. Retry only failures proven to occur before request submission. Never
automatically retry `delivery_ambiguous`. Write a new
`fb-autoposter-run/v1` result with `origin_run_id`; never alter Facebook attempt truth.

- [ ] **Step 4: Pass tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_delivery_reconciliation.py tests/test_outbox.py -v
git add scripts/reconcile_delivery.py src/outbox.py src/run_result.py tests/test_delivery_reconciliation.py
git commit -m "feat: reconcile delivery without Facebook submission"
```

### Task 7: Verify one diagnostic delivery and hidden scheduling

**Files:**
- Modify: `scripts/install_windows_tasks.ps1`
- Modify: `README.md`
- Modify: `README_ja.md`
- Test: `tests/test_hidden_launcher.py`

- [ ] **Step 1: Verify all automated tests**

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
git diff --check
```

- [ ] **Step 2: Run read-only production probes**

Require:

- private workbook and `.env` exact-match booleans;
- `getMe=true`;
- `getChat=true`;
- inbound mode `webhook`; and
- no token/chat ID in output.

- [ ] **Step 3: Request exact external-send confirmation**

Before sending, present destination `General bot/private chat`, purpose
`FB自動投稿 Telegram配送テスト`, and exact message text. Send only after the operator
confirms that exact diagnostic.

- [ ] **Step 4: Enqueue and reconcile one diagnostic**

Require one returned Telegram `message_id`, one delivered outbox row, and one success run
result. Do not call any Facebook module.

- [ ] **Step 5: Install hidden reconciliation task**

Reuse the tested hidden launcher from the runtime plan. The scheduled task waits for the
child and propagates its real exit code. Verify no console appears and Task Scheduler,
latest result, history result, and SQLite share the same run ID.

- [ ] **Step 6: Document and commit**

```powershell
git add scripts/install_windows_tasks.ps1 README.md README_ja.md tests/test_hidden_launcher.py
git commit -m "docs: operationalize Telegram delivery recovery"
```

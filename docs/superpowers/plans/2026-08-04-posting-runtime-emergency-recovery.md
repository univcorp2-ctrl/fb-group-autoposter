# Facebook Posting Runtime Emergency Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore truthful daily Facebook property posting, Telegram delivery, and EstateBoard evidence without weakening the existing account-protection behavior or retrying an ambiguous Facebook submission.

**Architecture:** Finish the already-designed runtime and delivery foundations instead of creating parallel code paths. Facebook submission produces durable attempt truth and downstream outbox events; Telegram and EstateBoard reconciliation run independently and can never construct a poster. A read-only composer diagnostic repairs the current selector failure before one tightly leased DAIWA canary is authorized.

**Tech Stack:** Python 3.11, Playwright, SQLite, requests/curl-compatible HTTPS transport, pytest, Ruff, Cloudflare Pages, Windows Task Scheduler and WSH.

---

**Spec:** `docs/superpowers/specs/2026-08-03-facebook-posting-messenger-recovery-design.md`

## Scope and supersession map

This is a closure and sequencing plan, not a replacement for the reviewed plans below.
Implement only the rows marked `Delta` here; execute retained tasks from their original
documents so their detailed safety contracts remain authoritative.

| Existing plan | Current disposition | Execution rule |
| --- | --- | --- |
| `2026-07-16-runtime-safety-recovery.md` Tasks 1-3 | Implemented; preserve | Run regression tests; do not redesign |
| `2026-07-16-runtime-safety-recovery.md` Tasks 4-8 | Retained | Execute before any live Facebook action |
| `2026-07-16-ai-gateway.md` Tasks 1-2, 4, and 6-8 | Retained with the Phase 1 transport rule below | Reuse protocol, renderer, HTTP, gateway, integration, and documentation contracts |
| `2026-07-16-ai-gateway.md` Tasks 3 and 5 | Superseded for Phase 1 | Implement one profile registry and one allowlisted JSON CLI runner supporting installed `claude`, `codex`, or `gemini`; do not create three provider-specific CLI adapter modules |
| `2026-07-31-telegram-delivery-recovery.md` Tasks 1-7 | Retained | Complete before posting canary; no direct notifier calls from Facebook producers |
| `2026-07-31-daiwa-source-ingestion.md` Tasks 1-6 | Retained | Complete after runtime and outbox foundations |
| `2026-07-31-daiwa-estateboard-canary.md` Tasks 1-7 | Retained | Its live Tasks 5-7 are the only authorized posting rollout path |
| `2026-07-16-estateboard-telegram-delivery.md` | Superseded | Do not implement separately |
| This plan Tasks 1-5 | Delta | Implements observed incident gaps and a single release gate |

Automatic community joining is outside this recovery and remains disabled. The account
trust incident must be resolved in a familiar browser before a live canary. No test in
Tasks 1-4 clicks Facebook's final Post button.

For avoidance of doubt, Phase 1 consists of the deterministic template, the existing
Anthropic API path, one OpenAI-compatible HTTP adapter, and one shared allowlisted JSON
CLI runner. Where retained AI Tasks 6-8 name the former provider-specific modules, replace
those references with the shared runner and its selected executable. Provider-native CLI
adapters and their version-specific argv builders are Phase 2 and are not recovery gates.
The shared runner is implemented in `src/ai_gateway/cli_process.py` and
`src/ai_gateway/adapters/json_cli.py`, with contracts in
`tests/ai_gateway/test_cli_process.py` and `tests/ai_gateway/test_json_cli.py`.

## File map

- Create `src/secret_redaction.py`: exact-value and Telegram URL sanitization shared by logs/results.
- Create `scripts/redact_revoked_telegram_token.py`: stdin-only exact-token cleanup tool.
- Modify `src/run_result.py`, `src/logging_setup.py`, `src/approval.py`, and Messenger notifier to use shared sanitization.
- Create `src/composer_diagnostic.py` and `scripts/diagnose_composer.py`: read-only composer evidence and stable reason codes.
- Modify `src/selectors.py` and `src/poster.py`: deterministic selector repair with no broad click fallback.
- Modify `src/orchestrator.py` and `scripts/run_daily.py`: notification isolation and truthful terminal result propagation.
- Modify `scripts/launch_hidden.vbs`, `scripts/launch_hidden.ps1`, and `scripts/install_windows_tasks.ps1`: wait for the child and preserve its exit code without a console.
- Create `docs/recovery-runbook.md`: sanitized production gates, token rotation, rollback, and evidence ledger.
- Add focused tests under `tests/`.

### Task 1: Lock the incident contract and current safety baseline

**Files:**
- Modify: `tests/test_protection_compatibility.py`
- Create: `tests/test_recovery_acceptance_contract.py`
- Modify: `docs/account-protection-compatibility.md`

- [ ] **Step 1: Write the failing acceptance-contract tests**

Assert statically and dynamically that:

- only a verified HTTPS permalink can produce a successful Facebook attempt;
- `write_started`, `clicked_unverified`, and unknown interruption states cannot be retried;
- a Telegram/EstateBoard exception cannot change Facebook attempt truth or consume a Facebook retry;
- automatic group joining is not reachable from the daily command;
- runtime gates default off for posting after install; and
- every terminal command maps to exit `0`, `20`, `30`, `40`, `50`, or `60` through `fb-autoposter-run/v1`.

- [ ] **Step 2: Verify the new test fails for the notification boundary**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_recovery_acceptance_contract.py tests/test_protection_compatibility.py -v
```

Expected: the new direct-notifier/terminal propagation assertions fail while the
previously implemented compatibility tests stay green.

- [ ] **Step 3: Record the frozen baseline**

Update the compatibility document with the current test names and the rule that a repair
may add a stricter preflight but may not remove human typing delays, challenge detection,
daily/group limits, cooldowns, immutable approvals, or ambiguous-attempt quarantine.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_recovery_acceptance_contract.py tests/test_protection_compatibility.py docs/account-protection-compatibility.md
git commit -m "test: freeze posting recovery safety contract"
```

### Task 2: Redact the revoked Telegram credential and isolate delivery failures

**Files:**
- Create: `src/secret_redaction.py`
- Create: `scripts/redact_revoked_telegram_token.py`
- Modify: `src/run_result.py`
- Modify: `src/logging_setup.py`
- Modify: `src/approval.py`
- Modify: `src/orchestrator.py`
- Modify: `scripts/run_daily.py`
- Modify: `messenger/src/notifier.py`
- Create: `tests/test_secret_redaction.py`
- Create: `tests/test_delivery_failure_isolation.py`
- Modify: `tests/test_approval_security.py`

- [ ] **Step 1: Write failing secret-redaction tests**

Cover Telegram Bot API URLs, `requests` exception strings, nested result JSON, logs, and
arbitrary exact revoked-token replacement. Assert the token value never appears in
stdout, stderr, exceptions, output JSON, or rewritten repository logs.

- [ ] **Step 2: Write failing isolation tests**

Inject Telegram timeouts, TLS EOF, and ambiguous post-submit delivery failures into
preview, verified-post, challenge, and summary paths. Assert the Facebook run reaches the
same attempt state and exit code as with a healthy notifier, while an outbox event records
the delivery failure. Assert no notification retry invokes `FacebookPoster`.

- [ ] **Step 3: Verify failures**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_secret_redaction.py tests/test_delivery_failure_isolation.py tests/test_approval_security.py -v
```

- [ ] **Step 4: Implement shared redaction and the cleanup tool**

The cleanup command reads the exact revoked token only from stdin, scans only explicitly
passed repository-relative log/result paths, atomically replaces exact matches and token
URL segments with `[REDACTED_TELEGRAM_TOKEN]`, and prints counts and paths only. It refuses
empty input, directory traversal, source files, `.env`, databases, and paths outside the
repository. It never stores the supplied token.

- [ ] **Step 5: Finish the existing Telegram outbox plan**

Execute Tasks 1-6 of `2026-07-31-telegram-delivery-recovery.md` in order. Route every
producer touched above through `src/outbox.py`. Keep the configured webhook unchanged;
do not call `setWebhook` or `deleteWebhook`. A request timeout after submission becomes
`delivery_ambiguous` and is not automatically resent.

- [ ] **Step 6: Pass focused and regression tests**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_secret_redaction.py tests/test_delivery_failure_isolation.py tests/test_telegram_transport.py tests/test_outbox.py tests/test_delivery_reconciliation.py tests/test_persistent_alerts.py -v
.venv\Scripts\python.exe -m ruff check src messenger scripts tests
```

- [ ] **Step 7: Commit only the delta after the referenced task commits**

```powershell
git add src/secret_redaction.py scripts/redact_revoked_telegram_token.py src/run_result.py src/logging_setup.py src/approval.py src/orchestrator.py scripts/run_daily.py messenger/src/notifier.py tests/test_secret_redaction.py tests/test_delivery_failure_isolation.py tests/test_approval_security.py
git commit -m "fix: isolate delivery failures and redact Telegram secrets"
```

### Task 3: Diagnose and repair the current composer-open failure without submission

**Files:**
- Create: `src/composer_diagnostic.py`
- Create: `scripts/diagnose_composer.py`
- Modify: `src/selectors.py`
- Modify: `src/poster.py`
- Create: `tests/fixtures/facebook/group_feed_composer.html`
- Create: `tests/fixtures/facebook/group_feed_no_composer.html`
- Create: `tests/test_composer_diagnostic.py`
- Modify: `tests/test_selectors.py`
- Modify: `tests/test_poster_preflight.py`

- [ ] **Step 1: Write failing fixture and policy tests**

Test Japanese and English accessible names, role/text alternatives, hidden duplicates,
zero match, multiple visible matches, checkpoint/login UI, and Facebook markup drift.
Require exactly one visible eligible composer trigger. Assert no locator is derived from
AI output and no generic page click is available.

- [ ] **Step 2: Write the diagnostic contract test**

`diagnose_composer.py --group-id <id>` may navigate to one configured joined group and
read DOM/accessibility evidence, but must not click a composer, type, upload, or submit.
It writes a sanitized run result with `composer_ready`, `selector_missing`,
`selector_ambiguous`, `login_required`, `checkpoint_required`, or `account_trust_blocked`.
Screenshots are opt-in, redacted, and never include Messenger or authentication pages.

- [ ] **Step 3: Verify failures**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_composer_diagnostic.py tests/test_selectors.py tests/test_poster_preflight.py -v
```

- [ ] **Step 4: Implement deterministic diagnosis and narrow selector repair**

Prefer stable role/accessibility contracts and validate visible uniqueness before click.
Preserve the existing delays and human-prefix typing. If zero or multiple candidates
remain, stop before write with exit `20`; do not invoke the vision healer to invent an
action. Keep final Post-button behavior unchanged and inaccessible from this diagnostic.

- [ ] **Step 5: Complete runtime plan Tasks 4-6**

Execute `2026-07-16-runtime-safety-recovery.md` Tasks 4-6. Use a tested profile clone and
the operational CLI; do not point tests at the live Facebook profile.

- [ ] **Step 6: Run offline verification and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_composer_diagnostic.py tests/test_selectors.py tests/test_poster_preflight.py tests/test_posting_reliability.py tests/test_submission_attempts.py -v
git add src/composer_diagnostic.py scripts/diagnose_composer.py src/selectors.py src/poster.py tests/fixtures/facebook tests/test_composer_diagnostic.py tests/test_selectors.py tests/test_poster_preflight.py
git commit -m "fix: diagnose Facebook composer before posting"
```

### Task 4: Make every scheduled process hidden and truthful

**Files:**
- Create or modify: `scripts/launch_hidden.ps1`
- Create or modify: `scripts/launch_hidden.vbs`
- Modify: `scripts/install_windows_tasks.ps1`
- Create or modify: `src/operational_cli.py`
- Modify: `tests/test_hidden_launcher.py`
- Create: `tests/test_scheduler_result_contract.py`

- [ ] **Step 1: Execute runtime plan Task 7 test-first**

The VBS launcher must call PowerShell with window style hidden and `wait=True`, then
return the child's real exit code. PowerShell invokes only an allowlisted operational CLI
command with an absolute repository working directory. No launcher uses `False` for the
WSH wait argument.

- [ ] **Step 2: Add scheduler-result tests**

Use fake child commands returning every allowed exit code. Assert WSH, PowerShell,
`latest.json`, run history, and SQLite agree on command, run ID, outcome, reason, and exit
code. Assert posting tasks install disabled and `MultipleInstances=IgnoreNew`.

- [ ] **Step 3: Verify focused tests**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_hidden_launcher.py tests/test_scheduler_result_contract.py tests/test_run_result.py -v
```

- [ ] **Step 4: Commit**

```powershell
git add scripts/launch_hidden.ps1 scripts/launch_hidden.vbs scripts/install_windows_tasks.ps1 src/operational_cli.py tests/test_hidden_launcher.py tests/test_scheduler_result_contract.py
git commit -m "fix: propagate hidden scheduler outcomes"
```

### Task 5: Stage DAIWA, Telegram, EstateBoard, and the one-post canary

**Files:**
- Modify: `docs/integration-manifest.json`
- Create or modify: `docs/recovery-runbook.md`
- Modify: `README.md`
- Modify: `README_ja.md`

- [ ] **Step 1: Complete retained implementation plans in dependency order**

Execute and record immutable passing commit SHAs for:

1. runtime plan Task 8;
2. AI gateway Phase 1 acceptance scope defined in this plan;
3. Telegram plan Task 7 Steps 1-3; pause at the exact external-send confirmation;
4. all DAIWA source-ingestion tasks;
5. DAIWA canary plan Tasks 1-4.

- [ ] **Step 2: Run the full offline release gate**

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
git diff --check
```

Expected: all pass. Confirm no secret value appears in tracked files or sanitized logs.

- [ ] **Step 3: Perform manual account and credential gates**

The operator must, in a familiar browser, confirm Facebook account security/2FA and clear
the unfamiliar-device condition. The operator rotates the exposed Telegram bot token in
BotFather, updates the ignored secret source, and supplies the revoked token by stdin to
the cleanup tool. Code does not automate these actions. Record booleans and timestamps,
never credentials.

- [ ] **Step 4: Run read-only live preflights**

Run Telegram `getMe/getChat/getWebhookInfo`, EstateBoard HTTP/DOM readback, Facebook login
and account-trust preflight, and one composer diagnostic. Require exit `0` and fresh
linked results. Do not click a composer or Post.

The guarded DAIWA canary in Step 6 is the first live verification that opens the posting
composer. The read-only diagnostic proves selector uniqueness but intentionally does not
click the composer.

- [ ] **Step 5: Request the two exact external-action approvals**

Present the exact Telegram diagnostic destination/text and the exact DAIWA
property/community/body/images for dry-run review. No broad approval is accepted.

- [ ] **Step 6: Execute the existing canary plan Tasks 5-7**

After approval, first resume Telegram recovery Task 7 Steps 4-6: enqueue and reconcile
exactly one diagnostic, require its returned `message_id` and delivered outbox row, install
the hidden reconciliation task, and record the passing evidence. Only then acquire exactly
one 15-minute live lease and perform one headed post under DAIWA canary Tasks 5-7.
Success requires a public HTTPS permalink, EstateBoard DOM readback for the exact
property/community, and one delivered Telegram outbox event. An ambiguous result exits
`40` and is never retried. Keep scheduled posting disabled until all evidence is reviewed.

- [ ] **Step 7: Enable staged daily operation only after evidence review**

Enable at most one posting task. Preserve existing daily/group caps and cooldowns. Require
seven successful scheduled scans across at least three days, zero ambiguous attempts,
zero account-risk events, and at least one operator-confirmed verified post before raising
any volume. Automatic joining remains disabled.

- [ ] **Step 8: Document rollback and commit**

The runbook must show how to disable the posting task, revoke a live lease, keep delivery
reconciliation running, switch AI profile to `template`, and inspect the authoritative
run/attempt/outbox/EstateBoard evidence.

```powershell
git add docs/integration-manifest.json docs/recovery-runbook.md README.md README_ja.md
git commit -m "docs: operationalize guarded posting recovery"
```

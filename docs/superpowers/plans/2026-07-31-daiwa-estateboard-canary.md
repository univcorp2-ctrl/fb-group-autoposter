# DAIWA EstateBoard and Facebook Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the canonical DAIWA feed and source-aware Facebook status to EstateBoard, then execute exactly one authorized DAIWA post to one confirmed community with Telegram and permalink evidence.

**Architecture:** A versioned `fb-post-status/v2` overlay joins normal and DAIWA properties by `(source, source_id)`. Deployment is verified by HTTP and DOM readback before one guarded live lease permits a single headed Facebook submission; all downstream reconciliation is incapable of constructing a Facebook poster.

**Tech Stack:** Python 3.11, SQLite, JSON, Playwright, Cloudflare Pages/Wrangler, Telegram, pytest, Ruff, Windows Task Scheduler.

---

**Spec:** `docs/superpowers/specs/2026-07-23-daiwa-facebook-delivery-design.md`

**Prerequisites:**

- Complete `docs/superpowers/plans/2026-07-31-daiwa-source-ingestion.md`.
- Complete `docs/superpowers/plans/2026-07-31-telegram-delivery-recovery.md`.
- Complete runtime and AI gateway plans referenced by
  `docs/superpowers/plans/2026-07-16-integration-rollout.md`.
- Record exact prerequisite commit SHAs in `docs/integration-manifest.json`.
- Automatic community joining remains disabled.

## Supersession and milestone map

This plan supersedes Tasks 2–4 of
`docs/superpowers/plans/2026-07-16-estateboard-telegram-delivery.md`; do not implement the
v1 overlay first. Tasks 1–3 here, together with the complete Telegram recovery plan, form
the `delivery` integration milestone. Tasks 4–7 extend, rather than separately repeat,
`docs/superpowers/plans/2026-07-16-integration-rollout.md`.

## File map

- Create/modify `src/status_overlay.py`: source-aware v2 overlay.
- Modify `scripts/sync_estateboard_status.py`: DAIWA feed and overlay deployment/readback.
- Modify `src/outbox.py`: EstateBoard event producer/handler contract.
- Modify `src/post_verify.py` and `scripts/verify_posts.py`: atomic EstateBoard event production.
- Modify `src/poster.py`: immediate verified/uncertain EstateBoard event production.
- Modify EstateBoard `docs/index.html`: exact source-aware join and status UI.
- Add tests in both repositories.
- Modify `src/operational_cli.py`: DAIWA dry-run/canary selection.
- Modify `docs/recovery-runbook.md`: sanitized rollout evidence.

### Task 1: Upgrade the posting overlay to `fb-post-status/v2`

**Files:**
- Create or modify: `src/status_overlay.py`
- Test: `tests/test_status_overlay.py`

- [ ] **Step 1: Write failing schema tests**

Test normal `eb-<ID>`, DAIWA `daiwa-<20-hex>`, v1 read compatibility, deterministic v2
output, group history, precedence `uncertain > verified > failed`, HTTPS permalink
validation, unmatched IDs, and stale-row removal.

- [ ] **Step 2: Verify failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_status_overlay.py -v
```

- [ ] **Step 3: Implement exact v2 rows**

Each row contains:

```json
{
  "source": "daiwa",
  "source_id": "daiwa-0123456789abcdef0123",
  "autoposter_property_id": "daiwa-0123456789abcdef0123",
  "overall_status": "verified",
  "latest_posted_at": "RFC3339 UTC",
  "groups": []
}
```

Never include post body, local paths, credentials, screenshots, or cookies.

- [ ] **Step 4: Pass tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_status_overlay.py -v
git add src/status_overlay.py tests/test_status_overlay.py
git commit -m "feat: export source-aware Facebook status overlay"
```

### Task 2: Publish DAIWA and overlay data to EstateBoard

**Files:**
- Modify: `scripts/sync_estateboard_status.py`
- Test: `tests/test_sync_estateboard_overlay.py`
- Modify in EstateBoard: `G:\マイドライブ\AI_Agents\github\repos\EstateBoard\docs\index.html`
- Create in EstateBoard: `G:\マイドライブ\AI_Agents\github\repos\EstateBoard\tests\test_daiwa_fb_overlay.py`

- [ ] **Step 1: Write failing sync and DOM tests**

Prove:

- `data_daiwa.json` must be non-empty and schema `estateboard-daiwa/v1`;
- overlay joins DAIWA by exact `(daiwa, daiwa-<20-hex>)`;
- normal EstateBoard joins remain correct;
- missing/stale/unmatched overlay displays a warning;
- every community remains separately visible; and
- a daily listing regeneration cannot erase posting truth.

- [ ] **Step 2: Verify both repositories fail**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_sync_estateboard_overlay.py -v
Set-Location G:\マイドライブ\AI_Agents\github\repos\EstateBoard
.venv\Scripts\python.exe -m pytest tests/test_daiwa_fb_overlay.py -v
```

- [ ] **Step 3: Implement atomic copy and client join**

Copy the validated full snapshots to:

- `EstateBoard/docs/data_daiwa.json`;
- `EstateBoard/docs/fb_post_status.json`.

Expose DOM diagnostics for schema, run ID, source count, joined count, and unmatched count.
Do not patch `投稿済` fields in generated listing JSON as source of truth.

- [ ] **Step 4: Pass tests and commit repositories separately**

Commit autoposter sync/tests first. Commit EstateBoard UI/tests second with intentional
file lists; never stage unrelated Drive-generated or `desktop.ini` changes.

### Task 3: Add deployment and DOM readback

**Files:**
- Create: `src/web_delivery_probe.py`
- Modify: `scripts/sync_estateboard_status.py`
- Modify: `src/outbox.py`
- Modify: `src/post_verify.py`
- Modify: `src/poster.py`
- Modify: `scripts/verify_posts.py`
- Modify: `scripts/reconcile_delivery.py`
- Test: `tests/test_web_delivery_probe.py`
- Create: `tests/test_estateboard_outbox.py`

- [ ] **Step 1: Write failing probe tests**

Cover exact HTTP schema/run/count, visible DAIWA record, visible status marker, DOM
diagnostics, stale/unmatched failure, timeout, unchanged-byte redeployment, and one
EstateBoard outbox event bound to `origin_run_id`, `attempt_id`, property, and group.
Exercise both immediate `src/poster.py` verified/uncertain transitions and later
`src/post_verify.py`/`scripts/verify_posts.py` promotion/demotion transitions.

- [ ] **Step 2: Implement and verify**

After an immediate verified/uncertain transition in `src/poster.py` or a later
promoted/demoted transition, atomically enqueue:

```text
estateboard:<attempt_id>:<event_type>
```

The EstateBoard destination handler regenerates the full overlay from SQLite, copies the
validated DAIWA feed/overlay, deploys, performs HTTP/DOM readback, and marks the event
delivered with the deployed run ID. It is registered in the generic downstream-only
reconciler from the Telegram plan. Deploy only validated snapshots. Use an isolated
non-Facebook browser profile for the DOM probe. A failure remains `web_sync_failed` and
never imports or constructs FacebookPoster.

- [ ] **Step 3: Pass tests and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_web_delivery_probe.py tests/test_sync_estateboard_overlay.py tests/test_estateboard_outbox.py tests/test_delivery_reconciliation.py -v
git add src/web_delivery_probe.py src/outbox.py src/poster.py src/post_verify.py scripts/verify_posts.py scripts/sync_estateboard_status.py scripts/reconcile_delivery.py tests/test_web_delivery_probe.py tests/test_sync_estateboard_overlay.py tests/test_estateboard_outbox.py tests/test_delivery_reconciliation.py
git commit -m "feat: verify EstateBoard DAIWA delivery"
```

### Task 4: Complete browser/runtime gates and implement the live lease

**Files:**
- As specified in `docs/superpowers/plans/2026-07-16-runtime-safety-recovery.md`
- Create: `src/rollout_lease.py`
- Modify: `src/queue_db.py`
- Modify: `src/operational_cli.py`
- Modify: `src/poster.py`
- Modify: hidden launcher installed by the runtime plan
- Create: `scripts/monitor_rollout_lease.py`
- Create: `tests/test_rollout_live_lease.py`
- Create: `tests/test_live_rollout_authorization.py`
- Create: `tests/test_final_click_guard.py`
- Modify: `tests/test_hidden_launcher.py`
- Modify: `docs/integration-manifest.json`

- [ ] **Step 1: Complete remaining reviewed runtime tasks**

Finish Chrome channel/profile compatibility, FacebookPoster integration, operational CLI,
hidden launcher, and scheduler tests. Do not change the frozen account-protection contract.

- [ ] **Step 2: Run full verification**

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
```

Expected: PASS with no live Facebook interaction.

- [ ] **Step 3: Write failing live-lease tests**

Test additive `live_rollout_authorizations` and `rollout_live_leases` persistence; a
creation command bound to exact property/group IDs, DAIWA publication authorization ID,
job approval ID, source/body hashes, generation fingerprint, proposed run ID, authorizer,
created time, and 15-minute expiry; exact run/process/authorization lease binding;
60-second heartbeat staleness; single active lease; launcher reopening the global circuit
on abnormal child exit/missing terminal result; and the final click refusing to proceed
unless the exact unexpired authorization, healthy lease, and hashes are present in the
same transaction that writes `click_started_at`.

- [ ] **Step 4: Implement lease, monitor, and atomic click guard**

Expose:

```python
def create_live_authorization(
    property_id, group_id, publication_authorization_id, approval_id,
    source_hash, body_hash, generation_fingerprint, run_id, authorizer, now
) -> LiveRolloutAuthorization: ...
def acquire_live_lease(run_id, pid, authorization_id, now) -> LiveLease: ...
def heartbeat_live_lease(lease_id, pid, now) -> None: ...
def assert_live_click_allowed(conn, attempt_id, lease_id, bound_hashes, now) -> None: ...
def close_live_lease(lease_id, terminal_state, now) -> None: ...
```

Add operational CLI command:

```powershell
python -m src.operational_cli authorize-live-rollout `
  --run-id ... --property-id ... --group-id ... `
  --publication-authorization-id ... --approval-id ... `
  --source-hash ... --body-hash ... --generation-fingerprint ... `
  --authorizer operator_live_rollout
```

It creates a single immutable authorization expiring after 15 minutes. Add a
`LiveLeaseHeartbeat` context used by `daily-post`; it refreshes every 20 seconds on a
dedicated thread/task and stops in `finally`. Before the canary, install and enable hidden
Task Scheduler task `FBAutoposter-RolloutLeaseMonitor` at one-minute repetition and invoke
it once to prove it can observe the DB. The independent monitor reopens
`rollout_in_progress` when heartbeat age exceeds 60 seconds or hard expiry passes. The
launcher `finally` path does the same on every non-success/non-50 exit or missing terminal
result.

- [ ] **Step 5: Pass lease/runtime tests**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_rollout_live_lease.py tests/test_live_rollout_authorization.py tests/test_final_click_guard.py tests/test_hidden_launcher.py -v
```

- [ ] **Step 6: Commit the lease implementation**

```powershell
git add src/rollout_lease.py src/queue_db.py src/operational_cli.py src/poster.py scripts/monitor_rollout_lease.py tests/test_rollout_live_lease.py tests/test_live_rollout_authorization.py tests/test_final_click_guard.py tests/test_hidden_launcher.py
git commit -m "feat: guard live rollout with expiring lease"
```

- [ ] **Step 7: Record prerequisite commits**

Verify each SHA exists and is an ancestor of HEAD. A missing/different prerequisite blocks
the canary and requires plan review.

### Task 5: Select and authorize one dry-run canary

**Files:**
- Modify: `src/operational_cli.py`
- Test: `tests/test_daiwa_canary_selection.py`

- [ ] **Step 1: Write failing selection tests**

Test two explicit phases:

1. `preview-candidate` may select exactly one complete/fresh DAIWA row while ignoring only
   the missing publication authorization; it remains submission-ineligible.
2. `authorized-canary` requires the active 30-hour publication authorization, current
   source fingerprint, and no duplicate/uncertain attempt.

Both phases require exactly one enabled membership-confirmed community with unchanged
rules hash.

- [ ] **Step 2: Implement `--source daiwa --max-targets 1`**

Add:

```powershell
python -m src.operational_cli preview-daiwa-canary --max-targets 1
python -m src.operational_cli authorize-daiwa-publication --property-id ... --row-fingerprint ... --literal-value TRUE ...
python -m src.operational_cli daily-post --source daiwa --dry-run --max-targets 1
```

The preview command generates and hashes copy, enqueues preview delivery, and clearly
reports `submission_eligible=false`. After the exact authorization command, the dry-run
must select the same unchanged row and persist no `click_started_at`. Neither command
creates a Facebook submission event.

- [ ] **Step 3: Pass tests and run production dry-run**

Require success/no-action exit `0`, one candidate at most, Telegram preview delivered, and
EstateBoard dry-run state not shown as posted.

- [ ] **Step 4: Commit**

```powershell
git add src/operational_cli.py tests/test_daiwa_canary_selection.py
git commit -m "feat: select one guarded DAIWA canary"
```

### Task 6: Execute exactly one live post

**Files:**
- Runtime SQLite/result/evidence only.

- [ ] **Step 1: Present immutable authorization details**

Present property ID/name, group ID/name, source-row fingerprint, source/body hashes,
generation fingerprint, publication authorization ID, job approval ID, and proposed run
ID. Obtain an explicit 15-minute `operator_live_rollout` authorization; broad prior
permission is not the final-click authorization.

- [ ] **Step 2: Disable scheduled posting and open rollout circuit**

Export task XML first. Keep every posting task disabled. Monitoring and downstream
reconciliation may remain enabled only if tests prove they cannot submit. Confirm
`FBAutoposter-RolloutLeaseMonitor` is enabled, has a successful sentinel run, and has a
next run before acquiring the live lease.

- [ ] **Step 3: Re-run read-only preflight**

Require healthy Chrome/session, exact Facebook identity and group ID, no challenge,
restriction, warning, membership question, duplicate, uncertain attempt, stale source,
changed rules, or changed hash.

- [ ] **Step 4: Acquire the bounded live lease**

Use a 60-second heartbeat and 15-minute hard expiry bound to the exact run/process and
authorization IDs. Close the rollout circuit only while that lease is healthy.

- [ ] **Step 5: Submit once in headed Facebook**

Persist the attempt before composer interaction and `click_started_at` before the final
click. Do not submit a second target. On any post-click ambiguity, mark
`uncertain/reconcile_only`, reopen the circuit, and verify only.

- [ ] **Step 6: Require public permalink verification**

Only an HTTPS Facebook permalink matching the exact property/group promotes the target to
`posted`. Missing/pending/ambiguous evidence is not posted.

### Task 7: Reconcile Telegram and EstateBoard without reposting

**Files:**
- Modify: `docs/recovery-runbook.md`

- [ ] **Step 1: Reconcile outbox destinations**

Require Telegram delivered with a remote message ID and EstateBoard HTTP/DOM readback with
the same origin run/property/group IDs. Reconciliation must not import or construct
FacebookPoster.

- [ ] **Step 2: Report the user-visible record**

Report property name/ID, community name/ID, verified timestamp, permalink, Telegram
delivery, and EstateBoard URL/status.

- [ ] **Step 3: Leave automation safe**

Keep scheduled posting disabled on any mismatch or ambiguity. If every assertion passes,
enable only the previously reviewed daily schedule at unchanged conservative volume.
Automatic community joining remains disabled.

- [ ] **Step 4: Final verification and sanitized commit**

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
git diff --check
```

Add only sanitized evidence to the runbook. Never commit tokens, chat IDs, cookies,
profiles, private paths, screenshots, DB files, or post bodies.

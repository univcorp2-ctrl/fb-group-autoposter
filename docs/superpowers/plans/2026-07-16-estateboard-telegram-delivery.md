# EstateBoard and Telegram Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish durable Facebook posting truth to EstateBoard and Telegram idempotently without ever causing another Facebook submission when delivery fails.

**Architecture:** SQLite keeps Facebook state and a separate outbox. A full-snapshot `fb_post_status.json` overlay is joined into EstateBoard by canonical property ID and verified after deployment; Telegram uses the same outbox and stable delivery keys.

**Tech Stack:** Python 3.11, SQLite, JSON, requests, Playwright isolated browser context, Cloudflare Pages/Wrangler, pytest.

---

**Prerequisite:** Complete Tasks 1–6 of
`docs/superpowers/plans/2026-07-16-runtime-safety-recovery.md`. This plan requires durable
`run_id`, `approval_id`, `attempt_id`, submission state, `src/run_result.py`, and
`src/operational_cli.py`. Record the prerequisite commit IDs before execution and stop for
plan re-review if those APIs differ.

## File map

- Create `src/outbox.py`: idempotent downstream events and reconciliation.
- Create `src/status_overlay.py`: canonical IDs and full SQLite snapshot.
- Modify `src/queue_db.py`: outbox tables and delivery states.
- Modify `src/poster.py`, `src/post_verify.py`, and `scripts/verify_posts.py`: atomic event producers.
- Modify `src/approval.py`: idempotent Telegram delivery API.
- Modify `scripts/sync_estateboard_status.py`: overlay generation/deployment/readback.
- Create `scripts/reconcile_delivery.py`: downstream-only reconciliation command.
- Modify EstateBoard `docs/index.html`/its actual root JS source to join the overlay.
- Create tests for outbox, canonical IDs, snapshot corrections, Telegram, and deployed DOM readback.

### Task 1: Add durable idempotent outbox

**Files:**
- Create: `src/outbox.py`
- Modify: `src/queue_db.py`
- Test: `tests/test_outbox.py`

- [ ] Write failing tests for unique event keys, lease/retry, delivered state, and crash
  recovery. Attempt events key on `(attempt_id, destination, event_type)`; environment,
  recovery, and summary events key on `(run_id, destination, event_type, subject_id)`.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_outbox.py -v`; expect missing API failure.
- [ ] Implement additive tables and one `finalize_attempt_and_enqueue(...)` transaction.
  Update producer call sites in `src/poster.py`, `src/post_verify.py`, and
  `scripts/verify_posts.py` for verified, uncertain, verification promotion/demotion, and
  delivery completion. Persistent environment/recovery/summary producers use the explicit
  run-scoped key. No producer calls a delivery API directly.
- [ ] Run `tests/test_outbox.py`, `tests/test_queue_db.py`, and `tests/test_queue_recovery.py`; expect PASS.
- [ ] Commit `src/outbox.py`, `src/queue_db.py`, `src/poster.py`, `src/post_verify.py`,
  `scripts/verify_posts.py`, and tests with message `feat: add idempotent downstream delivery outbox`.

### Task 2: Define canonical property IDs and full snapshot overlay

**Files:**
- Create: `src/status_overlay.py`
- Test: `tests/test_status_overlay.py`

- [ ] Write failing tests for EstateBoard `ID`, exactly one stripped `eb-` prefix,
  `propertyId` then `id`, trim-only/case-preserving behavior, empty/duplicate/conflicting
  IDs, unmatched IDs, deterministic order, and corrections that remove stale verified rows.
  Fix the schema as `fb-post-status/v1` with top-level `schema`, RFC3339 UTC
  `generated_at`, `source_run_id`, `counts` (`properties`, `verified`, `uncertain`,
  `failed`), and `properties`. Each row contains `estateboard_id`,
  `autoposter_property_id`, `overall_status`, `latest_posted_at`, and sorted `groups` of
  `group_id`, `group_name`, `status`, `posted_at`, and HTTPS `permalink`. Group facts are
  never collapsed. Overall precedence is `uncertain` > `verified` > `failed`; counts count
  property rows by that rule.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_status_overlay.py -v`; expect FAIL.
- [ ] Implement `canonical_estateboard_id`, `canonical_autoposter_id`,
  `build_full_snapshot`, and atomic JSON replacement with `schema`, `generated_at`,
  `source_run_id`, counts, and per-property state/permalinks.
- [ ] Verify the file contains no token, post body, cookie, or private path.
- [ ] Run tests and commit with `git commit -m "feat: export durable Facebook status overlay"`.

### Task 3: Make EstateBoard consume the overlay durably

**Files:**
- Modify: `scripts/sync_estateboard_status.py`
- Modify in EstateBoard repo: `G:\マイドライブ\AI_Agents\github\repos\EstateBoard\docs\index.html`
- Test: `tests/test_sync_estateboard_overlay.py`
- Test in EstateBoard repo: `G:\マイドライブ\AI_Agents\github\repos\EstateBoard\tests\test_fb_post_overlay.py`

- [ ] Write failing fixture tests proving a daily replacement of `data.json` does not remove overlay state and missing/stale overlay displays `unknown/stale`, not zero.
- [ ] Write failing DOM contract tests for `data-fb-overlay-schema`, `data-fb-overlay-run-id`, `data-fb-overlay-count`, `data-fb-joined-count`, and `data-fb-unmatched-count`.
- [ ] Implement full-snapshot copy to `EstateBoard/docs/fb_post_status.json`; stop patching generated posting fields as source of truth.
- [ ] Implement exact-ID client join and visible stale/unmatched warning.
- [ ] Run autoposter focused tests, then from EstateBoard run
  `.venv\Scripts\python.exe -m pytest tests/test_fb_post_overlay.py -v`; expect PASS.
- [ ] Commit autoposter and EstateBoard changes separately with intentional file lists.

### Task 4: Add deployment readback and isolated browser verification

**Files:**
- Modify: `scripts/sync_estateboard_status.py`
- Create: `src/web_delivery_probe.py`
- Test: `tests/test_web_delivery_probe.py`

- [ ] Write failing tests for HTTP schema/run/count readback, DOM diagnostic equality,
  visible verified marker, unmatched failure, timeout, a no-Git-diff redeployment after a
  prior deploy failure, and use of a temporary non-Facebook browser profile.
- [ ] Implement deployment only after snapshot validation; verify exact deployed run ID
  after Wrangler returns. Reconciliation must invoke deploy/readback even when overlay
  bytes are unchanged and Git has no diff, covering commit/push success followed by
  deployment/readback failure.
- [ ] Keep web state pending as `web_sync_failed` until both HTTP and DOM probes pass; never modify Facebook state.
- [ ] Run tests and commit with `git commit -m "feat: verify EstateBoard overlay delivery"`.

### Task 5: Route Telegram through the outbox

**Files:**
- Modify: `src/approval.py`
- Modify: `src/outbox.py`
- Test: `tests/test_telegram_outbox.py`
- Modify: `tests/test_persistent_alerts.py`

- [ ] Write failing tests for verified, uncertain, challenge, recovery, completion, and
  delivery-pending messages; assert stable idempotency keys and token redaction. Model the
  crash window: a timeout/disconnect after `sendMessage` is `delivery_ambiguous`, never an
  automatic resend. Only an operator `reconcile-delivery --confirm-not-received` may create
  a new explicit resend event.
- [ ] Test that missing-browser/provider failures create persistent environment alerts with stable reason codes.
- [ ] Implement outbox delivery using existing message wording and configured destination; preserve acknowledgement behavior.
- [ ] Verify current approval/persistent-alert tests and commit with `git commit -m "feat: deliver Telegram notices idempotently"`.

### Task 6: Add downstream-only reconciliation

**Files:**
- Create: `scripts/reconcile_delivery.py`
- Modify: `src/operational_cli.py`
- Modify: `src/run_result.py`
- Modify: `scripts/monitor.py`
- Test: `tests/test_delivery_reconciliation.py`
- Test: `tests/test_monitor.py`

- [ ] Write a failing test with a fake `FacebookPoster` that raises if constructed; reconcile pending web/Telegram events and assert it is never touched.
- [ ] Implement bounded leases, destination-specific retry/backoff, and exact convergence.
  The original posting history result remains immutable at exit 50. Reconciliation writes a
  new `fb-autoposter-run/v1` result with its own run ID plus `origin_run_id`, updates SQLite
  delivery state, and returns success/0 only when both destinations are delivered. Latest
  result and monitor resolve the origin through SQLite; Task Scheduler observes the
  reconciliation run. Telegram ambiguous events remain blocked pending operator evidence.
- [ ] Add `sync-status`/`reconcile-delivery` CLI paths and semantic results.
- [ ] Run reconciliation and monitor tests and commit all listed files with
  `git commit -m "feat: reconcile delivery without reposting Facebook"`.

### Task 7: Verify local and deployed delivery contracts

**Files:**
- Modify: `README.md`
- Modify: `README_ja.md`

- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_outbox.py tests/test_status_overlay.py tests/test_sync_estateboard_overlay.py tests/test_web_delivery_probe.py tests/test_telegram_outbox.py tests/test_delivery_reconciliation.py -v`.
- [ ] Run full pytest and Ruff; expect PASS.
- [ ] In dry-run fixture mode, build an overlay, serve EstateBoard locally, and verify all DOM diagnostics without Facebook.
- [ ] Document web/Telegram states, stale warnings, and reconciliation commands.
- [ ] Commit with `git commit -m "docs: document verified posting delivery"`.

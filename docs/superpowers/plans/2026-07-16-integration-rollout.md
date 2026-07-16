# Integration and Live Recovery Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the three completed subsystems, install truthful hidden scheduling, and restore one safely verified daily Facebook post with EstateBoard and Telegram evidence.

**Architecture:** Merge only tested subsystem commits, validate all sources/secrets read-only, export current tasks, run no-browser and cloned-profile gates, then perform one bounded live submission. Every later step consumes the same run ID and durable result; any risk or ambiguity stops rollout.

**Tech Stack:** Git, Python 3.11, pytest/Ruff, Windows Task Scheduler, Playwright headed Chrome, SQLite, Cloudflare Pages, Telegram.

---

**Prerequisite:** Runtime, AI-gateway, and delivery plans must be complete on the same
`codex/fb-autoposter-recovery` branch, each with passing full-suite evidence and a final
milestone commit. Before this plan starts, write their immutable commit IDs to
`docs/integration-manifest.json`; unresolved names or a dirty tree block rollout. The
design base is commit `49ffcce`.

### Task 1: Integrate and audit scope

**Files:**
- Modify: `docs/account-protection-compatibility.md`
- Create: `docs/recovery-runbook.md`
- Create: `docs/integration-manifest.json`

- [ ] Record exact final commit SHAs for `runtime`, `ai_gateway`, and `delivery` in the
  integration manifest. Verify each with `git cat-file -e <sha>^{commit}` and
  `git merge-base --is-ancestor <sha> HEAD`. Because plans execute sequentially on the same
  branch, no merge is needed; if any subsystem was implemented elsewhere, stop and amend
  this reviewed plan with the exact cherry-pick order before changing this branch.
- [ ] Confirm `git status --porcelain` is empty except the new rollout documents, only
  planned files changed, and user-owned `desktop.ini` files are absent from commits.
- [ ] Run `git diff 49ffcce...HEAD --stat` and map every changed posting symbol to the compatibility matrix.
- [ ] Run cross-subsystem tests for launcher→CLI→SQLite/result, gateway→approval→attempt,
  and attempt→outbox→web/Telegram before the full suite.
- [ ] Run full pytest and Ruff; require all PASS.
- [ ] Record exact rollback commits and stop conditions in the runbook.
- [ ] Commit documentation with `git commit -m "docs: add Facebook recovery runbook"`.

### Task 2: Validate runtime inputs without external writes

**Files:**
- Runtime only; no tracked secret changes.

- [ ] Confirm `G:` mount, operator property source, synchronized EstateBoard JSON, repo `.env`, ignored DB/profile paths, system Chrome, and pinned worktree `.venv`.
- [ ] Compare source age/size/SHA-256 and validate exact broker-sharing `TRUE` eligibility.
- [ ] Read Telegram credentials through the existing ignored `.env`; compare to the private workbook without printing values.
- [ ] Run `healthcheck --no-browser`, `preflight --source-only`, and `ai-profile test
  template`. Each result must have schema `fb-autoposter-run/v1`, one matching run ID in
  latest/history/SQLite, outcome `success` or `no_action`, exit `0`, no open global circuit,
  and no secondary risk reason.
- [ ] If any check fails, write result/Telegram environment alert and stop without Facebook.

### Task 3: Export and test scheduler migration

**Files:**
- Runtime archive: `_archive/<date>-task-scheduler-recovery/` outside the repository worktree.

- [ ] Export every existing `FBAutoposter-*` task XML and record name/action/trigger/settings hashes.
- [ ] Run launcher sentinel integration tests using the exact installed PowerShell/VBS paths.
- [ ] Open a durable global `rollout_in_progress` circuit and install all posting tasks
  disabled. Preserve unchanged times/random delays, hidden action chain, pinned
  interpreter, working directory, interactive-user logon mode, `IgnoreNew`,
  `StartWhenAvailable`, and no automatic restart. Monitoring/reconciliation tasks may be
  enabled only if they cannot submit.
- [ ] Invoke a no-browser health task manually and confirm no console appears, Task Scheduler receives the child exit, and latest/history/SQLite share one run ID.
- [ ] On any later rollout failure, keep/disable new posting tasks before restoring exported
  XML; restored posting tasks also remain disabled until the operator chooses rollback.

### Task 4: Perform cloned-profile Chrome compatibility gate

**Files:**
- Runtime ignored profile candidates/backups/evidence only.

- [ ] Acquire the application/profile lock and prove no Chrome/Playwright process uses `profiles/main`.
- [ ] Create validated rollback backup and redacted manifest evidence.
- [ ] Clone to a versioned candidate and launch stable Chrome headed with the preserved contract.
- [ ] Perform only Facebook home/authentication/challenge and UA checks; do not open any group composer.
- [ ] Exact pass result: schema `fb-autoposter-run/v1`, outcome `success`, exit `0`, reason
  `success`, authenticated identity/group probes known, UA compatible, no challenge marker,
  and matching run ID in result/SQLite. UA mismatch, challenge, restriction, unknown
  identity, or migration error opens its specified circuit, disables posting tasks, retains
  rollback, alerts Telegram, and stops.
- [ ] If healthy, promote the tested candidate atomically, retain rollback, close Chrome, and run a separate explicit read-only preflight to clear only eligible environment/session circuits.

### Task 5: Verify dry-run selection and approval

**Files:**
- Runtime results/DB only.

- [ ] Run `daily-post --dry-run --max-targets 1` using the template AI profile and require
  outcome `success|no_action`, exit `0`, no click-started attempt, and no Facebook outbox
  event.
- [ ] Confirm one eligible current property, one confirmed enabled group, unchanged limits/pacing, deterministic body hash/fingerprint, and no Facebook submission.
- [ ] Confirm approval state/hash/fingerprint and that a changed fixture invalidates approval.
- [ ] Confirm EstateBoard overlay and Telegram dry-run notification use fixture/outbox mode only.

### Task 6: Execute one bounded live post

**Files:**
- Runtime state/evidence only.

- [ ] Present the selected property ID, group ID, immutable `approval_id`, source hash, body
  hash, generation fingerprint, and proposed run ID to the operator. Record an explicit
  `operator_live_rollout` approval with a 15-minute expiry. Do not accept the earlier broad
  implementation authorization as this irreversible posting authorization.
- [ ] Re-run explicit preflight after authorization and require schema
  `fb-autoposter-run/v1`, outcome `success`, exit `0`, exact authorized IDs/hashes/fingerprint,
  no open circuit other than `rollout_in_progress`, no prior post today, no
  duplicate/uncertain attempt, fresh source, and matching group identity. Any changed value
  invalidates authorization and stops.
- [ ] While every scheduled posting task remains disabled, atomically clear
  `rollout_in_progress` and create a durable `rollout_live_lease` bound to the authorized
  run ID, process identity, 60-second heartbeat, and 15-minute hard expiry immediately
  before the authorized command. Execute
  `daily-post --run-id <authorized_run_id> --max-targets 1` in visible headed Chrome. If
  process start fails, immediately reopen the global circuit. The launcher `finally` path
  reopens it on every non-success/non-50 exit, abrupt child termination, or missing terminal
  result. An independent monitor reopens it when the lease heartbeat is older than 60
  seconds or the hard expiry passes. Thus the circuit is closed only while that exact
  authorized process is demonstrably active. Do not change UA, profile lineage, pacing,
  typing, targeting, or limits.
- [ ] In the same SQLite transaction immediately before setting `click_started_at`, require
  the live authorization to be unexpired and exactly bound to the command run ID,
  property/group IDs, `approval_id`, source/body hashes, generation fingerprint, and active
  rollout lease/heartbeat. Expiry
  or mismatch aborts pre-click, reopens `rollout_in_progress`, leaves tasks disabled, and
  returns `preflight_blocked`/20 without clicking.
- [ ] Persist attempt before composer and `click_started_at` before final click.
- [ ] On any post-click error, atomically mark `uncertain/reconcile_only`, outcome
  `submission_ambiguous`, exit `40`, reopen `rollout_in_progress`, keep posting tasks
  disabled, and use verification only.
- [ ] On success, require public match, HTTPS permalink, SQLite `posted`, and exact
  property/group/attempt/run IDs. Delivery-pending is outcome `posted_delivery_pending`,
  exit `50`; complete delivery is `success`, exit `0`. After the single submission reaches
  a terminal Facebook state and Chrome closes, reopen `rollout_in_progress` so no second
  post can occur while delivery acceptance is checked.

### Task 7: Verify every delivery and leave automation healthy

**Files:**
- Modify: `docs/recovery-runbook.md` with sanitized evidence summary.

- [ ] Confirm SQLite target/attempt, permalink, local XLSX/CSV, full overlay, deployed
  EstateBoard DOM diagnostics, groups page, Telegram receipt, outbox delivered states, and
  terminal result share the authorized run/property/group IDs.
- [ ] If exit `50`, run downstream reconciliation and require a new success/0 result linked
  by `origin_run_id`, both outbox destinations delivered, and a test/runtime trace proving
  no Facebook constructor/submission. Telegram ambiguous delivery requires operator
  confirmation, not automatic resend.
- [ ] Confirm Task Scheduler status and monitor agree with the canonical result.
- [ ] Only after all live and delivery assertions pass, clear `rollout_in_progress`, enable
  posting tasks, and verify their next-run conditions. Any failure keeps them disabled.
- [ ] Run the full test/Ruff suite once more and update the compatibility matrix.
- [ ] Commit only sanitized runbook evidence; never commit tokens, cookies, profiles, DB, screenshots, post body, or private paths.

### Task 8: Observe without increasing volume

**Files:**
- Runtime only.

- [ ] Leave existing conservative posting thresholds unchanged.
- [ ] Verify the next scheduled launcher produces a truthful result and no console window.
- [ ] Confirm the next EstateBoard daily regeneration preserves the overlay join.
- [ ] Treat any challenge, restriction, ambiguity, or stale overlay as a stop/reconcile condition, not a reason to retry Facebook.

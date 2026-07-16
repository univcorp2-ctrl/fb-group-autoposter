# Runtime Safety Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore truthful background execution and headed Chrome startup while preserving every existing Claude Code account-protection behavior and preventing duplicate or ambiguous resubmission.

**Architecture:** Add a repository-owned operational CLI, atomic run-result contract, durable circuits/submission attempts, and a hidden Windows launcher. Centralize Playwright launch options behind a compatibility-checked browser runtime that initially changes only the browser channel and operates on a tested profile clone.

**Tech Stack:** Python 3.11, asyncio, SQLite, Playwright, pytest, PowerShell, VBScript, Windows Task Scheduler.

---

## File map

- Create `src/run_result.py`: versioned result schema, atomic latest/history writes, exit mapping.
- Create `src/circuits.py`: durable global/group/environment circuit API.
- Create `src/browser_runtime.py`: Chrome discovery, UA/profile compatibility, cloned-profile probes.
- Create `src/operational_cli.py`: shared `preflight`, `daily-post`, `verify-posts`, `keepalive`, `healthcheck`, `sync-status` dispatcher.
- Create `scripts/launch_hidden.ps1`: run-id owner, logging, child wait, fallback finalization.
- Create `scripts/launch_hidden.vbs`: no-console shim that waits and propagates the launcher exit.
- Modify `src/queue_db.py`: schema migration for runs, circuits, approvals, attempts, and click boundary.
- Modify `src/poster.py`: use browser runtime and durable submission transitions without altering pacing/typing.
- Modify `src/session.py`: separate ordinary expiry from challenges and clone-only recovery.
- Modify `scripts/run_daily.py`, `scripts/keepalive.py`, `scripts/verify_posts.py`: thin wrappers over the shared CLI.
- Modify `scripts/install_windows_tasks.ps1`: use hidden launcher, `IgnoreNew`, no scheduler retry.
- Create focused tests under `tests/test_run_result.py`, `tests/test_circuits.py`, `tests/test_browser_runtime.py`, `tests/test_submission_attempts.py`, `tests/test_operational_cli.py`, and `tests/test_hidden_launcher.py`.

### Task 1: Freeze the Claude compatibility baseline

**Files:**
- Create: `docs/account-protection-compatibility.md`
- Modify: `tests/test_posting_reliability.py`
- Modify: `tests/test_poster_preflight.py`
- Modify: `tests/test_queue_db_extended.py`
- Create: `tests/test_protection_compatibility.py`

- [ ] **Step 1: Record the baseline matrix**

Add rows for headed mode, `profiles/main`, configured UA, viewport, scheduler jitter,
inter-post range, navigation dwell, mouse/scroll pauses, 18-character typed prefix,
active hours, daily/group limits, maximum groups per browser context, cooldowns,
duplicate/uncertain guards, retry exclusions, challenge stop, backup/restore,
membership/group-rule checks, evidence capture, approval behavior, persistent Telegram
alerts, read-only uncertain-post verification, and no auto-join. Record current symbol/test,
configuration threshold, planned touch point, and exact regression assertion.

- [ ] **Step 2: Write failing characterization tests for uncovered behavior**

Use source-level configuration fakes rather than Facebook. Example:

```python
def test_browser_contract_preserves_existing_identity(settings):
    contract = BrowserContract.from_settings(settings)
    assert contract.headless is False
    assert contract.user_data_dir == Path("profiles/main")
    assert contract.user_agent == settings.browser_user_agent
    assert contract.viewport == {"width": 1366, "height": 900}
```

- [ ] **Step 3: Run characterization tests and verify expected failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_protection_compatibility.py -v`
Expected: FAIL because `BrowserContract` does not yet exist.

- [ ] **Step 4: Add only the minimal read-only contract extraction**

Create `BrowserContract` in `src/browser_runtime.py` without changing `FacebookPoster`.

- [ ] **Step 5: Run old and new protection tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_protection_compatibility.py tests/test_posting_reliability.py tests/test_poster_preflight.py tests/test_queue_db_extended.py -v`
Expected: PASS; matrix shows no behavior removed.

- [ ] **Step 6: Commit**

```powershell
git add docs/account-protection-compatibility.md src/browser_runtime.py tests/test_protection_compatibility.py tests/test_posting_reliability.py tests/test_poster_preflight.py tests/test_queue_db_extended.py
git commit -m "test: freeze Facebook account protection baseline"
```

### Task 2: Add atomic operational run results

**Files:**
- Create: `src/run_result.py`
- Modify: `src/queue_db.py`
- Test: `tests/test_run_result.py`

- [ ] **Step 1: Write failing schema and atomicity tests**

```python
def test_terminal_result_is_atomic_and_versioned(tmp_path):
    store = RunResultStore(tmp_path)
    run = store.start("daily-post", run_id="run-1")
    store.finish(run, outcome="preflight_blocked", reason="browser_missing")
    result = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert result["schema"] == "fb-autoposter-run/v1"
    assert result["run_id"] == "run-1"
    assert result["exit_code"] == 20
    assert not list(tmp_path.glob("*.tmp"))
```

Cover all outcome/exit mappings, launcher finalization compare-and-replace, redaction,
dated history, freshness, and an additive SQLite `runs` row sharing the same `run_id`.

- [ ] **Step 2: Verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_run_result.py -v`
Expected: FAIL with missing `src.run_result`.

- [ ] **Step 3: Implement the minimal store**

Use `tempfile.NamedTemporaryFile(delete=False, dir=target.parent)`, `flush`, `os.fsync`,
and `os.replace`. Reject a second terminal write for the same run unless the existing
latest record is nonterminal. Add `runs` migration/API to `QueueDB`; a healthy terminal
result is fresh only when it is under 30 hours old and its run ID matches SQLite, except a
documented launcher-owned pre-SQLite terminal failure.

- [ ] **Step 4: Verify pass and lint**

Run: `.venv\Scripts\python.exe -m pytest tests/test_run_result.py -v && .venv\Scripts\python.exe -m ruff check src/run_result.py tests/test_run_result.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/run_result.py src/queue_db.py tests/test_run_result.py
git commit -m "feat: add atomic operational run results"
```

### Task 3: Add durable circuits and submission attempts

**Files:**
- Create: `src/circuits.py`
- Modify: `src/queue_db.py`
- Test: `tests/test_circuits.py`
- Test: `tests/test_submission_attempts.py`

- [ ] **Step 1: Write failing migration and circuit tests**

Cover global precedence, group/environment scope, every exact threshold/window in the
specification, scheduled inability to clear, expiry plus explicit preflight, and migration
of an existing database. Add integration fakes proving preflight/session/failure handlers
open the expected real circuit and circuit precedence blocks `FacebookPoster`.

- [ ] **Step 2: Write failing click-boundary recovery tests**

```python
def test_attempt_with_click_started_can_never_become_eligible(db):
    approval = db.approve_target("p", "g", body_hash="b", source_hash="s", generation_fingerprint="f")
    attempt = db.begin_attempt("p", "g", approval["approval_id"])
    db.mark_click_started(attempt)
    db.recover_incomplete_attempts()
    assert db.target_state("p", "g") == "uncertain/reconcile_only"
    assert db.can_submit("p", "g") is False
```

Also inject crashes before click, after click, after response, and before final SQLite
update. Cover every transition-table row: matching approval to `approved`, pre-click abort
back to `approved`, source/body/fingerprint invalidation to `pending_approval`,
verification-only promotion/demotion, and the permanent prohibition on making a
click-started property/group eligible again.

- [ ] **Step 2a: Write failing approval-state tests**

Assert default `AUTO_APPROVE=false`; immutable `approval_id`; provenance source/time;
binding to property/group/source hash/body hash/generation fingerprint; configured
`auto_policy` only after all gates; stale approval invalidation; and refusal to begin an
attempt unless all approval fields match.

- [ ] **Step 3: Verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests/test_circuits.py tests/test_submission_attempts.py -v`
Expected: FAIL for missing tables/APIs.

- [ ] **Step 4: Implement additive SQLite migrations and APIs**

Use `CREATE TABLE IF NOT EXISTS`, explicit transactions, unique
`(property_id, group_id, approval_id)`, and no destructive rewrite of existing `posted_at`
or target statuses. Implement `pending_approval`/`approved`, immutable approval rows, and
hash/fingerprint validation in the same transaction as attempt creation.

- [ ] **Step 5: Verify old DB behavior remains intact**

Run: `.venv\Scripts\python.exe -m pytest tests/test_circuits.py tests/test_submission_attempts.py tests/test_queue_db.py tests/test_queue_db_extended.py tests/test_queue_recovery.py tests/test_approval.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/circuits.py src/queue_db.py tests/test_circuits.py tests/test_submission_attempts.py
git commit -m "feat: persist safety circuits and submission attempts"
```

### Task 4: Add safe Chrome and profile compatibility runtime

**Files:**
- Modify: `src/browser_runtime.py`
- Modify: `src/session.py`
- Test: `tests/test_browser_runtime.py`
- Modify: `tests/test_session_restore.py`

- [ ] **Step 1: Write failing Chrome discovery and mismatch tests**

Assert system Chrome discovery, explicit `channel="chrome"`, unchanged viewport/UA/profile contract, missing Chrome reason, and verified UA mismatch returning `ua_mismatch` rather than launching a composer.

- [ ] **Step 2: Write failing clone/promotion tests**

Use temporary fake profiles. Assert rollback manifest creation, clone-only probe, atomic promotion, retention of untouched rollback, cleanup after failure, and zero promotion when a challenge is returned.

- [ ] **Step 3: Verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests/test_browser_runtime.py tests/test_session_restore.py -v`
Expected: FAIL for missing runtime functions.

- [ ] **Step 4: Implement browser preflight without Facebook writes**

Expose `discover_chrome()`, `build_launch_kwargs()`, `profile_manifest()`,
`prepare_candidate()`, `probe_candidate(probe_callable)`, and `promote_candidate()`.
Under the application lock, create `profiles/backups/<run_id>/main`, fsync/validate its
manifest, clone it to `profiles/candidates/<run_id>/main`, probe only the candidate, rename
the live directory to a versioned retained rollback path, then rename the tested candidate
to the unchanged live path. On any rename failure, restore the retained live directory;
never delete the validated backup. Exclude caches/cookies from logs and evidence hashes.

- [ ] **Step 5: Implement ordinary-expiry recovery boundary**

Challenges never call restore. Plain expiry may prepare/probe a candidate but returns `circuit_open=True` and `submission_allowed=False`; only a later explicit preflight may clear it.

- [ ] **Step 6: Verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_browser_runtime.py tests/test_session_restore.py tests/test_challenge_detection.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/browser_runtime.py src/session.py tests/test_browser_runtime.py tests/test_session_restore.py
git commit -m "feat: add fail-closed Chrome profile compatibility checks"
```

### Task 5: Integrate the runtime into FacebookPoster without changing behavior

**Files:**
- Modify: `src/poster.py`
- Modify: `src/orchestrator.py`
- Modify: `tests/test_protection_compatibility.py`
- Modify: `tests/test_posting_reliability.py`
- Test: `tests/test_poster_attempt_integration.py`

- [ ] **Step 1: Write failing integration tests with fake Playwright pages**

Assert the exact existing pacing ranges, prefix split, headed mode, UA, viewport, duplicate checks, challenge exceptions, and no retries for blocked/ambiguous states. Assert `click_started_at` commits before the fake final click.

- [ ] **Step 2: Verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests/test_poster_attempt_integration.py tests/test_protection_compatibility.py -v`
Expected: FAIL until `FacebookPoster` uses runtime/attempt APIs.

- [ ] **Step 3: Replace only launch construction and state writes**

Call `build_launch_kwargs(settings)` and the attempt API. Wire circuit checks before
browser construction and map session classification, posting blocks, selector failure,
ambiguity, runtime/profile/source failure, and explicit preflight clearance to
`CircuitStore`. A circuit must govern real orchestrator/poster execution, not merely be
recorded. Do not edit `_human_pause`, `_random_interval`, `_split_body_for_typing`,
`_enter_body`, active-hour logic, limits, selectors, group rules, or verifier semantics.

- [ ] **Step 4: Verify focused and complete suite**

Run: `.venv\Scripts\python.exe -m pytest tests/test_poster_attempt_integration.py tests/test_posting_reliability.py tests/test_poster_preflight.py tests/test_run_cycle_grouped.py -v`
Expected: PASS.

- [ ] **Step 5: Update compatibility matrix and commit**

```powershell
git add src/poster.py src/orchestrator.py tests/test_poster_attempt_integration.py tests/test_protection_compatibility.py docs/account-protection-compatibility.md
git commit -m "refactor: integrate safe runtime without changing posting cadence"
```

### Task 6: Add the common operational CLI

**Files:**
- Create: `src/operational_cli.py`
- Modify: `scripts/run_daily.py`
- Modify: `scripts/keepalive.py`
- Modify: `scripts/verify_posts.py`
- Modify: `scripts/healthcheck.py`
- Test: `tests/test_operational_cli.py`

- [ ] **Step 1: Write failing dispatch/result tests**

Cover all named commands, required `--run-id`, insertion/finalization of the same SQLite
run row, semantic exit codes, exception finalization, result freshness comparison, and
`preflight` never opening a composer. Reject execution before browser activity if the
launcher start/result sink is missing or unwritable.

- [ ] **Step 2: Verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_operational_cli.py -v`
Expected: FAIL for missing CLI.

- [ ] **Step 3: Implement argparse dispatcher and thin legacy wrappers**

Legacy scripts call `operational_cli.main([command])` so existing task/script names keep
working during migration. The launcher path passes its allocated `--run-id`; interactive
legacy invocation allocates one through the same result-start API before dispatch.

- [ ] **Step 4: Verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_operational_cli.py tests/test_dry_run.py tests/test_ensure_loop.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/operational_cli.py scripts/run_daily.py scripts/keepalive.py scripts/verify_posts.py scripts/healthcheck.py tests/test_operational_cli.py
git commit -m "feat: add shared operational CLI"
```

### Task 7: Add truthful no-console Windows launching

**Files:**
- Create: `scripts/launch_hidden.ps1`
- Create: `scripts/launch_hidden.vbs`
- Modify: `src/operational_cli.py`
- Modify: `scripts/install_windows_tasks.ps1`
- Test: `tests/test_hidden_launcher.py`

- [ ] **Step 1: Write failing sentinel launcher tests**

Run the PowerShell launcher with fake child scripts returning `0`, `20`, `30`, `40`, `50`,
and `60`; assert exact propagation, atomic launcher start record before the child, required
`--run-id`, one identical ID in latest/history/SQLite, dated logs, missing-interpreter
fallback, unwritable-start-sink abort before child, abrupt-child finalization, freshness,
preservation of a valid Python terminal result, and one sanitized minimal Telegram alert
attempt for both `launcher_failed` and launcher-finalized `internal_error`. Mock the HTTP
endpoint and assert token/chat ID never appear in logs/results and notification failure
does not overwrite the canonical exit/result.

- [ ] **Step 2: Verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/test_hidden_launcher.py -v`
Expected: FAIL because launcher files are missing.

- [ ] **Step 3: Implement launcher and VBS wait contract**

PowerShell allocates the run ID, atomically writes the nonterminal start record, and aborts
with 60 before Python/browser activity if that write fails. It invokes the fully quoted
absolute repository-pinned `.venv\Scripts\python.exe`, passes `--run-id`, sets the absolute
repository working directory, and waits with `Start-Process -Wait -PassThru -WindowStyle
Hidden`, redirecting streams. VBS calls the absolute PowerShell file with window style `0`
and `bWaitOnReturn=True`, then returns `WScript.Quit(exitCode)`.
When Python cannot start or leaves no terminal result, PowerShell reads only
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the ignored `.env`, constructs a fixed
reason-code/run-ID message with no post body/private path, attempts one bounded
`sendMessage`, redacts errors, and records only `notification_attempted`/`notification_state`
in the launcher-owned result. It never retries or changes exit `60`.

- [ ] **Step 4: Rewrite task actions without changing schedule jitter**

Preserve existing trigger times, `RandomDelay`, and `StartWhenAvailable`. Change only the
action chain, set `IgnoreNew`, remove `RestartCount`/`RestartInterval` for posting tasks,
and register posting tasks for the interactive operator account with `RunOnlyIfLoggedOn`
semantics so headed Chrome appears in that desktop session. Export current task XML before
replacement and test the generated principal/action/settings before registration.

Use this exact contract table; add the missing read-only/support command names to
`src/operational_cli.py` as thin wrappers over the existing scripts:

| Tasks | CLI command |
| --- | --- |
| `FBAutoposter-Morning`, `-Midday`, `-Afternoon`, `-Evening` | `daily-post` |
| `FBAutoposter-Keepalive` | `keepalive` |
| `FBAutoposter-Monitor-AM`, `-Monitor-PM` | `healthcheck` |
| `FBAutoposter-StatusDB`, `-Bridge` | `sync-status` |
| `FBAutoposter-Verify`, `-Verify-PM` | `verify-posts` |
| `FBAutoposter-Discover` | `discover-groups` |
| `FBAutoposter-Engagement`, `-Engagement-PM` | `monitor-engagement` |
| `FBAutoposter-Notifications`, `-Notifications-PM` | `monitor-notifications` |
| `FBAutoposter-NotionSync`, `-NotionSync-PM` | `sync-notion` |
| `FBAutoposter-Renotify` | `renotify-alerts` |

At installation, resolve the current interactive operator to its exact Windows SID using
`[Security.Principal.WindowsIdentity]::GetCurrent().User.Value`; use that SID as `UserId`,
`LogonType=Interactive`, and `RunLevel=Limited` for every table row. The action is absolute
`$env:SystemRoot\System32\wscript.exe`, with one fully quoted absolute
`scripts\launch_hidden.vbs --command <allowlisted-command>` argument and the absolute repo
working directory. Settings assertions are `MultipleInstances=IgnoreNew`,
`StartWhenAvailable=true`, `WakeToRun=true`, battery execution allowed,
`RestartCount=0`, and the existing per-task execution limit. Posting tasks are initially
disabled by the rollout plan. Parameterized tests enumerate every table row and fail on an
unknown/omitted task, wrong SID/logon/run level, non-absolute action/path, changed trigger
or random delay, unsupported command, enabled posting task, or settings mismatch.

- [ ] **Step 5: Verify launcher and static task contract**

Run: `.venv\Scripts\python.exe -m pytest tests/test_hidden_launcher.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add scripts/launch_hidden.ps1 scripts/launch_hidden.vbs src/operational_cli.py scripts/install_windows_tasks.ps1 tests/test_hidden_launcher.py
git commit -m "fix: propagate hidden background task results"
```

### Task 8: Complete runtime verification

**Files:**
- Modify: `docs/account-protection-compatibility.md`

- [ ] **Step 1: Run full unit and lint suite**

Run: `.venv\Scripts\python.exe -m pytest`
Expected: at least 253 tests plus new tests, all PASS.

Run: `.venv\Scripts\python.exe -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 2: Run non-Facebook CLI smoke tests**

Run: `.venv\Scripts\python.exe -m src.operational_cli healthcheck --no-browser`
Expected: terminal result with outcome `success` or an explicit environment reason; no browser window.

- [ ] **Step 3: Review the compatibility matrix**

Every baseline row must contain a passing test and result. Any changed behavior stops this plan for operator review.

- [ ] **Step 4: Commit documentation evidence**

```powershell
git add docs/account-protection-compatibility.md
git commit -m "docs: record runtime protection compatibility"
```

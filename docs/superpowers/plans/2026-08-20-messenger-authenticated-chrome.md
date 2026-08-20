# Messenger Authenticated Chrome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every Messenger browser entrypoint through the central authenticated Chrome `Default` profile and eliminate Guest-like Chromium launches and off-screen fixed viewports.

**Architecture:** A small Python adapter validates the immutable authenticated-profile policy, reads only the loopback port from `DevToolsActivePort`, probes the existing browser mode, and attaches over CDP without closing the externally owned Chrome. Messenger scan, draft, login, and explicit-send entrypoints reuse this adapter; unavailable or mode-mismatched sessions fail closed and retry without launching a fallback browser.

**Tech Stack:** Python 3.11, Playwright CDP, pytest, Windows Task Scheduler, PowerShell diagnostics.

---

### Task 1: Configuration policy

**Files:**
- Modify: `messenger/config.py`
- Create: `messenger/tests/test_authenticated_chrome.py`

- [ ] Write tests requiring `C:\AI-Agent\chrome-profile-authenticated`, profile directory `Default`, display mode `auto`, and no repository-local profile creation.
- [ ] Run the focused tests and confirm they fail because the current settings default to `profiles/messenger` and create that directory.
- [ ] Implement the minimal fail-closed configuration validation and safe directory creation.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: External authenticated Chrome attachment

**Files:**
- Create: `messenger/src/authenticated_chrome.py`
- Modify: `messenger/tests/test_authenticated_chrome.py`

- [ ] Write tests for bounded `DevToolsActivePort` parsing, loopback endpoint construction, browser-mode probing, non-Default rejection, stale endpoint rejection, and absence of `close()` calls.
- [ ] Run the tests and confirm the adapter is missing.
- [ ] Implement the minimal CDP attachment context manager with redacted errors and external ownership semantics.
- [ ] Re-run the tests and confirm they pass.

### Task 3: Scan and daemon migration

**Files:**
- Modify: `messenger/scripts/run_once.py`
- Modify: `messenger/scripts/run_draft_daemon.py`
- Modify: `messenger/tests/test_draft_daemon.py`
- Create: `messenger/tests/test_browser_entrypoints.py`

- [ ] Write tests proving Messenger production entrypoints do not call `launch_persistent_context`, set a fixed viewport, set a custom user agent, or keep a separate visible browser open.
- [ ] Run the tests and confirm the current launch/hold paths fail them.
- [ ] Replace scan and daemon browser creation with the shared authenticated context and structured retry state.
- [ ] Re-run focused tests and confirm they pass.

### Task 4: Visible and consequential entrypoint migration

**Files:**
- Modify: `messenger/scripts/login.py`
- Modify: `messenger/scripts/run_visible_drafts.py`
- Modify: `messenger/scripts/send_one_reply.py`
- Modify: `messenger/scripts/send_one_playwright_reply.py`
- Delete: `messenger/scripts/place_work_profile_drafts.ps1`
- Modify: `messenger/tests/test_browser_entrypoints.py`

- [ ] Write static and behavioral tests proving `Profile 1`, SendKeys JavaScript injection, bundled Chromium launch, fixed viewport, and per-script profile ownership are absent.
- [ ] Run the tests and confirm they fail on the legacy paths.
- [ ] Migrate every entrypoint to the shared adapter while retaining target, preview, stale-state, and explicit-send gates.
- [ ] Re-run focused tests and confirm they pass.

### Task 5: Composer visibility and conservative waits

**Files:**
- Modify: `messenger/src/fb_draft_writer.py`
- Create: `messenger/tests/test_fb_draft_writer.py`

- [ ] Write tests requiring `scroll_into_view_if_needed()` before composer interaction and condition-based visibility checks without Enter/Send.
- [ ] Run the tests and confirm the current writer fails the visibility contract.
- [ ] Implement the minimal visibility handling and retain final text readback.
- [ ] Re-run focused tests and confirm they pass.

### Task 6: Documentation and local runtime configuration

**Files:**
- Modify: `messenger/ARCHITECTURE_DRAFT_AUTOMATION.md`
- Modify: `messenger/.env.example`
- Modify locally, not commit: `messenger/.env`

- [ ] Document the central profile, ownership, retry, mode, block/checkpoint, and no-send boundaries.
- [ ] Replace safe local settings with the authenticated profile and `auto` mode without reading or rewriting secret values.
- [ ] Confirm no tracked file contains an account email, cookies, tokens, endpoint path, or generated personal conversation data.

### Task 7: Verification, integration, and production cutover

**Files:**
- No new production files.

- [ ] Run all `messenger/tests`, configured Ruff checks for changed Python files, and repository tests appropriate to the changed target.
- [ ] Confirm `git diff --check` and inspect the final diff.
- [ ] Commit, push, open a PR, and merge to `main`.
- [ ] Stop only the exact `FBAutoposter-MessengerDrafts` task/process tree after an idle check, update the task from merged `main`, and restart it windowlessly.
- [ ] Verify the live process tree contains no `ms-playwright\chromium-*` Messenger process, no local Messenger profile argument, and no visible off-screen Messenger window.
- [ ] Verify the daemon status shows the `Default` authenticated policy, a successful scan or a structured retry, and `send_enabled=false` unless the existing approved draft-only setting is active.


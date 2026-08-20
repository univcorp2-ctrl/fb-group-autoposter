# Messenger Authenticated Chrome Design

## Goal

Make every Messenger scan and draft-placement path use the authenticated Chrome `Default` profile in both background and visible operation, without launching Playwright's bundled Chromium, a Guest profile, an incognito profile, or a repository-local profile.

## Confirmed root cause

- `run_once.py` and `run_draft_daemon.py` call `chromium.launch_persistent_context()` with `messenger/profiles/messenger`.
- The live scheduled task therefore launches `Google Chrome for Testing` with automation-only flags including `--no-sandbox` and `--disable-sync`.
- `place_work_profile_drafts.ps1` separately hard-codes `Profile 1`.
- A fixed `1366 x 900` viewport created a `1293 x 733` outer window on a `1280 x 680` work area. The bottom 53 pixels and right 13 pixels were outside the usable desktop.
- A fixed Chrome 126 user agent is sent by a current Chrome 151 installation.

## Selected architecture

Add one Messenger-owned authenticated-session adapter. It reads the loopback endpoint published in `C:\AI-Agent\chrome-profile-authenticated\DevToolsActivePort`, verifies that the configured profile directory is exactly `Default`, and attaches with Playwright CDP. It never calls `browser.close()`, `context.close()`, or `page.close()` on the externally owned Chrome.

The scheduled daemon no longer opens or holds its own visible browser. It performs bounded scans through the shared authenticated session and then disconnects its client. If the shared session is unavailable, it records `authenticated_profile_unavailable`, keeps the daemon alive, and retries with bounded backoff. It never falls back to Guest, repository-local profiles, bundled Chromium, or a different account.

Visible Messenger work is routed through the central Executor using the same profile. The central visible Chrome is maximized to the Windows work area. Messenger composer operations call `scroll_into_view_if_needed()` before click/fill and verify the composer text afterward.

## Block-resistance boundary

Use the installed stable Chrome, the real signed-in profile, normal browser defaults, one serial session, condition-based waits, conservative scan frequency, and bounded backoff. Remove the stale user-agent override and synthetic browser launch flags. Do not spoof fingerprints, conceal automation, bypass CAPTCHA/checkpoints/2FA, or defeat platform controls; those conditions produce a structured stop requiring human completion.

## Safety and ownership

- Draft placement remains unsent. No Enter press, Send click, or messaging API is added.
- Inbox scans remain read-only until an already-approved draft-placement path is enabled.
- External Chrome ownership is preserved: only the client connection is released.
- Endpoint paths, cookies, tokens, and account metadata are not logged.
- `Default` is enforced for both headless and visible modes; a different profile is an error, not a fallback.

## Acceptance tests

1. Configuration defaults to `C:\AI-Agent\chrome-profile-authenticated` and `Default` and does not create the old repository-local profile.
2. Guest, incognito, non-Default, bundled-Chromium, and stale endpoint paths fail closed.
3. CDP attachment does not close the external browser or its context.
4. The daemon survives `authenticated_profile_unavailable` and retries without launching a browser.
5. No fixed viewport or stale user-agent override remains in Messenger production entrypoints.
6. Composer placement scrolls the actual composer into view and still never sends.
7. The real scheduled process tree contains no `ms-playwright\chromium-*` Messenger browser and uses the central authenticated Chrome `Default` profile.

## Rejected alternatives

- Launch system Chrome directly from each Messenger script: profile locking and ownership would race the central Executor.
- Keep the repository-local profile but improve its name or viewport: it remains the wrong authenticated identity and still permits Guest-like behavior.
- Add stealth plugins or fingerprint spoofing: brittle, unsafe, and outside the permitted platform-control boundary.

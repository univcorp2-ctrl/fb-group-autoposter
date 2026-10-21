# Messenger / EstateBoard continuation — 2026-10-21 19:10 JST

## Scope and safety
Existing normal Chat only; no Work/Cowork/Codex CLI/new Chat, customer send/post, PDF sending, auth/approval override, or GPT follower editing.

## Runtime observation
At 19:04:44 JST Messenger logged-in scan was 19:04:38, send_paused_fail_closed, attempted=0, send_pause.lock present, exactly one unresolved ledger attempt from Oct 19. Private Windows CRM Task last ran 19:03:03 with result 0. Hold never removed.

## Auth and preview isolation
Chrome Cloudflare dashboard only provided sign-in page; background tab id 63 was left for the user to authenticate. No Cloudflare Access application, audience, issuer, allowlist, secret or Preview D1 actual setting retrieved or changed. Existing wrangler.toml default and env.production share the same D1 database ID; no env.preview is configured. Official Pages documents clarify that preview environment config applies across preview deployments: https://developers.cloudflare.com/pages/functions/wrangler-configuration/ . Do not deploy/migrate without independently verified preview DB and access app.

## New tested fail-closed guard
Created isolated scripts/check_preview_d1_isolation.py and tests/test_check_preview_d1_isolation.py. On real current wrangler.toml, check returned 'BLOCK missing_preview_environment' exit 2. Four synthetic cases PASS: distinct preview DB allowed, missing preview refused, same preview/production DB refused, missing binding refused.
GitHub isolated EstateBoard branch commit/push 0bc605c8ce66d338ef147d3aedca6f7d965f7075 verified by ls-remote. Two artifacts copied with matching SHA256 to Google Drive and verified with Library readback:
https://drive.google.com/file/d/1GWzH9ummsg_ehD8K-LYUUvbE6Ox2clo1/view
https://drive.google.com/file/d/1looss3tM_esyVUQ8Gy4lPQsrPFEMe5tz/view

## Still pending
Uncommitted method guard files functions/_middleware.js and tests/test_private_crm_http_flow.mjs remain isolated, previously backed up on Drive. Prior real local Wrangler HTTP after middleware modification: unauthenticated HTML/summary 503; GET ingest 405; POST summary 405; nonexistent private API 404. Updated combined test run was blocked by tool safety checks, so latest branch-wide PASS is NOT asserted, nor did we push those two files.
Private CRM sync failure user notification and renewal warning remain unimplemented; existing 5-min Task Scheduler has a 365-day repetition from Oct 21 2026, with reminder goal by Sep 21 2027. No cloud deployment/D1 migration, no real Access login E2E, no Opus premium review or approved PDF delivery E2E.
Audit A safety PASS; B factual caveats PASS; C four D1 guard tests + GitHub/Drive artifact proof PASS, cloud/site/notifications/client delivery PENDING. Task status IN PROGRESS.

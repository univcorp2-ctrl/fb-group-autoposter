# Messenger CRM local smoke test — 2026-10-21 18:48 JST

Messenger production preflight 18:43:51 JST: authenticated scan at 18:43:33, send_paused_fail_closed, attempted=0, send_pause.lock exists, durable unresolved ledger=1. Private 5-minute CRM sync completed at 18:43:43, LastTaskResult=0. No send/post/CLI/Work/Cowork/follower edits.

Cloudflare staging was tested locally only, with Wrangler Pages dev on 127.0.0.1:9876. The installed workerd could not run the checked-in 2026-06-19 compatibility date (supports 2026-06-10 maximum). LOCAL-ONLY --compatibility-date 2026-06-10 override used; repository and production compatibility date unchanged.

Initial local HTTP: GET /facebook-crm/ ->503; GET /api/private/messenger/summary ->503; GET /api/private/messenger/ingest ->200 fallback HTML (bug). Added _middleware.js private route/method guard in isolated EstateBoard worktree. After local hot reload: GET /facebook-crm/ ->503; GET /api/private/messenger/summary ->503; GET /api/private/messenger/ingest ->405; POST /api/private/messenger/ingest ->503; POST /api/private/messenger/summary ->405; GET /api/private/messenger/unknown ->404. All were unauthenticated, fake/local requests. Local dev session terminated.

Prior 10/10 Node.js and 8/8 Python/Playwright tests PASSED on earlier code version. Added third method-guard test to tests/test_private_crm_http_flow.mjs, but rerunning tests and GitHub commit were blocked by tool safety checks; current changes are NOT claimed committed or tested at unit level. Last verified EstateBoard remote commit 375477a5646d5f216a415eb07584691f2ec1046f. Current patched files are in C isolated worktree awaiting allowed validation/sync.

Cloudflare Access real app/Team Domain/Audience/reader allowlist, Pages secrets, preview-safe D1 bindings, and live SSO login remain unverified. No Cloudflare deployment or D1 migration. Cloudflare docs warn Wrangler config for Pages previews can affect all preview deployments, not only one branch: https://developers.cloudflare.com/pages/functions/wrangler-configuration/ .

Windows private CRM failure notification and schedule expiry reminder remain NOT installed or delivered. Existing Windows schedule lasts P365D from October 21, 2026; renewal watch should begin September 21, 2027. Premium review/individual PDF approval/send E2E remains blocked by send hold.

Notion master log: https://app.notion.com/p/40010562e58b81d2b9bef6846118dd07 . Overall task IN PROGRESS.

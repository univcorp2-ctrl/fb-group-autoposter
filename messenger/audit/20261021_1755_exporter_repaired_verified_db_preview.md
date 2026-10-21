# Messenger CRM follow-up — 2026-10-21 17:55 JST

## Work authorization and safety
- Existing normal ChatGPT conversation only. No Work/Cowork, Codex CLI, new chat, external API reviewer invocation, customer send/post, auth stop override, or GPT follower edit.
- Messenger task FBAutoposter-MessengerDrafts remains Running. Last healthy scan 17:52:59 JST, authenticated=true.
- send_pause.lock exists and the current daemon reports send_paused_fail_closed; auto_reply.attempted=0; unresolved real ledger records=1, still no replay. The historical uncertain 2026-10-19 thread remains unresolved.
- Existing sender constraints, user approvals and PDF sharing conditions remain in place.

## CRM exporter incident closed in isolated branch
- Incident: a paused auto_reply_status.json omits lifetime confirmed and uncertain count fields; previous exporter converted missing to zero. This was wrong because auto_reply_ledger.json still contains one unresolved send.
- Updated scripts/export_real_crm_aggregate.py to require a durable ledger and count entries from ledger, failing closed if missing or corrupt. It excludes all client names, thread IDs and message bodies.
- Reworked tests/test_export_real_crm_aggregate.py: missing ledger must fail, paused status with one uncertain ledger item must report uncertain=1, malformed ledger fails, no sensitive data escapes.
- Entire isolated Messenger test suite PASS with exit 0 after updated test; no simulated client sends.
- On isolated audit branch, committed and pushed SHA 04b4882d82a4f060731a763373e49e75daf00289; git ls-remote agreed. Files mirrored to G:/マイドライブ/AI_Agents/github/repos/fb-group-autoposter/messenger, individual SHA256 comparisons PASS; cloud list/readback verified.
- This exporter is only in isolated safe branch and Google Drive mirror; the active C runtime has not been switched to it. It is safe to run read-only on the saved real status to create separate private aggregates.

## Verified private data, quarantined history
- Created new private snapshot G:/マイドライブ/AI_Agents/Private/FBGroupAutoposter/verified_messenger_snapshot_20261021.json. It includes 14 tracked threads, 0 confirmed sends, 1 unresolved send, 27 scanned last cycle at snapshot time. Numbers from scan are not unique leads.
- Created BRAND NEW private SQLite G:/マイドライブ/AI_Agents/Private/FBGroupAutoposter/messenger_crm_operational_history_VERIFIED_20261021.sqlite. Database was required not to preexist. Append-only/idempotent single aggregate insertion; independently re-read SQL count=1 via sqlite3 (not inferred from process exit). No customer info included.
- The older, contaminated messenger_crm_operational_history.sqlite still contains an incorrect uncertain=0 row. It is NOT canonical and was not deleted, merged or used for dashboards.
- Cloud Drive library confirmed new verified snapshot and verified SQLite as remote objects. This new DB is a point-in-time verified snapshot, not an authorized continuous CRM ledger of per-customer events.

## EstateBoard privacy-safe preview E2E
- Worktree C:/Users/t0015/AppData/Local/FBGroupAutoposter/stage_estateboard_messenger_20261021 remains on feature/messenger-crm-anonymous-20261021.
- Created local-only sanitized status.json from verified private snapshot using strict whitelist validator; no personal customer data.
- Headless Playwright opened a local 127.0.0.1 HTTP preview and verified page title Messenger CRM | EstateBoard, tracked threads=14, uncertain=1, confirmed sends=0. 7/7 tests PASS.
- Replaced the preview test with a self-contained synthetic fixture. Re-ran 7/7 tests PASS; synthetic browser E2E no longer relies on a local operational snapshot file.
- Removed the local operational status.json from staged public docs after testing. No status.json or private DB committed to public repository.
- Pushed only non-secret browser E2E test to isolated EstateBoard branch SHA 103e0dd0833e120e28d5c7ab3faf63a9f45dda5d. GitHub remote SHA verified; Drive mirrored test and SHA256 matched.
- Public https://estateboard.pages.dev/facebook-crm/ has not been deployed as a CRM page; previous HTTP 200 response was a homepage fallback. Access-controlled publishing and private lead-detail view remain unimplemented. Do not claim public E2E.

## Review and delivery gates
- External Codex CLI explicitly prohibited and not used. Latest isolated no-external-review policy returns needs_human; high-end LLM review through a real API is not configured/verified. Do not automatically release pause marker.
- No individual customer reply or PDF sent. Sending remains blocked; legacy ambiguous delivery requires independent exact text/PDF UI proof before reconciliation.
- Public estateboard counts will require explicit scope/access policy; no real customer list, files, emails, URLs, or Messenger chat data should ever be in docs/.

## Audits
preflight_notion_check=PASS; selected_theme_rules=PASS (13/13-CLOUD/16/16-CORE);
audit_A_rule_compliance=PASS for normal Chat/no Codex/no sends/maintained approvals and explicit hold.
audit_B_fact_challenge=PASS for old contaminated data vs new verified one-row database, old fallback URL vs local browser preview.
audit_C_execution_artifact=PASS for unit tests, private DB SQL readback, browser preview, two GitHub commits/remote refs, cloud Drive artifacts. FAIL for real high-end reviewer, authenticated private CRM frontend, published EstateBoard E2E, user-approved live sending.
learning_update=PASS; the old failure record of incorrect paused-mode counters has the reproduction, new ledger rule and test prevention.
final_notion_recheck=PENDING until final reread; notion_log_saved_and_refetched=PENDING until updated and reread.

## Next actions
1. Maintain send_pause.lock until user-approved premium review + property PDF sharing verification and individual receipt E2E.
2. Build access-controlled (not open CDN) EstateBoard CRM view and decide which anonymized aggregates may be public, if any. Authorize recurring private ingestion; do not publish stale snapshot as live.
3. Verify real CRM event ingestion and link to actual property registries with dedupe on exact conversation and evidence hashes; independent non-send browser E2E.
4. Document Cloudflare deployment tests and preserve GitHub/Drive/Notion readback. Overall task remains IN PROGRESS.

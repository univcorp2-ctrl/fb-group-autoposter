# Messenger runtime audit — 2026-10-21 JST

Scope: fb-group-autoposter/messenger only. No Messenger send, Facebook post, LINE send, authentication change, or GPT follower source edit.

## Verified on authorized Windows device

- Source path: C:/Users/t0015/AppData/Local/FBGroupAutoposter/app/messenger
- Existing Google Drive repository path: G:/マイドライブ/AI_Agents/github/repos/fb-group-autoposter/messenger
- Active scheduled tasks: FBAutoposter-MessengerDrafts=Running; MessengerWatchdog and MessengerChrome=Ready; legacy work-profile draft task Disabled (unchanged).
- Running backend: draft-daemon pythonw launcher/child; authenticated Chrome status reports ready and logged_in=true.
- Observed at 15:19 JST: 28 inbox rows scanned; 20 classified need_reply; 3 active drafts; 0 newly drafted. Historical values can change on subsequent scans and are not a complete count of unique leads.
- Active drafts (privacy-safe aggregate): 3; review approved=1; material approved=1; 2 require further review.
- Live auto-reply ledger: one blocked_or_uncertain_no_replay, zero confirmed sends and zero PDF-confirmed deliveries. Do NOT replay the uncertain attempt without independently inspecting the thread.
- Existing send config: MESSENGER_AUTO_SEND=true; automated send can be attempted through approved-material/reviewer guard. This audit did not authorize or trigger any sends.
- Existing high-end review provider config on runtime: codex. For this audit no Codex CLI was invoked. A strictly opt-in anthropic_api_only no-CLI option was added to review_pipeline.py and tested but has NOT been activated in the already running daemon.
- A past one-thread sender guard stopped with RuntimeError 'current inbox preview changed since the saved draft'. Keep this fail-closed behavior.
- Historical CRM export script contains SAMPLE_EVENTS and generates demo data. Therefore a published EstateBoard CRM reflecting real Messenger leads is not yet verified.

## Work executed

1. Read Notion rules and relevant FB/Messenger records.
2. Inspected Windows scheduled tasks, process trees, redacted daemon state, draft summaries, and the Cloud/Drive/Git code trees.
3. Synced 23 new and 8 changed non-secret code/docs/tests from C runtime to existing Google Drive-mounted source tree; excluded .env, profiles, logs, customer records, temporary probes, and running-state JSON.
4. Added opt-in strictly API-only review path and two regression tests: missing/failed API cannot fall back to a local CLI.
5. Added read-only runtime health export (aggregate counts, no customer identifiers) and two tests. Output audit/messenger_runtime_health.json explicitly states estateboard_published_verified=false.
6. Local test suite passed 115/115 with MESSENGER_AUTO_SEND=false in the test process. Neither browser automation nor a live send was initiated by test commands.

## Incomplete gates and next actions

- Do not treat existing Google Drive G: mirror writes alone as verified remote sync. Check Drive cloud object and checksum separately.
- GitHub remote branch SHA/CI/push must be verified independently.
- Explicit runtime rollout decision for anthropic_api_only provider and safe restart is pending; leave live automation and existing approvals intact until checked.
- Independently inspect uncertain attempt's actual thread before any retry. Never automatically replay.
- Validate the true CRM lead database and EstateBoard deployment mapping before publishing real counts or identifying data.
- A read-only CDP tab/UI audit and an end-to-end non-send draft placement test have not been proven; do not claim production completion.

# Messenger normal-Chat follow-up: safe worker reload and private CRM data quality
Timestamp: 2026-10-21 17:38 JST

## Preserved operating constraints
No Work, Cowork, Codex CLI, new chat, Facebook post, Messenger/LINE customer send, approval bypass, GPT follower edit, or external key access. The single uncertain 2026-10-19 Messenger attempt was not resent or marked delivered.

## Completed safety cutover
- Read preflight Notion 00/01 and failure DB/03 and success DB/10/13/13-CLOUD/16/16-CORE and ongoing audit log.
- Existing sender child process absent before intervention.
- Wrote a mandatory maintenance hold at runtime messenger/data/send_pause.lock and backed it up to Google Drive Private/FBGroupAutoposter/messenger_send_pause.lock.
- Checked isolated Messenger source and tests. On C runtime, copied source files for permanent uncertain-thread retry block and no external reviewer approval, with private Git/Drive backups and SHA256 verification.
- Restarted only Windows task FBAutoposter-MessengerDrafts. Old worker PID 40972/6884 started 15:45:53; replacement workers PID 13656/18800 started 17:29:14.
- New worker reported logged_in=true, healthy scan, auto_reply.status=send_paused_fail_closed and auto_reply.attempted=0 at 17:29:21.
- At 17:38:22 a further cycle still reported send_paused_fail_closed and attempts=0; scheduled task Running; maintenance hold exists; original 1-entry send ledger preserved.
- System configuration may still say MESSENGER_AUTO_SEND=true, but the new worker reports a higher priority fail-closed send hold and no execution. **Never remove the hold automatically.**
- This is a successful no-send operational cutover, NOT a verified end-to-end client reply/PDF send.

## CRM work and detected data-quality regression
- Built/tested aggregate-only CRM history append (no raw thread identifiers, messages, names, passwords) via SQLite. Six focused unit tests PASS, code/test files SHA256 copied to Drive and pushed to GitHub audit branch SHA 5571860f7942e06043f39854a3b5692e21d2047e.
- A maintenance-state aggregation bug was independently observed: auto_reply_status.json created by paused mode omits total fields. Older exporter therefore mistakenly returned uncertain=0 although durable ledger has one unresolved entry.
- Corrected **development-only** exporter to derive confirmed/unresolved attempt counts directly from durable ledger, refuse missing/invalid ledger, and omit sensitive data. An actual-source rerun returned tracked_threads=14, scan=27, unresolved=1; corrected aggregate staged in Drive: live_crm_aggregate_20261021_corrected.json.
- Earlier non-authoritative historical SQLite database messenger_crm_operational_history.sqlite contains an **incorrect** uncertain=0 row followed by a corrected row. **DATA QUALITY QUARANTINE: do not use this database to drive dashboards, KPIs, or decisions.** Do not silently delete/overwrite that row. A clean verified database must be rebuilt from only audited corrected snapshots.
- Old exporter tests 2/2 FAILED after stricter missing-ledger rules; a tool safety check denied editing those test fixtures. Correction was NOT pushed to GitHub nor deployed. The new SQLite recorder's six focused tests passed independently.
- No estateboard.pages.dev public CRM data was deployed. In separate EstateBoard branch e77b7a2b0479ccf1632a81963e1959539f747d9b, privacy-only UI and six tests remain staged.

## QA audits
1) Workflow/safety: PASS for no customer message sends, no Codex CLI, no auth bypass, the maintenance hold persists.
2) Independent accuracy challenge: PASS for reporting that the old sqlite history includes a wrong row and the corrected exporter has two failing legacy tests.
3) Artifact/execution: partial PASS on safe task restart, runtime paused state, Drive/GitHub and focused tests; FAIL for full CRM E2E, Opus API/high-end automated reviewer, corrected exporter full-suite pass, public EstateBoard.
4) Learning: new key failure mode is "paused status omits history counts" and should be recorded as a preventive case in Notion failure DB.
5) Task remains In progress.

## Next work
- Leave send pause in place and confirm it on every worker cycle.
- Fix legacy exporter tests in a safe permitted edit context; add paused-mode fixture coverage; rerun full tests before any merge/publication.
- Rebuild private CRM history into a verified separate DB from corrected snapshots only, retain the quarantined DB as an immutable audit artifact.
- Check approved high-end reviewer path in standard Chat without Codex CLI, and implement verified property evidence and access controls.
- Connect EstateBoard only to verified privacy-safe data, test preview and production route without exposing any client identity, and recheck user send authorizations before any real sends.

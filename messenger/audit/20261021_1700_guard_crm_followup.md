# Messenger repair evidence — 2026-10-21 ~17:00 JST

## Execution safety
- Existing normal ChatGPT only. No Work/Cowork/Codex CLI, no new Chat, no message send, post, reauthorization, Chrome shutdown or GPT follower edit.
- Existing daemon running; no stop/restart. Live automatic-send configuration was not changed.
- Existing approval and failed/uncertain-send ledger unchanged.

## Actual read-only Messenger UI
- Attached to authenticated Chrome via externally owned CDP browser.
- Opened only a temporary background page for exact one historical uncertain thread.
- UI navigated to exact expected thread and returned nonempty main text, 417 chars.
- Archive had 72 candidate records, but zero eligible exact text + PDF delivery proofs, and zero matching outgoing accessibility labels.
- No confirmed sent reply or attached PDF. Ambiguous thread remains blocked_or_uncertain_no_replay, no manual replay.

## Safety code fix and tests
- Isolated worktree: C:/Users/t0015/AppData/Local/FBGroupAutoposter/stage_messenger_20261021.
- Added has_unresolved_attempt() before send eligibility; any non-confirmed attempt on the same thread is blocked indefinitely, including after 24h and a new last_message.
- Five new unit tests cover old uncertain attempt, newer inbound, confirmed_sent exception, invalid ledger, unknown state.
- Added anonymized live Messenger CRM aggregate and two privacy regression tests. Retained two API-only no-Codex-reviewer tests.
- Isolated pytest 122/122 passed. Runtime existing pytest 113/113 passed after on-disk patch (different suite; don't conflate).
- Safe-branch GitHub push verified commit d9351ec83faf2928b5eb8badbbd4467c7a05817b at audit/messenger-safe-20261021.

## Drive and runtime
- Five new/changed non-secret code/test files copied with matching SHA256 into G:/マイドライブ/AI_Agents/github/repos/fb-group-autoposter/messenger.
- Google Drive cloud readback confirmed aggregate, exporter and regression test files.
- Real 16:55 JST aggregate: tracked_threads 14, scanned 22, need_reply 15, active drafts 4, approved drafts 3, confirmed sends 0, uncertain 1. This is a single scan, not unique real leads.
- Current on-disk runtime src/auto_reply.py was backed up to Drive audit with SHA256, then safely replaced with the exact isolated guard file. SHA256 after install = 1B7903709C4C4885AC08C697091A695706BF751D8926F8E26D589432E1A06F15.
- Messenger task remains Running (same family); no restart. **The existing Python process may continue running the previously imported module. The new guard is on disk but NOT independently verified active in memory.**
- Existing public EstateBoard is NOT verified and its CRM exporter still uses SAMPLE_EVENTS. This aggregate has not been published to EstateBoard.

## Required closure
1. At a safe idle boundary, execute a controlled Messenger-only process reload with a strict non-sending validation window and process identity check. Never restart GPT follower or reuse an uncertain send.
2. Verify runtime imports the new permanent guard while keeping existing customer approval and automation stop conditions. Independently verify uncertain thread stays blocked.
3. Verify a production-quality high-end reviewer using Opus API without Codex CLI; no live provider change claimed.
4. Validate true CRM event ingestion and EstateBoard publication, without customer identifiers; test public site (external web was inaccessible).
5. Archive final test + deployment evidence to Drive/GitHub and re-fetch Notion.

Audit: preflight_notion_check PASS; selected_theme_rules PASS (13, 13-CLOUD, 16, 16-CORE); audit_A_rule_compliance PASS for no-send and isolated changes; audit_B_fact_challenge PASS for verified raw data with exclusions; audit_C_execution_artifact PARTIAL (isolated tests/GitHub/Drive PASS; running-process reload/CRM published E2E FAIL); learning_update PASS (Notion preventive hypothesis). Task overall IN PROGRESS.

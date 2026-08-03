# Facebook Posting and Messenger Draft Recovery Design

**Date:** 2026-08-03
**Status:** User direction approved; independent spec review pending
**Repository:** `fb-group-autoposter`

## 1. Purpose

Restore two production outcomes without weakening the existing Claude-era account
protections:

1. publish property posts on the intended daily cadence and prove each successful
   publication with a public Facebook permalink; and
2. prepare a reply draft automatically in the Facebook Messenger composer for only
   high-confidence inbound one-to-one text inquiries, while making message sending
   impossible through this automation.

"Complete" means that every run reaches a durable, operator-visible terminal state.
It does not mean that Facebook or Telegram can never fail. Unknown UI state, account
challenge, or ambiguous submission must stop safely and remain diagnosable.

The approved DAIWA recovery specification remains the source of truth for DAIWA
ingestion, publication authorization, EstateBoard projection, Telegram outbox, and
the one-property/one-group live canary:

- `docs/superpowers/specs/2026-07-23-daiwa-facebook-delivery-design.md`

This document adds the Messenger contract and the cross-cutting recovery gates found
necessary during the 2026-08-03 live audit.

## 2. Current Evidence and Problems

The current live state is not healthy:

- no permalink-confirmed post exists after 2026-07-25;
- `monitor_status.json` reports zero posts for 24 hours, 48 hours, and seven days;
- Task Scheduler reports success because the VBS launchers do not wait for Python;
- Facebook's current DOM can fail before the composer opens;
- Telegram HTTPS failures escape from notification code and abort Facebook work;
- Telegram bot credentials can appear inside exception URLs in local logs;
- Messenger inbox enumeration is nondeterministic and has misclassified a real
  one-to-one inquiry as a group conversation;
- `drafts.json` overwrites earlier drafts and `threads_state.json` does not retain
  their text;
- the Messenger profile reached Account Center but was classified as an unfamiliar
  device, so production browser writes must remain gated until the operator confirms
  account security in a familiar browser.

## 3. Non-Negotiable Safety Invariants

### 3.1 Shared Facebook invariants

- Do not bypass CAPTCHA, checkpoint, two-factor authentication, group moderation,
  rate limits, or Facebook security controls.
- Do not add stealth plugins, rotating fingerprints, proxies, or detection-evasion
  behavior.
- Preserve existing group rules, membership checks, pacing, duplicate prevention,
  freshness checks, and permalink verification unless a reviewed change makes a
  protection strictly stronger.
- Only one process may own a Facebook profile at a time.
- Any login, checkpoint, CAPTCHA, unusual-device, or unknown-DOM state opens a
  circuit and prevents further Facebook writes.

### 3.2 Posting invariants

- A closed composer is not success. Only a verified public permalink is `posted`.
- An ambiguous final submission is never blindly retried.
- Telegram and EstateBoard failures are delivery failures, not Facebook submission
  failures, and can never cause another Facebook submission.
- The first recovered production post remains one explicitly authorized property to
  one already-joined, confirmed group under the existing 15-minute live lease.

### 3.3 Messenger invariants

- The automation must not send a Messenger message.
- No code path may click a Send button, press Enter in the composer, invoke a message
  sending API, or reuse a generic action capable of doing those things.
- Composer placement is allowed only for a high-confidence one-to-one inbound plain
  text message.
- Photos or attachments without sufficient text, completion acknowledgements,
  ambiguous groups, identity/contract/payment matters, personal-data requests, and
  low-confidence drafts are excluded.
- Opening a selected thread may produce a read receipt or typing indicator. The user
  has accepted this consequence of automatic composer placement.
- Each inbound message fingerprint can produce at most one placement unless the
  operator explicitly resets it.

## 4. Architecture

Posting and Messenger remain separate roles with distinct profiles, settings,
single-instance locks, schedules, and state. They share only small, stable service
interfaces for AI draft generation, durable delivery, run results, and secret
redaction. Neither role imports the other's browser automation.

### 4.1 Agent-neutral entrypoint

A background job entrypoint launches deterministic Python workloads without needing
Claude, Codex, Gemini, or another interactive agent to stay alive. AI text generation
is behind a provider gateway. Supported adapters are:

- Anthropic API or Claude CLI;
- OpenAI API or Codex CLI;
- Gemini API or Gemini CLI;
- GLM or another OpenAI-compatible endpoint; and
- a local OpenAI-compatible LLM endpoint.

Provider selection is configuration, not business logic. Every provider must accept
the same minimal JSON input and return the same schema. Recovery is deliberately
phased so it does not become a provider-platform rewrite:

- Phase 1 requires the deterministic conservative template, preserves the existing
  Anthropic API adapter, adds one OpenAI-compatible HTTP adapter for OpenAI, GLM, and
  local compatible endpoints, and adds one allowlisted JSON CLI adapter for installed
  `claude`, `codex`, or `gemini` executables.
- Phase 2 may add provider-native adapters after posting and Messenger production
  recovery. Phase 2 is not an acceptance gate for this recovery.

Subprocess adapters use explicit executable allowlists and argument arrays, never a
shell, and have bounded timeouts and output-size limits. This supplies the requested
provider switching through two stable transports without duplicating business logic
for every model vendor.

### 4.2 Durable state

Messenger adds `messenger/data/messenger.db` with additive tables for:

- scan runs and terminal outcomes;
- inbox snapshots and message fingerprints;
- generated draft versions and provider metadata;
- composer placement attempts and readback evidence; and
- Telegram delivery outbox events.

Before any browser mutation, the database inserts a unique placement intent keyed by
`(thread_id, inbound_message_fingerprint)`. Its state advances through `intent_recorded`,
`write_started`, and either `placed_not_sent`, `placement_ambiguous`, or `excluded`.
The unique intent and transaction commit happen before the composer is focused. A
process restart never inserts the same tuple again. An interrupted `intent_recorded`
means no composer input began; it becomes per-item `recovery_required_no_write` and a
run-level `preflight_blocked` / exit 20 until reconciled. An interrupted
`write_started` means input may have occurred; it becomes per-item
`placement_ambiguous` and run-level `placement_ambiguous` / exit 40. It requires human
inspection of the existing composer and can never be retried automatically.

Existing `drafts.json` and `threads_state.json` are imported once and retained for
compatibility. `drafts.json` may remain a latest-view projection but is no longer the
record of history. Private Messenger content is never published to the public
EstateBoard site.

### 4.3 Inbox snapshot and classification

The scanner records a bounded snapshot before generating or placing anything. It
must:

- wait for a stable conversation-list container;
- enumerate from a deterministic start position and accumulate stable thread IDs;
- detect suspicious count changes and unknown row shapes;
- distinguish group evidence from incidental image counts;
- identify whether the latest visible preview is inbound or from the operator; and
- stop without placement if the snapshot is incomplete or ambiguous.

Classification produces `eligible`, `excluded`, or `needs_review` plus explicit
reason codes. Only `eligible` can continue automatically. The initial limit is at
most three placements per run and is configurable only downward until the canary
period completes.

### 4.4 Draft generation

The draft request includes only the minimum required conversation fields: stable
thread reference, display name, visible inbound preview, and approved business links.
It excludes cookies, tokens, unrelated threads, and browser profile data.

The returned draft must pass deterministic validation:

- polite Japanese with no unsupported promises or invented property facts;
- no request for passwords, payment, identity documents, or other high-risk data;
- no control characters, line separators, or keyboard sequences;
- within a configured length; and
- classified as safe for automatic placement.

Failed validation becomes `needs_review`; it is never placed automatically.

### 4.5 No-send composer placement

The writer uses a dedicated `MessengerComposerPlacer` boundary rather than a generic
Facebook click helper. The flow is:

1. acquire the Messenger profile lease;
2. revalidate the exact thread and inbound fingerprint;
3. stop on any account or DOM safety circuit;
4. require exactly one visible composer;
5. read the composer and require it to be empty after normalization;
6. if operator-entered or older draft text exists, preserve it unchanged and record
   `excluded:existing_composer_draft`;
7. commit the unique `intent_recorded` row and then mark `write_started` before the
   first input event;
8. record the pre-placement last-message fingerprint and sent-message count;
9. focus only the composer and insert sanitized text without Enter or line breaks;
10. read the composer back and require an exact normalized match;
11. confirm that the sent-message count and last outbound fingerprint did not change;
12. record `placed_not_sent` atomically; and
13. close the browser context without clicking another control.

An incomplete or mismatched composer becomes `placement_ambiguous`. It is not
automatically cleared or retried because further editing could create a worse state.
The operator receives a link and an explanation through the delivery outbox.

The feature has two independent gates, both off by default:

- `MESSENGER_AUTO_DRAFT_ENABLED`; and
- `MESSENGER_COMPOSER_WRITE_ENABLED`.

Both are enabled only after unit, synthetic-browser, dry-run, account-security, and
one-thread live canary gates pass.

Account security is an explicit local authorization, not an inferred cookie state.
After the operator confirms two-factor and recovery settings from a familiar browser,
an agent-neutral CLI records the role, profile fingerprint, authorizer, timestamp,
and a maximum 30-day expiry without storing passwords or 2FA data. Any checkpoint,
CAPTCHA, unusual-device warning, login recovery, profile replacement, or fingerprint
change revokes it immediately. Expiry blocks composer writes but still permits local
diagnostics that do not open Facebook.

### 4.6 Telegram and EstateBoard delivery

Facebook state transitions and delivery events are committed together. Telegram and
EstateBoard handlers consume a durable outbox and cannot throw back into browser
automation. Each event has an idempotency key and one of `pending`, `delivered`,
`delivery_ambiguous`, or `failed`.

All HTTP errors redact bot tokens before logging. The exposed Telegram bot credential
must be rotated before production schedules resume, and the new credential must be
updated in the private workbook and runtime environment without entering Git history.
After rotation, a narrowly scoped migration replaces the exact revoked token only in
this repository's historical runtime logs using atomic file replacement. It records
file paths, timestamps, replacement counts, and before/after hashes without recording
the token. It does not scan unrelated private folders and does not retain an unredacted
backup. The revoked token is supplied once over standard input to the maintenance
command, is never accepted as a command-line argument or environment variable, and is
retained only in process memory for the duration of the redaction pass.

Messenger Telegram notices contain the thread display name, short inbound preview,
draft, thread URL, and `FB入力欄に配置済み・未送信`. They never claim that a message
was sent.

### 4.7 Background scheduling

Every scheduled task calls the same agent-neutral job entrypoint. VBS launchers wait
for the child process, stay hidden, and return the canonical exit code. Posting and
Messenger schedules must not overlap and must refuse to start if the corresponding
profile lease is active.

Scheduler success means a canonical run-result file exists and validates. Task
Scheduler `0x00000000` alone is never reported as workload success.

## 5. Error and Run-Result Contract

Each role writes one atomic JSON result with a run ID, start/end timestamps, mode,
counts, terminal outcome, safe reason codes, artifact paths, and delivery status.

Posting uses this explicit canonical outcome and exit contract, which also resolves
any omission in the referenced DAIWA specification:

- `success` or `no_action` / exit 0;
- `preflight_blocked` / exit 20;
- `risk_stopped` / exit 30;
- `submission_ambiguous` / exit 40;
- `posted_delivery_pending` / exit 50; and
- `internal_error` / exit 60.

Messenger uses analogous outcomes without pretending a draft is a sent message:

- `completed` / exit 0: scan completed and all eligible drafts reached a durable
  terminal state;
- `no_action` / exit 0: no eligible inbound text;
- `preflight_blocked` / exit 20: configuration, account-security gate, profile lease,
  or incomplete snapshot prevented placement;
- `risk_stopped` / exit 30: checkpoint, CAPTCHA, unknown DOM, or other account risk;
- `placement_ambiguous` / exit 40: composer state cannot be proven safely;
- `delivery_pending` / exit 50: composer state is durable but Telegram delivery is
  pending or ambiguous; and
- `internal_error` / exit 60: unexpected internal failure.

No outcome maps a draft placement to `sent`.

Every property, group, thread, placement, and delivery retains its own terminal state.
For a run containing mixed states, the single run outcome follows this precedence:

1. `risk_stopped` when an account-safety signal exists;
2. `submission_ambiguous` or `placement_ambiguous` when external mutation cannot be
   determined and no risk signal exists;
3. `internal_error` for an unexpected failure with no ambiguous external mutation;
4. `posted_delivery_pending` or `delivery_pending` when the Facebook state is proven
   but a delivery is outstanding;
5. `preflight_blocked` when no external mutation occurred and a known gate blocked;
6. `success`/`completed` or `no_action` otherwise.

The run result includes all per-item states, so precedence never hides which items
succeeded, failed, or need human inspection.

## 6. Test Strategy

Implementation follows test-driven development.

### 6.1 Static no-send contract

Tests scan the Messenger production modules and reject:

- Enter/Return key actions in composer code;
- Send-button selectors or clicks;
- Messenger message-send API calls;
- generic click helpers inside the placement boundary; and
- production imports that bypass `MessengerComposerPlacer`.

### 6.2 Unit and integration tests

Tests cover:

- personal versus group classification, including the observed image-count false
  positive;
- completion acknowledgements and attachment-only exclusion;
- message fingerprint deduplication;
- preservation of every non-empty composer without alteration;
- crash recovery for `intent_recorded` as `recovery_required_no_write` / exit 20 and
  for `write_started` as `placement_ambiguous` / exit 40;
- provider gateway validation and fallback;
- append-only state and latest-view projections;
- exact composer readback and sent-message invariants;
- Telegram exception isolation and token redaction;
- profile leases, overlap rejection, and canonical run results; and
- hidden launcher child-exit propagation.

### 6.3 Synthetic browser tests

Local HTML fixtures model normal, changed, ambiguous, checkpoint, and composer-mismatch
states. These tests prove that only the composer is edited and that the placement
boundary never sends.

### 6.4 Live canaries

Live actions remain sequential and bounded:

1. posting and Messenger preflight-only runs;
2. Messenger scan with both write gates off;
3. one explicitly selected high-confidence thread with composer placement enabled,
   followed by human visual confirmation that it is still unsent;
4. Telegram outbox delivery and local history reconciliation;
5. one-property/one-group Facebook posting canary under the existing 15-minute lease;
6. permalink, SQLite, Telegram, EstateBoard, browser DOM, and run-result reconciliation;
7. enable hidden schedules only after all evidence agrees.

No canary proceeds while Account Center reports the automation profile as an
unfamiliar device or while the operator has not confirmed account security from a
familiar browser.

During the canary period the placement limit is one per run. Canary completes only
after at least seven successful scheduled scans across at least three calendar days,
at least one human-verified `placed_not_sent` composer canary, zero risk or ambiguous
placement outcomes, zero sent-message invariant changes, and full outbox
reconciliation. Only then may the configured limit increase, and never above three
per run without a new reviewed design.

## 7. Acceptance Criteria

The recovery is ready for unattended operation only when all of the following hold:

- the complete root and Messenger test suites pass with lint clean;
- the no-send static contract passes;
- no Facebook profile overlap or visible CLI window occurs;
- a Messenger canary leaves the exact draft in the intended composer and creates no
  sent message;
- the draft remains discoverable in Messenger after browser restart and in local
  durable history;
- Telegram reports `placed_not_sent` through the outbox without affecting composer
  state;
- a posting canary creates exactly one verified permalink and no duplicate;
- EstateBoard shows the same property, group, result, and permalink;
- scheduled tasks return child workload exits and point to atomic result files;
- secrets are absent from logs and the exposed Telegram token has been rotated; and
- rollback disables both live-write gates without deleting history.

## 8. Rollback

Rollback is configuration-first and history-preserving:

- disable posting live authorization and both Messenger write gates;
- disable only the affected scheduled tasks;
- preserve SQLite, JSONL, screenshots, run results, and outbox records;
- do not restore old browser profiles automatically after a checkpoint or unfamiliar-
  device event; and
- resume only through the same preflight and canary sequence.

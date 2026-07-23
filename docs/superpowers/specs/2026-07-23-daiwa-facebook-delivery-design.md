# DAIWA Facebook delivery recovery design

Date: 2026-07-23  
Status: operator-approved direction; awaiting written-spec review

## 1. Objective

Restore the DAIWA property feed, make Facebook posting truth auditable, repair Telegram
delivery, and complete one bounded production post whose property, community, permalink,
Telegram receipt, and EstateBoard state can all be reconciled.

This design extends, rather than replaces:

- `2026-07-16-background-autoposter-recovery-design.md`;
- `2026-07-16-runtime-safety-recovery.md`;
- `2026-07-16-estateboard-telegram-delivery.md`; and
- `2026-07-16-integration-rollout.md`.

The existing Claude-era browser behavior, brand masking, pacing, group rules, membership
checks, duplicate protection, circuit breakers, and post verification remain compatibility
requirements.

## 2. Confirmed current state

On 2026-07-23:

- the operator confirmed that Facebook automation permission has been obtained;
- the approved source root is
  `G:\マイドライブ\00.Bukken_Master_DB\0.Master_DB_for_AIagent\DAIWA`;
- the source root contains one ten-row CSV, one workbook, and multiple PDFs;
- the child folder `大和未公開物件（取扱注意）` is present;
- the public `https://estateboard.pages.dev/data_daiwa.json` contains zero rows;
- `EstateBoard/scripts/load_daiwahouse.py` still defaults to the obsolete source
  `G:\マイドライブ\0.物件資料_お客様紹介用\0.Master_DB\DAIWA`;
- the current loader replaces the public feed with an empty payload when no readable
  source exists, assigns unstable sequential IDs when IDs are absent, and performs no
  cross-file deduplication;
- the configured Telegram token and chat are valid and reachable through `getMe` and
  `getChat`;
- the bot has an active webhook at the existing operator-owned Cloudflare Worker, while
  the autoposter callback code uses `getUpdates`;
- direct outbound `sendMessage` is independent of the webhook, but historical live-post
  logs contain `telegram disabled: sendMessage`; and
- Windows tasks report launcher success even though that does not prove child delivery or
  Facebook success.

The public 62-row Facebook status visible in the main EstateBoard feed is not accepted as
Facebook truth unless it has a verified permalink in the autoposter ledger.

## 3. Safety and publication boundary

### 3.1 DAIWA source boundary

The importer reads only supported files directly under the approved source root. It does
not recurse. This excludes `大和未公開物件（取扱注意）`, extracted ZIP directories, and
other nested folders by construction.

The first implementation supports CSV and XLSX. PDF parsing remains a separate,
reviewable extraction step whose output must pass the same validation before import.
ZIP files are never read directly.

### 3.2 Public versus private fields

The private canonical database may retain source file, source hash, internal grade, and
validation reasons. The public EstateBoard projection must not expose:

- local or private paths;
- internal notes such as financing or screening commentary;
- staff names;
- source hashes;
- Telegram identifiers or tokens;
- Facebook cookies/profile data; or
- unpublished post bodies.

Only public listing facts, public status fields, community display name, timestamps, and
verified Facebook permalinks are published.

### 3.3 Facebook boundary

No CAPTCHA, checkpoint, 2FA, restriction, warning, membership question, or ambiguous
submission is bypassed. Browser fingerprints, user agents, proxies, and typing behavior
are not altered to avoid detection.

The first live rollout is exactly one property to one already membership-confirmed
community. Scheduled posting remains disabled during the canary. A second submission is
impossible until the first attempt has a terminal Facebook state and delivery is
reconciled.

Automatic community joining is a later, separately switchable capability. It is disabled
during the DAIWA canary. When enabled after a successful canary, it may attempt at most one
candidate per JST day, only for a Telegram-approved candidate and only when no membership
question, warning, challenge, or account circuit is present. A join request is recorded
as an attempt, not membership; posting remains blocked until a later read-only membership
probe confirms the composer and group identity.

## 4. Canonical data model

SQLite remains the authoritative operational store. EstateBoard JSON and Telegram are
delivery projections, never posting authority.

### 4.1 DAIWA properties

`daiwa_properties` contains:

- `property_id`: stable `daiwa-<id>` key;
- normalized public facts;
- `source_name`, `source_modified_at`, and SHA-256;
- `source_row_fingerprint`;
- `first_seen_at`, `last_seen_at`, and `source_active`;
- `validation_state` and machine-readable validation reasons;
- `publication_scope`;
- `content_hash`; and
- private internal fields kept out of the public projection.

An explicit source ID is preferred. When absent, the ID is a deterministic hash of
normalized immutable identity fields and source lineage. Sequential row numbers are not
IDs. Reordering a CSV cannot create new properties.

### 4.2 Eligibility

`daiwa_eligibility` records a decision version rather than mutating facts:

- property exists in the latest successful source snapshot;
- source is inside the approved non-recursive root;
- property name, location, price, and at least one meaningful investment fact are present;
- no confidential marker or forbidden source lineage is present;
- source age is within the configured freshness limit;
- group-specific rules can be applied without losing mandatory facts;
- no verified or uncertain duplicate exists for the same property/community; and
- no relevant circuit is open.

Missing or contradictory facts produce `not_eligible`; they do not fall back to invented
copy. Internal grades are informative and do not independently authorize or prohibit a
listing.

### 4.3 Community permissions

`community_permissions` binds authorization to:

- exact Facebook group ID and normalized URL;
- membership verification timestamp;
- group-rules hash;
- permission source and timestamp;
- posting enabled/paused/revoked state; and
- optional expiry.

A changed group ID, changed rules hash, unknown membership, or restriction invalidates
posting eligibility.

### 4.4 Posting and delivery ledger

The existing `job_targets`, approvals, submission attempts, circuits, and run-result
tables remain authoritative. Additive outbox records bind each downstream event to stable
`run_id`, `attempt_id`, `property_id`, and `group_id` values.

Each user-visible posting record includes:

- property ID and property name;
- community ID, name, and URL;
- attempt and run IDs;
- attempted, clicked, verified, or failed timestamps;
- state and safe reason code;
- HTTPS Facebook permalink only when verified;
- Telegram delivery state; and
- EstateBoard delivery state.

`uncertain` is never displayed as posted and permanently blocks automatic resubmission
until reconciled.

## 5. DAIWA ingestion flow

1. Resolve the approved source root from configuration. The documented path is the
   default, not an unrelated legacy path.
2. Acquire an ingestion lock and inventory direct-child CSV/XLSX files.
3. If the root is missing, unreadable, or yields zero valid rows, emit a failed run result
   and keep the last known good database and public JSON unchanged.
4. Parse into a staging snapshot without modifying the canonical database.
5. Normalize values, compute stable IDs/hashes, deduplicate, and validate.
6. Produce a validation report with accepted, rejected, duplicate, and incomplete counts.
7. Commit the source snapshot and property changes atomically.
8. Generate a public `data_daiwa.json` projection atomically.
9. Deploy and read back the exact schema, generation ID, count, and sample canonical IDs.
10. Only a successful readback marks EstateBoard delivery complete.

The importer must be repeatable: identical input produces identical property IDs and no
new logical records.

## 6. Telegram recovery

### 6.1 Outbound delivery

All outbound messages use a durable outbox. A producer commits the Facebook/property
state and outbox event in the same SQLite transaction. A separate delivery worker calls
`sendMessage`.

Messages cover:

- DAIWA ingestion success/failure and counts;
- canary preview and authorization request;
- preflight failure;
- submission uncertainty or restriction;
- verified post with property/community/permalink;
- EstateBoard delivery confirmation; and
- persistent environment/session alerts.

Each event has a stable idempotency key. A confirmed Telegram message ID marks delivery.
A timeout after submission is `delivery_ambiguous` and is not blindly resent.

Startup validation must fail loudly if the repo-root `.env` is not loaded. No path may
silently downgrade to `telegram disabled` in production mode.

### 6.2 Inbound callbacks

The existing webhook is not deleted or replaced as part of this recovery. The application
must detect webhook mode before calling `getUpdates`.

For the canary, the outbound message and explicit operator command can record approval
without altering the shared webhook. A later callback integration must use the existing
Cloudflare Worker route or a dedicated autoposter bot; polling and webhook consumption
must never be active for the same bot simultaneously.

## 7. EstateBoard presentation

EstateBoard reads two independent sources:

- normalized DAIWA listing facts; and
- the full `fb_post_status.json` delivery overlay.

The overlay is joined by canonical property ID and survives the next daily regeneration.
For each DAIWA property the UI shows:

- never posted;
- approval pending;
- submission uncertain;
- verified posted;
- failed/blocked; or
- delivery stale.

The details view lists every community separately with community name, verified time, and
permalink. A stale or unmatched overlay is visibly reported rather than interpreted as
zero posts.

## 8. One-post production rollout

The canary sequence is:

1. ingest and validate DAIWA data;
2. select one complete, fresh, non-confidential property;
3. select one enabled, membership-confirmed community;
4. generate group-compliant copy with existing brand masking;
5. run no-browser and read-only Facebook preflights;
6. send a Telegram preview and persist a short-lived canary approval bound to exact
   property/group/source/body hashes;
7. execute one visible, headed Facebook submission with all scheduled posters disabled;
8. persist the attempt before opening the composer and `click_started_at` before the final
   click;
9. verify the public post and capture its HTTPS permalink;
10. enqueue Telegram and EstateBoard deliveries without invoking Facebook again;
11. read back Telegram delivery and deployed EstateBoard state; and
12. leave posting automation disabled on any mismatch, restriction, ambiguity, or stale
    delivery.

The operator receives a concise reconciliation record containing the property,
community, state, permalink, and both delivery results.

## 9. Background execution

All scheduled CLI work uses the pinned repository interpreter and explicit repository
working directory. PowerShell runs with `-NoProfile`; VBS or the task action keeps the
console hidden. The launcher waits for the child, propagates the real exit code, and writes
one canonical run result.

Task Scheduler success is not accepted unless the run-result JSON and SQLite terminal
record agree.

## 10. Error handling

- Missing/empty DAIWA source: preserve last known good data and alert.
- Invalid rows: quarantine logically through validation reasons; do not delete source.
- Duplicate IDs with conflicting facts: fail the snapshot.
- Telegram configuration missing: production preflight fails.
- Telegram send timeout: mark ambiguous; do not auto-resend.
- Webhook/polling conflict: disable polling and report the mode.
- EstateBoard deploy/readback failure: keep delivery pending; never repost Facebook.
- Facebook challenge/restriction/unknown identity: open the global circuit and stop.
- Post-click uncertainty: reconcile-only; never retry submission.
- Public permalink missing: not verified and not displayed as posted.

## 11. Verification

Automated tests must cover:

- source-root resolution and non-recursive confidential-folder exclusion;
- missing/empty source preserving last known good output;
- stable IDs under row reorder and cross-file deduplication;
- required-field and confidential-marker rejection;
- private/public field separation;
- atomic database and JSON replacement;
- DAIWA adapter brand masking;
- outbox idempotency and ambiguous delivery;
- repo-root `.env` loading from hidden launchers;
- webhook detection preventing `getUpdates`;
- EstateBoard exact-ID join, stale warning, and full community history;
- no second Facebook attempt during delivery reconciliation;
- challenge/restriction/uncertain fail-closed behavior; and
- exact one-property/one-community canary enforcement.

Before live submission, the full pytest suite and Ruff must pass. After submission, the
same `run_id`, `attempt_id`, `property_id`, `group_id`, and permalink must reconcile across
SQLite, run results, Telegram, and EstateBoard.

## 12. Rollout order

1. Implement and test DAIWA ingestion and canonical IDs.
2. Publish and read back a non-empty DAIWA EstateBoard feed.
3. Implement the durable Telegram outbox and production configuration gate.
4. Prove one outbound Telegram diagnostic receipt.
5. Complete the remaining browser/runtime recovery tasks.
6. Run a dry-run canary with no Facebook click.
7. Present the immutable canary identifiers for final live authorization.
8. Execute one live post and reconcile every destination.
9. Observe without increasing volume.
10. Enable at most one automatic community-join candidate per day only after the posting
    canary remains healthy and the separate join feature tests pass.


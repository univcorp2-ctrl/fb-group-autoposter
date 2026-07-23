# DAIWA Facebook delivery recovery design

Date: 2026-07-23  
Status: operator-approved direction; awaiting written-spec review

## 1. Objective

Restore the DAIWA property feed, make Facebook posting truth auditable, repair Telegram
delivery, and complete one bounded production post whose property, community, permalink,
Telegram receipt, and EstateBoard state can all be reconciled.

This design extends, rather than replaces:

- `docs/superpowers/specs/2026-07-16-background-autoposter-recovery-design.md`;
- `docs/superpowers/plans/2026-07-16-runtime-safety-recovery.md`;
- `docs/superpowers/plans/2026-07-16-estateboard-telegram-delivery.md`; and
- `docs/superpowers/plans/2026-07-16-integration-rollout.md`.

The existing Claude-era browser behavior, brand masking, pacing, group rules, membership
checks, duplicate protection, circuit breakers, and post verification remain compatibility
requirements.

## 2. Confirmed current state

On 2026-07-23:

- the operator confirmed that Facebook automation permission has been obtained;
- the approved source root is
  `G:\マイドライブ\00.Bukken_Master_DB\0.Master_DB_for_AIagent\DAIWA`;
- after a user-managed reorganization on 2026-07-21/22, the only current direct-child
  source is the native Google Sheet shortcut `DAIWA_物件一覧.csv.gsheet`;
- the native Google Sheet is titled `DAIWA_物件一覧.csv`, has spreadsheet ID
  `1UtgWig_6qMMj4SEdZYrNSvHj8nvfP3nYRBn7CQ7Nw5A`, and contains a single `Sheet1` tab;
- historical CSV/XLSX files are now nested under `old\03_一覧・分析`, and source PDFs are
  under `物件資料`;
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

The canonical current source is the exact native Google Sheet ID
`1UtgWig_6qMMj4SEdZYrNSvHj8nvfP3nYRBn7CQ7Nw5A`, tab `Sheet1`. The local `.gsheet`
placeholder is discovery evidence, not readable row data.

The background importer reads this Sheet through the Google Sheets API using an explicitly
configured service account. The Sheet must be shared read-only with that service account.
Configuration uses `DAIWA_SHEET_ID`, `DAIWA_SHEET_TAB`, and the existing ignored Google
service-account credential path. The importer rejects a different spreadsheet ID, tab, or
header contract. It never searches Drive broadly at runtime.

The importer does not recurse into `old`, `物件資料`, extracted ZIP folders, or any other
child folder. Historical CSV/XLSX and PDF parsing are migration tools only and cannot
silently become the production source. A future source change requires a reviewed config
change and a new successful source preflight.

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

Only the following normalized DAIWA facts may enter `data_daiwa.json` or generated copy:

| Input column | Canonical field | Public |
| --- | --- | --- |
| `レコード種別` | `record_type` | no; must equal `物件` |
| `受領日` | `received_at` | no |
| `物件名・資料群` | `title` | yes |
| `資料種別` | `listing_type` | yes |
| `所在地` | `location` | yes |
| `価格(万円)` | `price_man` | yes |
| `表面利回り(%)` | `yield_pct` | yes |
| `状況` | `occupancy_status` | yes, normalized allowlist only |
| `ソースファイル` | `source_file` | no |
| `ページ` | `source_page` | no |
| `Google Drive URL` | `source_url` | no |
| `備考` | `internal_note` | no |
| `ファイルサイズ(bytes)` | `source_size` | no |

Unknown input columns fail the schema preflight until explicitly classified. Public
projection is allowlist-based, never pass-through. Staff, screening, cash-flow, financing,
source URLs, notes, and file metadata remain private.

### 3.3 Facebook boundary

No CAPTCHA, checkpoint, 2FA, restriction, warning, membership question, or ambiguous
submission is bypassed. Browser fingerprints, user agents, proxies, and typing behavior
are not altered to avoid detection.

The first live rollout is exactly one property to one already membership-confirmed
community. Scheduled posting remains disabled during the canary. A second submission is
impossible until the first attempt has a terminal Facebook state and delivery is
reconciled.

Automatic community joining is outside this DAIWA recovery specification and remains
disabled. It requires a separate operator-approved design that explicitly reconciles or
supersedes the inherited no-auto-join compatibility rule.

## 4. Canonical data model

SQLite remains the authoritative operational store. EstateBoard JSON and Telegram are
delivery projections, never posting authority.

### 4.1 DAIWA properties

`daiwa_properties` contains:

- `property_id`: stable `daiwa-<20-hex>` key;
- normalized public facts;
- `source_name`, `source_modified_at`, and SHA-256;
- `source_row_fingerprint`;
- `first_seen_at`, `last_seen_at`, and `source_active`;
- `validation_state` and machine-readable validation reasons;
- `content_hash`; and
- private internal fields kept out of the public projection.

The current Sheet has no explicit ID column. Its ID is therefore
`daiwa-` plus the first 20 lowercase hexadecimal characters of SHA-256 over this
length-delimited UTF-8 tuple:

`(spreadsheet_id, source_file, source_page, normalized_title, normalized_location)`.

Normalization is Unicode NFKC, trim, internal-whitespace collapse, and no case folding for
Japanese text. Missing any tuple field makes the row ineligible and prevents ID creation.
Sequential row numbers are never IDs. Reordering the Sheet cannot create new properties.

### 4.2 Eligibility

`daiwa_eligibility` records a decision version rather than mutating facts:

- property exists in the latest successful source snapshot;
- source is inside the approved non-recursive root;
- title, location, positive `price_man`, and positive `yield_pct` are present;
- `occupancy_status` is either `満室` or a syntactically valid positive `occupied/total入居`
  value; `工事中`, empty, and unknown status values are ineligible;
- none of `取扱注意`, `社外秘`, `転載禁止`, `配布禁止`, or `公開禁止` appears after NFKC
  normalization in `物件名・資料群`, `資料種別`, `ソースファイル`, or `備考`;
- the source snapshot age is at most the inherited 30 hours;
- a property-specific availability/publication authorization is at most 30 hours old;
- group-specific rules can be applied without losing mandatory facts;
- no verified or uncertain duplicate exists for the same property/community; and
- no relevant circuit is open.

Missing or contradictory facts produce `not_eligible`; they do not fall back to invented
copy. Internal grades are informative and do not independently authorize or prohibit a
listing.

Facebook automation permission does not grant property publication permission.
`daiwa_publication_authorizations` records the DAIWA equivalent of the inherited exact
`property.allowBrokerSharing == "TRUE"` gate. It binds:

- exact `property_id` and source-row fingerprint;
- authorizing Telegram user/chat or explicit operator command;
- `authorized_at` and `availability_confirmed_at`;
- the literal authorization value `TRUE`; and
- optional revocation.

The DAIWA adapter materializes `property.allowBrokerSharing` as the literal string `TRUE`
only while that exact authorization is active and both timestamps are within 30 hours.
Missing, stale, revoked, mismatched, numeric, or any value other than exact `TRUE` is
ineligible. A changed source-row fingerprint invalidates the authorization. For the first
canary, the Telegram preview approval creates this exact property authorization and the
separate short-lived live-submission approval; one cannot substitute for the other.

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

### 4.5 Cross-source ID and overlay contract

Normal EstateBoard properties retain `eb-<EstateBoard ID>`. DAIWA properties use the
canonical `daiwa-<20-hex>` ID defined above. They are not converted to `eb-` IDs.

The delivery overlay writer emits `fb-post-status/v2`. Each property row contains:

- `source`: `estateboard` or `daiwa`;
- `source_id`: the unprefixed EstateBoard ID for `estateboard`, or the full canonical
  `daiwa-<20-hex>` ID for `daiwa`;
- `autoposter_property_id`: `eb-<ID>` or the same canonical DAIWA ID; and
- the inherited per-group status/permalink fields.

The EstateBoard client joins on `(source, source_id)`, not on display title or row
position. The v2 reader remains backward-compatible with v1 EstateBoard-only snapshots;
the writer emits only v2 once DAIWA support is enabled. `data_daiwa.json` uses schema
`estateboard-daiwa/v1`, exposes the canonical DAIWA ID as `ID`, and includes
`source_run_id`, `generated_at`, `count`, the exact public-field allowlist, and `items`.

## 5. DAIWA ingestion flow

1. Resolve and verify the exact configured spreadsheet ID and tab.
2. Authenticate using the ignored service-account credential and fetch the bounded used
   range plus Drive modified time.
3. Verify the exact thirteen-column header contract shown in section 3.2. Unknown,
   missing, or duplicate headers fail before row processing.
4. Acquire an ingestion lock and create an immutable private staging snapshot.
5. If the Sheet is missing, unreadable, stale, or yields zero valid rows, emit a failed run result
   and keep the last known good database and public JSON unchanged.
6. Normalize values, compute stable IDs/hashes, deduplicate, and validate.
7. Produce a validation report with accepted, rejected, duplicate, incomplete, and
   publication-authorized counts.
8. Commit the source snapshot and property changes atomically.
9. Generate a public `estateboard-daiwa/v1` projection atomically.
10. Deploy and read back the exact schema, generation ID, count, and sample canonical IDs.
11. Only a successful readback marks EstateBoard delivery complete.

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
6. send a Telegram preview and persist both the exact 30-hour DAIWA publication
   authorization and an inherited 15-minute canary approval bound to exact
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

- exact Google Sheet ID/tab resolution, service-account access, and no runtime Drive
  search or child-folder traversal;
- missing/empty source preserving last known good output;
- exact header contract, stable IDs under row reorder, and duplicate/conflict handling;
- required-field, occupancy-status, freshness, and authorization rejection;
- private/public field separation;
- exact DAIWA publication authorization materializing only the literal `TRUE`;
- `fb-post-status/v2` source-aware ID joins and v1 read compatibility;
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
10. Keep automatic community joining disabled; address it only through a separate approved
    specification.

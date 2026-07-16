# Facebook group autoposter recovery design

Date: 2026-07-16
Status: internally approved; awaiting operator approval for implementation planning
Primary objective: protect the Facebook account before maximizing posting volume

## 1. Problem statement

The posting pipeline has not published a verified post since 2026-07-11. The current
failure is deterministic: the installed Playwright package expects Chromium build
`chromium-1223`, but `%LOCALAPPDATA%\ms-playwright` has no matching browser binary.
Every posting and keepalive run therefore fails before opening Facebook.

The public EstateBoard root dashboard has a separate persistence defect. On 2026-07-15,
the posting sync committed and deployed 53 marked records, but EstateBoard's 2026-07-16
daily dashboard regeneration replaced `docs/data.json`. The live file at 13:03 contained
1,157 properties and zero non-empty `投稿済`, `投稿日`, or `投稿先` values. The group registry
remained healthy with 11 active groups and verified-post history. Directly patching generated
`data.json` therefore cannot be the durable posting-status interface.

Windows Task Scheduler still reports success because the tasks invoke a hidden VBS
wrapper that calls `WScript.Shell.Run(..., 0, False)`. The wrapper exits immediately
without waiting for Python, so it cannot propagate the real process exit code.

Earlier Claude Code sessions also identified and corrected long-body input timeouts,
false `uncertain` verification, `posted_at` inflation, approval-pending posts counted as
published, and redundant `run_daily` processes. The recovery must preserve those safety
fixes and must not reintroduce aggressive retrying or duplicate posting.

## 2. Goals and precedence

The system shall apply this precedence order:

1. Protect the Facebook account and stop when risk signals appear.
2. Never create duplicate or uncertain repeat submissions.
3. Publish only eligible, current, broker-OK property information to confirmed groups.
4. Verify the public result and record evidence.
5. Keep daily operation reliable and observable without visible console windows.

No implementation can guarantee that Facebook will never restrict an account. The
design reduces risky behavior and fails closed. It does not attempt to defeat Facebook
security controls.

## 3. Explicit non-goals

- No CAPTCHA solving, checkpoint bypass, 2FA automation, password entry, or challenge
  circumvention.
- No stealth plugins, browser fingerprint spoofing, webdriver concealment, proxy
  rotation, or other measures intended to deceive Facebook's detection systems.
- No volume ramp solely to increase reach.
- No unattended retry after a checkpoint, posting restriction, suspicious-session
  signal, or ambiguous submission.
- No dependency on Claude Code, Codex, or any hosted model for ordinary scheduled runs.

## 4. Architecture

### 4.1 Deterministic common CLI

Create one repository-owned job entry point with named commands such as:

- `daily-post`
- `verify-posts`
- `keepalive`
- `healthcheck`
- `sync-status`
- `preflight`

Claude Code, Codex CLI, and a human operator shall invoke the same entry point. Each
command returns a meaningful exit code and writes a result document under
`output/run-results/` using an atomic latest-file plus dated history pattern. Results
include command, timestamps, outcome, reason code, property ID, group ID, permalink,
notification state, web-sync state, and evidence paths. Secrets and post bodies are not
included in the operational result document.

The result schema is versioned as `fb-autoposter-run/v1` and contains `run_id`, command,
started/finished timestamps, outcome, primary reason, secondary reasons, Facebook state,
delivery states, identifiers, evidence references, and a result timestamp. Allowed
outcomes and process exit codes are:

- `success` or `no_action`: `0`
- `preflight_blocked`: `20`
- `risk_stopped`: `30`
- `submission_ambiguous`: `40`
- `posted_delivery_pending`: `50`
- `internal_error`: `60`

The PowerShell launcher allocates exactly one `run_id` and writes the start record
atomically before Python or any browser action. It passes that ID to Python as an explicit
argument. Python reuses it when inserting the SQLite run row and owns final-result and
history writes by temporary-file flush and atomic rename. The launcher writes a final
result if Python cannot start. After any child exit, the launcher verifies that a terminal
result with the same `run_id` exists. If Python started but exited before finalization, the
launcher uses a compare-and-replace check that only replaces the still-nonterminal start
record, atomically finalizes it as `internal_error` with `finalized_by: launcher`, forces
exit `60` even if the child returned `0`, and attempts the failure notification. It never
overwrites a valid Python terminal result.
If the start/result sink cannot be written, the run aborts before submission with exit
`60`. A result is fresh for scheduler health only when `finished_at` is within 30 hours and
`run_id` matches the latest run in SQLite. Canonical results with
`finalized_by: launcher`—both `launcher_failed` and pre-SQLite `internal_error`—are exempt
because they intentionally may have no SQLite row.

The supported entry for scheduled tasks, Claude Code, Codex, and human operators is the
same repository PowerShell launcher. Scheduled tasks reach it through the hidden VBS shim;
interactive callers invoke it from their existing terminal. AI tools are optional control
planes for diagnosis, repair, and one-off execution, not production dependencies.

### 4.2 Provider-neutral AI gateway

AI is an optional content service behind one repository-owned `AIGateway` interface. It
never owns scheduling, property eligibility, group selection, approval, Facebook browser
control, verification, circuit clearance, web publication, or Telegram delivery. The
ordinary posting path remains valid with `AI_PROFILE=template`, which uses the existing
deterministic Japanese template and requires no model, subscription, or network request.

The gateway exposes two versioned capabilities:

- `generate_post_copy`: accepts a fact-only property payload, group content constraints,
  and output schema; returns a structured fact-key content plan plus provider metadata.
  Trusted local code alone renders the candidate title/body. The `template` adapter emits
  the same plan schema deterministically, so all adapters share one validation path.
- `analyze_ui_evidence`: accepts an explicitly allowed, redacted screenshot and a narrowly
  scoped question; returns structured observations only. It cannot click or directly
  supply an executable browser action. Production selectors remain deterministic and any
  proposed selector change follows the normal tested code-review path.

All providers consume the same `ai-gateway-request/v1` envelope and return
`ai-gateway-response/v1`. A response records profile name, adapter kind, provider, model,
capabilities, latency, token/usage fields when available, and a normalized outcome. The
post body is stored only in the existing approval/content records, not in operational
result logs. API keys, authorization headers, CLI session data, prompts containing private
paths, and raw provider traces are never persisted in normal logs.

Version-controlled, non-secret provider profiles define adapter, model, capability flags,
timeouts, and fallback policy. Secrets remain in ignored environment materialization.
`AI_PROFILE` selects exactly one named profile. `AI_FALLBACK` is either `template` or
`stop`; no external provider can be a fallback, and at most one template fallback is
attempted before approval. Configuration cannot contain arbitrary shell fragments. The
gateway uses built-in adapters and argument arrays, resolves an allowlisted executable,
uses `shell=False`, supplies prompts through stdin or a temporary ignored request file,
captures bounded stdout/stderr, and starts CLI children with no visible console window.

Supported adapters are:

| Adapter | Intended profiles | Contract |
| --- | --- | --- |
| `template` | no AI / emergency fallback | deterministic local copy generation |
| `openai_compatible` | OpenAI API, Gemini API compatibility, Z.AI/GLM, Ollama, LM Studio, vLLM, and other compatible services | configured base URL, model, secret environment-key name, structured JSON response |
| `codex_cli` | Codex | noninteractive `codex exec`, ephemeral/read-only isolated working directory, JSON Schema output |
| `claude_cli` | Claude Code | noninteractive print mode, bare/no-session mode, tools disabled, JSON Schema output |
| `gemini_cli` | Gemini CLI | headless JSON output in an isolated directory with a deny-all tool policy |

CLI adapters are text-generation compatibility options, not unattended coding agents.
They receive no repository write access, browser profile, Facebook cookies, Telegram token,
Cloudflare credential, or tool permission. The parent constructs an environment from a
small allowlist rather than inheriting its environment, creates an isolated temporary
working directory plus isolated HOME/config directories, and disables repository/user
instructions, tools, plugins, MCP servers, hooks, extensions, and session persistence.
Only the selected profile's named API-key variable is added. If a CLI cannot authenticate
from that key, the operator may configure one dedicated provider credential store; the
child receives that single store read-only and never the operator's general agent config.
Unattended subscription/keychain sessions that cannot meet this boundary are unsupported
and fail preflight. Temporary requests and responses are deleted after parsing; failed
cleanup is quarantined in an ignored directory with a maximum 24-hour retention and no
ordinary log content. Children run for one bounded request with a hard timeout and
output-size limit. API/CLI authentication remains provider-owned; the gateway only reports
`provider_unavailable`, `provider_timeout`, `provider_auth_failed`,
`provider_output_invalid`, or `provider_policy_rejected` without leaking credentials.

The model does not return an unrestricted final advertisement. It returns a structured
content plan containing only allowed `fact_key` references, an allowlisted tone/lead/CTA
intent, and optional non-factual connective text. The local renderer injects canonical
source values and required disclaimers. It rejects unknown fact keys and any free text
containing an unreferenced number, currency, location, yield, date, availability claim,
property attribute, superlative, guarantee, or forbidden term. Thus every factual statement
is traceable to a source field and arbitrary prose is not trusted as its own evidence.

Every rendered body then passes deterministic validation before approval: schema validity,
source-fact preservation, required disclaimers, forbidden terms, group rules, link/image
policy, length, unsupported-claim rejection, and normalized body hash. The model cannot
invent or override price, location, yield, availability, broker-sharing eligibility,
target group, or posting cadence. The content record also stores a versioned
`generation_fingerprint` over profile, adapter, provider, model, prompt/template version,
relevant generation parameters, renderer version, and policy version. Approval binds both
the body hash and generation fingerprint. Changing either requires reapproval even when
the rendered text is identical. Invalid output never reaches Facebook. Depending on
configured policy, the run either falls back once to `template` before approval or stops
as `ai_generation_blocked`; it never cycles providers after submission has begun.

An approval has its own immutable `approval_id`. The durable attempt idempotency key is
`(property_id, group_id, approval_id)`. Before `click_started_at`, invalidating an approval
may terminally abort the old attempt and permit a new approved attempt. Once
`click_started_at` exists, the target remains `uncertain/reconcile_only` or `posted`;
neither a new generation fingerprint nor a new approval can make that property/group
submission-eligible again.

Provider selection is observable but provider-neutral. `ai-profile list`,
`ai-profile show`, `ai-profile test NAME`, and `ai-profile set NAME` provide the operator
workflow. `set` changes only the ignored active-profile selector, requires a successful
synthetic test unless `--no-test` is explicitly used in an interactive terminal, writes
atomically under the application lock, and prints the rollback profile. `preflight --ai`
validates the selected profile without Facebook, and the test uses a synthetic property
fixture and never reads production credentials beyond the selected provider's own key.
Run results record only profile, adapter, provider, model, outcome, and timing.
Provider performance is compared using valid-output rate, p50/p95 latency, fallback rate,
and estimated cost where the provider returns usage; Facebook success rate is not used to
let an AI provider alter safety controls.

If the selected provider fails and `AI_FALLBACK=template`, the result records the provider
failure, `fallback_used: template`, and the template generation fingerprint; the template
body still requires the normal approval. With `AI_FALLBACK=stop`, or if template validation
fails, the canonical outcome is `preflight_blocked`, primary reason
`ai_generation_blocked`, secondary provider reason, and exit code `20`. Task Scheduler,
latest result JSON, monitor, and Telegram use that same classification.

`README.md` and `README_ja.md` document the same switching procedure: configure a named
profile, materialize only its required secret, run the AI smoke test, then set
`AI_PROFILE`. They include tested examples for Codex, Claude, Gemini, GLM through the
OpenAI-compatible endpoint, Ollama/local LLM, and `template`; capability limitations,
health checks, rollback to no-AI, background/no-console behavior, and the rule that the AI
gateway never operates Facebook are explicit. Provider examples use placeholders only.

### 4.3 Hidden console launcher

Replace the fire-and-forget VBS behavior with a repository-owned launcher that:

- starts Python with no visible console window;
- waits for the child process;
- returns the child's exit code to Task Scheduler;
- redirects stdout and stderr to dated log files;
- records launcher failures before Python starts;
- uses the repository as the working directory;
- prevents overlapping runs with the existing application lock plus task-level
  `IgnoreNew` behavior.

The exact chain is Task Scheduler -> repository VBS shim -> hidden repository PowerShell
launcher -> repository-pinned `.venv\Scripts\python.exe` -> common CLI. The launcher, not
Task Scheduler, invokes Python with fully quoted absolute paths and the repository working
directory, waits, logs, and returns the child exit code through the VBS shim. Posting tasks
run only when the operator is logged on, use `IgnoreNew`, and have no automatic restart or
Task Scheduler retry after a nonzero exit. `StartWhenAvailable` may perform one catch-up
run; application idempotency decides whether it is a no-op. Launcher tests use sentinel
child exit codes and a missing-interpreter case to prove propagation.

The PowerShell launcher passes its `run_id` into the common Python CLI. If Python is
missing or cannot start, it atomically writes the canonical `launcher_failed` result,
returns `60`, and attempts the minimal Telegram failure notice itself using sanitized
`.env` values. If Python starts but leaves no terminal result, the launcher writes the
fallback `internal_error` result and sends the same failure notice. The independent monitor
reads this canonical file and Task Scheduler status, so SQLite absence is expected for a
launcher failure rather than treated as an inconsistent Python run.

Chrome remains visible in the interactive user session. Only console windows are hidden.
The task must run only when the operator's desktop session can display the headed browser.

### 4.4 Browser runtime

Use installed stable Google Chrome through Playwright's branded Chrome channel in headed
mode. This avoids dependence on a separately downloaded Playwright Chromium cache, which
is the current failure point. The initial recovery changes only browser executable/channel
selection and preserves the existing persistent profile, configured user-agent override,
viewport, headed mode, timing, typing, and posting limits. A user-agent change is a separate
compatibility migration: preserve the configured value from silent replacement, but a
verified mismatch between it and the installed Chrome identity fails closed for live
posting. Do not alter the identity or resume submission until a read-only Facebook
preflight, regression comparison, and explicit operator approval have approved either the
real browser identity or another non-deceptive compatible configuration.

The new browser channel must never open the sole live `profiles/main` first. Under the
application lock, create and validate an untouched rollback backup, record a redacted
profile-version/manifest hash, clone the profile to an ignored versioned candidate path,
and run the new Chrome channel's authentication/challenge compatibility probe only on that
clone without opening a composer. Chrome may migrate the candidate, never the rollback
copy. Only a healthy read-only result may atomically promote the already-tested candidate
to `profiles/main`; promotion records before/after evidence and retains the original
rollback copy. Clone, probe, or promotion failure blocks live rollout.

Preflight verifies that Chrome exists, the dedicated `profiles/main` directory belongs to
this application and is not locked, a read-only authenticated Facebook page probe
succeeds, no checkpoint or challenge is visible, and no other posting process is active.
Cookie presence alone is not authentication proof. A failed preflight performs no
submission.

`keepalive` is strictly read-only. It may open the Facebook home page and read login or
challenge state; it never opens a composer, posts, reacts, comments, messages, or interacts
with a challenge. Login/challenge findings open the same persistent circuit as posting.

### 4.5 Property source

Treat
`G:\マイドライブ\0.物件資料_お客様紹介用\Estateboard`
as the operator-facing property source. The machine-readable input remains the synchronized
`_データ\properties.json` / EstateBoard repository export. Preflight compares source
existence, maximum age of 30 hours, file size, and SHA-256 before selecting a property.
The selected flattened record must contain `property.allowBrokerSharing`; nested input may
instead use `property: {allowBrokerSharing: ...}`. Normalize with `str(value).upper()` and accept
only the exact value `TRUE`, matching `src.estateboard_adapter.is_broker_ok`. Missing,
null, empty, numeric, or any other value is ineligible. It must not recursively
scan the entire document tree during every run.

### 4.6 State and interfaces

SQLite remains the posting source of truth. A target is `posted` only after a public match
is found and a permalink is captured. `uncertain` and approval-pending targets block
automatic repeat submission but never appear as verified posts.

Scheduled runs select only targets in an explicit `approved` state. Approval binds
`property_id`, `group_id`, normalized generated-body SHA-256, source-record SHA-256,
generation fingerprint, immutable approval ID, approval source (`telegram`, `operator`, or
configured `auto_policy`), and approval time.
The repository defaults remain `AUTO_APPROVE=false`; when production explicitly enables
`AUTO_APPROVE=true`, policy approval is persisted as `auto_policy` only after every
eligibility and safety gate passes. Any source hash, generated-content hash, or
generation-fingerprint change invalidates the approval and prevents posting until a new
approval exists.

Before opening the composer, create a durable submission attempt keyed by
`(property_id, group_id, approval_id)` in the same SQLite transaction that moves the
target from `approved` to `submitting`. Immediately before the final Post click, persist
`click_started_at`. Any process interruption after that point recovers as
`uncertain/reconcile_only`, never as eligible for submission. `verify-posts` may only
confirm, demote, or retain an attempt; it never submits. Crash-injection tests cover
failure before click, after click, after Facebook response, during verification, and before
the final SQLite update.

Allowed submission-state transitions are:

| From | Condition | To | Submission eligible afterward |
| --- | --- | --- | --- |
| `pending_approval` | source hash, body hash, generation fingerprint, and immutable approval ID all match | `approved` | yes |
| `approved` | attempt transaction commits | `submitting` | no |
| `submitting` | planned failure or recovery while `click_started_at` is null | `approved` plus terminal `aborted_preclick` attempt | yes |
| `submitting` | `click_started_at` exists, process exits, or result is ambiguous | `uncertain/reconcile_only` | never |
| `submitting` | public match and permalink found | `posted` | never |
| `uncertain/reconcile_only` | later public match found | `posted` | never |
| `uncertain/reconcile_only` | no conclusive match | unchanged | never |
| `posted` | pending-approval evidence or prior verification proven invalid | `uncertain/reconcile_only` | never |
| `approved` | source hash, body hash, or generation fingerprint changes | `pending_approval` | no |

The final-click function refuses to interact unless `click_started_at` was committed first.
No state with `click_started_at` may transition to `approved`, a new attempt, or any other
submission-eligible state. In this design, verification "demote" means only
`posted` -> `uncertain/reconcile_only`.

All consumers use the same normalized result:

1. SQLite target state and evidence.
2. Local `posting_status.xlsx` and `posting_status.csv`.
3. A durable EstateBoard posting-status overlay joined into the root dashboard by property
   ID.
4. Group registry at `https://estateboard.pages.dev/groups.html`.
5. Telegram success, warning, and persistent failure notices.
6. The common CLI result JSON for Claude Code and Codex.

Downstream publication uses a durable SQLite outbox. Each event is keyed by
`(attempt_id, destination, event_type)` and delivered idempotently. Facebook state and
delivery state are separate: a verified Facebook post remains verified when web or
Telegram delivery is pending. Outbox reconciliation never invokes Facebook submission.

## 5. Account-protection controls

### 5.0 Existing Claude implementation preservation contract

The current Claude Code implementation is the compatibility baseline, not disposable
prototype code. Before changing posting behavior, capture characterization tests and a
configuration snapshot for all existing account-protection behavior, including:

- headed Playwright persistent context using `profiles/main`;
- the configured stable user-agent and viewport;
- randomized Task Scheduler windows, inter-post intervals, navigation dwell, mouse/scroll
  pauses, and bounded slow-typed prefix plus fast remainder input;
- active-hour rules, global daily limit, one post per group per JST day, same-group spacing,
  maximum groups per browser context, and configured cooldowns;
- duplicate-property prevention where both `posted` and `uncertain` block another post;
- no automatic group joining and membership/group-rule checks;
- immediate stop and manual handling for checkpoint, CAPTCHA, 2FA, account warning,
  posting block, unclassified login state, and post-submit ambiguity;
- no poster-level automatic retry for `SessionExpired`, `PostingBlocked`, or
  `PostNotVerified`; the existing outer recovery path for an ordinary expired session is
  preserved only under the safer sequence below;
- healthy-profile backup, bounded candidate restore for ordinary session expiry only, and
  no restore attempt intended to bypass a Facebook challenge;
- persistent Telegram alerts, evidence capture, approval handling, and later read-only
  verification of uncertain/pending posts.

Implementation begins by turning these behaviors into regression tests where coverage is
missing. Existing tests are retained. No baseline behavior may be deleted, weakened,
renamed into a silent no-op, or have its thresholds increased without a documented
before/after comparison and explicit operator approval. Refactoring must preserve public
configuration names and state semantics or provide a tested backward-compatible migration.

The first recovery patch is deliberately narrow: browser channel resolution, truthful
hidden-launcher exit propagation, result observability, and the already approved durable
state/web-delivery fixes. It does not change live user-agent, browser profile, pacing,
typing cadence, group targeting, daily volume, or challenge behavior, except that a tested
clone may be promoted to preserve the same profile lineage across Chrome's required format
migration; it never creates a fresh Facebook identity. New safeguards are
additive and may only make posting more conservative, observable, or fail-closed. Any later
proposal to remove or replace an existing behavior is isolated in its own change, tested
with a read-only Facebook probe where applicable, and presented to the operator before a
live rollout.

Session classification precedes any restore. Checkpoint, CAPTCHA, 2FA, account warning,
posting restriction, or an unclassified login state opens the indefinite global circuit
and never invokes restore. A positively classified ordinary `session_expired` opens the
session environment circuit. The bounded recovery may restore a validated healthy backup
only into a cloned candidate profile, perform a read-only authentication/challenge probe,
and promote it with the same backup/promotion rules used for browser migration. It cannot
clear a circuit, open a composer, or submit in that run. A later explicit successful
`preflight` clears only the ordinary session circuit; scheduled posting cannot clear it.

Claude Code history and the commits/tests associated with long-body typing, uncertain-post
handling, duplicate guards, checkpoint alerts, profile recovery, and scheduler pacing are
review inputs for the implementation plan. A protection-compatibility matrix records each
baseline behavior, current code/test, planned touch points, regression test, and post-change
result. Rollback preserves the original profile and database and never retries a target
whose submission state is ambiguous.

### 5.1 Conservative eligibility

- Post only to groups that are enabled, membership-confirmed, and suitable for property
  listings.
- Respect group-specific rules, link/image settings, forbidden terms, and active hours.
- Retain brand masking and current-property freshness checks.
- Default to one target per group per JST calendar day and at least 24 hours between
  submissions to the same group.
- Keep a global daily ceiling as a hard maximum, not a target.
- Never retry an ambiguous submission automatically.
- Require the configured group ID to match the loaded Facebook group page and membership
  probe. Missing or unknown identity is `group_unconfirmed` and fails closed.

### 5.2 Normal but non-deceptive interaction

Retain moderate randomized dwell times and typing cadence so the automation does not
hammer the UI or submit multiple actions instantaneously. Delays are operational pacing,
not security-control evasion. Use the normal visible Chrome UI and do not spoof browser
identity.

### 5.3 Circuit breakers

Circuit state is durable in SQLite and includes scope, reason, opened time, expiry, and
clearance. Every trigger has an executable scope:

| Trigger | Threshold/window | Scope | Minimum duration | Clearance |
| --- | --- | --- | --- | --- |
| Checkpoint, CAPTCHA, 2FA, account warning, restriction, posting-block marker, or unclassified login state | first occurrence | global | indefinite | operator command after manual review |
| Positively classified ordinary session expiry | first occurrence | environment/session | until healthy | candidate restore may prepare recovery but cannot clear it; later explicit successful preflight |
| Public verification failure or any post-submit ambiguity | first occurrence | affected group and attempt | 24 hours; attempt always reconcile-only | timer may reopen group, but attempt only resolves by verification |
| Composer or selector failure | 2 for one group in rolling 24 hours | affected group | 24 hours | automatic after expiry plus successful explicit preflight |
| Composer or selector failures across groups | failures in 3 distinct groups in rolling 24 hours | global | 24 hours | operator command after review and successful explicit preflight |
| Concurrent runner, locked/corrupt profile | first occurrence | environment | until healthy | successful explicit preflight; corrupt profile also requires operator review |
| Source missing, stale, hash/identity mismatch, or broker approval unknown | first occurrence | environment | until healthy | successful explicit preflight with valid source |
| Browser missing/runtime mismatch | first occurrence; no retry loop | environment | until healthy | successful explicit preflight |
| Other pre-submit browser/runtime failures | 3 in rolling 6 hours | environment | until healthy | successful explicit preflight |

Global circuits stop all posting. Group circuits stop only that group. Environment circuits
stop all browser submission while allowing read-only diagnosis and status reconciliation.
A global circuit always wins; scheduled runs cannot clear any circuit.

## 6. Web and Telegram behavior

### 6.1 Existing behavior to preserve

The repository already:

- writes verified posting metadata and permalink into the EstateBoard master and
  dashboard;
- deploys the EstateBoard `docs/` dashboard through Wrangler when data changes;
- publishes the group registry to `estateboard.pages.dev/groups.html`;
- sends Telegram messages for verified posts, uncertain posts, persistent session
  alerts, recovery, and daily completion summaries.

Logs from 2026-07-15 confirm successful group-registry publication and successful
EstateBoard commit, push, and deployment. On 2026-07-16, status synchronization continued
but no new verified post existed because the browser could not start. The later EstateBoard
daily regeneration erased the patched posting fields from public `data.json`, proving that
the current direct-patch strategy is not persistent.

Replace direct generated-file ownership with `docs/fb_post_status.json`, a durable overlay
owned by the posting pipeline. Every write is an atomically replaced full snapshot of the
current SQLite truth, not a single outbox-event payload. It contains schema version,
generated time, source `run_id`, deterministic canonical-ID ordering, status counts, and
per-property verified/uncertain/failed state, groups, dates, and permalinks. Corrections and
demotions therefore remove or change stale verified state on the next snapshot without
losing unrelated history.

Canonical property IDs follow one shared contract in the SQLite exporter, overlay builder,
and dashboard:

- EstateBoard `data.json` uses the trimmed string value of field `ID`.
- Autoposter SQLite uses `property_id` matching `^eb-(.+)$`; remove exactly one leading
  `eb-` and trim the remainder.
- Source records use trimmed `propertyId`, falling back to trimmed `id` only when
  `propertyId` is absent.
- IDs are otherwise case- and character-preserving; empty IDs, duplicate canonical IDs,
  invalid autoposter prefixes, or fallback conflicts are errors.

The overlay stores both `estateboard_id` and `autoposter_property_id`. The EstateBoard root
page loads `data.json` and the overlay independently and joins by `estateboard_id`. Each
overlay row must match exactly one dashboard property. Any unmatched or multiply matched
row keeps web delivery pending as `web_sync_failed`, raises a visible dashboard warning,
and enters downstream-only reconciliation; it never invokes Facebook submission.

EstateBoard daily property regeneration must not delete or rewrite the overlay. The root
dashboard publishes DOM diagnostics after joining:
`data-fb-overlay-schema`, `data-fb-overlay-run-id`, `data-fb-overlay-count`,
`data-fb-joined-count`, and `data-fb-unmatched-count`. Overlay delivery completes only
after both an HTTP overlay read-back confirms schema/run/count and an isolated browser
integration probe of the deployed root page confirms the same schema/run ID, joined count
equals overlay count, unmatched count is zero, and at least the expected verified rows are
visibly marked. The probe uses an isolated non-Facebook browser context and never opens the
Facebook profile.

If the overlay is missing, unreadable, or older than 30 hours, the root dashboard displays
a visible posting-status warning and `unknown/stale`; it must not silently display empty
posting columns as zero posts. The group registry remains a separate group-level view.

### 6.2 Required completion contract

Telegram credential recovery uses
`G:\マイドライブ\AI_Agents\Private\API_AWS_DB.xlsx` as the operator-owned private source.
The runtime `.env` remains the ignored local materialization used by the application. A
2026-07-16 read-only check confirmed that both `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` currently match the private source. Values must never enter Git,
structured run results, ordinary logs, screenshots, or design documents. Credential
rotation is an explicit setup operation, not part of each scheduled run.

A successful daily run requires all of:

- Facebook submission completed;
- public post match found;
- permalink captured;
- SQLite target status is `posted`;
- local status files refreshed;
- EstateBoard posting overlay generated and joined by the root dashboard;
- web deployment confirmed and result recorded;
- Telegram completion message delivery confirmed and result recorded.

Web or Telegram delivery failure must not change a verified Facebook post back to failed.
Instead, the run becomes `posted_delivery_pending`, queues reconciliation, and alerts
the operator without submitting the property again.

For the live recovery rollout, acceptance requires eventual confirmed delivery to both
EstateBoard/web and Telegram. A scheduled run may exit `50` after a verified Facebook post
while delivery remains pending; outbox reconciliation must bring it to a recorded delivered
state without re-entering Facebook submission.

## 7. Error handling and observability

Use stable reason codes rather than parsing free-form logs, including:

- `browser_missing`
- `launcher_failed`
- `profile_locked`
- `overlap_locked`
- `session_expired`
- `facebook_challenge`
- `posting_blocked`
- `approval_pending`
- `approval_invalidated`
- `group_unconfirmed`
- `submission_uncertain`
- `verification_failed`
- `source_missing`
- `source_stale`
- `ai_generation_blocked`
- `provider_unavailable`
- `provider_timeout`
- `provider_auth_failed`
- `provider_output_invalid`
- `provider_policy_rejected`
- `web_sync_failed`
- `telegram_failed`
- `already_posted_today`
- `success`

Task Scheduler exit status, latest result JSON, monitor status, and Telegram alert must
agree on the outcome. A monitor must consider successful process exit insufficient unless
the result document is fresh and semantically healthy.

Operational logs and screenshots live only in ignored runtime directories. They redact
tokens, cookies, authorization headers, credentials, unnecessary local private paths, and
full post bodies. Screenshots are limited to posting evidence where practical and never
capture password, challenge-code, Messenger, or unrelated personal screens. Retain routine
screenshots for 30 days and structured operational logs for 90 days; retaining incident
evidence longer requires an operator decision.

## 8. Testing and rollout

1. Add failing tests for browser selection, preflight reason codes, result-file writes,
   hidden-launcher exit propagation, approval hash invalidation, durable attempt recovery,
   circuit thresholds, outbox idempotency, full-snapshot overlay corrections,
   canonical-ID missing/duplicate/unmatched cases, EstateBoard overlay persistence and
   browser join read-back, root dashboard stale-warning behavior, and delivery-warning
   semantics. An end-to-end
   launcher test asserts one identical `run_id` across the start record, final latest JSON,
   dated history record, and SQLite row. It also injects an import-time/abrupt Python exit
   and asserts that the launcher finalizes the same run as `internal_error` without
   overwriting a valid terminal result.
   Add gateway contract tests for every built-in adapter, executable allowlisting,
   no-shell/no-console process creation, environment/config isolation, timeouts and output
   limits, temporary-file cleanup, secret redaction,
   deterministic template fallback, fact/claim validation, approval invalidation after a
   profile or model change, and identical protocol, safety-validation, approval, failure,
   and fallback semantics across provider switches. Only the template profile must produce
   byte-identical text for a synthetic fixture. CLI adapter tests use fake executables;
   live provider smoke tests are opt-in.
   Before modifying posting code, add characterization tests for every item in the existing
   Claude implementation preservation contract and produce the protection-compatibility
   matrix. The recovery test suite must prove unchanged configured UA, persistent profile,
   headed mode, viewport, pacing ranges, typed-prefix behavior, active-hour/daily/group
   limits, duplicate/uncertain guards, retry exclusions, and challenge/manual-stop behavior.
2. Run the existing unit suite and Ruff without live posting.
3. Validate the common CLI in dry-run mode.
4. Validate headed Chrome login and challenge detection without opening the composer.
   Before the first branded-Chrome launch, validate the rollback backup, run the probe on a
   cloned candidate profile, record redacted profile-version/manifest evidence, promote
   only the tested clone, and prove that the untouched rollback copy remains restorable.
5. Install the corrected scheduled tasks and confirm no console window appears while the
   real exit code reaches Task Scheduler.
6. Execute one authorized live post within configured limits.
7. Verify the Facebook permalink, SQLite row, local status files, EstateBoard dashboard,
   group registry, Telegram message, and result JSON.
8. Leave conservative limits unchanged after the first success and observe before any
   future volume change.

## 9. Rollback

Before task replacement, export existing `FBAutoposter-*` task definitions to a dated
archive outside runtime folders. If the new launcher or Chrome channel fails, disable the
posting tasks, preserve database state and evidence, restore the task definitions if
needed, and do not retry a possibly submitted target.

## 10. Acceptance criteria

- Claude Code, Codex, Gemini, GLM/other OpenAI-compatible services, and local LLMs can be
  selected through documented provider profiles without changing posting code.
- `AI_PROFILE=template` completes copy generation with no hosted AI dependency, and an AI
  provider outage cannot bypass validation, approval, or Facebook safety circuits.
- README files document provider setup, switching, smoke testing, capability differences,
  secret handling, and rollback to the no-AI profile.
- Claude Code and Codex can execute and inspect the same documented operational CLI
  commands independently of which AI generation profile is selected.
- Scheduled runs show no console window; headed Facebook Chrome may appear.
- Task Scheduler reflects the actual child-process result.
- Missing browser/runtime state is detected before retry loops begin.
- A Facebook challenge or restriction causes an immediate fail-closed stop.
- Existing Claude Code account-protection behavior has a completed compatibility matrix,
  passes regression tests, and is not weakened or silently replaced by the recovery.
- Initial recovery leaves configured UA, persistent-profile path and identity lineage,
  headed mode, viewport, pacing, typing cadence, group targeting, and posting-volume
  thresholds unchanged.
- A mismatched configured UA blocks live posting and is never silently changed; any identity
  migration requires read-only evidence and explicit operator approval.
- The first new-channel and ordinary-session recovery probes use cloned profiles, preserve
  an untouched validated rollback copy, and cannot submit or clear a circuit in the same
  run.
- No target is reposted after an uncertain or verified submission.
- A verified live post has a permalink and appears in SQLite, EstateBoard, the web
  dashboard, Telegram reporting, and the CLI result document after reconciliation.
- A subsequent EstateBoard daily `data.json` rebuild does not remove posting state from the
  root dashboard, and a missing/stale overlay produces a visible warning instead of zero
  posted rows.
- Existing user-owned `desktop.ini` changes and unrelated workspace files remain untouched.

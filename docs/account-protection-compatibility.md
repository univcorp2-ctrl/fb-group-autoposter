# Facebook account-protection compatibility baseline

This matrix freezes the Claude Code behavior at base commit `bf62f11`. Tests are offline
characterization tests or source/configuration checks; they do not access Facebook. The
planned touch point names the later runtime-recovery task that may interact with the row.

| Protection | Current symbol or test | Configuration threshold | Planned touch point | Exact regression assertion |
| --- | --- | --- | --- | --- |
| Headed mode | `FacebookPoster._post_job_real`; `test_browser_contract_preserves_existing_identity` | `headless=False` | Task 4 browser launch builder; Task 5 poster integration | `BrowserContract.from_settings(settings).headless is False`. |
| Persistent main profile | `Settings.profile_dir`; `test_browser_contract_preserves_existing_identity` | `PROFILE_DIR=profiles/main` | Task 4 candidate clone/read-only probe | Contract `user_data_dir == Path("profiles/main")`; the live identity path does not change. Windows automatic profile promotion is intentionally disabled pending a separately reviewed OS-atomic mechanism. |
| Configured stable UA | `Settings.browser_user_agent`; `test_browser_contract_preserves_existing_identity` | configured `BROWSER_USER_AGENT`; fallback Chrome 126 UA | Task 4 UA preflight; Task 5 launch builder | Contract UA equals `settings.browser_user_agent`, and the fallback ends in `Chrome/126.0.0.0 Safari/537.36`. |
| Viewport | `FacebookPoster._post_job_real`; `test_browser_contract_preserves_existing_identity` | 1366 x 900 | Task 4 launch builder | Contract viewport is exactly `{"width": 1366, "height": 900}`. |
| Scheduler jitter | `scripts/install_windows_tasks.ps1`; `test_scheduler_keeps_randomized_posting_windows` | Morning/Evening 45 min; Midday/Afternoon 30 min | Task 7 task action rewrite | All four posting task times and `RandomDelayMin` values remain exact. |
| Inter-post range | `FacebookPoster._random_interval`; `test_settings_defaults_preserve_conservative_runtime_controls` | `MIN_INTERVAL_MIN=15`, `MAX_INTERVAL_MIN=35` | Task 5 poster integration | Defaults remain `(15, 35)` and `_random_interval` continues to draw between those minute bounds. |
| Navigation dwell | `FacebookPoster._post_one`; `test_poster_keeps_navigation_and_human_pause_ranges` | 1200-3500 ms | Task 5 poster integration | Source retains `random.randint(1200, 3500)` immediately after navigation. |
| Mouse/scroll pauses | `FacebookPoster._human_pause`; `test_poster_keeps_navigation_and_human_pause_ranges` | two mouse moves, wheel 100-400, pause 800-3200 ms when `HUMANIZE=true` | Task 5 poster integration | Humanization remains enabled by default and retains both moves, wheel range, and pause range. |
| Typed prefix | `HUMAN_TYPED_PREFIX_CHARS`; `test_human_typed_prefix_is_exactly_eighteen_characters` | exactly 18 characters; remainder delay 0 | Task 5 poster integration | Constant equals 18 and split recombines to the unchanged body. |
| Active hours | `FacebookPoster._group_allowed_now`; `test_preflight_blocks_outside_group_active_hours` | group `active_hours`, shared default `[7, 23]` | Task 5 preflight integration | A false active-hours decision yields exact reason `outside_active_hours`. |
| Daily/group limits | `FacebookPoster._preflight_target`; `test_preflight_blocks_daily_limit`; `QueueDB.posted_same_group_today` | configured `.env.example`: 2/day and one/group/JST day; code fallbacks 10/day and 20h | Task 3 circuits; Task 5 preflight integration | At the daily cap reason is `daily_limit`; posted or uncertain blocks the group for the JST day. |
| Maximum groups per browser context | `Settings.max_groups_per_browser`; `test_settings_defaults_preserve_conservative_runtime_controls` | 5 | Task 4 runtime; Task 5 poster integration | Default remains 5 and the poster recycles the context at `posted_in_browser >= 5`. |
| Cooldowns | `Settings.cooldown_hours`; `test_settings_defaults_preserve_conservative_runtime_controls` | 24 hours | Task 3 durable circuits | `cooldown_hours == 24`; later circuits may be stricter but never shorten this configured cooldown. |
| Duplicate/uncertain guards | `QueueDB.duplicate_property_posted_ever`; `test_duplicate_property_posted_ever_treats_uncertain_as_duplicate` | all-time per property/group; statuses `posted`, `uncertain` | Task 3 attempts; Task 5 poster integration | Either status makes `duplicate_property_posted_ever(...) is True`. |
| Retry exclusions | `FacebookPoster._post_one.retry`; `test_poster_retry_excludes_session_block_and_ambiguity` | 3 attempts for eligible failures; exclude `SessionExpired`, `PostingBlocked`, `PostNotVerified` | Task 3 attempts; Task 5 poster integration | Tenacity retry predicate returns false for each excluded exception. |
| Challenge stop | `CheckpointRequired`; `test_current_checkpoint_flow_restores_once_then_retries_before_stopping`; `tests/test_challenge_detection.py` | checkpoint, CAPTCHA, 2FA and login challenge require manual handling; current ensure flow inherits `SessionExpired` behavior and permits one restore plus one retry | Task 3 global circuit; Task 4 recovery boundary | Current flow classifies and records the challenge, restores once, retries once, then stops as `session_unrecoverable`; Task 4 must introduce the planned stricter rule that challenges never restore or retry. |
| Backup/restore | `backup_profile`, deprecated `restore_profile`; `tests/test_session_restore.py` | backups may be retained, but scheduler recovery is fail-closed | Task 4 clone-only recovery | `restore_profile` never overwrites the live profile. Scheduled ordinary expiry is canonicalized to `manual_profile_recovery_required` with a circuit open; only read-only preflight/manual login may proceed. |
| Membership/group-rule checks | `load_groups`, `validate_group`, `scripts/check_membership.py`; `test_membership_check_is_report_only_without_explicit_enable_flag` | only enabled, validated groups; membership script writes only with `--enable` | Task 5 eligibility; Task 6 CLI | Default membership invocation is report-only and posting loads only enabled, validated groups. |
| Evidence capture | `save_screenshot`; `FacebookPoster._post_one`; `test_posting_block_records_failure_without_screenshot_evidence` | screenshots for verified posted, uncertain, and ordinary exception failures; permalink required for posted; current `PostingBlocked` branch has no screenshot | Task 2 results; Task 3 attempts | Posted requires a found permalink; posted/uncertain/ordinary-failure paths retain screenshots, while the current `PostingBlocked` no-screenshot gap remains explicitly characterized until a later additive safeguard closes it. |
| Approval behavior | `TelegramApproval.auto_or_send_preview`; `tests/test_approval.py`; `test_settings_defaults_preserve_conservative_runtime_controls` | `AUTO_APPROVE=false`; degraded auto-approval skipped by default | Task 3 immutable approvals | Manual approval remains the default and approval is required before non-dry-run submission. |
| Persistent Telegram alerts | `TelegramApproval.raise_persistent_alert`; `tests/test_persistent_alerts.py` | re-notify every 30 minutes until acknowledged | Task 6 operational CLI; Task 7 launcher fallback | Alert is durably recorded, re-sent while pending, and removed only on acknowledgement/explicit recovery. |
| Read-only uncertain-post verification | `scripts/verify_posts.py`; `test_uncertain_verifier_probe_preserves_targets_but_may_initialize_schema` | `--probe` does not promote/demote target rows; constructing `QueueDB` may create or migrate schema | Task 3 reconcile-only attempts; Task 6 `verify-posts` | With an offline fake browser, probe leaves existing target rows unchanged while missing schema tables may be initialized. |
| No auto-join | `scripts/discover_groups.py`; scheduler description; `test_membership_check_is_report_only_without_explicit_enable_flag` | discovery is review-only; no join action | Task 6 `discover-groups`; Task 7 task migration | Scheduled discovery remains review-only, and membership checking cannot enable a group without explicit `--enable`. |

The production `.env.example` is intentionally more conservative than code fallbacks for
`MAX_POSTS_PER_DAY` and `MIN_SAME_GROUP_HOURS`. Runtime recovery must preserve the
configured values and configuration names; it must not treat the fallback values as a
reason to increase live cadence.

## Windows promotion boundary

On the production Windows runtime, candidate preparation and compatibility probing are
available only as contained, read-only recovery checks. Automatic replacement, restoration,
or promotion of `profiles/main` is intentionally disabled: the runtime returns
`manual_promotion_required` and does not rename or write the live/rollback/journal paths.
A separately reviewed OS-atomic mechanism is required before that policy can change.

## Recovery acceptance contract

`tests/test_recovery_acceptance_contract.py` freezes the recovery boundary with these
offline assertions:

- `test_invalid_permalink_cannot_confirm_a_submission_attempt` and
  `test_submission_attempt_record_accepts_a_captured_https_facebook_permalink`:
  the durable attempt record accepts only a captured HTTPS Facebook permalink;
  every other confirmation candidate becomes reconcile-only/uncertain.
- `test_daily_posting_reachable_modules_have_no_explicit_group_join_action`: the daily posting
  command's reachable `run_daily -> orchestrator -> poster` modules cannot invoke an
  explicit group-join API, URL, or Join/参加 button path. The strict pending
  `test_unreviewed_write_action_never_uses_healer_coordinate_click` blocks generic healer
  coordinate clicks until Task 3 limits them to reviewed composer actions.
- `test_telegram_and_estateboard_failures_preserve_attempt_truth_and_retry_budget`:
  injected Telegram and EstateBoard failures leave the Facebook attempt's posted truth,
  retry count, and single execution unchanged.
- The strict pending verified-post, preview, challenge, and summary producer contracts inject
  notification failures at their real boundaries and require unchanged target/attempt truth,
  no retry-budget loss, and a pending delivery event.
- `test_terminal_outcomes_have_the_canonical_exit_code_contract`: terminal outcomes use
  `fb-autoposter-run/v1` and map only to exit codes `0`, `20`, `30`, `40`, `50`, and `60`.
- `test_runtime_posting_gates_default_off_in_settings_defaults` in
  `tests/test_protection_compatibility.py`: posting remains dry-run and manual-approval
  gated in settings defaults. `test_installer_keeps_daily_posting_tasks_disabled_until_runtime_gates_pass`
  separately verifies the installer action state.

The legacy direct poster, named interruption-state, installer-gate, and terminal-propagation
assertions are strict pending contracts (`test_poster_runtime_invalid_permalink_never_records_posted`,
`test_named_interruption_states_quarantine_attempts_without_retry`,
`test_installer_keeps_daily_posting_tasks_disabled_until_runtime_gates_pass`, and
`test_scheduled_daily_child_propagates_canonical_terminal_result`). The generic-healer and
producer-delivery pending contracts are also strict (`test_unreviewed_write_action_never_uses_healer_coordinate_click`,
`test_verified_post_notification_failure_preserves_posted_truth_and_queues_delivery`,
`test_preview_notification_failure_preserves_approval_truth_and_queues_delivery`,
`test_challenge_notification_failure_preserves_challenge_stop_and_queues_delivery`, and
`test_summary_notification_failure_preserves_existing_targets_and_queues_delivery`). They are
intentionally `xfail(strict=True)` until their runtime boundaries exist; an unexpected pass
must be investigated, not silently accepted.

Repairs may add stricter preflight checks, but may not remove human typing delays,
challenge detection, daily/group limits, cooldowns, immutable approvals, or ambiguous-attempt
quarantine.

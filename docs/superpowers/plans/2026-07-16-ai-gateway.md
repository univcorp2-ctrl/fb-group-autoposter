# Provider-Neutral AI Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make post-copy generation and optional UI evidence analysis switchable among template, Codex, Claude, Gemini, GLM/other OpenAI-compatible APIs, and local LLMs without granting any AI control over Facebook.

**Architecture:** A typed `AIGateway` accepts a fact-only request and returns a structured content plan. Trusted local code renders all factual copy, validates every claim, and binds approval to a generation fingerprint; provider adapters are isolated behind one interface with template-only fallback.

**Tech Stack:** Python 3.11, dataclasses, YAML, requests/httpx, subprocess, pytest, Codex CLI, Claude Code CLI, Gemini CLI, OpenAI-compatible HTTP.

---

**Prerequisite:** Complete Tasks 1–6 of
`docs/superpowers/plans/2026-07-16-runtime-safety-recovery.md` first. This plan depends on
the created `src/operational_cli.py` plus immutable approval, attempt, run-result, and
circuit APIs. If those reviewed APIs change, update and re-review this plan rather than
inventing a parallel state path.

## File map

- Create `src/ai_gateway/models.py`: v1 request/response/content-plan models.
- Create `src/ai_gateway/evidence.py`: redacted screenshot allowlisting and observation protocol.
- Create `src/ai_gateway/profiles.py`: non-secret YAML profile loading and active selector.
- Create `src/ai_gateway/renderer.py`: deterministic local Japanese rendering.
- Create `src/ai_gateway/validation.py`: fact-key and unsupported-claim checks.
- Create `src/ai_gateway/gateway.py`: provider selection, one-shot template fallback, metrics.
- Create `src/ai_gateway/adapters/{template,openai_compatible,codex_cli,claude_cli,gemini_cli}.py`.
- Create `config/ai_profiles.example.yaml`.
- Modify `src/generator.py` and `src/healer.py` to use the gateway.
- Modify `src/operational_cli.py` for `ai-profile` commands.
- Modify `config.py`, `.env.example`, `README.md`, and `README_ja.md`.
- Add `tests/ai_gateway/` contract, isolation, rendering, validation, fallback, and CLI tests.

### Task 1: Define one provider-independent protocol

**Files:**
- Create: `src/ai_gateway/__init__.py`
- Create: `src/ai_gateway/models.py`
- Create: `src/ai_gateway/evidence.py`
- Test: `tests/ai_gateway/test_models.py`

- [ ] **Step 1: Write failing round-trip and rejection tests**

```python
def test_response_contains_plan_not_final_copy():
    response = GatewayResponse.from_dict({
        "schema": "ai-gateway-response/v1",
        "profile": "template",
        "plan": {"lead_intent": "new_listing", "fact_keys": ["price", "location"], "cta_intent": "inquiry"},
    })
    assert response.plan.fact_keys == ("price", "location")
    assert not hasattr(response, "post_body")
```

Reject unknown schema, unknown fact keys, arbitrary provider commands, and raw secret
fields. Define separate `ai-ui-evidence-request/v1` and `ai-ui-evidence-response/v1`
contracts with redacted image bytes/hash, an allowed question enum, observation enum, and
confidence. The schema has no selector, coordinate, script, or executable-action field.

- [ ] **Step 2: Verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_models.py -v`
Expected: FAIL for missing package.

- [ ] **Step 3: Implement immutable dataclasses and strict parsing**

Define `GatewayRequest`, `ContentPlan`, `GatewayResponse`, `EvidenceRequest`,
`EvidenceObservation`, `EvidenceResponse`, `ProviderMetadata`, capability dispatch, and
normalized outcomes. Ignore no unknown fields; reject them.

- [ ] **Step 4: Verify pass and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_models.py -v
git add src/ai_gateway tests/ai_gateway/test_models.py
git commit -m "feat: define provider-neutral AI protocol"
```

### Task 2: Add deterministic template, rendering, and factual validation

**Files:**
- Create: `src/ai_gateway/adapters/template.py`
- Create: `src/ai_gateway/renderer.py`
- Create: `src/ai_gateway/validation.py`
- Test: `tests/ai_gateway/test_renderer.py`
- Test: `tests/ai_gateway/test_validation.py`

- [ ] **Step 1: Write failing deterministic rendering tests**

Assert byte-identical output for identical synthetic facts, canonical insertion of price/location/yield, mandatory disclaimer/signature, and unchanged group-rule post-processing.

- [ ] **Step 2: Write failing unsupported-claim tests**

Reject an unreferenced number, currency, location, date, availability statement, attribute, superlative, guarantee, unknown fact key, and forbidden term. Accept connective text with no factual assertion.

- [ ] **Step 3: Verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_renderer.py tests/ai_gateway/test_validation.py -v`
Expected: FAIL for missing renderer/validator.

- [ ] **Step 4: Implement local renderer and validator**

The adapter returns the same `ContentPlan` schema as remote providers. Only renderer code inserts canonical values; all output goes through existing `apply_group_rules` and numeric-fact regression checks.

- [ ] **Step 5: Verify current generator invariants**

Run: `.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_renderer.py tests/ai_gateway/test_validation.py tests/test_generator.py tests/test_generator_body.py tests/test_group_rules.py tests/test_randomized_invariants.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/ai_gateway/adapters/template.py src/ai_gateway/renderer.py src/ai_gateway/validation.py tests/ai_gateway/test_renderer.py tests/ai_gateway/test_validation.py
git commit -m "feat: render validated property copy locally"
```

### Task 3: Add profile configuration and safe switching

**Files:**
- Create: `src/ai_gateway/profiles.py`
- Create: `config/ai_profiles.example.yaml`
- Modify: `config.py`
- Modify: `.env.example`
- Test: `tests/ai_gateway/test_profiles.py`

- [ ] **Step 1: Write failing profile validation tests**

Cover `template`, `openai_compatible`, and three fixed CLI adapters; reject shell fragments, credentials in URLs/YAML, unknown executables, remote plaintext HTTP, non-loopback local HTTP, external fallback profiles, and missing capability flags.

- [ ] **Step 2: Verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_profiles.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement reviewed profile loading**

`AI_PROFILE` selects a named profile. `AI_FALLBACK` accepts only `template|stop`. Remote base URLs require HTTPS; HTTP is allowed only for loopback local LLMs. Secrets are referenced by environment-variable name, never value.

- [ ] **Step 4: Implement atomic ignored selector**

`ai-profile set` writes `data/active_ai_profile.json` under the application lock and returns the previous profile for rollback; environment `AI_PROFILE` has explicit documented precedence.

- [ ] **Step 5: Verify and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_profiles.py -v
git add src/ai_gateway/profiles.py config/ai_profiles.example.yaml config.py .env.example tests/ai_gateway/test_profiles.py
git commit -m "feat: add safe AI provider profiles"
```

### Task 4: Add OpenAI-compatible API adapter

**Files:**
- Create: `src/ai_gateway/adapters/openai_compatible.py`
- Test: `tests/ai_gateway/test_openai_compatible.py`

- [ ] **Step 1: Write failing HTTP contract tests**

The first implementation supports OpenAI Chat Completions at
`<base_url>/chat/completions`. Use a fake transport and assert configured base
URL/model/key name, structured response parsing, timeout, size limit, 401/403
classification, malformed JSON, secret redaction, and no retry storm. Other protocols
require a new adapter/profile version.

- [ ] **Step 2: Verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_openai_compatible.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement one bounded request**

Send only the fact envelope and schema instruction. Map failures to stable reason codes and never log headers or raw prompt/response.

- [ ] **Step 4: Verify and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_openai_compatible.py -v
git add src/ai_gateway/adapters/openai_compatible.py tests/ai_gateway/test_openai_compatible.py
git commit -m "feat: add OpenAI-compatible AI adapter"
```

### Task 5: Add secret-isolated background CLI adapters

**Files:**
- Create: `src/ai_gateway/cli_process.py`
- Create: `src/ai_gateway/containment.py`
- Create: `src/ai_gateway/adapters/codex_cli.py`
- Create: `src/ai_gateway/adapters/claude_cli.py`
- Create: `src/ai_gateway/adapters/gemini_cli.py`
- Test: `tests/ai_gateway/test_cli_process.py`
- Test: `tests/ai_gateway/test_cli_adapters.py`

- [ ] **Step 1: Write fake-executable isolation tests**

The fake executable dumps argv, cwd, and environment keys. Assert `shell=False`, no
console creation flag on Windows, isolated cwd/HOME/config, allowlisted environment only,
no Facebook/Telegram/Cloudflare variables, no repository path, bounded stdout/stderr,
timeout termination, request-file cleanup, cleanup-failure quarantine, and a 24-hour cap.
An adversarial fake attempts to read sentinel files in the repository, live profile, `G:`
source, and parent user profile; every read must fail.

- [ ] **Step 2: Write exact argv tests**

Assert current supported noninteractive forms:

```text
codex exec --ephemeral --sandbox read-only --output-schema <schema> -
claude -p --bare --tools "" --no-session-persistence --output-format json --json-schema <schema>
gemini -p <prompt> --output-format json --approval-mode plan --policy <deny-all-policy>
```

The implementation may adapt flags by detected CLI version, but every supported version has an explicit tested argv builder. Unsupported versions fail preflight.

- [ ] **Step 3: Verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_cli_process.py tests/ai_gateway/test_cli_adapters.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement process isolation and adapters**

Use a constructed environment, `subprocess.Popen` argument lists, `CREATE_NO_WINDOW`, hard
timeout, output cap, and `finally` cleanup. CLI execution is allowed only through a
built-in containment backend exposing the isolated request directory and one dedicated
credential store but not host drives/user profile (initial backends: `windows_sandbox` or
`docker`). A host-process backend is forbidden even with Codex `--sandbox read-only`,
because that does not deny host reads. If no backend passes the sentinel-read preflight,
CLI profiles are unsupported and production follows configured template fallback/stop.
Dedicated credential stores are exposed read-only.

- [ ] **Step 5: Verify and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_cli_process.py tests/ai_gateway/test_cli_adapters.py -v
git add src/ai_gateway/cli_process.py src/ai_gateway/containment.py src/ai_gateway/adapters/codex_cli.py src/ai_gateway/adapters/claude_cli.py src/ai_gateway/adapters/gemini_cli.py tests/ai_gateway/test_cli_process.py tests/ai_gateway/test_cli_adapters.py
git commit -m "feat: add isolated Codex Claude and Gemini adapters"
```

### Task 6: Implement gateway fallback, fingerprint, and metrics

**Files:**
- Create: `src/ai_gateway/gateway.py`
- Modify: `src/queue_db.py`
- Modify: `src/approval.py`
- Modify: `src/orchestrator.py`
- Test: `tests/ai_gateway/test_gateway.py`
- Test: `tests/ai_gateway/test_approval_fingerprint.py`

- [ ] **Step 1: Write failing gateway semantics tests**

Assert exactly one selected provider call; template-only one-shot fallback; `stop` maps to `preflight_blocked`/20; validation failure cannot reach approval; and provider failure is retained as a secondary reason.

- [ ] **Step 2: Write failing fingerprint approval tests**

Fingerprint profile, adapter, provider, model, prompt/template version, parameters,
renderer version, and policy version. Identical text with a changed fingerprint invalidates
approval. Cover real Telegram preview/callback payloads, stale callback rejection after
regeneration, auto-approval, pre-click revised approval, and post-click permanent
ineligibility end to end through `approval.py` and orchestrator.

- [ ] **Step 3: Verify failures**

Run: `.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_gateway.py tests/ai_gateway/test_approval_fingerprint.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement gateway and additive DB fields**

Record only provider/profile/model/outcome/latency/usage. Update `approval.py` callbacks
and orchestrator auto-policy to call the immutable approval API with property/group/source
hash/body hash/generation fingerprint/approval ID. Never store raw prompt, raw trace, or
secrets in run results.

- [ ] **Step 5: Verify and commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_gateway.py tests/ai_gateway/test_approval_fingerprint.py -v
git add src/ai_gateway/gateway.py src/queue_db.py src/approval.py src/orchestrator.py tests/ai_gateway/test_gateway.py tests/ai_gateway/test_approval_fingerprint.py
git commit -m "feat: bind approval to AI generation provenance"
```

### Task 7: Replace direct Claude calls without changing post semantics

**Files:**
- Modify: `src/generator.py`
- Modify: `src/healer.py`
- Modify: `src/operational_cli.py`
- Test: `tests/test_generator.py`
- Test: `tests/ai_gateway/test_generator_integration.py`
- Test: `tests/ai_gateway/test_healer_boundary.py`
- Test: `tests/ai_gateway/test_evidence_protocol.py`

- [ ] **Step 1: Write failing integration tests**

Assert generator uses gateway then local renderer/group rules. For evidence, test the
separate versioned request/response, capability rejection, screenshot source allowlist,
redaction callback, maximum dimensions/bytes, image hash, no retention, and denial of raw
password/challenge/Messenger/unrelated screens. Assert healer returns observations, never
executable clicks/selectors; `FacebookPoster` continues using deterministic selectors.

- [ ] **Step 2: Verify failure**

Run: `.venv\Scripts\python.exe -m pytest tests/ai_gateway/test_generator_integration.py tests/ai_gateway/test_healer_boundary.py tests/ai_gateway/test_evidence_protocol.py -v`
Expected: FAIL while direct Anthropic calls remain.

- [ ] **Step 3: Route generator and healer through AIGateway**

Keep existing template wording and group-rule behavior. Implement evidence capability
dispatch independently from content generation; adapters without vision fail with
`provider_policy_rejected`. Remove provider-specific settings from execution paths only
after backward-compatible config translation is tested.

- [ ] **Step 4: Add `ai-profile list/show/test/set` commands**

The synthetic test never opens Facebook or reads production property data. `set` requires
a successful test unless an interactive operator uses `--no-test`; noninteractive
`--no-test` is rejected. Test selector rollback, failed-test no-change, and printing the
previous profile.

- [ ] **Step 4a: Implement and test `preflight --ai`**

Extend the existing operational preflight without opening Facebook. Validate the selected
profile's capability, authentication, supported CLI version, containment backend and
sentinel-read denial, endpoint policy, and synthetic schema response. Any failure writes
`fb-autoposter-run/v1` with outcome `preflight_blocked`, primary reason
`ai_generation_blocked`, a specific secondary provider reason, and exit `20`. Add focused
tests to `tests/ai_gateway/test_preflight.py` for every failure and template success.

- [ ] **Step 5: Verify current and new tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_generator.py tests/test_generator_body.py tests/test_randomized_invariants.py tests/ai_gateway -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/generator.py src/healer.py src/operational_cli.py tests/ai_gateway tests/test_generator.py
git commit -m "refactor: route optional AI through gateway"
```

### Task 8: Document and verify provider switching

**Files:**
- Modify: `README.md`
- Modify: `README_ja.md`
- Modify: `docs/account-protection-compatibility.md`

- [ ] **Step 1: Document every supported profile**

Include template, Codex CLI, Claude CLI, Gemini CLI, GLM API, generic compatible API, and Ollama/local examples with placeholders only. Document capabilities, credentials, smoke test, switch, rollback, background behavior, and AI/Facebook boundary.

- [ ] **Step 2: Run fake-provider smoke matrix**

Run: `.venv\Scripts\python.exe -m pytest tests/ai_gateway -v`
Expected: every adapter has identical protocol/safety/failure semantics; generated prose may differ.

- [ ] **Step 3: Run full suite and lint**

Run: `.venv\Scripts\python.exe -m pytest && .venv\Scripts\python.exe -m ruff check .`
Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add README.md README_ja.md docs/account-protection-compatibility.md
git commit -m "docs: explain AI gateway provider switching"
```

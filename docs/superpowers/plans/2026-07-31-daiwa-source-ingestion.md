# DAIWA Canonical Source Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the approved DAIWA Google Sheet into stable, private SQLite records and an allowlisted public JSON feed without publishing empty, stale, confidential, or unauthorized properties.

**Architecture:** A narrow Google Sheets reader fetches one pinned spreadsheet/tab through a service account. Pure normalization code validates the exact 13-column contract and creates deterministic `daiwa-<20-hex>` IDs; SQLite stores private facts and property-specific publication authorizations, while an atomic exporter writes only `estateboard-daiwa/v1` public fields.

**Tech Stack:** Python 3.11, google-auth AuthorizedSession, SQLite, JSON, openpyxl for test fixtures only, pytest, Ruff.

---

**Spec:** `docs/superpowers/specs/2026-07-23-daiwa-facebook-delivery-design.md`

**Prerequisites:**

- Work only in `C:\Users\t0015\.config\superpowers\worktrees\fb-group-autoposter\recovery`.
- Preserve commits through `5aa8677`.
- Do not read `old`, `物件資料`, ZIP files, PDFs, or broad Drive search results at runtime.
- Do not modify the source Google Sheet or the private credential workbook.

## Cross-plan execution order

Execute this plan Tasks 1–3 first, then Telegram recovery Tasks 1–3 to establish the
generic outbox, then return here for Tasks 4–6. Continue with Telegram Tasks 4–7 and only
then start the canary plan. This order lets ingestion atomically enqueue notifications
without inventing a second event store.

## File map

- Modify `requirements.txt`: add the supported Google authentication dependency.
- Modify `config.py`: pinned DAIWA Sheet/tab/credential/output settings.
- Create `src/daiwa_sheet_source.py`: authenticated, bounded Sheet read and source metadata.
- Create `src/daiwa_records.py`: exact header validation, normalization, IDs, and public projection.
- Create `src/daiwa_store.py`: DAIWA snapshot and authorization persistence.
- Modify `src/queue_db.py`: additive DAIWA tables and indexes.
- Modify `src/daiwa_adapter.py`: consume canonical records and exact broker-sharing gate.
- Modify `scripts/daiwa_drafts.py`: read the canonical local export, never legacy paths.
- Create `scripts/ingest_daiwa.py`: operational ingestion entrypoint and run result.
- Create `scripts/authorize_daiwa.py`: exact property/fingerprint publication grant CLI.
- Create focused tests under `tests/`.
- Modify `.env.example`, `README.md`, and `README_ja.md`.

### Task 1: Pin configuration and Google Sheet transport

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py`
- Create: `src/daiwa_sheet_source.py`
- Test: `tests/test_daiwa_sheet_source.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Add tests proving defaults resolve to the approved spreadsheet ID and `Sheet1`, credential
paths are explicit, and an empty/different ID is rejected in production:

```python
def test_daiwa_defaults_pin_approved_sheet(monkeypatch, tmp_path):
    monkeypatch.delenv("DAIWA_SHEET_ID", raising=False)
    monkeypatch.delenv("DAIWA_SHEET_TAB", raising=False)
    settings = Settings.load(tmp_path / ".env")
    assert settings.daiwa_sheet_id == "1UtgWig_6qMMj4SEdZYrNSvHj8nvfP3nYRBn7CQ7Nw5A"
    assert settings.daiwa_sheet_tab == "Sheet1"
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_daiwa_sheet_source.py -v
```

Expected: FAIL because the settings and source client do not exist.

- [ ] **Step 3: Add settings and dependency**

Add `google-auth>=2.0` to `requirements.txt`. Add immutable settings:

```python
daiwa_sheet_id: str
daiwa_sheet_tab: str
google_application_credentials: Path
daiwa_public_output: Path
```

Default `DAIWA_PUBLIC_OUTPUT` to `data/daiwa_public.json`. Do not default credentials to a
tracked path.

- [ ] **Step 4: Implement the bounded source client**

Create a `DaiwaSheetSnapshot` dataclass and:

```python
EXPECTED_SHEET_ID = "1UtgWig_6qMMj4SEdZYrNSvHj8nvfP3nYRBn7CQ7Nw5A"

def fetch_sheet_snapshot(
    *,
    spreadsheet_id: str,
    tab: str,
    credentials_path: Path,
    now: datetime,
) -> DaiwaSheetSnapshot:
    ...
```

Use `service_account.Credentials.from_service_account_file` and
`google.auth.transport.requests.AuthorizedSession`. Request only:

- Sheets values range `Sheet1!A1:N1001`;
- Drive metadata fields `id,name,mimeType,modifiedTime`; and
- read-only scopes for Sheets and Drive metadata.

Columns A:M contain the exact contract. Reject any non-empty value in column N, any
non-empty row 1001, a different ID/tab, non-Sheet MIME type, missing credentials, or a
source modified more than 30 hours ago. This sentinel read proves the importer did not
truncate an added column or 1,001st row. Never log authorization headers, credential JSON,
or returned source URLs.

- [ ] **Step 5: Pass transport and configuration tests**

Run the tests from Step 2. Expected: PASS with mocked HTTP only.

- [ ] **Step 6: Commit**

```powershell
git add requirements.txt config.py src/daiwa_sheet_source.py tests/test_config.py tests/test_daiwa_sheet_source.py
git commit -m "feat: read pinned DAIWA Google Sheet"
```

### Task 2: Normalize exact DAIWA records and stable IDs

**Files:**
- Create: `src/daiwa_records.py`
- Test: `tests/test_daiwa_records.py`

- [ ] **Step 1: Write failing normalization tests**

Use the exact header fixture:

```python
EXPECTED_HEADERS = (
    "レコード種別", "受領日", "物件名・資料群", "資料種別", "所在地",
    "価格(万円)", "表面利回り(%)", "状況", "ソースファイル", "ページ",
    "Google Drive URL", "備考", "ファイルサイズ(bytes)",
)
```

Test:

- exact header acceptance and unknown/missing/duplicate header rejection;
- NFKC/trim/whitespace normalization;
- stable ID under row reorder;
- ID change when a tuple identity field changes;
- conflicting duplicate ID failure;
- `工事中`, missing price/yield/location, and confidential markers are ineligible;
- public output contains only the allowlist.

- [ ] **Step 2: Verify tests fail**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_daiwa_records.py -v
```

Expected: import failure for `src.daiwa_records`.

- [ ] **Step 3: Implement pure normalization**

Expose focused interfaces:

```python
def validate_headers(headers: Sequence[str]) -> None: ...
def canonical_daiwa_id(row: Mapping[str, Any], spreadsheet_id: str) -> str: ...
def normalize_daiwa_row(row: Mapping[str, Any], spreadsheet_id: str) -> DaiwaRecord: ...
def public_daiwa_item(record: DaiwaRecord) -> dict[str, Any]: ...
```

Compute the ID exactly as specified:

```python
payload = b"".join(len(part).to_bytes(4, "big") + part for part in encoded_parts)
property_id = "daiwa-" + hashlib.sha256(payload).hexdigest()[:20]
```

Keep `source_url`, `internal_note`, `source_file`, and `source_page` private. Public keys are
only `ID`, `物件名`, `種別`, `所在地`, `価格(万円)`, `表面利回り(%)`, and normalized `状況`.

- [ ] **Step 4: Pass tests**

Run Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/daiwa_records.py tests/test_daiwa_records.py
git commit -m "feat: normalize canonical DAIWA records"
```

### Task 3: Persist snapshots and exact publication authorizations

**Files:**
- Modify: `src/queue_db.py`
- Create: `src/daiwa_store.py`
- Create: `scripts/authorize_daiwa.py`
- Test: `tests/test_daiwa_store.py`
- Test: `tests/test_authorize_daiwa.py`

- [ ] **Step 1: Write failing migration and authorization tests**

Test creation and behavior of:

- `daiwa_source_runs`;
- `daiwa_properties`;
- `daiwa_publication_authorizations`;
- atomic snapshot commit;
- last-known-good preservation;
- literal `TRUE` only;
- 30-hour expiry;
- row-fingerprint invalidation;
- revocation; and
- no secrets/private paths in public queries.

- [ ] **Step 2: Verify failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_daiwa_store.py -v
```

Expected: missing table/API failure.

- [ ] **Step 3: Add additive migrations**

Do not rebuild `jobs`, attempts, approvals, or circuit tables. Add indexes on canonical
property ID, active source snapshot, and authorization expiry. Foreign-key authorizations
to the canonical property ID and retain historical source runs.

- [ ] **Step 4: Implement authorization semantics**

Expose:

```python
def authorize_publication(
    property_id: str,
    row_fingerprint: str,
    authorized_by: str,
    authorized_at: datetime,
    availability_confirmed_at: datetime,
    literal_value: str,
) -> str: ...

def broker_sharing_value(property_id: str, row_fingerprint: str, now: datetime) -> str:
    return "TRUE" if exact_active_authorization else "FALSE"
```

Never treat broad Facebook automation permission, a job approval, or `AUTO_APPROVE` as this
property authorization.

- [ ] **Step 5: Implement the exact authorization CLI**

Add:

```powershell
python scripts/authorize_daiwa.py `
  --property-id <daiwa-id> `
  --row-fingerprint <sha256> `
  --literal-value TRUE `
  --authorized-by operator_live_rollout `
  --availability-confirmed-at <RFC3339>
```

The CLI reads the current canonical row, refuses a fingerprint mismatch, accepts only the
literal uppercase string `TRUE`, writes one authorization, and prints only IDs/timestamps.
It never accepts an unbound “authorize all” option.

- [ ] **Step 6: Pass focused and existing DB tests**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_daiwa_store.py tests/test_authorize_daiwa.py tests/test_submission_attempts.py tests/test_circuits.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/queue_db.py src/daiwa_store.py scripts/authorize_daiwa.py tests/test_daiwa_store.py tests/test_authorize_daiwa.py
git commit -m "feat: persist DAIWA snapshots and publication grants"
```

### Task 4: Add atomic ingestion and public export

**Files:**
- Create: `scripts/ingest_daiwa.py`
- Modify: `src/run_result.py`
- Modify: `src/outbox.py`
- Test: `tests/test_ingest_daiwa.py`

- [ ] **Step 1: Write failing command tests**

Test successful ingestion, overlap rejection, stale/missing/empty source, invalid headers,
conflicting duplicates, unchanged rerun, atomic JSON replacement, preservation of the
previous good output after failure, and `--preflight-only` making no SQLite/JSON changes.

- [ ] **Step 2: Verify failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ingest_daiwa.py -v
```

- [ ] **Step 3: Implement the operational command**

**Task prerequisite:** Telegram recovery Task 3 has created the generic outbox.

The normal command must:

1. claim one `ingest-daiwa` run;
2. fetch and validate in memory;
3. persist one source run and all records atomically;
4. write `estateboard-daiwa/v1` through temp-file replace;
5. include `source_run_id`, UTC `generated_at`, `count`, fixed columns, and items;
6. enqueue `telegram:<run_id>:daiwa_ingestion:<outcome>` in the same transaction as the
   terminal source-run state;
7. finalize `fb-autoposter-run/v1`; and
8. return `0` only after DB, local JSON, and outbox event agree.

Map source/config errors to the existing `risk_stopped`/30 outcome, validation failures to
`preflight_blocked`/20, and unexpected internal errors to `internal_error`/60. An overlap
is also `internal_error`/60 with safe reason `overlap_rejected`. Exit 40 remains reserved
exclusively for `submission_ambiguous`. Add the required DAIWA reason codes to the
validated `REASON_CODES` set before using them.

Implement `--preflight-only` in the same task. It performs credential, exact Sheet
ID/tab/header, modified-time, row-bound, normalization, duplicate, and accepted-count
checks, but does not instantiate `QueueDB`, acquire an ingestion claim, or write SQLite,
run-result history, or public JSON. It prints one sanitized preflight JSON object and
returns 0/20/30/60 using the same semantic mapping.

- [ ] **Step 4: Pass tests and inspect a fixture export**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ingest_daiwa.py tests/test_run_result.py -v
```

Expected: PASS and a fixture export containing no `備考`, `Google Drive URL`, staff, token,
or local path. The `--preflight-only` tests must assert byte-for-byte unchanged DB/output
fixtures and no created run-result files.

- [ ] **Step 5: Commit**

```powershell
git add scripts/ingest_daiwa.py src/run_result.py src/outbox.py tests/test_ingest_daiwa.py
git commit -m "feat: ingest DAIWA source atomically"
```

### Task 5: Connect canonical DAIWA records to draft generation

**Files:**
- Modify: `src/daiwa_adapter.py`
- Modify: `scripts/daiwa_drafts.py`
- Test: `tests/test_daiwa_adapter.py`
- Create: `tests/test_daiwa_drafts.py`

- [ ] **Step 1: Write failing adapter tests**

Require canonical fields, exact property ID preservation, literal
`property.allowBrokerSharing`, and brand masking. Verify incomplete/unauthorized records
cannot produce a postable property.

- [ ] **Step 2: Verify failure**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_daiwa_adapter.py tests/test_daiwa_drafts.py -v
```

- [ ] **Step 3: Implement minimal adapter changes**

Remove legacy row-number ID construction. `daiwa_to_property` must copy the canonical
`ID`, map only public facts, attach the exact broker-sharing value, and retain existing
`mask_brands` behavior. Change drafts to read `DAIWA_PUBLIC_OUTPUT` and fail loudly on
missing/invalid schema instead of returning an empty draft set.

- [ ] **Step 4: Pass focused tests**

Run Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/daiwa_adapter.py scripts/daiwa_drafts.py tests/test_daiwa_adapter.py tests/test_daiwa_drafts.py
git commit -m "feat: generate drafts from canonical DAIWA feed"
```

### Task 6: Verify and document DAIWA ingestion

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `README_ja.md`

- [ ] **Step 1: Run complete verification**

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
git diff --check
```

Expected: all tests pass, Ruff passes, and no whitespace error.

- [ ] **Step 2: Run read-only source preflight**

Run the command in `--preflight-only` mode using the service account. It may read the
pinned Sheet but must not write SQLite/public JSON. Record only schema, counts, age,
configured booleans, and safe reason codes.

- [ ] **Step 3: Run one real ingestion without Facebook**

Require a non-zero accepted count, exact `estateboard-daiwa/v1` schema, stable rerun IDs,
and no private fields. This step does not deploy EstateBoard and does not construct a
Facebook browser.

- [ ] **Step 4: Document configuration and recovery**

Document pinned Sheet ID/tab, service-account sharing, authorization expiry, last-known-good
behavior, and commands. Do not document secret values.

- [ ] **Step 5: Commit**

```powershell
git add .env.example README.md README_ja.md
git commit -m "docs: document canonical DAIWA ingestion"
```

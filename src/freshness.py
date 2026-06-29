"""Pre-post freshness gate: confirm a property is STILL live on EstateBoard
right before posting, so we never post a listing that has since been deleted,
unpublished, sold, or pulled.

Why this exists: a job/property can be selected (or sit in the inbox/DB) and
then the underlying listing disappears from EstateBoard before we actually post.
Posting it anyway sends people to a property they cannot find — exactly the
problem this guards against. The check re-reads the LATEST EstateBoard export at
post time (not the snapshot used when the job was queued) and re-validates.

States:
  - "fresh"   : still postable on EstateBoard            -> allow posting
  - "stale"   : gone / deleted / unpublished / no price  -> SKIP + alert
  - "unknown" : source unreadable or property is from an unverifiable origin
                (manual/sample) -> fail OPEN (allow) but log; callers may alert
                when a source file that *should* exist is missing, so a silent
                verification outage never looks like "all fresh".

Fail-open on "unknown" is deliberate: a transient missing-file must not halt all
posting (that would recreate the "投稿抜け日" problem), while a definitively
absent/deleted listing is always caught.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.estateboard_adapter import _get, is_broker_ok

log = logging.getLogger(__name__)

FRESH = "fresh"
STALE = "stale"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class FreshnessResult:
    state: str  # FRESH | STALE | UNKNOWN
    reason: str

    @property
    def is_stale(self) -> bool:
        return self.state == STALE

    @property
    def allow_post(self) -> bool:
        # Only a definitive STALE blocks; FRESH and UNKNOWN both allow.
        return self.state != STALE

    @property
    def source_missing(self) -> bool:
        return self.state == UNKNOWN and self.reason.endswith("_source_unavailable")


def _eb_key(item: dict[str, Any]) -> str:
    """Rebuild the same property_id the adapter assigns: eb-<propertyId|id>."""
    return f"eb-{item.get('propertyId') or item.get('id')}"


def _eb_stale_reason(item: dict[str, Any]) -> str:
    """Return '' if the item is postable, else the specific stale reason."""
    if item.get("deletedAt"):
        return "deleted"
    if item.get("publicationStatus") != "PUBLISHED":
        return "unpublished"
    if not is_broker_ok(item):
        return "broker_sharing_off"
    if not _get(item, "price"):
        return "no_price"
    return ""


def _load_json(path: Path | None) -> Any | None:
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("freshness source not found: %s", path)
        return None
    except Exception as exc:  # noqa: BLE001 - a malformed source must not crash posting
        log.warning("freshness source unreadable %s: %s: %s", path, type(exc).__name__, exc)
        return None


def _items_of(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        return data.get("items", []) or []
    return data if isinstance(data, list) else []


class FreshnessChecker:
    """Re-validates a property against the latest EstateBoard exports.

    Sources are loaded lazily and cached for the life of the checker (one posting
    run), so repeated per-target checks do not re-read the files.
    """

    def __init__(self, eb_source: Path | str | None, daiwa_source: Path | str | None = None):
        self._eb_source = Path(eb_source) if eb_source else None
        self._daiwa_source = Path(daiwa_source) if daiwa_source else None
        self._eb_index: dict[str, dict[str, Any]] | None = None
        self._eb_loaded = False
        self._daiwa_ids: set[str] | None = None
        self._daiwa_loaded = False

    def _eb(self) -> dict[str, dict[str, Any]] | None:
        if not self._eb_loaded:
            self._eb_loaded = True
            data = _load_json(self._eb_source)
            if data is None:
                self._eb_index = None
            else:
                self._eb_index = {_eb_key(it): it for it in _items_of(data)}
        return self._eb_index

    def _daiwa(self) -> set[str] | None:
        if not self._daiwa_loaded:
            self._daiwa_loaded = True
            data = _load_json(self._daiwa_source)
            if data is None:
                self._daiwa_ids = None
            else:
                self._daiwa_ids = {f"daiwa-{row.get('ID')}" for row in _items_of(data)}
        return self._daiwa_ids

    def check(self, property_id: str) -> FreshnessResult:
        pid = str(property_id or "")
        if pid.startswith("eb-"):
            return self._check_eb(pid)
        if pid.startswith("daiwa-"):
            return self._check_daiwa(pid)
        # sample-/manual ingests have no authoritative source to verify against.
        return FreshnessResult(UNKNOWN, "unverifiable_source")

    def _check_eb(self, pid: str) -> FreshnessResult:
        index = self._eb()
        if index is None:
            return FreshnessResult(UNKNOWN, "eb_source_unavailable")
        item = index.get(pid)
        if item is None:
            return FreshnessResult(STALE, "not_in_estateboard")
        reason = _eb_stale_reason(item)
        if reason:
            return FreshnessResult(STALE, reason)
        return FreshnessResult(FRESH, "postable")

    def _check_daiwa(self, pid: str) -> FreshnessResult:
        ids = self._daiwa()
        if ids is None:
            return FreshnessResult(UNKNOWN, "daiwa_source_unavailable")
        if pid not in ids:
            return FreshnessResult(STALE, "not_in_daiwa")
        return FreshnessResult(FRESH, "present")


def build_checker(eb_source: Path | str | None, daiwa_source: Path | str | None = None) -> FreshnessChecker:
    """Construct a checker, deriving the Daiwa source from the EB source when not
    given (EstateBoard/output/received/properties.json -> EstateBoard/docs/data_daiwa.json)."""
    if daiwa_source is None and eb_source is not None:
        eb = Path(eb_source)
        # parents: [received, output, <EstateBoard repo root>]
        if len(eb.parents) >= 3:
            candidate = eb.parents[2] / "docs" / "data_daiwa.json"
            daiwa_source = candidate if candidate.exists() else None
    return FreshnessChecker(eb_source, daiwa_source)

"""Fail-closed Chrome and cloned-profile compatibility boundary.

This module is intentionally independent of the poster.  It never opens a
composer and it never launches a browser itself; callers inject a read-only
probe for the cloned profile.  That keeps the migration gate testable offline
and prevents an untested Chrome version from touching the live profile.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shutil
import stat
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_VOLATILE = frozenset({"SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"})
_SENSITIVE_COMPONENT_PREFIXES = ("cookie", "cache", "codecache", "gpucache", "diskcache", "dawncache")
_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class BrowserContract:
    """Identity and display settings that runtime recovery must preserve."""

    headless: bool
    user_data_dir: Path
    user_agent: str
    viewport: Mapping[str, int]

    @classmethod
    def from_settings(cls, settings: Any) -> "BrowserContract":
        return cls(
            headless=False,
            user_data_dir=Path(settings.profile_dir),
            user_agent=settings.browser_user_agent,
            viewport=MappingProxyType({"width": 1366, "height": 900}),
        )


@dataclass(frozen=True)
class CandidateProfile:
    """Paths for one contained clone-and-promote attempt."""

    run_id: str
    profile_root: Path
    live_path: Path
    backup_path: Path
    candidate_path: Path
    rollback_path: Path
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class ProbeResult:
    """Read-only probe decision.  Nothing here permits a submission by itself."""

    reason: str
    healthy: bool
    circuit_open: bool
    submission_allowed: bool
    manifest: Mapping[str, Any] | None = None
    candidate_binding: str | None = None


@dataclass(frozen=True)
class ProbeContext:
    """The only runtime information exposed to a read-only probe callback."""

    run_id: str
    launch_kwargs: Mapping[str, Any]
    binding: str


def discover_chrome(*, candidates: Iterable[str | Path] | None = None) -> Path | None:
    """Return a system Chrome executable if present, otherwise ``None``.

    The stable ``browser_missing`` reason is returned by :func:`probe_candidate`
    so this low-level discovery helper remains useful for an operator preflight.
    ``candidates`` is deliberately injectable for offline tests.
    """

    if candidates is None:
        program_files = os.environ.get("PROGRAMFILES", r"C:\\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\\Program Files (x86)")
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        candidates = (
            Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe",
        )
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def build_launch_kwargs(contract: BrowserContract, *, user_data_dir: str | Path | None = None) -> dict[str, Any]:
    """Build the exact persistent-context contract for branded, headed Chrome."""

    profile = Path(user_data_dir) if user_data_dir is not None else contract.user_data_dir
    return {
        "channel": "chrome",
        # The compatibility gate is always visible.  A manually constructed
        # contract cannot silently turn the migration probe into headless mode.
        "headless": False,
        "user_data_dir": str(profile),
        "user_agent": contract.user_agent,
        "viewport": dict(contract.viewport),
    }


def profile_manifest(profile_dir: str | Path, *, profile_root: str | Path | None = None) -> Mapping[str, Any]:
    """Return a redacted integrity manifest for safe, non-sensitive profile data.

    Cookie and cache paths and values are intentionally omitted from both the
    digest and returned evidence.  The result contains only a digest and count,
    never a file list or profile contents.
    """

    profile, _root = _contained_profile(profile_dir, profile_root)
    if not profile.is_dir():
        raise ValueError("profile directory is missing")
    _validate_tree(profile)
    digest = hashlib.sha256()
    files = 0
    for path in sorted((item for item in profile.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
        relative = path.relative_to(profile)
        if _excluded_from_manifest(relative):
            continue
        files += 1
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return MappingProxyType({"manifest_hash": digest.hexdigest(), "file_count": files})


def prepare_candidate(
    profile_dir: str | Path,
    run_id: str,
    *,
    profile_root: str | Path | None = None,
) -> CandidateProfile:
    """Create a validated rollback and isolated candidate under ``profile_root``.

    No caller-supplied path may escape the configured root.  The original live
    profile is copied twice: first to the retained backup, which is fsynced and
    validated, then from that backup to the candidate that Chrome may migrate.
    """

    _validate_run_id(run_id)
    live, root = _contained_profile(profile_dir, profile_root)
    with _application_lock(root):
        return _prepare_candidate(live, root, run_id)


def _prepare_candidate(live: Path, root: Path, run_id: str) -> CandidateProfile:
    if not live.is_dir():
        raise ValueError("profile directory is missing")
    _validate_tree(live)
    backup = root / "backups" / run_id / "main"
    candidate = root / "candidates" / run_id / "main"
    rollback = root / "rollbacks" / run_id / "main"
    for target in (backup, candidate, rollback):
        _assert_contained(target, root)
        _validate_destination_parent(target.parent, root)
    if backup.exists() or candidate.exists() or rollback.exists():
        raise ValueError("run_id already has profile state")

    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(live, backup, ignore=_ignore_volatile)
    _fsync_tree(backup)
    source_manifest = profile_manifest(live, profile_root=root)
    backup_manifest = profile_manifest(backup, profile_root=root)
    if source_manifest != backup_manifest:
        raise RuntimeError("backup_manifest_mismatch")

    candidate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(backup, candidate, ignore=_ignore_volatile)
    _fsync_tree(candidate)
    return CandidateProfile(run_id, root, live, backup, candidate, rollback, backup_manifest)


def probe_candidate(
    candidate: CandidateProfile,
    probe_callable: Callable[[ProbeContext], Mapping[str, Any] | None],
    *,
    contract: BrowserContract,
) -> ProbeResult:
    """Run a caller-provided read-only probe against the candidate only.

    The probe may report ``challenge``, ``session_expired``, ``authenticated``
    and a verified ``user_agent``.  Browser absence and identity mismatch stop
    before the callable can reach a composer.  A healthy compatibility result
    is promotable but is not, by itself, authorization to submit anything.
    """

    _validate_candidate(candidate)
    # The callback may launch a headed Chrome instance against the candidate,
    # so retain the root lock for the entire probe/migration window.
    with _application_lock(candidate.profile_root):
        chrome = discover_chrome()
        if chrome is None:
            return _probe_result(candidate, "browser_missing", healthy=False)
        context = _probe_context(candidate, contract)
        try:
            observed = _invoke_probe(probe_callable, context)
        except Exception:
            return _probe_result(candidate, "probe_failed", healthy=False)
        if observed is _DEPRECATED_PROBE:
            return _probe_result(candidate, "probe_contract_deprecated", healthy=False)
        if not isinstance(observed, Mapping):
            return _probe_result(candidate, "probe_failed", healthy=False)
        if observed.get("context_binding") != context.binding:
            return _probe_result(candidate, "probe_context_mismatch", healthy=False)

        challenge = observed.get("challenge")
        if challenge:
            return _probe_result(candidate, str(challenge), healthy=False)
        if observed.get("session_expired"):
            return _probe_result(candidate, "session_expired", healthy=False)
        verified_ua = observed.get("user_agent") or observed.get("observed_user_agent")
        if verified_ua is None:
            return _probe_result(candidate, "ua_unverified", healthy=False)
        if verified_ua != contract.user_agent:
            return _probe_result(candidate, "ua_mismatch", healthy=False)
        if observed.get("authenticated") is not True:
            return _probe_result(candidate, "authentication_unverified", healthy=False)
        return _probe_result(candidate, "healthy", healthy=True)


def promote_candidate(candidate: CandidateProfile, probe: ProbeResult) -> ProbeResult:
    """Fail closed: Windows automatic profile promotion is intentionally disabled."""

    # Deliberately do not take the runtime lock or validate/rename the live,
    # rollback, or journal paths.  This return is a manual-review handoff only.
    return ProbeResult("manual_promotion_required", False, True, False, probe.manifest, probe.candidate_binding)


def _probe_result(candidate: CandidateProfile, reason: str, *, healthy: bool) -> ProbeResult:
    """Bind every result to the candidate's exact post-probe state."""

    manifest = profile_manifest(candidate.candidate_path, profile_root=candidate.profile_root)
    binding = _candidate_binding(candidate, manifest)
    return ProbeResult(reason, healthy, not healthy, False, manifest, binding)


def _verify_probe_binding(candidate: CandidateProfile, probe: ProbeResult) -> None:
    """Reject a cross-candidate result or any mutation after the probe."""

    manifest = profile_manifest(candidate.candidate_path, profile_root=candidate.profile_root)
    expected = _candidate_binding(candidate, manifest)
    if probe.candidate_binding is None or probe.candidate_binding != expected:
        raise ValueError("candidate binding does not match the post-probe profile")


def _candidate_binding(candidate: CandidateProfile, manifest: Mapping[str, Any]) -> str:
    payload = {
        "candidate_path": str(candidate.candidate_path.resolve(strict=False)),
        "manifest_hash": manifest["manifest_hash"],
        "private_state": _private_state_digest(candidate.candidate_path, candidate.profile_root),
        "run_id": candidate.run_id,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_DEPRECATED_PROBE = object()


def _probe_context(candidate: CandidateProfile, contract: BrowserContract) -> ProbeContext:
    manifest = profile_manifest(candidate.candidate_path, profile_root=candidate.profile_root)
    opaque_binding = _candidate_binding(candidate, manifest)
    return ProbeContext(
        run_id=candidate.run_id,
        launch_kwargs=_deep_freeze(build_launch_kwargs(contract, user_data_dir=candidate.candidate_path)),
        binding=opaque_binding,
    )


def _invoke_probe(
    probe_callable: Callable[[ProbeContext], Mapping[str, Any] | None], context: ProbeContext
) -> Mapping[str, Any] | None | object:
    """Reject the old path/kwargs callback shape rather than leaking live state."""

    try:
        parameters = inspect.signature(probe_callable).parameters
    except (TypeError, ValueError):
        parameters = {}
    if len(parameters) != 1:
        return _DEPRECATED_PROBE
    return probe_callable(context)


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_deep_freeze(item) for item in value)
    return value


@contextmanager
def _application_lock(profile_root: Path):
    """Acquire a fail-closed root-local lock without breaking stale owners."""

    lock = profile_root / ".profile-runtime.lock"
    _assert_contained(lock, profile_root)
    _validate_destination_parent(lock.parent, profile_root)
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise RuntimeError("profile_locked_manual_recovery_required") from exc
    try:
        yield
    finally:
        lock.rmdir()


def _validate_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id) or ".." in run_id or "/" in run_id or "\\" in run_id:
        raise ValueError("invalid run_id")


def _contained_profile(profile_dir: str | Path, profile_root: str | Path | None) -> tuple[Path, Path]:
    raw_profile = Path(profile_dir)
    raw_root = Path(profile_root) if profile_root is not None else raw_profile.parent
    _validate_raw_configured_path(raw_root)
    _validate_raw_configured_path(raw_profile)
    profile = raw_profile.resolve(strict=False)
    root = raw_root.resolve(strict=False)
    _assert_contained(profile, root)
    return profile, root


def _validate_raw_configured_path(path: Path) -> None:
    """Check every existing raw component before resolving possible junctions."""

    absolute = path if path.is_absolute() else Path.cwd() / path
    for component in reversed([absolute, *absolute.parents]):
        if component.exists():
            _validate_filesystem_entry(component)


def _assert_contained(path: Path, root: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ValueError("path is outside configured profile root") from exc


def _validate_candidate(candidate: CandidateProfile) -> None:
    _validate_run_id(candidate.run_id)
    for path in (candidate.live_path, candidate.backup_path, candidate.candidate_path, candidate.rollback_path):
        _assert_contained(path, candidate.profile_root)
        if path.exists():
            _validate_tree(path)


def _validate_tree(root: Path) -> None:
    """Reject symlinks, Windows junctions, and hardlinked evidence files."""

    _validate_filesystem_entry(root)
    for directory, directories, filenames in os.walk(root, followlinks=False):
        for name in [*directories, *filenames]:
            _validate_filesystem_entry(Path(directory) / name)


def _validate_destination_parent(path: Path, root: Path) -> None:
    _assert_contained(path, root)
    current = root
    _validate_filesystem_entry(current)
    relative = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    for component in relative.parts:
        current = current / component
        if current.exists():
            _validate_filesystem_entry(current)


def _validate_filesystem_entry(path: Path) -> None:
    information = _path_lstat(path)
    if stat.S_ISLNK(information.st_mode) or getattr(information, "st_file_attributes", 0) & _REPARSE_POINT:
        raise ValueError("profile reparse points are not allowed")
    if stat.S_ISREG(information.st_mode) and information.st_nlink > 1:
        raise ValueError("profile hardlinks are not allowed")


def _path_lstat(path: Path | str) -> os.stat_result:
    return os.lstat(path)


def _excluded_from_manifest(relative: Path) -> bool:
    return any(
        part in _VOLATILE or _normalized_component(part).startswith(_SENSITIVE_COMPONENT_PREFIXES)
        for part in relative.parts
    )


def _normalized_component(component: str) -> str:
    return "".join(character for character in component.casefold() if character.isalnum())


def _private_state_digest(profile: Path, profile_root: Path) -> str:
    """Hash all candidate state privately, including cookie/cache contents.

    This hash is mixed only into the opaque candidate binding.  It is never
    returned in a manifest or journal, avoiding leakage of sensitive profile
    paths and values while still making their mutation promotion-blocking.
    """

    _assert_contained(profile, profile_root)
    _validate_tree(profile)
    digest = hashlib.sha256()
    for path in sorted(profile.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(profile)
        info = _path_lstat(path)
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(f"\0{info.st_mode}:{info.st_size}:{info.st_mtime_ns}:{info.st_nlink}\0".encode("ascii"))
        if path.is_file():
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
    return digest.hexdigest()


def _ignore_volatile(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _VOLATILE}


def _fsync_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            # Windows rejects fsync() on a read-only CRT file descriptor.
            # Backups/candidates are private copies, so opening read-write does
            # not alter their contents while giving the OS a flushable handle.
            with path.open("rb+") as handle:
                os.fsync(handle.fileno())
    _fsync_directory(root)


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)

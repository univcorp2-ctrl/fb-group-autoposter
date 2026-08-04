"""Offline tests for the Chrome/profile compatibility recovery boundary."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace as Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.browser_runtime as runtime


def _contract(profile: Path, user_agent: str = "configured-stable-user-agent"):
    return runtime.BrowserContract.from_settings(
        SimpleNamespace(profile_dir=profile, browser_user_agent=user_agent)
    )


def _probe_response(context, **values):
    return {"context_binding": context.binding, **values}


def _profile(tmp_path: Path) -> Path:
    profile = tmp_path / "profiles" / "main"
    profile.mkdir(parents=True)
    (profile / "Preferences").write_text('{"profile":"safe"}', encoding="utf-8")
    (profile / "Cookies").write_text("secret-cookie-value", encoding="utf-8")
    (profile / "Cache").mkdir()
    (profile / "Cache" / "entry").write_text("cache-value", encoding="utf-8")
    return profile


def test_discover_chrome_selects_an_existing_system_candidate(tmp_path):
    missing = tmp_path / "missing.exe"
    chrome = tmp_path / "chrome.exe"
    chrome.write_text("", encoding="utf-8")

    assert runtime.discover_chrome(candidates=[missing, chrome]) == chrome


def test_build_launch_kwargs_keeps_branded_headed_identity_contract(tmp_path):
    profile = _profile(tmp_path)

    kwargs = runtime.build_launch_kwargs(_contract(profile))

    assert kwargs == {
        "channel": "chrome",
        "headless": False,
        "user_data_dir": str(profile),
        "user_agent": "configured-stable-user-agent",
        "viewport": {"width": 1366, "height": 900},
    }


def test_build_launch_kwargs_cannot_make_the_compatibility_probe_headless(tmp_path):
    profile = _profile(tmp_path)
    contract = runtime.BrowserContract(
        headless=True,
        user_data_dir=profile,
        user_agent="configured-stable-user-agent",
        viewport={"width": 1366, "height": 900},
    )

    assert runtime.build_launch_kwargs(contract)["headless"] is False


def test_prepare_candidate_creates_validated_backup_and_redacted_manifest(tmp_path):
    profile = _profile(tmp_path)

    candidate = runtime.prepare_candidate(profile, "run-001")

    assert candidate.backup_path == tmp_path / "profiles" / "backups" / "run-001" / "main"
    assert candidate.candidate_path == tmp_path / "profiles" / "candidates" / "run-001" / "main"
    assert candidate.backup_path.is_dir()
    assert candidate.candidate_path.is_dir()
    assert candidate.manifest == runtime.profile_manifest(candidate.backup_path, profile_root=tmp_path / "profiles")
    serialized = repr(candidate.manifest).lower()
    assert "cookie" not in serialized
    assert "cache" not in serialized
    assert "secret-cookie-value" not in serialized


def test_profile_manifest_excludes_cookie_and_cache_variants_from_digest_and_count(tmp_path):
    profile = _profile(tmp_path)
    before = runtime.profile_manifest(profile)
    for relative in (
        "Cookies-wal",
        "Cookies-journal",
        "CacheStorage/indexed/entry",
        "Code Cache/js/entry",
        "GPUCache/entry",
        "Disk Cache/entry",
    ):
        path = profile / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("sensitive-browser-state", encoding="utf-8")

    after = runtime.profile_manifest(profile)

    assert after == before


def test_private_probe_binding_changes_when_sensitive_cookie_state_changes(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    candidate = runtime.prepare_candidate(profile, "run-001")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))
    result = runtime.probe_candidate(
        candidate,
        lambda context: _probe_response(
            context, authenticated=True, user_agent="configured-stable-user-agent"
        ),
        contract=_contract(profile),
    )
    (candidate.candidate_path / "Cookies-wal").write_text("changed-secret", encoding="utf-8")
    after = runtime.probe_candidate(
        candidate,
        lambda context: _probe_response(
            context, authenticated=True, user_agent="configured-stable-user-agent"
        ),
        contract=_contract(profile),
    )

    assert result.candidate_binding != after.candidate_binding


def test_profile_manifest_rejects_simulated_windows_reparse_point(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    real_lstat = os.lstat

    def simulated_lstat(path):
        result = real_lstat(path)
        attributes = 0x400 if Path(path).name == "Preferences" else 0
        return Namespace(
            st_mode=result.st_mode,
            st_nlink=result.st_nlink,
            st_file_attributes=attributes,
        )

    monkeypatch.setattr(runtime, "_path_lstat", simulated_lstat, raising=False)

    with pytest.raises(ValueError, match="reparse"):
        runtime.profile_manifest(profile)


def test_prepare_rejects_reparse_point_in_raw_configured_profile_root(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    real_lstat = os.lstat

    def simulated_lstat(path):
        result = real_lstat(path)
        attributes = 0x400 if Path(path).name == "profiles" else 0
        return Namespace(
            st_mode=result.st_mode,
            st_nlink=result.st_nlink,
            st_file_attributes=attributes,
        )

    monkeypatch.setattr(runtime, "_path_lstat", simulated_lstat)

    with pytest.raises(ValueError, match="reparse"):
        runtime.prepare_candidate(profile, "run-001", profile_root=tmp_path / "profiles")


def test_profile_manifest_rejects_hardlinked_files(tmp_path):
    profile = _profile(tmp_path)
    try:
        os.link(profile / "Preferences", profile / "linked-preferences")
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="hardlink"):
        runtime.profile_manifest(profile)


def test_stale_owner_lock_remains_fail_closed_for_manual_recovery(tmp_path):
    profile = _profile(tmp_path)
    lock = tmp_path / "profiles" / ".profile-runtime.lock"
    lock.mkdir()
    (lock / "owner.json").write_text(json.dumps({"pid": 42, "started_at": 0, "nonce": "stale"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="manual_recovery_required"):
        runtime.prepare_candidate(profile, "run-001")

    assert lock.is_dir()


@pytest.mark.parametrize("owner_text", (None, "not-json"))
def test_ownerless_or_invalid_lock_remains_fail_closed(tmp_path, owner_text):
    profile = _profile(tmp_path)
    lock = tmp_path / "profiles" / ".profile-runtime.lock"
    lock.mkdir()
    if owner_text is not None:
        (lock / "owner.json").write_text(owner_text, encoding="utf-8")
    with pytest.raises(RuntimeError, match="manual_recovery_required"):
        runtime.prepare_candidate(profile, "run-001")


def test_fresh_ownerless_lock_remains_fail_closed(tmp_path):
    profile = _profile(tmp_path)
    lock = tmp_path / "profiles" / ".profile-runtime.lock"
    lock.mkdir()

    with pytest.raises(RuntimeError, match="manual_recovery_required"):
        runtime.prepare_candidate(profile, "run-001")

    assert lock.is_dir()


def test_probe_callable_receives_only_an_immutable_candidate_probe_context(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    candidate = runtime.prepare_candidate(profile, "run-001")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))

    def probe(context):
        assert isinstance(context, runtime.ProbeContext)
        assert context.run_id == "run-001"
        assert context.launch_kwargs["user_data_dir"] == str(candidate.candidate_path)
        assert not hasattr(context, "live_path")
        assert not hasattr(context, "profile_root")
        return {
            "authenticated": True,
            "user_agent": "configured-stable-user-agent",
            "context_binding": context.binding,
        }

    result = runtime.probe_candidate(candidate, probe, contract=_contract(profile))

    assert result.healthy is True


def test_probe_context_deep_freezes_nested_viewport_options(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    candidate = runtime.prepare_candidate(profile, "run-001")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))

    def probe(context):
        assert context.launch_kwargs["viewport"] == {"width": 1366, "height": 900}
        with pytest.raises(TypeError):
            context.launch_kwargs["viewport"]["width"] = 1
        return _probe_response(context, authenticated=True, user_agent="configured-stable-user-agent")

    result = runtime.probe_candidate(candidate, probe, contract=_contract(profile))

    assert result.healthy is True


def test_prepare_candidate_rejects_run_id_traversal_and_profile_outside_root(tmp_path):
    profile = _profile(tmp_path)

    with pytest.raises(ValueError, match="run_id"):
        runtime.prepare_candidate(profile, "../escape")
    with pytest.raises(ValueError, match="profile root"):
        runtime.prepare_candidate(profile, "run-001", profile_root=tmp_path / "other")


def test_prepare_candidate_fails_closed_when_profile_runtime_lock_is_held(tmp_path):
    profile = _profile(tmp_path)
    lock = tmp_path / "profiles" / ".profile-runtime.lock"
    lock.mkdir()

    with pytest.raises(RuntimeError, match="profile_locked"):
        runtime.prepare_candidate(profile, "run-001")

    assert not (tmp_path / "profiles" / "backups" / "run-001").exists()


def test_missing_chrome_fails_with_stable_reason_before_probe(tmp_path, monkeypatch):
    candidate = runtime.prepare_candidate(_profile(tmp_path), "run-001")
    called = False
    monkeypatch.setattr(runtime, "discover_chrome", lambda: None)

    def probe(_candidate, _kwargs):
        nonlocal called
        called = True
        return {"authenticated": True}

    result = runtime.probe_candidate(candidate, probe, contract=_contract(candidate.live_path))

    assert result.reason == "browser_missing"
    assert result.submission_allowed is False
    assert called is False


def test_authenticated_probe_without_observed_user_agent_fails_closed(tmp_path, monkeypatch):
    candidate = runtime.prepare_candidate(_profile(tmp_path), "run-001")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))

    result = runtime.probe_candidate(
        candidate,
        lambda context: _probe_response(context, authenticated=True),
        contract=_contract(candidate.live_path),
    )

    assert (result.reason, result.healthy, result.submission_allowed) == (
        "ua_unverified",
        False,
        False,
    )


def test_verified_ua_mismatch_stops_before_any_composer_activity(tmp_path, monkeypatch):
    candidate = runtime.prepare_candidate(_profile(tmp_path), "run-001")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))
    calls: list[Path] = []

    def probe(context):
        calls.append(Path(context.launch_kwargs["user_data_dir"]))
        return _probe_response(context, authenticated=True, user_agent="another-browser-identity")

    result = runtime.probe_candidate(candidate, probe, contract=_contract(candidate.live_path))

    assert result.reason == "ua_mismatch"
    assert result.circuit_open is True
    assert result.submission_allowed is False
    assert calls == [candidate.candidate_path]
    assert candidate.live_path.is_dir()
    assert runtime.promote_candidate(candidate, result).reason == "manual_promotion_required"


def test_healthy_candidate_requires_manual_promotion_without_live_mutation(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    candidate = runtime.prepare_candidate(profile, "run-001")
    (candidate.candidate_path / "Preferences").write_text('{"profile":"migrated"}', encoding="utf-8")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))

    result = runtime.probe_candidate(
        candidate,
        lambda context: _probe_response(
            context, authenticated=True, user_agent="configured-stable-user-agent"
        ),
        contract=_contract(profile),
    )
    before_live = profile.joinpath("Preferences").read_text(encoding="utf-8")
    promoted = runtime.promote_candidate(candidate, result)

    assert promoted.reason == "manual_promotion_required"
    assert profile.joinpath("Preferences").read_text(encoding="utf-8") == before_live
    assert candidate.backup_path.is_dir()
    assert not candidate.rollback_path.exists()
    assert candidate.candidate_path.is_dir()
    assert not (tmp_path / "profiles" / ".promotion-journal.json").exists()


def test_manual_promotion_does_not_use_a_cross_candidate_probe_result(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    candidate_a = runtime.prepare_candidate(profile, "run-a")
    candidate_b = runtime.prepare_candidate(profile, "run-b")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))
    result_a = runtime.probe_candidate(
        candidate_a,
        lambda context: _probe_response(
            context, authenticated=True, user_agent="configured-stable-user-agent"
        ),
        contract=_contract(profile),
    )

    result = runtime.promote_candidate(candidate_b, result_a)

    assert result.reason == "manual_promotion_required"
    assert profile.is_dir()
    assert candidate_a.candidate_path.is_dir()
    assert candidate_b.candidate_path.is_dir()


def test_manual_promotion_does_not_touch_a_mutated_candidate(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    candidate = runtime.prepare_candidate(profile, "run-001")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))
    result = runtime.probe_candidate(
        candidate,
        lambda context: _probe_response(
            context, authenticated=True, user_agent="configured-stable-user-agent"
        ),
        contract=_contract(profile),
    )
    (candidate.candidate_path / "Preferences").write_text('{"profile":"mutated"}', encoding="utf-8")

    manual = runtime.promote_candidate(candidate, result)

    assert profile.joinpath("Preferences").read_text(encoding="utf-8") == '{"profile":"safe"}'
    assert manual.reason == "manual_promotion_required"
    assert profile.joinpath("Preferences").read_text(encoding="utf-8") == '{"profile":"safe"}'


def test_probe_holds_the_root_lock_for_the_read_only_probe_callback(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    candidate = runtime.prepare_candidate(profile, "run-001")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))

    def probe(context):
        assert (tmp_path / "profiles" / ".profile-runtime.lock").is_dir()
        with pytest.raises(RuntimeError, match="profile_locked"):
            runtime.prepare_candidate(profile, "contended")
        return _probe_response(context, authenticated=True, user_agent="configured-stable-user-agent")

    result = runtime.probe_candidate(candidate, probe, contract=_contract(profile))

    assert result.healthy is True
    assert not (tmp_path / "profiles" / ".profile-runtime.lock").exists()


def test_manual_promotion_never_invokes_profile_rename(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    candidate = runtime.prepare_candidate(profile, "run-001")
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))
    probe = runtime.probe_candidate(
        candidate,
        lambda context: _probe_response(
            context, authenticated=True, user_agent="configured-stable-user-agent"
        ),
        contract=_contract(profile),
    )
    monkeypatch.setattr(
        Path,
        "rename",
        lambda *_args: (_ for _ in ()).throw(AssertionError("rename must not run")),
    )

    result = runtime.promote_candidate(candidate, probe)

    assert result.reason == "manual_promotion_required"
    assert profile.is_dir()
    assert profile.joinpath("Preferences").read_text(encoding="utf-8") == '{"profile":"safe"}'
    assert candidate.backup_path.is_dir()
    assert candidate.candidate_path.is_dir()


def test_challenge_never_promotes_and_plain_expiry_keeps_circuit_open(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    monkeypatch.setattr(runtime, "discover_chrome", lambda: Path("C:/Chrome/chrome.exe"))

    challenged = runtime.prepare_candidate(profile, "challenge-001")
    challenge = runtime.probe_candidate(
        challenged,
        lambda context: _probe_response(context, challenge="checkpoint"),
        contract=_contract(profile),
    )
    assert (challenge.reason, challenge.circuit_open, challenge.submission_allowed) == (
        "checkpoint",
        True,
        False,
    )
    assert runtime.promote_candidate(challenged, challenge).reason == "manual_promotion_required"

    expired = runtime.prepare_candidate(profile, "expiry-001")
    expiry = runtime.probe_candidate(
        expired,
        lambda context: _probe_response(context, session_expired=True),
        contract=_contract(profile),
    )
    assert (expiry.reason, expiry.circuit_open, expiry.submission_allowed) == (
        "session_expired",
        True,
        False,
    )

"""Tests for the persistent acknowledge-until-cleared alert store."""
import itertools

from src.alerts import AlertStore


def _clock():
    """Deterministic, monotonically increasing ISO timestamps for tests."""
    counter = itertools.count()
    return lambda: f"2026-06-22T00:00:{next(counter):02d}+00:00"


def test_raise_creates_unacknowledged_alert(tmp_path):
    store = AlertStore(tmp_path / "alerts.json", now_fn=_clock())
    alert = store.raise_alert("session_dead", "再ログインしてください")
    assert alert["kind"] == "session_dead"
    assert alert["acknowledged"] is False
    assert alert["occurrences"] == 1
    assert store.pending_unacknowledged() and store.pending_unacknowledged()[0]["kind"] == "session_dead"


def test_reraise_refreshes_without_unacknowledging(tmp_path):
    store = AlertStore(tmp_path / "alerts.json", now_fn=_clock())
    store.raise_alert("session_dead", "msg1")
    store.acknowledge("session_dead")
    # A new run re-raises while the session is still dead — must NOT spam again.
    refreshed = store.raise_alert("session_dead", "msg2")
    assert refreshed["acknowledged"] is True  # stays acknowledged for this episode
    assert refreshed["occurrences"] == 2
    assert refreshed["message"] == "msg2"
    assert store.pending_unacknowledged() == []  # acknowledged -> not pending


def test_clear_then_reraise_is_fresh_unacknowledged(tmp_path):
    # Recovery clears the alert; a later death re-arms notifications.
    store = AlertStore(tmp_path / "alerts.json", now_fn=_clock())
    store.raise_alert("session_dead", "msg")
    store.acknowledge("session_dead")
    assert store.clear("session_dead") is True
    again = store.raise_alert("session_dead", "msg again")
    assert again["acknowledged"] is False
    assert again["occurrences"] == 1
    assert len(store.pending_unacknowledged()) == 1


def test_acknowledge_unknown_returns_false(tmp_path):
    store = AlertStore(tmp_path / "alerts.json", now_fn=_clock())
    assert store.acknowledge("nope") is False
    assert store.clear("nope") is False


def test_mark_notified_bumps_count(tmp_path):
    store = AlertStore(tmp_path / "alerts.json", now_fn=_clock())
    store.raise_alert("checkpoint", "checkpoint!")
    store.mark_notified("checkpoint")
    store.mark_notified("checkpoint")
    alert = store.get("checkpoint")
    assert alert["notify_count"] == 2
    assert alert["last_notified"] is not None


def test_state_survives_new_instance(tmp_path):
    path = tmp_path / "alerts.json"
    AlertStore(path, now_fn=_clock()).raise_alert("session_dead", "msg")
    # A fresh instance (new process) sees the persisted alert.
    assert AlertStore(path).get("session_dead")["message"] == "msg"


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "alerts.json"
    path.write_text("{ not json", encoding="utf-8")
    store = AlertStore(path)
    assert store.all() == []
    # And can still be written to afterwards.
    store.raise_alert("x", "y")
    assert store.get("x") is not None

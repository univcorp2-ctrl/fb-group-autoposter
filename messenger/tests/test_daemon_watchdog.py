from scripts.watch_messenger_daemon import decide

def test_running_recent_is_healthy():
    assert decide("Running",30)=="healthy_running"

def test_stale_running_does_not_kill_inflight_sends():
    assert decide("Running",2000)=="stale_running_investigate_without_kill"

def test_stopped_task_can_restart_silently():
    assert decide("Ready",None)=="start_stopped_daemon"

def test_disabled_task_not_started():
    assert decide("Disabled",None).startswith("blocked_")
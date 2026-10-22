from scripts.watch_extension_health import eligible_for_restart

NOW = 1800000


def test_restarts_only_unresponsive_extension_with_idle_operator():
    h = {"extension_polling": False, "active_lease": False, "posting_paused": False}
    assert eligible_for_restart(h, idle=901, last_restart=0, now=NOW)


def test_no_restart_while_extension_is_healthy():
    h = {"extension_polling": True, "active_lease": False, "posting_paused": False}
    assert not eligible_for_restart(h, idle=3600, last_restart=0, now=NOW)


def test_never_interrupt_an_active_facebook_submission():
    h = {"extension_polling": False, "active_lease": True, "posting_paused": False}
    assert not eligible_for_restart(h, idle=3600, last_restart=0, now=NOW)


def test_never_restart_while_user_is_active():
    h = {"extension_polling": False, "active_lease": False, "posting_paused": False}
    assert not eligible_for_restart(h, idle=75, last_restart=0, now=NOW)


def test_never_restart_when_posting_paused():
    h = {"extension_polling": False, "active_lease": False, "posting_paused": True}
    assert not eligible_for_restart(h, idle=3600, last_restart=0, now=NOW)


def test_enforce_six_hour_restart_cooldown():
    h = {"extension_polling": False, "active_lease": False, "posting_paused": False}
    assert not eligible_for_restart(h, idle=3600, last_restart=NOW - 3600, now=NOW)

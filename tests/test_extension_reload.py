from scripts.watch_extension_health import eligible_for_restart


def test_idle_version_update_can_reload_even_with_live_polling():
    health = {'extension_polling': True, 'needs_extension_reload': True,
              'active_lease': False, 'pending_tasks': 0, 'posting_paused': False}
    assert eligible_for_restart(health, idle=901, last_restart=0, now=1800000)
    for changed in ({'active_lease': True}, {'pending_tasks': 1}, {'posting_paused': True}):
        assert not eligible_for_restart({**health, **changed}, idle=901, last_restart=0, now=1800000)
    assert not eligible_for_restart(health, idle=100, last_restart=0, now=1800000)
    assert not eligible_for_restart(health, idle=901, last_restart=1799999, now=1800000)

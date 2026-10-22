from scripts.facebook_recovery_pump import safe_to_run, MAX_STARTS_PER_DAY

HEALTH={
 "ok": True,"extension_version":"1.1.7","extension_polling":True,
 "active_lease":False,"pending_tasks":0,"posting_paused":False,
}

def test_only_loaded_latest_extension_can_post():
    assert safe_to_run(HEALTH, "1.1.7")== (True, "ready")
    assert safe_to_run(HEALTH, "1.1.8")== (False,"extension_version_not_loaded")

def test_fail_closed_when_paused_busy_or_offline():
    for key,val in (
        ("ok",False),("extension_polling",False),
        ("active_lease",True),("pending_tasks",1),("posting_paused",True),
    ):
        patched={**HEALTH,key:val}
        ok,_=safe_to_run(patched,"1.1.7")
        assert not ok

def test_operator_limits():
    assert MAX_STARTS_PER_DAY<=6

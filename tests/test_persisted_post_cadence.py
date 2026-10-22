from datetime import datetime,timezone,timedelta
from src.authenticated_post_transport import cadence_remaining


def test_restart_cannot_accelerate_after_an_uncertain_click():
    now=datetime(2026,10,22,2,10,tzinfo=timezone.utc)
    clicked=(now-timedelta(minutes=7)).isoformat()
    assert cadence_remaining(clicked,15,now=now)==480
    assert cadence_remaining((now-timedelta(minutes=16)).isoformat(),15,now=now)==0
    assert cadence_remaining(None,15,now=now)==0

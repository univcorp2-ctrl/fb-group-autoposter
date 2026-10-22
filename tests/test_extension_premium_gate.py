import asyncio
from types import SimpleNamespace
import pytest
from src import extension_poster


def test_unreviewed_copy_never_begins_submission(monkeypatch):
    changes = []
    poster = object.__new__(extension_poster.ExtensionFacebookPoster)
    poster.db = SimpleNamespace(update_target_status=lambda *a, **kw: changes.append((a, kw)))
    def forbidden(*_):
        raise AssertionError('An unapproved copy must never start a submission attempt')
    poster._begin_submission_if_bound = forbidden
    monkeypatch.setattr(extension_poster, 'review_post_copy', lambda *a: {'approved': False, 'reason': 'source changed'})
    asyncio.run(poster._post_target_via_extension({'job_id': 'test-job'}, {'group_id': 'test-group'}, {}))
    assert changes[0][0][-1] == 'failed'
    assert changes[0][1]['error'].startswith('premium_review_hold:')


def test_exact_approved_copy_can_reach_existing_approval_binding(monkeypatch):
    poster = object.__new__(extension_poster.ExtensionFacebookPoster)
    monkeypatch.setattr(extension_poster, 'review_post_copy', lambda *a: {'approved': True})
    class ReachedExistingBinding(Exception):
        pass
    def existing_binding(*_):
        raise ReachedExistingBinding()
    poster._begin_submission_if_bound = existing_binding
    with pytest.raises(ReachedExistingBinding):
        asyncio.run(poster._post_target_via_extension({'job_id': 'test-job'}, {'group_id': 'test-group'}, {}))

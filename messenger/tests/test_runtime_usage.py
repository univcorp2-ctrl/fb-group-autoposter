import json
from src.runtime_usage import UsageRun


def test_cache_is_subset_and_duplicate_completion_is_not_added(monkeypatch, tmp_path):
    monkeypatch.setenv('AI_TASK_USAGE_DIR', str(tmp_path))
    run = UsageRun('messenger-auto-reply', 'gpt-6-astra')
    pending = json.loads(run.path.read_text())
    assert pending['totalTokens'] is None
    event = json.dumps({'type': 'turn.completed', 'usage': {
        'input_tokens': 100, 'cached_input_tokens': 80, 'output_tokens': 20}})
    run.finish(event)
    run.finish(event)
    rows = list(tmp_path.glob('*.json'))
    assert len(rows) == 1
    row = json.loads(rows[0].read_text())
    assert row['totalTokens'] == 120
    assert row['cachedInputTokens'] == 80
    assert 'prompt' not in row


def test_missing_usage_stays_unknown(monkeypatch, tmp_path):
    monkeypatch.setenv('AI_TASK_USAGE_DIR', str(tmp_path))
    run = UsageRun('messenger-auto-reply', 'gpt-6-astra')
    run.finish('{"type":"error","message":"private error"}')
    row = json.loads(run.path.read_text())
    assert row['totalTokens'] is None
    assert row['status'] == 'unknown'
    assert 'private error' not in run.path.read_text()

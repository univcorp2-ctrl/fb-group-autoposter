import json
from pathlib import Path
from types import SimpleNamespace

from src import review_pipeline as reviews


def setup_reviewer(monkeypatch, tmp_path, login='Logged in using ChatGPT'):
    executable = tmp_path / 'codex.exe'
    executable.write_bytes(b'synthetic test executable')
    monkeypatch.setenv('MESSENGER_REVIEW_PROVIDER', 'codex_login')
    monkeypatch.setenv('MESSENGER_REVIEW_CODEX_EXE', str(executable))
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-be-used')
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs.get('shell', False) is False
        assert 'OPENAI_API_KEY' not in kwargs['env']
        if argv[1:3] == ['login', 'status']:
            return SimpleNamespace(returncode=0, stdout=login, stderr='')
        assert kwargs['input'] == 'synthetic evidence only'
        assert argv[argv.index('--model') + 1] == 'gpt-6-astra'
        assert argv[argv.index('--sandbox') + 1] == 'read-only'
        assert '--ignore-user-config' in argv
        assert 'shell_tool' in argv and 'multi_agent_v2' in argv
        result = Path(argv[argv.index('--output-last-message') + 1])
        result.write_text(json.dumps({'verdict': 'approve', 'reply': '検証用の返信です。',
                                     'reason': 'synthetic'}), encoding='utf-8')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(reviews.subprocess, 'run', run)
    return calls


def test_authorized_login_reviewer_uses_premium_model_without_api(monkeypatch, tmp_path):
    calls = setup_reviewer(monkeypatch, tmp_path)
    result = reviews._call_opus('synthetic evidence only', api_key='ignored-api-key')
    assert result is not None
    raw, model = result
    assert json.loads(raw)['verdict'] == 'approve'
    assert model == 'gpt-6-astra/high'
    assert len(calls) == 2


def test_api_authenticated_cli_is_rejected(monkeypatch, tmp_path):
    calls = setup_reviewer(monkeypatch, tmp_path, login='Logged in using an API key')
    assert reviews._call_opus('synthetic evidence only') is None
    assert len(calls) == 1


def test_sender_recognizes_authorized_premium_checker():
    from argparse import Namespace
    import hashlib
    from scripts.send_one_playwright_reply import _require_premium_approval
    row = {'name': '検証用', 'last_message': 'ご連絡ありがとうございます',
           'draft': 'ご連絡ありがとうございます。引き続きよろしくお願いいたします。',
           'review_status': 'approved', 'review_model': 'gpt-6-astra/high'}
    row['review_message_sha256'] = hashlib.sha256(
        (row['name'] + '\0' + row['last_message']).encode('utf-8')).hexdigest()
    _require_premium_approval(Namespace(send=True), row, row['draft'])

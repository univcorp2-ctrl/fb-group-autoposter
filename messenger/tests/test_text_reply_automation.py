import hashlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src import auto_reply


@pytest.mark.parametrize('incoming,followup,expected', [
    ('この物件はまだ販売中ですか？', False, 1),
    ('この物件の賃料を教えてください', True, 1),
    ('この物件の資料をください', False, 0),
    ('あなた: この物件は販売中です', False, 0),
])
def test_reviewed_text_without_pdf_and_new_followups(monkeypatch, tmp_path, incoming, followup, expected):
    for name, filename in [('LEDGER', 'ledger.json'), ('STATUS', 'status.json'),
                           ('DRIVE_STATUS', 'drive.json'), ('DRIVE_LEDGER', 'drive-ledger.json'),
                           ('BASELINE_INBOX', 'baseline.json'), ('SEND_PAUSE_FILE', 'pause.lock')]:
        monkeypatch.setattr(auto_reply, name, tmp_path / filename)
    monkeypatch.setenv('MESSENGER_AUTO_SEND', 'true')
    (tmp_path / 'baseline.json').write_text('{"previews":{}}')
    settings = SimpleNamespace(data_dir=tmp_path)
    auto_reply.run_pending(settings)
    if followup:
        ledger = json.loads(auto_reply.LEDGER.read_text())
        ledger['attempts']['previous-hash'] = {'thread_id': '123456789',
            'state': 'confirmed_sent', 'created_at': datetime.now(auto_reply.JST).isoformat()}
        auto_reply.safe_save(auto_reply.LEDGER, ledger)
    row = {'thread_id': '123456789', 'url': 'https://www.messenger.com/t/123456789',
           'name': '検証用', 'last_message': incoming, 'one_to_one_verified': True,
           'participant_count': 1, 'is_group': False, 'time_text': '1分前',
           'review_status': 'approved', 'review_model': 'gpt-6-astra/high',
           'review_message_sha256': hashlib.sha256(('検証用\0' + incoming).encode()).hexdigest(),
           'material': None, 'draft': 'お問い合わせありがとうございます。資料で確認できる範囲の情報をご案内いたします。'}
    (tmp_path / 'drafts.json').write_text(json.dumps({'drafts': [row]}, ensure_ascii=False), encoding='utf-8')
    stamp = (datetime.now(auto_reply.JST) + timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M JST')
    (tmp_path / 'drafts_archive.jsonl').write_text(json.dumps({'checked_at': stamp, **row}), encoding='utf-8')
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout='{"sent":true,"attachment_confirmed":true}', stderr='')

    monkeypatch.setattr(auto_reply.subprocess, 'run', run)
    result = auto_reply.run_pending(settings)
    assert result['confirmed'] == expected
    assert len(calls) == expected
    assert auto_reply.run_pending(settings)['attempted'] == 0

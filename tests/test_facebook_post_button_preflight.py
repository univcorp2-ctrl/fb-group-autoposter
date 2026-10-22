import json
from scripts import facebook_post_button_preflight as preflight


def test_cached_layout_pass_requires_same_version_and_source(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight,"STATUS",tmp_path/"layout.json")
    monkeypatch.setattr(preflight,"source_digest",lambda:"abc123")
    monkeypatch.setattr(preflight,"VALID_SECONDS",86400)
    data={"status":"passed","version":"1.1.7","group_id":"1281008662437696",
          "source_digest":"abc123","passed_at_epoch":100000}
    preflight.STATUS.write_text(json.dumps(data),encoding="utf-8")
    assert preflight.cached_passed("1.1.7","1281008662437696",now=100060)
    assert not preflight.cached_passed("1.1.6","1281008662437696",now=100060)
    assert not preflight.cached_passed("1.1.7","1281008662437696",now=200000)
    monkeypatch.setattr(preflight,"source_digest",lambda:"modified")
    assert not preflight.cached_passed("1.1.7","1281008662437696",now=100060)


def test_layout_gate_rejects_non_group_without_sending():
    result=preflight.ensure_layout_gate({"id":"foo","post_url":"https://example.com"},"1.1.7")
    assert result["status"]=="blocked"

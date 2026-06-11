import json

from src.ingest import ingest_manual, scan_inbox


def test_ingest_manual_normalizes():
    prop = ingest_manual({"title": "手入力", "price": "1億円"})
    assert prop["title"] == "手入力"
    assert prop["price"] == "1億円"
    assert prop["yield_pct"] == "記載なし"


def test_scan_inbox_reads_json(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.json").write_text(json.dumps({"title": "JSON物件"}, ensure_ascii=False), encoding="utf-8")
    props = scan_inbox(inbox)
    assert len(props) == 1
    assert props[0]["title"] == "JSON物件"

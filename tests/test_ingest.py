from pathlib import Path

from src.ingest import ingest_manual, scan_inbox


def test_ingest_manual_defaults_and_id_stable():
    prop = ingest_manual({"title": "A", "price": "1億円"})
    assert prop["title"] == "A"
    assert prop["price"] == "1億円"
    assert prop["yield_pct"] == "記載なし"
    assert prop["property_id"]


def test_scan_inbox_reads_json(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "p.json").write_text('{"title":"Json物件","price":"1000万円"}', encoding="utf-8")
    props = scan_inbox(inbox)
    assert len(props) == 1
    assert props[0]["title"] == "Json物件"

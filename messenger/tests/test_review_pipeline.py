import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import pytest

from src.property_evidence import lookup_property
from src import review_pipeline


def mock_evidence(tmp_path: Path):
    p=tmp_path/"properties.json"
    p.write_text(json.dumps({"items":[{
        "propertyId":"23586", "property.label":"リアライズ幕張ビル",
        "property.cityLabel":"千葉市美浜区", "property.price":"3250000000",
        "detail_url":"https://example.org/property/23586",
        "publicationScope":"USER"
    }]}, ensure_ascii=False),encoding="utf-8")
    return p


def test_32oku_makuhari_is_specific_not_hausu(tmp_path):
    result=lookup_property("幕張32億の収益ビルの資料をください",mock_evidence(tmp_path))
    assert result.matched and result.property_id=="23586"
    assert result.label=="リアライズ幕張ビル" and result.price_jpy==3250000000
    assert result.sharing_cleared is False and result.publication_scope=="USER"


def test_high_end_unavailable_rejects_generic_template(monkeypatch):
    monkeypatch.setattr(review_pipeline,"_call_opus",lambda *a,**kw:None)
    result=review_pipeline.review_draft("Hiroaki Kobayashi","幕張32億の収益ビルの資料をください",
        history="こちらで確認します。以前ご案内した幕張のビルの件です。具体的にどの資料をお渡しするか確認しています。")
    assert result["review_status"]=="needs_human"
    assert result["draft"]==""
    assert result["review_reason"]=="high_end_reviewer_unavailable"


def test_inadequate_history_rejected_without_api(monkeypatch):
    api=Mock(side_effect=AssertionError("premium call must be skipped"))
    monkeypatch.setattr(review_pipeline,"_call_opus",api)
    result=review_pipeline.review_draft("客","物件の資料をください",history="")
    assert result["review_reason"]=="conversation_history_unavailable"
    api.assert_not_called()


def test_reject_marketing_and_draft_disclaimer():
    ev=review_pipeline.lookup_property("幕張32億の収益ビルの資料をください")
    for bad in (
        "リアライズ幕張ビルの資料の件ですね。公式LINEへお問い合わせください。",
        "リアライズ幕張ビルの資料の件ですね。（※この返信は下書きです）",
        "リアライズ幕張ビルの資料の件ですね。ご希望のエリアや予算を教えてください。",
    ):
        assert review_pipeline._validate(bad,"幕張32億の収益ビルの資料をください",ev) is not None


def test_high_end_approve_draft_but_do_not_share_restricted_listing(monkeypatch):
    reply="リアライズ幕張ビルのご質問ですね。物件資料の内容と共有できる範囲を確認してから、ご案内いたします。"
    monkeypatch.setattr(review_pipeline,"_call_opus",
        lambda *a,**kw:(json.dumps({"verdict":"approve","reply":reply,"reason":"資料の共有条件を確認する必要あり"},ensure_ascii=False),"claude-opus-4-6"))
    result=review_pipeline.review_draft("Hiroaki Kobayashi","幕張32億の収益ビルの資料をください",
        history="以前幕張の収益ビルの話をしていました。資料をいただけますか。")
    assert result["review_status"]=="needs_human"
    assert result["review_reason"]=="document_sharing_requires_verification"
    assert result["draft"]==reply


def test_invalid_review_result_rejected(monkeypatch):
    monkeypatch.setattr(review_pipeline,"_call_opus",lambda *a,**kw:("not json","claude-opus-4-6"))
    result=review_pipeline.review_draft("客","幕張32億の収益ビルの資料をください",
        history="先日から幕張のビルについてやりとりしています。")
    assert result["review_status"]=="needs_human"
    assert not result["draft"]

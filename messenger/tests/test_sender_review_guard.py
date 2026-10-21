from argparse import Namespace
import hashlib
import pytest

from scripts.send_one_playwright_reply import _require_premium_approval

def args(send=True):
    return Namespace(send=send)

def row(**changes):
    base={
      "name":"山田さん",
      "last_message":"賃料を教えてください",
      "review_status":"approved",
      "review_model":"gpt-5.6-terra/high",
      "draft":"お問い合わせありがとうございます。確認できた物件情報を整理してご案内いたします。",
    }
    base["review_message_sha256"]=hashlib.sha256(
      (base["name"]+"\0"+base["last_message"]).encode("utf-8")
    ).hexdigest()
    base.update(changes)
    return base

def test_premium_review_allows_matching_message():
    r=row()
    _require_premium_approval(args(),r,r["draft"])

def test_fail_closed_legacy_and_unreviewed():
    for state in ({"review_status":None},{"review_status":"needs_human"},{"review_model":"cheap-template"},
                  {"review_message_sha256":"bad"}):
        with pytest.raises(RuntimeError):
            r=row(**state);_require_premium_approval(args(),r,r["draft"])

def test_bypass_reply_text_or_base64_forbidden():
    r=row()
    with pytest.raises(RuntimeError,match="reply_must_equal"):
        _require_premium_approval(args(),r,"これは外部で作った未承認の返信文です。送信してください。")

def test_block_human_unapproved_source_doc_even_with_fake_review():
    r=row(name="Hiroaki Kobayashi",last_message="幕張32億の収益ビルの資料をください",
          draft="リアライズ幕張ビルの資料を共有しますので、確認してください。")
    r["review_message_sha256"]=hashlib.sha256(
        (r["name"]+"\0"+r["last_message"]).encode("utf-8")
    ).hexdigest()
    with pytest.raises(RuntimeError,match="restricted_property_material_not_verified"):
        _require_premium_approval(args(),r,r["draft"])

def test_preflight_allowed_without_send():
    _require_premium_approval(args(send=False),{},"")

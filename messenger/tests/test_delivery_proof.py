from src.delivery_proof import inspect_outgoing_text

REPLY="お問い合わせありがとうございます。こちらの物件資料をお送りします。"
PDF="概要書.pdf"

def test_sent_text_and_pdf_accessibility_proof():
    text=("10:22\n送信済み\n"+REPLY+
          "\n10:22にあなたが送信したメッセージ: "+REPLY+"を入力\n"+
          PDF+"\n1.45 MB\n10:22にあなたが送信したメッセージを入力")
    result=inspect_outgoing_text(text,REPLY,PDF)
    assert result["confirmed"] and result["text_confirmed"] and result["pdf_confirmed"]

def test_composer_text_or_unattached_file_is_not_proof():
    assert not inspect_outgoing_text("作成\nAa\n"+REPLY+"\n"+PDF,REPLY,PDF)["confirmed"]
    assert not inspect_outgoing_text("10:22にあなたが送信したメッセージ: "+REPLY+"を入力",REPLY,PDF)["confirmed"]

def test_pdf_from_prior_message_does_not_count():
    text=PDF+"\n10:11にあなたが送信したメッセージを入力\n10:22にあなたが送信したメッセージ: "+REPLY+"を入力"
    assert not inspect_outgoing_text(text,REPLY,PDF)["confirmed"]

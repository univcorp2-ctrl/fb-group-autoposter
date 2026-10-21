"""Read-only independent proof of Messenger outbound text and PDF.

Do not count a filled editor as a sent message: Messenger accessibility
labels contain explicit 'あなたが送信したメッセージ' on confirmed outbound rows.
"""
from __future__ import annotations
import re
from typing import Any

def inspect_outgoing_text(text: str, reply: str, pdf_name: str) -> dict[str, Any]:
    if not text or not reply or not pdf_name:
        return {"confirmed":False,"text_confirmed":False,"pdf_confirmed":False}
    label="にあなたが送信したメッセージ: "
    exact=label+reply+"を入力"
    pos=text.find(exact)
    text_confirmed=pos>=0
    pdfpos=text.find(pdf_name,pos+len(exact)) if text_confirmed else -1
    # Separate accessibility label for a file bubble sent by own account.
    suffix=text[pdfpos+len(pdf_name):pdfpos+len(pdf_name)+240] if pdfpos>=0 else ""
    pdf_confirmed=pdfpos>=0 and bool(re.search(r"にあなたが送信したメッセージを入力",suffix))
    return {"confirmed":bool(text_confirmed and pdf_confirmed),
            "text_confirmed":bool(text_confirmed),
            "pdf_confirmed":bool(pdf_confirmed),
            "pdf_file_name":pdf_name if pdf_confirmed else ""}

async def verify_outgoing_thread(page: Any, thread_id: str, reply: str, pdf_name: str) -> dict[str,Any]:
    from playwright.async_api import Error as PlaywrightError
    if f"/t/{thread_id}" not in str(page.url):
        return {"confirmed":False,"reason":"wrong_thread"}
    try:
        main=page.locator('main').first
        if not await main.count():
            main=page.locator('[role="main"]').first
        if not await main.count():
            return {"confirmed":False,"reason":"main_not_found"}
        content=await main.inner_text(timeout=12000)
    except (PlaywrightError,Exception) as error:
        return {"confirmed":False,"reason":type(error).__name__}
    return {**inspect_outgoing_text(content,reply,pdf_name),"reason":"ui_outbound_verified" if inspect_outgoing_text(content,reply,pdf_name)["confirmed"] else "no_exact_outbound_proof"}

"""Stage an approved PDF in a Messenger composer.

No action in this module clicks Send. Browser DOM upload is only invoked
after exact recipient/inbound matching and premium review are complete.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

FILE_SELECTOR = 'input[type="file"][accept="*/*"]'

async def attachment_input_ready(page: Any) -> bool:
    loc=page.locator(FILE_SELECTOR)
    return (await loc.count())==1


async def stage_verified_pdf(page: Any, local_pdf: Path, display_name: str) -> dict:
    if local_pdf.suffix.lower() != ".pdf" or not local_pdf.is_file():
        raise RuntimeError("verified_pdf_missing")
    if local_pdf.name != display_name:
        raise RuntimeError("approved_filename_mismatch")
    if not await attachment_input_ready(page):
        raise RuntimeError("messenger_attachment_input_missing_or_ambiguous")
    body_before = (await page.locator("body").inner_text()).count(display_name)
    upload=page.locator(FILE_SELECTOR)
    await upload.set_input_files(str(local_pdf),timeout=30_000)
    staged=False
    for i in range(24):
        await page.wait_for_timeout(500)
        body=await page.locator("body").inner_text()
        if body.count(display_name)>body_before:
            staged=True
            break
    if not staged:
        # May mean Messenger auto-sent the document at upload time. Do NOT
        # click send or retry; mark outcome uncertain for a human check.
        raise RuntimeError("attachment_stage_not_observable_stop_no_resend")
    return {"staged":True,"file_name":display_name}


async def attachment_visible_after_send(page: Any, display_name: str) -> bool:
    try:
        body=await page.locator("body").inner_text(timeout=10000)
        return display_name in body
    except Exception:
        return False

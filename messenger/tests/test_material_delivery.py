import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.material_delivery import plan_material,download_material
from src.messenger_attachment import attachment_input_ready,stage_verified_pdf

def record(tmp_path, *, broker="True", permit=True, pdf_id="1N5nTOn1Q3JqYYE2enc2CC4X0_PeuEPDF"):
    source=tmp_path/"source.json"
    reg=tmp_path/"registry.json"
    source.write_text(json.dumps({"items":[{
        "propertyId":"23586","property.label":"リアライズ幕張ビル",
        "property.cityLabel":"千葉市","property.price":"3250000000",
        "property.allowBrokerSharing":broker,
        "property.disclosureStatus":"ABLE_TO_SHOW",
        "publicationStatus":"PUBLISHED","publicationScope":"USER",
        "updatedAt":"2026-10-19T11:00:00Z",
        "property.propertyAttachments":json.dumps([{"path":"production/property/attachment/123-資料.pdf"}])
    }]},ensure_ascii=False),encoding="utf8")
    reg.write_text(json.dumps({"materials":[{
        "property_id":"23586","file_name":"資料.pdf",
        "source_attachment_name":"資料.pdf",
        "drive_file_id":pdf_id,"mime_type":"application/pdf",
        "google_drive_permission":"anyone_reader",
        "broker_sharing_verified":True,
        "manual_document_sharing_approval":permit,
    }]},ensure_ascii=False),encoding="utf8")
    return source,reg

def test_approved_pdf_is_exact_property_only(tmp_path):
    source,reg=record(tmp_path)
    p=plan_material("幕張32億の収益ビル資料をください",source,reg)
    assert p.approved and p.property_id=="23586"
    assert not plan_material("東京の物件資料をください",source,reg).approved

def test_permission_gate_rejects_unapproved_and_broker_no(tmp_path):
    source,reg=record(tmp_path,permit=False)
    assert not plan_material("幕張32億資料ください",source,reg).approved
    source,reg=record(tmp_path,broker="False")
    assert not plan_material("幕張32億資料ください",source,reg).approved

def test_non_pdf_rejected(tmp_path):
    source,reg=record(tmp_path)
    x=json.loads(reg.read_text(encoding="utf8"))
    x["materials"][0]["mime_type"]="text/plain"
    reg.write_text(json.dumps(x),encoding="utf8")
    assert not plan_material("幕張32億資料をください",source,reg).approved

def test_download_checks_pdf_signature_and_hash(tmp_path,monkeypatch):
    source,reg=record(tmp_path)
    plan=plan_material("幕張32億資料ください",source,reg)
    data=b"%PDF-1.7\n"+b"a"*1900+b"\n%%EOF"
    class FakeResponse:
        url="https://drive.usercontent.google.com/download/..."
        def raise_for_status(self): return None
        def iter_content(self,n): yield data
    monkeypatch.setattr("src.material_delivery.requests.get",lambda *a,**kw:FakeResponse())
    result=download_material(plan,tmp_path/"drive-private")
    assert result.sha256==hashlib.sha256(data).hexdigest()
    assert Path(result.file_path).read_bytes()==data
    assert Path(result.file_path).name=="資料.pdf"

def test_html_error_rejected_without_saving(tmp_path,monkeypatch):
    source,reg=record(tmp_path)
    class FakeResponse:
        url="https://drive.google.com/uc..."
        def raise_for_status(self):return None
        def iter_content(self,n):yield b"<html>login</html>"
    monkeypatch.setattr("src.material_delivery.requests.get",lambda *a,**kw:FakeResponse())
    with pytest.raises(RuntimeError,match="not_a_pdf"):
        download_material(plan_material("幕張32億資料ください",source,reg),tmp_path/"private")


class FakeFileInput:
    async def count(self):return 1
    async def set_input_files(self,path,timeout=None):self.path=path

class FakeBody:
    def __init__(self,host):self.host=host
    async def inner_text(self):return self.host.name if self.host.current else ""

class FakePage:
    def __init__(self,name):self.name=name;self.current=False;self.upload=FakeFileInput()
    def locator(self,selector):
        return FakeBody(self) if selector=="body" else self.upload
    async def wait_for_timeout(self,ms):self.current=True

def test_stages_pdf_in_exact_composer_without_click(tmp_path):
    file=tmp_path/"資料.pdf";file.write_bytes(b"%PDF-")
    page=FakePage(file.name)
    result=asyncio.run(stage_verified_pdf(page,file,file.name))
    assert result["staged"] is True and page.upload.path==str(file)

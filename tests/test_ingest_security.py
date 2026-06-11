import pytest

from src.ingest import _validate_url, ingest_manual


def test_validate_url_rejects_file_scheme():
    with pytest.raises(ValueError, match="scheme not allowed"):
        _validate_url("file:///etc/passwd")


def test_validate_url_rejects_ftp_scheme():
    with pytest.raises(ValueError, match="scheme not allowed"):
        _validate_url("ftp://evil.com/payload")


def test_validate_url_rejects_localhost():
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://localhost/admin")


def test_validate_url_rejects_127():
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://127.0.0.1:8080/secret")


def test_validate_url_rejects_metadata_ip():
    with pytest.raises(ValueError, match="blocked address"):
        _validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_allows_https():
    _validate_url("https://example.com/property/123")


def test_validate_url_allows_http():
    _validate_url("http://example.com/property/123")


def test_ingest_manual_generates_id_for_empty_property_id():
    prop = ingest_manual({"property_id": "", "title": "A"})
    assert prop["property_id"]

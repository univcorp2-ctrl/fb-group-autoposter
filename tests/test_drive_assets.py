from pathlib import Path

from src.drive_assets import attach_drive_images, normalize_name, resolve_property_images


def test_normalize_name_handles_width_and_symbols() -> None:
    assert normalize_name("ＡＢＣ-１２３ 物件") == "abc123物件"


def test_resolve_images_by_property_id(tmp_path: Path) -> None:
    folder = tmp_path / "物件 12345 サンプル"
    images = folder / "images"
    images.mkdir(parents=True)
    image = images / "front.jpg"
    image.write_bytes(b"jpg")
    item = {"propertyId": "12345", "property.label": "別名"}
    assert resolve_property_images(item, tmp_path) == [str(image.resolve())]


def test_attach_images_maps_estateboard_id(tmp_path: Path) -> None:
    folder = tmp_path / "777 テスト物件"
    folder.mkdir()
    image = folder / "01.png"
    image.write_bytes(b"png")
    props = [{"property_id": "eb-777", "images": []}]
    source = [{"propertyId": "777", "property.label": "テスト物件"}]
    result = attach_drive_images(props, source, tmp_path)
    assert result[0]["images"] == [str(image.resolve())]

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.drive_assets import resolve_property_images


def check(name: str, ok: bool, detail: str) -> dict[str, object]:
    print(f"{'OK' if ok else 'NG'}  {name}: {detail}")
    return {"name": name, "ok": ok, "detail": detail}


def main() -> int:
    settings = Settings.load()
    drive_root = Path(
        os.getenv(
            "ESTATEBOARD_DRIVE_ROOT",
            r"G:\マイドライブ\0.物件資料_お客様紹介用\Estateboard",
        )
    )
    rows: list[dict[str, object]] = []
    rows.append(check("python", sys.version_info >= (3, 11), sys.version.split()[0]))
    rows.append(check("estateboard_source", settings.estateboard_source.exists(), str(settings.estateboard_source)))
    rows.append(check("drive_archive", drive_root.exists(), str(drive_root)))
    rows.append(check("profile_parent_writable", settings.profile_dir.parent.exists(), str(settings.profile_dir)))
    rows.append(check("database_parent_writable", settings.db_path.parent.exists(), str(settings.db_path)))

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            executable = Path(p.chromium.executable_path)
            rows.append(check("playwright_chromium", executable.exists(), str(executable)))
    except Exception as exc:
        rows.append(check("playwright_chromium", False, f"{type(exc).__name__}: {exc}"))

    sample_count = 0
    if drive_root.exists():
        for folder in drive_root.iterdir():
            if not folder.is_dir() or folder.name.startswith("_"):
                continue
            images = list((folder / "images").glob("*")) if (folder / "images").exists() else []
            if images:
                sample_count = len(images)
                break
    rows.append(check("drive_image_sample", sample_count > 0, f"sample images={sample_count}"))

    result = {"ok": all(bool(row["ok"]) for row in rows), "checks": rows}
    output = Path(os.getenv("LOCALAPPDATA", str(ROOT))) / "FBGroupAutoposter" / "preflight.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {output}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

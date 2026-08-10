from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups


def check(name: str, ok: bool, detail: str, *, required: bool = True) -> dict[str, object]:
    label = "OK" if ok else ("WARN" if not required else "NG")
    print(f"{label} {name}: {detail}")
    return {"name": name, "ok": ok or not required, "detail": detail, "required": required}


def main() -> int:
    settings = Settings.load()
    drive_root = Path(
        os.getenv("ESTATEBOARD_DRIVE_ROOT", r"G:\マイドライブ\0.物件資料_お客様紹介用\Estateboard")
    )
    rows: list[dict[str, object]] = []
    rows.append(check("python", sys.version_info >= (3, 11), sys.version.split()[0]))
    rows.append(check("estateboard_source", settings.estateboard_source.exists(), str(settings.estateboard_source)))
    rows.append(check("drive_archive", drive_root.exists(), str(drive_root)))
    rows.append(check("profile_outside_drive", "マイドライブ" not in str(settings.profile_dir), str(settings.profile_dir)))
    rows.append(check("database_outside_drive", "マイドライブ" not in str(settings.db_path), str(settings.db_path)))
    rows.append(check("groups", bool(load_groups()), f"enabled={len(load_groups())}"))
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
        rows.append(check("playwright_chromium", executable.exists(), str(executable)))
    except Exception as exc:
        rows.append(check("playwright_chromium", False, f"{type(exc).__name__}: {exc}"))
    codex_requested = os.getenv("POST_TEXT_PROVIDER", "").casefold() == "codex"
    rows.append(
        check(
            "codex_cli",
            shutil.which(os.getenv("CODEX_CLI", "codex")) is not None,
            shutil.which(os.getenv("CODEX_CLI", "codex")) or "not installed; template/Claude remains usable",
            required=codex_requested,
        )
    )
    image_count = 0
    if drive_root.exists():
        try:
            for folder in drive_root.iterdir():
                image_dir = folder / "images"
                if folder.is_dir() and image_dir.exists():
                    image_count = len([p for p in image_dir.iterdir() if p.is_file()])
                    if image_count:
                        break
        except OSError:
            pass
    rows.append(check("drive_image_sample", image_count > 0, f"sample images={image_count}"))
    result = {"ok": all(bool(row["ok"]) for row in rows), "checks": rows}
    output = Path(os.getenv("LOCALAPPDATA", str(ROOT))) / "FBGroupAutoposter" / "preflight.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {output}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

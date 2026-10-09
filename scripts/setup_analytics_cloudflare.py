"""Initialize EstateBoard Facebook analytics secrets without writing values to Git.

Run once on the authorized Windows posting PC. Re-runs reuse the existing
private Drive backup, preventing accidental credential rotation.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

AUTOP_ROOT = Path(__file__).resolve().parents[1]
ESTATEBOARD_ROOT = Path(r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard")
PRIVATE_BACKUP = Path(r"G:\マイドライブ\AI_Agents\Private\estateboard_analytics_tokens.json")
ENV_PATH = AUTOP_ROOT / ".env"
SECRETS = ("ANALYTICS_INGEST_TOKEN", "ANALYTICS_DASHBOARD_TOKEN")


def update_env(pairs: dict[str, str]) -> None:
    original = ENV_PATH.read_text(encoding="utf-8-sig") if ENV_PATH.exists() else ""
    lines = original.splitlines()
    for name, value in pairs.items():
        hits = [i for i, row in enumerate(lines) if row.lstrip().startswith(name + "=")]
        if hits:
            lines[hits[0]] = f"{name}={value}"
            for duplicate in reversed(hits[1:]):
                del lines[duplicate]
        else:
            lines.append(f"{name}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not ESTATEBOARD_ROOT.is_dir():
        raise RuntimeError("existing EstateBoard Drive repository not found")
    if PRIVATE_BACKUP.exists():
        existing = json.loads(PRIVATE_BACKUP.read_text(encoding="utf-8"))
        data = {name: str(existing.get(name, "")) for name in SECRETS}
        if any(len(value) < 40 for value in data.values()):
            raise RuntimeError("incomplete private token backup; refusing to rotate silently")
    else:
        data = {name: secrets.token_urlsafe(48) for name in SECRETS}
        PRIVATE_BACKUP.parent.mkdir(parents=True, exist_ok=True)
        PRIVATE_BACKUP.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    update_env({
        "ANALYTICS_SYNC_ENABLED": "true",
        "ANALYTICS_BASE_URL": "https://estateboard.pages.dev",
        "ANALYTICS_INGEST_TOKEN": data["ANALYTICS_INGEST_TOKEN"],
    })
    filename = None
    try:
        with tempfile.NamedTemporaryFile("w", prefix="estateboard-analytics-", suffix=".json",
                                         encoding="utf-8", delete=False) as tmp:
            filename = tmp.name
            json.dump(data, tmp)
        cp = subprocess.run(
            ["npx.cmd", "--no-install", "wrangler", "pages", "secret", "bulk",
             filename, "--project-name=estateboard"],
            cwd=ESTATEBOARD_ROOT, text=True, capture_output=True, timeout=180, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        print("CLOUDFLARE_SECRET_STATUS", "OK" if cp.returncode == 0 else "FAILED")
        print("CLOUDFLARE_SECRET_NAMES", ",".join(data))
        print("CLOUDFLARE_EXIT_CODE", cp.returncode)
        print("CLOUDFLARE_RESPONSE", (cp.stdout + cp.stderr)[-1600:])
        print("LOCAL_ANALYTICS_ENABLED", True)
        print("PRIVATE_DRIVE_BACKUP_CREATED_OR_REUSED", PRIVATE_BACKUP.exists())
        return 0 if cp.returncode == 0 else 2
    finally:
        if filename:
            Path(filename).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())

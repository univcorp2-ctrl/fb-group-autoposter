# Codex operating notes

- Production entrypoint: `scripts/run_daily_drive.py`
- Repair command: `scripts/repair_windows_runtime.ps1`
- Never store Facebook profiles, SQLite databases, screenshots, `.env`, API keys, or browser cookies in Git.
- Keep EstateBoard/Drive input read-only.
- Preserve duplicate guards and `uncertain` semantics; uncertain may already be published.
- Run `ruff check .`, `pytest -q --no-cov`, and `python -m compileall -q src scripts tests` before pushing.
- Codex CLI is an optional text provider only. Browser posting remains Playwright in an interactive Windows session.

# CODEX

## Mission

Build and maintain the Facebook group property distribution pipeline exactly as specified by the construction brief.

## Guardrails

- Never commit `.env`, Facebook passwords, API keys, Telegram tokens, cookies, profiles, logs, screenshots, or SQLite runtime DBs.
- Keep `DRY_RUN=true` and `AUTO_APPROVE=false` as safe defaults.
- Do not add automatic tests that publish to Facebook.
- Preserve idempotency around `job_targets` and never repost uncertain targets automatically.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
ruff check .
```

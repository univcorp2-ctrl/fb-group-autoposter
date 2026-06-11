# Setup Guide

## 初回セットアップ

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```

`.env` に `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` を入れる。Facebookパスワードは保存しない。

`groups.yaml` のダミーIDを実グループへ差し替える。

```powershell
python scripts/login_once.py
python scripts/run_pipeline.py --selftest
```

`--selftest` は `DRY_RUN=true` のまま、サンプル物件で文面生成、キュー登録、承認、投稿モック、レポートまで通す。

## Windowsタスク登録

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
```

登録されるタスク:

- `FBGroupAutoposter-Pipeline`: 1時間ごと
- `FBGroupAutoposter-ApprovalPoll`: 5分ごと
- `FBGroupAutoposter-Healthcheck`: 30分ごと

## 本番移行

1. `DRY_RUN=true`, `AUTO_APPROVE=false` でTelegram承認フローを確認。
2. 問題なければ `DRY_RUN=false` に変更。
3. 安定後に `AUTO_APPROVE=true` へ変更。
4. `degraded` ジョブは `AUTO_APPROVE_SKIP_DEGRADED=true` なら自動承認されず、人間確認になる。

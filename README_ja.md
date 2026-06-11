# fb-group-autoposter

Facebook非公開グループ向けの不動産物件自動配信パイプライン。

## 概要

物件データ（PDF/JSON/URL）を取り込み、Claude APIでグループ別の投稿文面を生成し、Telegram承認ゲートを経てPlaywrightで自動投稿します。

### 主要機能

- **物件取込**: PDF（PyMuPDF）、JSON、URL、手動dict入力に対応
- **文面生成**: Claude APIでグループのトーン・規約に合わせた文面を自動生成（API不可時はフォールバック）
- **承認ゲート**: Telegramボットで投稿プレビュー・承認・却下・修正指示
- **自動投稿**: Playwright persistent contextによるFacebook投稿
- **安全機能**: dry_runモード、投稿頻度制限、セッション切れ検知、グループ別サーキットブレーカー
- **Vision修復**: セレクタ失敗時にClaude Visionで要素を特定するフォールバック

### フェイルセーフ設計

- `DRY_RUN=true`（デフォルト）: 実投稿しない
- `AUTO_APPROVE=false`（デフォルト）: Telegram承認必須
- Facebookパスワードは保存しない
- `.env`、`profiles/`、`logs/`、`screenshots/`、`jobs.db` はgit管理対象外

## セットアップ

### 1. 依存関係インストール

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

### 2. 環境変数設定

```bash
cp .env.example .env
```

`.env` に以下の実値を設定:

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | Yes | Claude API キー |
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram Bot トークン |
| `TELEGRAM_CHAT_ID` | Yes | 通知先 Telegram チャットID |
| `DRY_RUN` | No | `true`（デフォルト）= 実投稿しない |
| `AUTO_APPROVE` | No | `false`（デフォルト）= 手動承認 |

全環境変数一覧は `.env.example` を参照。

### 3. グループ設定

`groups.yaml` のダミーIDを実際のグループ情報に差し替えます:

```yaml
groups:
  - id: "実際のグループID"
    name: "グループ名"
    post_url: "https://www.facebook.com/groups/実際のグループID/"
    enabled: true
    tone: "丁寧・硬め"
    max_chars: 1500
    active_hours: [9, 22]
    allow_links: true
    allow_images: true
    signature: "\n---\nお問い合わせはDMにて"
    forbidden: ["絶対", "必ず儲かる", "保証"]
```

### 4. Facebook ログイン（初回のみ）

```bash
python scripts/login_once.py
```

ブラウザが開くので手動でログインし、2FA/checkpointも手動で完了してください。プロファイルは `profiles/main` に保存され、以後の投稿で再利用されます。

### 5. 動作確認

```bash
python scripts/run_pipeline.py --selftest
```

`DRY_RUN=true` の状態でパイプライン全体が正常に動くことを確認します。

## 実行方法

### パイプライン実行

```bash
python scripts/run_pipeline.py
```

### Telegram承認ポーリング

```bash
python scripts/approval_listener.py
```

### ヘルスチェック

```bash
python scripts/healthcheck.py
```

### Windows タスクスケジューラ登録

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
```

登録されるタスク:
- **Pipeline**: 1時間ごとにキュー処理
- **ApprovalPoll**: 5分ごとにTelegram callback取得
- **Healthcheck**: 30分ごとにheartbeat確認

## テスト

```bash
# 通常テスト
pytest

# カバレッジ付き
pytest --cov=src --cov=config --cov-report=term-missing

# リントチェック
ruff check src/ config.py tests/

# 10回連続検証
python scripts/run_tests_10.py

# 50回連続深掘り検証
python scripts/run_tests_50.py
```

## 本番移行手順

1. `.env` に秘密情報を設定
2. `groups.yaml` に実グループ情報を設定
3. `python scripts/login_once.py` でFacebookにログイン
4. `DRY_RUN=true` で `python scripts/run_pipeline.py --selftest` を実行
5. Telegram承認フローを確認
6. 問題なければ `DRY_RUN=false` に変更して本投稿開始
7. 安定稼働後に `AUTO_APPROVE=true` で完全無人化

## セキュリティ

### 秘密情報の管理

以下は絶対にGitHubにコミットしないでください:

- `.env` ファイル（APIキー、トークン含む）
- `profiles/` ディレクトリ（Facebookセッション）
- `data/jobs.db`（投稿履歴）

`.gitignore` で `.env`, `.env.*`, `*.pem`, `*.key`, `*.p12` を除外済みです。

### GitHub Actions / CI での秘密情報

GitHub Secrets に以下を設定:
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

CIではテストのみ実行し、実投稿は行いません。

### 実装済みセキュリティ対策

- **Telegram認証**: コールバックは設定済み `TELEGRAM_CHAT_ID` からのみ受付
- **SSRF防止**: `ingest_url()` でスキーム・ホスト検証（localhost, メタデータIP等をブロック）
- **SQLインジェクション防止**: 全クエリでパラメータ化
- **Telegram Token保護**: HTTP例外からトークンを除去してログ記録
- **エラーサニタイズ**: DB保存・Telegram通知時に内部パスを含まないよう制限

## アーキテクチャ

```
PDF / URL / JSON → ingest.py → generator.py (Claude API)
    → SQLite jobs.db → Telegram承認ゲート
    → orchestrator.py → poster.py (Playwright)
    → verifier.py (スクショ検証) → Telegram報告
```

詳細は [`docs/architecture.md`](docs/architecture.md) を参照。

## 注意事項

- Facebookの自動操作は利用規約に抵触するリスクがあります
- 投稿頻度を抑え、各グループの規約を遵守してください
- 投稿専用アカウントの分離を推奨します
- 本システムのデフォルト設定はフェイルセーフです

## ライセンス

Private repository - univ合同会社

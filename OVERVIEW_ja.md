# プロジェクト全体像 — Facebook 不動産オートメーション

このリポジトリは **1つのプロジェクト**として、3つの役割を**疎結合**で束ねています。
各役割は**それぞれ独立**（own `src` / `config` / `.env` / プロファイル）しており、
互いに強い依存（import 依存）を持ちません。プロジェクト全体としては「一つのスクリプトの束」
として管理します。

```
fb-group-autoposter/                ← 親プロジェクト（1つのフォルダで完結）
├── src/ scripts/ groups.yaml ...    ← 役割1: Facebook 自動投稿（既存・安定運用）
├── messenger/                       ← 役割2: Messenger 返信下書き
└── collector/                       ← 役割3: グループ物件コレクター
```

## 3つの役割

### 役割1: Facebook 自動投稿（ルート直下）
EstateBoard の物件を、自動的かつ安定的に Facebook グループへ投稿する。
- 投稿前に物件の鮮度を再確認（削除済みは投稿しない）／投稿後に permalink で実投稿を検証
- 失敗は Telegram 通知＋自動リカバリ。1グループ1日1回（JST暦日）
- 実行: `python scripts/run_daily.py`

### 役割2: Messenger 返信下書き（`messenger/`）
投稿を見て届く Messenger メッセージに、適切な返信の**下書き**を用意する。
- **(a) 他グループには絶対に投稿しない** — このフォルダに投稿機能は存在しない（読むだけ＋下書きのみ）
- **(b) 1対1のメッセージのみ**に下書きを作成（グループ会話・システム通知は除外）
- 送信は必ず人間。下書きは Notion + Telegram（任意で FB 入力欄）に保存
- 実行: `python messenger/scripts/run_once.py`

### 役割3: グループ物件コレクター（`collector/`）
所属する Facebook グループの投稿から**物件情報を収集**し、新しい**物件DB**を構築する。
- READ-ONLY（投稿・いいね・コメントなし）。フィードを読むだけ
- 投稿テキストから価格/利回り/所在地/種別/駅/築年/面積を抽出 → SQLite + JSON に保存
- 実行: `python collector/scripts/collect.py`

## 疎結合の原則（重要）

- 各役割は**自分のフォルダ内で完結**。`messenger/` と `collector/` は
  ルートの役割1コード（`src/`）を import しません。逆も同様。
- 各役割は**別プロファイル**で Facebook セッションを持ち、互いを壊しません
  （役割1=`profiles/main`、役割2=`messenger/profiles/messenger`、役割3=`collector/profiles/collector`）。
- 設定（`.env`）・データ（`data/`）・ログも役割ごとに分離。共通の Telegram BOT は
  同じトークンを各 `.env` に置くだけ（コード共有なし＝低依存）。
- Python 仮想環境はリポジトリ直下の `.venv` を共用（依存パッケージは共通）。
  → 「一つのスクリプトの束」として動かしつつ、役割同士は独立。

## テスト

各役割は自分の `tests/` を持ちます。

```bash
.venv/Scripts/python -m pytest                    # 役割1（ルート）
cd messenger && ../.venv/Scripts/python -m pytest # 役割2
cd collector && ../.venv/Scripts/python -m pytest # 役割3
```

## セキュリティ方針（全役割共通）
- アカウント停止(BAN)回避が最優先。役割2/3は**読むだけ・送信や投稿をしない**。
- ブランド名マスキング・物件鮮度チェックなど、各役割の README を参照。

# 役割3: グループ物件コレクター (collector)

所属している Facebook グループの投稿から**物件情報を収集**し、新しい**物件データベース**を構築する役割。

> 親プロジェクト `fb-group-autoposter` 内の**独立した1役割**。投稿(役割1)・Messenger(役割2)
> とは**別プロファイル・別.env**で、相互に依存しません。

## 安全方針
- **READ-ONLY**：投稿・いいね・コメントを一切しません。グループフィードを**読むだけ**。
- 別プロファイル `profiles/collector` で役割1/2に非干渉。固定UA・人間らしい間隔。

## 構成

| ファイル | 役割 |
|---|---|
| `config.py` | 設定（別プロファイル・収集対象・DB出力先） |
| `src/property_extractor.py` | 投稿テキスト→物件項目を抽出する**純粋関数**（価格/利回り/所在地/種別/駅/築年/面積）。テスト済 |
| `src/scraper.py` | グループフィードの**読み取り専用**取得（仮想化対応スクロール蓄積） |
| `src/store.py` | 収集物件を SQLite + JSON に保存（投稿テキストの署名で冪等） |
| `src/session.py` | ログイン状態判定（c_user Cookie） |
| `src/notifier.py` | Telegram通知（収集サマリー） |
| `scripts/login.py` | 収集用プロファイルへの一度きりログイン |
| `scripts/collect.py` | 収集オーケストレータ |

## 使い方

```bash
# 1) 収集対象グループを設定
cp collector/sources.yaml.example collector/sources.yaml   # 所属グループのURLを記入
cp collector/.env.example collector/.env                   # Telegram等は任意

# 2) 一度だけログイン（収集用プロファイル）
python collector/scripts/login.py

# 3) 収集実行（読むだけ → 物件DBへ）
python collector/scripts/collect.py
```

出力：`collector/data/collected.db`（SQLite）＋ `collector/data/collected.json`。

## テスト

```bash
cd collector && ../.venv/Scripts/python -m pytest -q && ../.venv/Scripts/python -m ruff check .
```

## 状態

抽出ロジック（`property_extractor`）と保存（`store`）は実装・テスト済み。フィード取得
（`scraper`）は FB の DOM 変動に合わせて実データでの微調整が必要な段階です（実運用前に
`collect.py` を対象グループで試走し、抽出件数を確認してください）。

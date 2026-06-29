# fb-messenger-assistant

Facebook **Messenger の1対1メッセージ**を読み取り、**返信が必要なものだけ**を判定して、
**返信下書き**を Notion と Telegram に保存するアシスタント。

> 🤝 これは自動投稿リポジトリ `fb-group-autoposter` とは**完全に独立**しています。
> 別プロファイル・別 `.env`・別スケジュールで動き、**自動投稿には一切干渉しません**。

---

## 🛡️ アカウント停止(BAN)回避の設計

最優先は「**絶対にアカウントを止めないこと**」。そのため：

| 方針 | 内容 |
|---|---|
| **送信しない** | 下書きを作るだけ。**実際の送信は必ず人間**が行う。コードに送信パスは存在しない。 |
| **デフォルト読むだけ** | `READ_ONLY=true`。FBへの書き込みゼロ＝最も安全。 |
| **別プロファイル** | `profiles/messenger`。自動投稿の `profiles/main` とは別。同時起動でも互いに壊さない。 |
| **控えめな頻度** | 1回あたりのスキャン上限・人間らしい間隔/マウス操作。1日数回の実行を想定。 |
| **固定UA** | 自動投稿と同じ固定User-Agent（変えると本人確認を誘発しやすい）。 |

### 2段階の下書き保存

- **Tier A（デフォルト・最も安全）** — FBは読むだけ。下書きは **Notion＋Telegram** に保存。
  Telegram通知からコピペ、または Notion DB で管理して人間が送信。
- **Tier B（オプトイン・初期OFF）** — `WRITE_DRAFT_TO_FB=true` で、下書きを **FBの入力欄に配置**（送信はしない）。
  Messenger は未送信の入力内容をスレッドごとに下書き保持するので、人間は「確認して送信」だけ。

---

## セットアップ

```bash
cd fb-messenger-assistant
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
playwright install chromium

cp .env.example .env   # 値を設定（Telegram / Notion / LINE URL 等）
```

### 1) 一度だけ手動ログイン

```bash
python scripts/login.py
```

ブラウザが開くので Facebook/Messenger にログイン（2FA・本人確認も対応）。
受信箱が出たらターミナルで Enter。セッションが `profiles/messenger` に保存されます。

### 2) スキャン実行（読み取り→下書き保存）

```bash
python scripts/run_once.py
```

- 1対1で相手が最後に送ったスレッドだけを「要返信」として抽出
- 各スレッドの返信下書きを生成し、Notion＋Telegram に保存
- `--no-telegram` で Telegram 通知を抑止

---

## 仕組み（パイプライン）

```
受信箱を開く（専用プロファイル）
  └─ 未ログインなら Telegram 通知して終了（無理なリトライはしない）
スレッド一覧を取得 → 要返信を判定（src/classifier.py）
  └─ 1対1のみ / 相手が最後 / 自動応答やグループは除外
新着のものだけ:
  ├─ 直近メッセージを読む（読むだけ）
  ├─ 返信下書きを生成（src/drafter.py。ANTHROPIC_API_KEY があれば Claude、無ければテンプレ）
  └─ 保存: ローカルJSON ＋ Notion(任意) ＋ Telegram通知
  └─ (Tier B) FB入力欄に配置（送信なし。WRITE_DRAFT_TO_FB=true のときだけ）
```

## モジュール

| ファイル | 役割 |
|---|---|
| `config.py` | 設定（別プロファイル・Telegram・Notion・URL） |
| `src/session.py` | ログイン状態の検知 |
| `src/scraper.py` | Messenger 受信箱・会話の**読み取り専用**取得 |
| `src/classifier.py` | 要返信の判定（純粋関数・テスト済） |
| `src/drafter.py` | 返信下書き生成（テンプレ＋任意でClaude） |
| `src/notion_sync.py` | 返信下書きDBへ upsert（スレッドIDで冪等） |
| `src/notifier.py` | Telegram通知 |
| `src/store.py` | 既処理スレッドの状態管理（再通知防止） |
| `src/fb_draft_writer.py` | **Tier B**：FB入力欄へ配置（送信しない） |
| `scripts/login.py` | 一度だけの手動ログイン |
| `scripts/run_once.py` | スキャン実行のオーケストレータ |

## テスト

```bash
pytest
ruff check .
```

## 必要なクレデンシャル（ユーザー側で用意）

- **Messengerログイン** — `scripts/login.py` で手動（2FAがあるため自動化不可）
- **NOTION_TOKEN** ＋ 返信下書きDBへのコネクト（Notion自動保存に必要。未設定でもローカル/Telegramは動作）
- **TELEGRAM_BOT_TOKEN / CHAT_ID** — 自動投稿と同じBOT/チャットで可

## スケジュール実行（任意）

Windows タスクスケジューラで `python scripts/run_once.py` を1日数回。
自動投稿のタスクとは**別時刻**に設定し、ブラウザ同時起動を避けるのが無難です。

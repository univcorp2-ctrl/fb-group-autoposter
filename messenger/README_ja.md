# fb-messenger-assistant

Facebook **Messenger の1対1メッセージ**を読み取り、**返信が必要なものだけ**を判定して、
**返信下書き**を Notion と Telegram に保存するアシスタント。

> 🤝 これは自動投稿リポジトリ `fb-group-autoposter` とは**完全に独立**しています。
> ブラウザは中央Executorが所有する認証済み `Default` を再利用し、Messenger側は起動・終了しません。

---

## 🛡️ 安定稼働とプラットフォーム保護の設計

最優先は「**絶対にアカウントを止めないこと**」。そのため：

| 方針 | 内容 |
|---|---|
| **daemonは送信しない** | 定期処理は下書き作成・入力欄配置まで。明示的な1件送信CLIは別経路で、対象・preview・重複・`--send`を検証する。 |
| **デフォルト読むだけ** | `READ_ONLY=true`。FBへの書き込みゼロ＝最も安全。 |
| **認証済みDefault固定** | `C:\AI-Agent\chrome-profile-authenticated` / `Default`へCDP接続。Guest・一時profile・別アカウントへfallbackしない。 |
| **通常Chromeを維持** | bundled Chromium、固定UA、`--no-sandbox`等を使わず、中央Executorの実Chromeへ接続する。 |
| **控えめな頻度** | 1回のスキャン上限、直列処理、条件待ち、bounded backoffを使う。 |
| **本人確認を回避しない** | CAPTCHA、checkpoint、2FAは同じDefaultの正規画面で人が完了する。 |

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

cp .env.example .env   # 値を設定（Telegram / Notion / LINE URL 等）
```

### 1) 一度だけ手動ログイン

```bash
python scripts/login.py
```

先に中央Executorを `display_mode=visible` で起動し、このスクリプトを実行します。
既存の認証済み `C:\AI-Agent\chrome-profile-authenticated` / `Default` に接続するので、
Facebook/Messengerの2FA・本人確認はその正規Chrome画面で完了します。

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
中央Executor所有の認証済みDefaultへCDP接続
  └─ 未起動・未ログイン・mode不一致ならfallbackせず状態記録＋bounded retry
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
| `config.py` | 認証済みDefault固定、表示mode、Telegram・Notion・URL設定 |
| `src/authenticated_chrome.py` | DevToolsActivePort検証、外部ChromeへのCDP接続、所有権保護 |
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

`scripts/install_windows_task.ps1` はwindowless daemonを登録します。daemonは中央Chromeへ接続するだけで、
別の可視ブラウザやGuest profileを起動しません。接続不能時もプロセスを維持して再試行します。


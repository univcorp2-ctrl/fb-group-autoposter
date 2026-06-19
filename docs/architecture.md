# Architecture

物件情報の取得 → Claudeによる文面生成 → SQLiteキュー → 承認ゲート → Playwright投稿 →
投稿後検証 → ヘルスチェックを、**「毎日必ず1回・重複なし・止まらず完遂」** で回すパイプライン。

---

## 1. 全体データフロー

```mermaid
flowchart TD
  EB["EstateBoard<br/>properties.json"]:::src

  subgraph TRIG["Windows タスクスケジューラ（8タスク）"]
    direction LR
    KA["Keepalive<br/>8:00 + ログオン"]:::task
    T1["Morning<br/>9:30 + ログオン取りこぼし"]:::task
    T2["Midday 13:00"]:::task
    T3["Afternoon 16:30"]:::task
    T4["Evening 20:30"]:::task
    MON["Monitor<br/>12:00 / 23:00"]:::task
    DSC["Discover 7:00"]:::task
  end

  T1 --> RD["run_daily.py"]
  T2 --> RD
  T3 --> RD
  T4 --> RD

  RD --> ENS["ensure.py<br/>完遂ループ"]
  ENS --> RC["orchestrator.run_cycle"]

  EB --> SEL["estateboard_adapter<br/>select_postable<br/>（投稿済み除外）"]
  SEL --> INBOX[("data/inbox/<br/>eb-*.json")]
  RC --> ING["ingest.scan_inbox"]
  INBOX --> ING
  ING --> GEN["generator<br/>Claude API<br/>（失敗時テンプレ=degraded）"]
  GEN --> DB[("SQLite jobs.db<br/>jobs / job_targets")]
  DB --> APR["approval<br/>AUTO_APPROVE / Telegram"]
  APR --> POST["poster.post_job<br/>Playwright headed<br/>永続プロファイル"]

  POST --> GUARD{"preflight<br/>ガード"}
  GUARD -->|"暦日1回 / 上限 / 重複 / 時間外"| SKIP["target=skipped"]:::warn
  GUARD -->|OK| ONE["_post_one"]
  ONE --> HEAL["healer<br/>Vision座標フォールバック"]
  ONE --> VER["verifier<br/>composer閉=投稿成立"]
  VER --> FB(("Facebook<br/>グループ")):::ext
  POST --> DB

  KA --> SESS["session<br/>keepalive + backup"]
  SESS --> BK[("profiles/<br/>backup_*")]
  DB --> MON
  MON --> STAT["logs/<br/>monitor_status.json"]

  classDef src fill:#e3f2fd,stroke:#1976d2;
  classDef task fill:#fff3e0,stroke:#f57c00;
  classDef ext fill:#e8f5e9,stroke:#388e3c;
  classDef warn fill:#fbe9e7,stroke:#d84315;
```

---

## 2. 完遂ループ（`ensure.py` — 投稿を完遂するまで止まらない）

各トリガーが `run_daily.py` を起動し、`ensure_posted_today` が回す。すべての再試行は
**JST暦日1回ガード**により冪等（何度走っても二重投稿しない）。

```mermaid
flowchart TD
  S([run_daily 起動]) --> Q1{"全グループ<br/>本日投稿済み?"}
  Q1 -->|Yes| DONE([already_done<br/>即終了・ブラウザ起動なし]):::ok
  Q1 -->|No| Q2{"活動時間内で<br/>投稿可能?"}
  Q2 -->|No| WAIT([outside_active_hours<br/>次トリガーへ委譲]):::warn
  Q2 -->|Yes| RUN["run_once<br/>inbox更新 + run_cycle"]
  RUN --> E1{SessionExpired?}
  E1 -->|Yes| RST["restore_profile<br/>直近バックアップ復元"]:::rec
  RST --> Q3
  E1 -->|"その他例外"| Q3
  E1 -->|No| Q3{"投稿成立?"}
  Q3 -->|Yes| OK([posted<br/>完了]):::ok
  Q3 -->|No| Q4{"時間予算<br/>超過?"}
  Q4 -->|Yes| BUD([budget_exhausted<br/>次トリガーへ委譲]):::warn
  Q4 -->|No| BO["指数バックオフ sleep"] --> Q1

  classDef ok fill:#e8f5e9,stroke:#388e3c;
  classDef warn fill:#fff3e0,stroke:#f57c00;
  classDef rec fill:#e3f2fd,stroke:#1976d2;
```

**多重トリガーで取りこぼさない**：Morning（＋ログオン取りこぼし）/ Midday / Afternoon / Evening
のどれか1つが成功すれば、残りは暦日ガードでスキップ。1回の `budget_exhausted` でも次のトリガーが続行する。

---

## 3. セッション維持と自動復旧

ヘッドありブラウザ＝ログオン中のみ実行（ブロック回避のための意図的設計）。
セッションは温め続け、健全時にスナップショットし、切れたら自動復元する。

```mermaid
flowchart LR
  KA["keepalive.py<br/>8:00 + ログオン"] --> OPEN["FBを開く"]
  OPEN --> CHK{"ログイン中?"}
  CHK -->|Yes| WARM["スクロール等で<br/>セッション維持"]
  WARM --> BK["backup_profile<br/>健全スナップショット"]
  BK --> STORE[("profiles/backup_*<br/>（最新N世代）")]
  CHK -->|No| AL["Telegramアラート<br/>login_once.py で再ログイン要"]:::warn

  POST2["投稿中にセッション切れ"] -->|SessionExpired| RS["restore_profile"]:::rec
  STORE --> RS

  classDef warn fill:#fff3e0,stroke:#f57c00;
  classDef rec fill:#e3f2fd,stroke:#1976d2;
```

---

## 4. ジョブ／ターゲットの状態遷移と冪等性

`jobs` は配信単位、`job_targets` はジョブ×グループ単位。`UNIQUE(job_id, group_id)` で二重登録を防ぐ。

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> approved: AUTO_APPROVE / Telegram
  pending --> rejected: reject
  approved --> posting: orchestrator が取得
  posting --> done: target が成功/スキップのみ（失敗なし）
  posting --> partial_failed: 一部成功 + 一部失敗
  posting --> failed: 失敗のみ
  posting --> approved: スタールロック復旧
```

- **target状態**：`pending / posted / uncertain / skipped / failed`。
- **`uncertain`** は「ほぼ公開された」とみなし `posted_at` を刻む → ガードが再投稿を防ぐ（ブロック回避優先）。
- **`skipped`**（ガードによる正常な「何もしない」）は失敗扱いしない。
- **冪等性の要＝暦日1回ガード** `posted_same_group_today`：同一グループはJST暦日で1回まで。
  朝に投稿→夜はスキップ。時間ベース間隔は投稿時刻が日々後退して丸1日抜けるため不採用。

---

## 5. 多層フォールバック（投稿をミスしない）

| 層 | 仕組み |
|----|--------|
| 操作レベル | セレクタ配列を順試行 → 失敗時 `healer.py` がVisionで座標特定 → 操作単位で指数バックオフ再試行 |
| セッション | `keepalive` で維持＋健全バックアップ、切れたら `restore_profile` で自動復元して再試行 |
| 実行レベル | `ensure` 完遂ループが活動時間内は成立まで再試行、予算切れは次トリガーへ委譲 |
| スケジュール | Morning＋ログオン取りこぼし＋Midday＋Afternoon＋Evening の多重トリガー |
| グループ隔離 | グループ単位で連続失敗を計数し、閾値で `enabled:false` 検討をTelegram通知 |
| 安全停止 | 投稿制限 / checkpoint 検知時は当日の残投稿を止めて通知（暴走しない） |
| 監視 | `monitor.py` が26h投稿なしで stalled 判定、`session_status.json` で健全性記録 |

---

## 6. Secrets / 拡張点

実値はrepoに置かない（`.env.example` のキー名のみ）：`ANTHROPIC_API_KEY` / `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`。
`.env` `profiles/` `logs/` `screenshots/` `data/jobs.db` はgit管理外。

- `BROWSER_BACKEND=adspower`：将来のCDP接続差し替え口として予約。
- `ingest.py`：既存スクレイパー出力dictを `ingest_manual()` で受け取れる（SSRFガード付きURL取得も）。
- 1日2回投稿したい場合は `groups.yaml` にグループを2つ以上登録（同一グループ2回はブロックリスクのため避ける）。

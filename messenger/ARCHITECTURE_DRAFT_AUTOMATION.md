# Messenger 定期返信下書きアーキテクチャ

## 目的

Messenger の受信箱を定期巡回し、1:1 の未返信メッセージだけを判定して返信下書きを生成し、Messenger の返信入力欄まで自動配置する。送信操作は自動化しない。人が Messenger 画面で内容を確認し、必要なら編集して手動送信する。

## 全体構成

```text
Windows Task Scheduler
        |
        v
run_draft_daemon.py  (常駐 / 既定30分周期 / 単一起動ロック)
        |
        +--> run_once._scan()
        |      |
        |      +--> Playwright persistent profile
        |      +--> Messenger inbox scrape
        |      +--> classifier: 要返信 / 返信済み / close 判定
        |      +--> ThreadStateStore: 同一受信状態の重複排除
        |      +--> drafter: 返信下書き生成
        |      +--> drafts.json / drafts_archive.jsonl
        |      +--> Notion / Telegram (設定時のみ)
        |      +--> fb_draft_writer: 入力欄へ下書き配置、送信なし
        |
        +--> 最新/高優先度の要返信スレッドを再度開く
               |
               +--> 下書きが空なら配置
               +--> 同じ下書きならそのまま
               +--> 人の別テキストがあれば上書きしない
               +--> 次回巡回まで返信画面を表示したまま保持
```

## 実行周期

既定は 30 分。`MESSENGER_DRAFT_INTERVAL_MINUTES` で 5〜240 分に変更できる。Windows タスク自体はログオン 2 分後に常駐プロセスを起動し、07:30 の日次トリガーを復旧用に持つ。`MultipleInstances IgnoreNew` とプロセス内ロックの二重防止で多重起動を防ぐ。

## セッション

通常 Chrome の Default/Profile 1 等ではなく、`messenger/config.py` が指す専用 Playwright プロファイルを使う。Messenger ログイン状態をこのプロファイルに保持し、通常ブラウザのログイン状態に依存しない。

## 下書き生成と重複防止

`ThreadStateStore` が `thread_id + 最新preview` の状態を記録する。同じ受信状態なら新規生成を繰り返さず、既存 `drafts.json` を再利用する。相手への返信済みが検出された場合は active draft から除外する。

## Composer 保護

`src/fb_draft_writer.py` は送信機能を持たない。入力欄が空なら下書きを入れ、同一文なら成功扱いにし、異なるテキストが存在する場合は人による編集とみなして一切上書きしない。Enter キー押下や Send ボタン操作のコードは持たない。

## 監視・状態ファイル

- `data/drafts.json`: 現在アクティブな下書き
- `data/drafts_archive.jsonl`: 下書き履歴
- `data/threads_state.json`: メッセージ状態の重複防止
- `data/draft_daemon_status.json`: 常駐デーモンの最新状態、巡回結果、表示中スレッド、エラー
- `data/draft_daemon.lock`: 多重起動防止

ログイン切れや DOM 変更等で1サイクルが失敗しても、常駐プロセス全体は終了せず、短いバックオフ後に再試行する。Telegram 通知が設定されている場合、既存のログイン切れ通知も利用する。

## セキュリティ境界

自動化の責務は「読む・分類する・文章を生成する・返信欄へ未送信テキストを置く」まで。自動送信、購入、契約、認証変更、秘密情報の抽出は行わない。送信は人が Messenger 画面で確認後に手動で行う。

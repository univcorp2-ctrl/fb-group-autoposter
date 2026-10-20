# Messenger 自動返信＋物件資料PDF送付（2026-10-20）

## 既存の実装を再利用する
- 対象リポジトリ: `univcorp2-ctrl/fb-group-autoposter` 内 `messenger/`
- Windows Task Scheduler: `FBAutoposter-MessengerDrafts` （常駐、15分ごと）
- Chrome: 認証済み `C:\AI-Agent\chrome-profile-authenticated` の既存Default
- ChatGPTのスケジュール機能は使わない。
- Google Drive: `G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter`

## 5段階の完了条件
1. Messengerの受信箱から、相手の1対1スレッドID、最後の問い合わせ、会話履歴を取得。
2. EstateBoard最新JSONの `propertyId`、物件名・価格・資料添付情報を照合。
3. Drive Privateの `material_registry.json` で閲覧権限・媒介共有許可・書類の個別送付許可を照合し、Drive原本PDFをダウンロード。PDFマジック、SHA-256、サイズを検査し `material_cache\<propertyId>\` に格納。
4. 安価な初稿を作り、高性能モデル（Claude Opus または Codex高推論）で会話・PDF本文をレビュー。未承認なら送信禁止。
5. `send_one_playwright_reply.py --send` は同一スレッド、相手名、最新受信文、レビュー本文ハッシュ、物件・PDFのID/ハッシュを再照合。本文とPDFをMessengerに添付し、DOM・受信箱の事後照合を記録。確認不能は自動再送しない。

## 既知の制限と障害
- 2026-10-20夜時点、Codex高性能モデルはusage limit、Claude Codeは組織設定でサブスク利用禁止。APIキーを勝手に購入・追加しない。レビューできない間はフェイルクローズし、正常になれば定期実行を継続する。
- 物件資料レジストリには実際に確認したものだけ登録する。未登録物件・添付不明の物件は止めて人へ回す。資料の無条件全件送付はしない。
- 現時点で **MessengerのPDF実送信成功は0件**。コード単体テスト・UIのファイル添付欄検出だけを本番送付と混同しない。
- 既存受信箱のベースラインと過去のuncertain送信履歴を削除しない。
- 実送信の確認と相手の返信実績が取得できて初めてDONE。単なるWindowsタスクRunning・レビュー生成成功・URL検出はDONEではない。

## 実行コマンド（Codex/Claude CLIが利用枠内になった時）
```powershell
Set-Location 'C:\Users\t0015\AppData\Local\FBGroupAutoposter\app\messenger'
& 'C:\Users\t0015\AppData\Local\FBGroupAutoposter\.venv\Scripts\python.exe' -m pytest tests -q
Get-ScheduledTask -TaskName FBAutoposter-MessengerDrafts
Get-Content .\data\draft_daemon_status.json -Raw
Get-Content .\data\auto_reply_status.json -Raw
```

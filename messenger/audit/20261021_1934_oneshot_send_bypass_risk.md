# Messenger 個別送信スクリプトの停止条件に関する新規監査 — 2026-10-21 19:34 JST

## ルール
既存通常Chatのみ。Work/Cowork・Codex CLI・別Chatなし。送信・投稿・PDF添付は実施せず。本人認証と顧客送信承認を解除せず。GPT follower共有コードは編集していない。

## 直近の実機確認
2026-10-21 19:31:28 JST、認証済みMessengerスキャン19:31:04、auto_reply.status=send_paused_fail_closed、attempted=0、data/send_pause.lock存在、送信未確定のledger1件。Windows 5分Private CRM同期19:28:28正常終了(result=0)、次回19:33:33。これらは常駐自動返信の観測結果であり、別個の個別送信CLIの安全性を自動的に証明するものではない。

## 新規の高優先リスク
隔離ソース messenger/src/auto_reply.py は run_pending() 冒頭で send_pause.lockをチェックしてreturnするため、常駐daemonではfail-closed実測あり。
隔離ソース messenger/scripts/send_one_playwright_reply.py の main() と _require_premium_approval() の静的読取りでは、args.sendを使用する送信経路に対し同じsend_pause.lockチェックが見つからない。既存のreview_status・review_model・指紋・宛先・資料検証はあるが、保守用停止ファイルを横断する明示判定がない。また _block_duplicate() は args.force が真なら直近ステータスによる重複確認をskipする。未確定ledgerに残る同一threadの再送停止を個別スクリプト側で強制する経路も静的には見つからない。
このため、「常駐監視は保留されている」ことは確認済みでも、「全ての送信経路が絶対に保留される」ことはまだ証明できない。個別スクリプトが実際に送信されたという証拠はない。C本番版の同一性は今回未照合。ユーザー指定を尊重し、送信・ブラウザcomposer編集・PDFアップロードは一切試行していない。

## 必要な修復と受け入れ条件
(1) 個別スクリプトで args.send に入る前に runtime Settings.data_dir/send_pause.lock存在を検証し、保留なら引数や--forceにかかわらず拒否。
(2) 過去のauto_reply_ledger.jsonに当該threadのattempted_unconfirmed / blocked_or_uncertain_no_replay が1件でもあれば、本文変更・日時変更・--forceにかかわらず絶対再送禁止。
(3) ledger欠落・破損時には安全側に拒否、正常な非送信preflightだけ許可。
(4) 合成データの隔離テストで保留on/off、未確定履歴と--force、ledger欠落、正常な非送信preflightを検証。全テスト成功後のみruntime版へ非破壊バックアップ+SHA照合して適用し、送信しないE2Eを確認。
(5) 保留ファイルの削除や顧客送信承認解除はしない。2026-10-19の未確定1件を明示的な同一本文/PDF証拠なしに再送しない。

## 実行制限
上記リスク発見直後、Desktop Commanderで個別送信関連のテストファイル一覧を確認しようとした操作は安全性チェックによってブロックされた。別手段へ切り替えて拒否を迂回することはせず、このターンでは送信スクリプトの修正・テスト・本番反映を行っていない。コードの具体的修正と検証は未完了として扱う。

## CloudflareとCRM
Cloudflare Chromeタブ63は dash.cloudflare.com/login で本人認証待ち。Zero Trust実Issuer/Audience、閲覧許可者、Preview専用D1・Secretsは未確認。公開デプロイ・D1 migrationなし。
EstateBoard隔離ブランチSHA5ab716d59ccf93530f79f9388c0dd09eaa88e13e、Node11 + Python/Playwright12テスト全件成功、GitHubとDrive同期済み。Private CRM 5分同期稼働、ユーザー通知監視は以前のツール拒否によって未実装。
全体完了判定: IN PROGRESS。優先順位は個別送信経路にも一貫した送信停止・未確定再送禁止ガードの整備、Cloudflare本人認証、独立Preview D1の確認、非本番E2E、通知送達、承認付き高品質レビューとPDF送達。

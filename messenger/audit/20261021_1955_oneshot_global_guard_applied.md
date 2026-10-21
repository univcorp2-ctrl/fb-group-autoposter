# 2026-10-21 Messenger P0 個別送信経路の停止ガード修復・検証

## 制約
既存の通常Chatだけで実施。Work/Cowork/Codex CLI・別チャット・実送信/投稿/添付操作なし。GPT follower非編集。本人認証・顧客送信承認は未解除。

## 原因と修復
以前は src/auto_reply.py の常駐監視だけが send_pause.lock を確認していた。個別送信 scripts/send_one_playwright_reply.py の --force は古いステータスの重複検査を省略する可能性があった。
送信スクリプトに _assert_global_send_guard(data_dir, thread_id) を新設。pauseあり・ledger欠落/破損・同一スレッドの非confirmed_sent履歴ではRuntimeErrorで拒否。mainの--send実行前、composer入力直前、send_button.click直前の計3か所で呼び出す。--force で回避不可。停止ファイルや履歴は変更しない。

## テスト
隔離の新規非送信ガードテスト13件PASS。隔離 Messenger 全150テストPASS。C本番の実コードをimportした13件もPASS。
本番側既存テスト2件は実pauseマーカーを参照し、過去の非保守状態を期待したため一度失敗。テストのSEND_PAUSE_FILEを合成tmp_pathに差し替え、production markerを保持したまま本番側全113テストPASS。
19:55の実Ledger追加確認：本番send_pause.lockで拒否、実台帳だけを一時ディレクトリへコピーしても未確定1件は uncertain_prior_delivery_no_replay で拒否。テスト終了後一時ディレクトリ削除。実送信試行なし。

## 本番安全適用と保存
パッチ前に個別送信プロセスが0件、runtime pauseマーカー存在を確認。
本番スクリプト元SHA256 F60BA7A41B898A92BFBF179CEC02DB33B7AA6B832AD12ABDDD1E95C1B97543B6 を Drive audit/send_one_before_global_guard_20261021.py にバックアップ。
隔離とC本番スクリプトには既存のリクエスト承認処理など28行の差分があり、本番全体を上書きせず関数+呼び出し3か所を個別編集。本番コードカスタマイズを保持。適用後の本番 SHA256 087F5E8380EE7D29A642839317D50C7799BE594A1411FBB8381D8CF60BF17866、Drive audit/send_one_runtime_patched_20261021.py と一致。
本番テスト元もDrive audit/test_auto_reply_before_pause_fixture_20261021.py にバックアップ。
GitHub univcorp2-ctrl/fb-group-autoposter 専用ブランチ audit/messenger-safe-20261021、commit 7864493b9da8bfd42e42b7be7260c40bb042174a、git ls-remote一致。ステージの送信スクリプトとテスト2本をDrive正本へSHA256一致で同期。

## 最終実測 2026-10-21 19:55:14 JST
Messengerログイン済みスキャン19:54:16成功。daemon send_paused_fail_closed、attempted=0。実send_pause.lock存在、10月19日未確定履歴1件、個別送信プロセス0。Private CRM5分同期19:53:53終了コード0、次19:58:58予定。

## 未完了
Cloudflare既存タブ63が未ログイン。実Accessアプリ、Issuer/Audience、閲覧許可者、別Preview D1、Secretsは未照合。Cloudflareへのデプロイ、D1マイグレーションなし。
高品質レビュー経路は現状needs_humanフェイルクローズで実Opus API/CLIは未使用。個別承認された資料PDF/宛先/実送達E2Eは未達。
非公開CRM5分同期失敗時のユーザー通知・2027年9月の期限予告は安全性チェックで未実装。
全ての未知の外部送信経路まで検証したとの主張はしない。個別送信CLIのP0コード修正と静的/非送信テストは完了、事業全体はIn progress。
Notion監査ログ: https://app.notion.com/p/40010562e58b81d2b9bef6846118dd07
Notion Critical事故: https://app.notion.com/p/40010562e58b81d4aac3e6c52315b1fc
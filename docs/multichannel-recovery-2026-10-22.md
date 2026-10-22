# Facebook / Messenger / LINE 復旧状態 — 2026-10-22

目標は3経路の実投稿・適切な返信・高性能チェック・条件に合う物件と資料の自主案内。**未完了、継続中**。

## 今回の変更と実証

- ユーザーが今回、追加API課金なしのCodexログイン経由でMessengerの自動チェックを明示許可。`MESSENGER_REVIEW_PROVIDER=codex_login` の場合だけアプリ同梱codex.exeを使う。ChatGPTログインを毎回検査し、API認証は拒否。APIキー環境変数を子へ渡さず、APIへのフォールバックはない。
- レビューモデルは `gpt-6-astra/high`。read-only、ephemeral、構造化JSON。shell_tool、multi_agent、multi_agent_v2、Web検索、MCP/プラグインを無効化。ソース側とC稼働先それぞれで実モデル接続成功。ただしこの接続検証は架空データであり、顧客送付E2Eの証明ではない。
- Messengerの物件照合が固定8地域と億円表記を必須としていた問題を修正。正規化した明示物件名または物件IDで一意照合。重複名・IDと名前の矛盾・価格矛盾を拒否。候補照合と資料共有許可は分離したまま。
- makerの初稿を高性能レビューへ渡す既存構成を再使用。レビュー結果の認識を送信処理・レビューキャッシュでも統一。本文・相手・PDF照合、未確定送信の永久再送禁止は維持。
- 対象コードをC実稼働先へ個別反映。反映前に差分を確認し、C固有処理を上書きしないことを確認。旧コードはC runtime `tmp/2026-10-22-property-identity/` に保全。
- 旧 `messenger/data/send_pause.lock` は、現在の復旧・送信依頼と自動レビュー許可に基づき、C runtime `_archive/2026-10-22-messenger-review/send_pause.lock` に保全して解除。`FBAutoposter-MessengerDrafts` を実タスク経路から再起動。入口はpythonw.exe。
- 09:04:03 JSTの実スキャン：37件、ログイン済み、自動返信armed=true、新規資料請求0、送信試行0。過去の未確定1件は保持・再送なし。実送達成功は未証明。
- 検証：Gソース176件PASS、C実稼働先149件PASS、変更ファイルの致命的構文/名前エラー検査PASS。両環境は既存テスト構成が異なるため、件数を同一とは扱わない。

## 他経路の現況

| 対象 | 現在の証拠 | 未達・次の作業 |
|---|---|---|
| Facebook投稿 | 拡張機能1.1.5のポーリング回復を確認。処理中だったタスクは投稿ではなくsession probeで、期限切れ・送信クリック前失敗 | 投稿ボタン無効の根因。Chrome UIでは正常入力で投稿ボタンが有効になることを確認。診断文字は消去しダイアログ閉鎖済み。実公開URL未確認 |
| Messenger | C daemonは認証済み、今回の高性能チェック実装で自動処理再開 | 現状の自動対象は新規の明示資料請求だけ。通常質問・既存保留・自主案内の対応拡大、実会話+PDF+実送達E2Eが必要 |
| LINE | LineAutoReply5mは継続走査、直近エラー0、pendingReview=1 | 誤ったno_reply_neededから昇格した資料請求1件は未解決。物件・資料と買主条件を照合し適切に返信。自主提案の実送信も未証明 |

## 再開位置

1. C Messenger `data/draft_daemon_status.json` と `auto_reply_status.json` を再読し、プロセスと最新走査を確認。過去の `blocked_or_uncertain_no_replay` は絶対に消さない。
2. Facebookの実稼働拡張機能はC `app/extension/` の1.1.5、G `extension/` は1.1.1。旧G版でC版を一括上書きしない。最新失敗はcomposer_readyの後に投稿ボタンを認識できない。UI上の通常入力は有効化できたため、実拡張の入力/認識経路を再現して修正する。
3. Messengerの通常返信と歴史的保留を、最新会話・独立レビュー・重複防止を使って処理できるよう復旧する。資料権限不足を根拠なく承認しない。
   - 追加で通常返信を妨げる実装を確認：`send_one_playwright_reply.py` の `attachment` がChrome接続の `BrowserAttachment` とPDFの双方に使われている。資料なしではChrome接続オブジェクトに `file_path` を要求する経路がある。ブラウザ接続と送付PDFを分離し、本文だけの送信経路を回帰検証すること。
4. LINEのC runtimeはGソースよりバックグラウンド接続・巡回カーソルの修正が進んでいる。G版の一括配置は禁止。現行台帳は `C:/AI-Agent/line-draft-automation/state/line-auto-state-v2.json`。
5. Windows起動時の可視コンソール0件の前後比較、再ログイン/再起動後の継続も未検証。pythonw入口だけで全子プロセスの無窓動作を証明しない。

KEEP: ソース・回帰テスト・本記録。ARCHIVE: 旧送信保留マーカー。DELETE: なし。

## 追加依頼：タスク別トークン自動連携

Facebook・Messenger・LINEに実行別の実測記録を追加し、既存 `AI-Operations-LightCheck` の15分更新へ接続した。09:20:02 JSTの本番ダッシュボードAPIで、3タスクの値が私有台帳と一致（Facebook 0、Messenger 15,190、LINE 19,516）。初期値は実接続・未送信の生成検証に使った実測量であり、顧客実送達の証明ではない。過去の未収集分は補完しない。

LINEは既存依存関係のあるNTFS検証用コピーでbuildと328テストPASS、Python11テストPASS。Messenger178テストPASS、集計PowerShell17テストPASS。SQLite子プロセスの無窓起動へ修正後、実スケジュール起動の40秒観測で新規可視コンソール0件、集計タスク終了0を確認。

連携仕様と再開位置は兄弟リポジトリ `cloud-local-task-dashboard/docs/token-usage.md`。集計元の実稼働コードは `C:/Users/t0015/codex-workspace-local-copy/automation-control-center-site/scripts/agent-health/`。投稿・返信・自主案内の完全復旧という元の目標は引き続き未完了。

## 続行結果：本文返信とFacebookウィンドウ（09:35 JST）

- Messengerのブラウザ接続と添付PDFの変数衝突を実送信フローの合成ブラウザで再現（送信前にfile_path属性エラー）し修正。資料なしの本文返信、送信前の最終ガード、DOMによる事後確認が通る回帰テストを追加。
- 資料請求だけのフィルターを外し、新規・最近の1対1問い合わせを高性能レビュー対象へ追加。自身の送信・締めの相槌・グループ等は既存classifierで除外。PDFが必要な依頼では従来通り資料検証必須。通常質問に不要なPDFを要求しないよう、資料依頼判定をレビューと個別送信で統一。
- 同一スレッドで24時間一切返信しない制限を撤去し、別の最新受信への追加質問に回答可能とした。同じ受信hashの再送禁止、未確定履歴の永久再送禁止、全体の日次上限は保持。
- G Messenger183件PASS、C稼働先154件PASS。Cへ反映前に独立の短期メンテナンス保留を置き、送信プロセス0を確認してdaemonを停止・反映・テスト・再開。自身が置いた保留は `_archive/2026-10-22-messenger-review/ordinary-replies-runtime-update.pause` に保全。以前の保留や台帳を削除していない。
- C実モデルで架空の通常質問をレビューし、gpt-6-astra/highが根拠に沿う32文字の本文をapproved、material=nullと判定。顧客へは未送信。09:35:25の実daemonは認証済み・armed=true、送信試行0、未確定1維持。新規問い合わせは0。
- Facebook未送信診断の最初のhandleは `data/extension_tasks/layout-check-20261022-0331f2bf.json`。取得後tab_openedにも進まず期限切れ。Defaultプロフィールにインストールされた拡張機能 `kofaofnbmnnianmdobmfgcfhakllhoal` の保存エラーで `No current window` を確認した。ポーリングは動いても、Chromeがバックグラウンドのみではtabs.createに使えるウィンドウがなかった。
- Default Chromeだけに最小化したabout:blankウィンドウを作成（再起動なし、認証済みMessenger/LINEプロフィールは維持）。その後のhandle `layout-check-window-20261022-a928175e.json` はcomposer_readyへ到達し、layout_ok / mode=paste / lines=3/3で完了。診断文字は拡張機能自身が消去する経路。投稿クリックは0。これで入力の実診断は成功したが、公開URLの確認ではない。
- 次の再発対策は拡張機能1.1.6。`postingWindowId()` が同じプロフィールの通常ウィンドウを使用し、なければfocused=false/state=minimizedで所有ウィンドウを作成。作成失敗はクリック前失敗として記録する。Cの稼働版1.1.5のcontent/background/manifestをG正本へ取り込み、その上に修正。C旧版は `_archive/2026-10-22-extension-owner-window/` に保全。ウィンドウ作成・再使用・incognito除外のNodeテストと構文検査PASS、既存permalink検査PASS。
- **版の再読込はまだ未確認**。09:35:18のwatchdog check-onlyはloaded=1.1.5 / expected=1.1.6、idle=439秒で待機。watchdogに版不一致を検出する処理を追加し、既存の15分アイドル・6時間再起動間隔・投稿停止なし・active leaseなしに加えてpending taskなしの場合だけ再読込する。ソースとCへ配置し7回帰テストPASS。既存の5分タスクで安全条件成立時に反映する。次回、実heartbeatのversion=1.1.6を確認すること。check-only待機を完了扱いにしない。

次の優先作業：1.1.6の実読込を確認し、Facebook本文の高性能レビューを現行承認ハッシュと最新sourceに結び付けて実公開を検証。LINEの明示資料請求を無条件skipするno_reply_needed再レビュー経路と、メーカーがsend=falseの場合に独立チェッカーを飛ばす経路を修復し、実会話に対する適切な返信を検証。Messengerの既存4保留も個別に解決し、新規限定の運用だけで完了としない。

KEEP: 返信修正・テスト・拡張機能1.1.6・監視修正・本記録。ARCHIVE: C旧拡張版と短期メンテナンス保留。DELETE: なし。

## 2026-10-22 10:10 JST: priority customer replies executed
- Messenger: はしもと ゆき, thread 2189053298490382, 10:08 JST. Sent the approved answer giving the requested property address. Reloaded conversation showed exact outgoing text and sent label. Recorded confirmed_sent in runtime ledger; preserved the other unresolved attempt.
- LINE: pending material request Uf4c489602183c36e6d4ba7bf544a9cd6, 10:09:53 JST. Independent gpt-6-astra review passed. Sent: 松が谷の2件は除外いたします。ほかの物件資料をご案内するため、ご希望のエリアを教えていただけますか？ Runtime ledger status=sent, sent=1, scanned=1, errors=[], pendingReview=0. No PDF attached. Sender reread the conversation and matched the exact outgoing text.
- Messenger daemon was briefly stopped during manual browser send, then restarted. The one-shot sender previously timed out navigating the inbox before composing; it did not send.
- LINE priority scan helper now selects a never-attempted pending request before rotating the remaining scan. Source targeted review tests: 3 passed. Existing failed-model cooldown for this never-sent request was cleared after checking the current model worked; the guarded second review completed and sent.
- Outstanding broader recovery: other Messenger conversations and Facebook publication proof. Runtime posting suite returned 5 failures (analytics import, backend validation, extension guard expectation, metrics import, schedule string expectation); no claim of full posting verification.
- KEEP: priority scan helper, runtime delivery ledgers, this evidence note. ARCHIVE: none. DELETE: none.

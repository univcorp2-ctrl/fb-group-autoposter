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
4. LINEのC runtimeはGソースよりバックグラウンド接続・巡回カーソルの修正が進んでいる。G版の一括配置は禁止。現行台帳は `C:/AI-Agent/line-draft-automation/state/line-auto-state-v2.json`。
5. Windows起動時の可視コンソール0件の前後比較、再ログイン/再起動後の継続も未検証。pythonw入口だけで全子プロセスの無窓動作を証明しない。

KEEP: ソース・回帰テスト・本記録。ARCHIVE: 旧送信保留マーカー。DELETE: なし。

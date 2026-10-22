# Facebookグループ新規投稿：Claudeレポート再利用と本番復旧（2026-10-22）

## 利用した既存資産
- Google Drive source: `G:/マイドライブ/AI_Agents/github/repos/fb-group-autoposter/`
- Claude復旧レポート: `docs/multichannel-recovery-2026-10-22.md`
- Claudeの診断用スクリプト: `tmp/claude_layout_check.py`, `tmp/claude_find_posts.py` など（本番C側）
- 本番PCソース: `C:/Users/t0015/AppData/Local/FBGroupAutoposter/app`
- 拡張ID: `kofaofnbmnnianmdobmfgcfhakllhoal`（Chrome Default）

## 実際に確認した停止原因
- 2026-10-22 午前、本番bridge正常 / extension_polling=true だが、ロード済み拡張は **1.1.5**。
- ソースの1.1.6/1.1.7とは食い違う。1.1.6には `No current window` 対策済み。
- 投稿候補は作れるが、本番の複数ジョブが **「投稿ボタンが押せる状態になりません」** でクリック前失敗。
- ClaudeのUI診断は、新規スレッド投稿欄へ3行を投入できることを確認済み。しかし投稿ボタン有効の確認までは従来のlayout_checkで担保できなかった。

## 今回の修復
1. `extension/content.js`：Lexical投稿欄で、貼り付けた文字列のDOM表示だけではなく「投稿」ボタンの有効状態を要求。無効なら段落入力方式へ切り替え、再評価。それでも無効なら診断付きでクリック前中止。
2. 親buttonの無効属性と表示を正しく読むようPostボタン候補を改善。コメント・返信欄の拒否は保持。
3. `extension/manifest.json`：バージョンを**1.1.7**へ更新。
4. `scripts/facebook_post_button_preflight.py`：投稿しないlayout_checkを発行。3行の保持＋Postボタンの有効化を**両方**確認した場合のみ許可。
5. `scripts/facebook_recovery_pump.py`：橋渡し稼働、正しい拡張バージョン、pause/lease/queue無し、非公開入力検証の成功が揃う場合のみ既存投稿パイプラインを実行。既存重複・鮮度・承認・投稿間隔制御を再利用。
6. Windowsタスク `FBAutoposter-RecoveryPump`：**30分間隔、pythonw.exe（非表示）**、多重起動防止。ChatGPTスケジュール不使用。
7. `FBAutoposter-ExtensionWatchdog` は従来どおり5分ごと。ユーザー操作が15分以上なく、実送信中でなく、6時間クールダウン条件に合うときのみChromeを安全に再起動し、新版拡張の読込を確認。無断で前面表示しない。

## 実行・検証状態
- GitHubブランチ: `fix/facebook-composer-submit-20261022`
- コミット: `2a450de`（新規投稿欄修正）、`47f962e`（復旧ポンプ）
- `node --check extension/content.js` PASS
- Python新規投稿・ポンプ・layout_gate向けテスト **11件PASS**
- Windows `FBAutoposter-RecoveryPump` 登録済み・手動起動でブロック判定を確認
- 現時点の結果: `expected_version=1.1.7`, `loaded_version=1.1.5`, `extension_version_not_loaded`, 実投稿成功0件。**完了扱い禁止**。

## 完了条件
- bridge `/health` が `extension_version=1.1.7`, `extension_polling=true`。
- `recovery_layout_gate.json` が `status=passed`、3/3行＋`enabled=true`。
- 保存された投稿対象物件・グループ・本文の鮮度と承認を再照合。
- Facebook新規スレッド（コメント/返信は禁止）に1件実投稿し、**permalinkが実際に確認できる**。
- SQLite、Google Drive、既存EstateBoard Web分析画面の3者で同じ投稿を照合。10件依頼の残件を進める。
- 失敗やuncertain送信は無条件再送せず実確認で判定。

## 現在の障害・コピペ用対応
本番Chromeの拡張は1.1.5が動いており、GitHub/PCの1.1.7が未ロード。本人の操作画面を前面に出さず復旧するため、既存Windows watchdogが15分以上アイドルになると自動再起動・新バージョン照合を行う。実行中のFacebook送信leaseや未処理タスクがある場合は再起動禁止。その後、30分ごとのRecoveryPumpが3行の非公開入力＋投稿ボタン有効化を検査し、成功した場合のみ既存承認済み投稿キューへ進む。Facebookへの実投稿permalinkが0件の間は完了扱いしない。

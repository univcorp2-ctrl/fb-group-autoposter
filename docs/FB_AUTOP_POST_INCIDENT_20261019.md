# Facebook自動投稿停止の原因と対応（2026-10-19）

## 結論
Facebookのログイン切れを確認したわけではない。直接確認できた停止原因は、Default Chromeプロファイルに登録されたMV3拡張から、localhost bridgeへの定期通信が止まっていること。

## 本番PCでの証拠
- 2026-10-19 15:55 JST頃、bridge /health: ok=true、extension_polling=false、最後のpollから約46,773秒（約13時間）。
- 拡張の最後のwake reasonは alarm-busy。拡張の最終通信が停止した正確なブラウザ内部原因は未確定。
- Chrome DefaultのSecure Preferencesには拡張ID kofaofnbmnnianmdobmfgcfhakllhoal とローカル実装パスが存在。
- Windows FBAutoposter-Morning は当日09:48に終了コード0だが、投稿の成功URLは得られていない。
- run_dailyのログは extension_probe_timeout を manual_profile_recovery_required に置き換えて「Facebookセッション切れ」と誤報していた。
- 実運用SQLiteの10/19新規確認済み投稿は0件。Google Drive上 post10_status.json は confirmed_new_threads=0。
- Cloudflare EstateBoard分析APIはhealthy（履歴3,411件）。Web基盤側ではなくChrome拡張の通信停止。
- 既存の不明投稿（uncertain）83件は実投稿とみなさず、無条件の再送禁止。

## 今回反映した修正
1. src/session_preflight.py：新規probeを作る前にlocalhost bridgeの通信状態を読み取り、無反応なら extension_not_polling と即時返す。
2. scripts/run_daily.py：拡張停止・bridge障害と本物のログイン切れを区別し、ログイン切れと誤報しない。
3. scripts/watch_extension_health.py：Windowsから5分ごとにChrome拡張の通信を監視。PCが15分以上操作されず、投稿中ではなく、6時間の再起動間隔を満たす場合に限りDefault Chromeを安全に再起動して再検証する。
4. Windows Task Scheduler：FBAutoposter-ExtensionWatchdogを登録。ChatGPTスケジュールは不使用。
5. Google Drive Private/FBGroupAutoposter/extension_watchdog_status.json：監視実行結果を記録。
6. tests/test_extension_watchdog.py：投稿中断防止、PC操作中の再起動禁止、再起動連打防止など6件。既存新規スレッド保護4件と合わせて10件パス。

## 最終状態・残課題
修正コードとWindowsの定期実行を配備。監視実行で extension_not_polling を正しく検出した。Chromeが現在操作中のため、ブラウザ再起動は未実行であり「Facebook投稿復旧完了」とは判定しない。次に安全なアイドル時間が来たら監視タスクが復旧を試み、成功後も各投稿の新規スレッドpermalinkとWeb反映が必要。現在、目標10件中の新規確認済み投稿は0件。

GitHub: https://github.com/univcorp2-ctrl/fb-group-autoposter/tree/fix/facebook-extension-e2e-20261007
Web: https://estateboard.pages.dev/facebook-analytics/
Google Drive: G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter

# Windows production setup

## 1. 自動修復

管理者PowerShellで次を実行します。

```powershell
cd G:\マイドライブ\AI_Agents\github\repos\fb-group-autoposter
powershell -ExecutionPolicy Bypass -File scripts\repair_windows_runtime.ps1
```

これにより `%LOCALAPPDATA%\FBGroupAutoposter` にDrive同期されない実行環境を構築し、既存DBとFacebook profileを未初期化時だけコピーします。

## 2. preflightの合格条件

`python`、`estateboard_source`、`drive_archive`、`profile_outside_drive`、`database_outside_drive`、`groups`、`playwright_chromium`、`drive_image_sample` が `OK` になります。Codexを選ばない限り `codex_cli` はWARNでも投稿できます。

## 3. Facebookの一度だけの操作

Facebookがログインを要求した場合のみ、ログイン中のWindowsユーザーで次を実行し、表示されたChromiumでログインを完了します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\FBGroupAutoposter\run-task.ps1" -Script scripts\login_once.py
```

checkpoint、CAPTCHA、2FAは自動回避しません。認証完了後は同じlocal profileを全scheduled taskが再利用します。

## 4. 本番確認

`.env` の `DRY_RUN=false`、`AUTO_APPROVE=true` を確認し、Morning taskを手動開始します。

```powershell
Start-ScheduledTask -TaskName FBAutoposter-Morning
Start-Sleep -Seconds 10
Get-ScheduledTaskInfo -TaskName FBAutoposter-Morning
```

成功判定はSQLiteの `posted`、取得済みpermalink、Facebook上の実投稿、公開status dashboardの4点一致です。

## 5. Codex CLI

`-PostTextProvider codex` でrepairすると、npmがあれば `@openai/codex` をインストールします。初回だけCodex CLIの通常ログインが必要です。CLIが失敗しても物件投稿はテンプレートへフォールバックします。

## 6. 本番に必要なもの

- Windows 11端末が投稿時刻に起動またはスリープ復帰可能
- 同じWindowsユーザーがログイン状態
- Google Drive for desktopでG:が利用可能
- Facebookグループへの投稿権限
- Git remoteへpush可能な既存資格情報（status dashboard自動更新用）
- 任意: Telegram、Anthropic API、Codex CLI

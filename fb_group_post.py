#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fb_group_post.py
Facebookグループへ投稿するPlaywright自動化スクリプト。
Claude in Chrome の権限レイヤーを通さないため、操作ごとの許可ダイアログは出ない。

2つの動作モード:
  - cdp     : 既にログイン済みのChromeに --remote-debugging-port 経由でアタッチ（最速・ログイン不要）
  - profile : 専用プロファイルで起動。初回だけ手動ログイン→以降は自動

使い方は README_ja.md を参照。
"""
import os
import sys
import time
import argparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def find_and_open_composer(page):
    """グループページの投稿欄を開いて「投稿を作成」ダイアログを出す。"""
    # 投稿欄のトリガー（日本語UI: 「テキストを入力...」/ 英語: "Write something")
    triggers = [
        "テキストを入力", "投稿を作成", "Write something", "Create a post",
        "何を考えていますか", "What's on your mind",
    ]
    for t in triggers:
        try:
            el = page.get_by_text(t, exact=False).first
            el.wait_for(state="visible", timeout=4000)
            el.click()
            return True
        except PWTimeout:
            continue
        except Exception:
            continue
    return False


def type_post_body(page, text: str):
    """ダイアログ内の本文エリアにテキストを入力。"""
    # 「投稿を作成」ダイアログを待つ
    dialog = page.get_by_role("dialog")
    dialog.wait_for(state="visible", timeout=8000)

    # contenteditable の本文欄を取得
    box = None
    for sel in [
        'div[role="dialog"] div[role="textbox"]',
        'div[role="dialog"] div[contenteditable="true"]',
    ]:
        try:
            cand = page.locator(sel).first
            cand.wait_for(state="visible", timeout=4000)
            box = cand
            break
        except Exception:
            continue
    if box is None:
        raise RuntimeError("本文入力欄が見つかりませんでした")

    box.click()
    # insert_text は改行・日本語をそのまま入力できる（IME/補完を避ける）
    page.keyboard.insert_text(text)
    time.sleep(1.0)


def click_post_button(page):
    """ダイアログ内の「投稿」ボタンを押す。"""
    names = ["投稿", "Post", "シェア", "Share"]
    for n in names:
        try:
            btn = page.get_by_role("dialog").get_by_role("button", name=n, exact=True).first
            btn.wait_for(state="visible", timeout=4000)
            if btn.is_enabled():
                btn.click()
                return True
        except Exception:
            continue
    return False


def run(page, group_url: str, text: str, dry_run: bool):
    print(f"[*] グループへ移動: {group_url}")
    page.goto(group_url, wait_until="domcontentloaded")
    time.sleep(3)

    # ログイン判定
    if "login" in page.url or "/login" in page.url:
        print("[!] 未ログインです。開いたウィンドウでログインしてから再実行してください。")
        return False

    if not find_and_open_composer(page):
        raise RuntimeError("投稿欄（コンポーザー）が見つかりませんでした。ページ構造が変わった可能性があります。")
    print("[*] 投稿ダイアログを開きました")
    time.sleep(1.5)

    type_post_body(page, text)
    print("[*] 本文を入力しました")

    if dry_run:
        shot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dryrun_preview.png")
        page.screenshot(path=shot, full_page=False)
        print(f"[DRY_RUN] 投稿せず終了。プレビュー: {shot}")
        return True

    if not click_post_button(page):
        raise RuntimeError("「投稿」ボタンが押せませんでした")
    print("[+] 投稿を実行しました")
    time.sleep(4)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["cdp", "profile"], default=os.getenv("FB_MODE", "profile"))
    ap.add_argument("--group-url", default=os.getenv("GROUP_URL", "https://www.facebook.com/groups/1281008662437696"))
    ap.add_argument("--text-file", default=os.getenv("POST_TEXT_FILE", "post.txt"))
    ap.add_argument("--cdp-url", default=os.getenv("CDP_URL", "http://localhost:9222"))
    ap.add_argument("--user-data-dir", default=os.getenv("USER_DATA_DIR", "./fb_profile"))
    ap.add_argument("--dry-run", action="store_true", default=os.getenv("DRY_RUN", "false").lower() == "true")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    text_path = args.text_file if os.path.isabs(args.text_file) else os.path.join(here, args.text_file)
    text = load_text(text_path)
    print(f"[*] 投稿本文 {len(text)} 文字を読み込み（mode={args.mode}, dry_run={args.dry_run}）")

    with sync_playwright() as p:
        if args.mode == "cdp":
            print(f"[*] 既存Chromeへ接続: {args.cdp_url}")
            browser = p.chromium.connect_over_cdp(args.cdp_url)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ok = run(page, args.group_url, text, args.dry_run)
            # CDPモードではブラウザは閉じない（ユーザーのChromeなので）
        else:
            udd = args.user_data_dir if os.path.isabs(args.user_data_dir) else os.path.join(here, args.user_data_dir)
            print(f"[*] 専用プロファイルで起動: {udd}")
            ctx = p.chromium.launch_persistent_context(
                udd,
                headless=False,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ok = run(page, args.group_url, text, args.dry_run)
            ctx.close()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

/* FB Group 物件投稿ヘルパー content script
 * 実セッション内で動くため、自動化検知も許可ダイアログも発生しない。
 * フロー: グループの投稿欄を開く → 本文をReactが拾う形で流し込む → 「投稿」を押す。
 */
(function () {
  "use strict";

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function waitFor(fn, { timeout = 8000, interval = 200 } = {}) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      try {
        const v = fn();
        if (v) return v;
      } catch (_) {}
      await sleep(interval);
    }
    return null;
  }

  // ---- 要素検出 -------------------------------------------------------------
  function findComposerTrigger() {
    // フィード上の「テキストを入力...」/「何を考えていますか？」ボックス
    const labels = ["テキストを入力", "何を考えていますか", "Write something", "What's on your mind", "投稿を作成"];
    const nodes = document.querySelectorAll('div[role="button"], span, div');
    for (const n of nodes) {
      const txt = (n.textContent || "").trim();
      if (!txt || txt.length > 30) continue;
      if (labels.some((l) => txt.includes(l))) {
        const clickable = n.closest('div[role="button"]') || n;
        if (clickable && clickable.offsetParent !== null) return clickable;
      }
    }
    return null;
  }

  function findDialogEditable() {
    const sels = [
      'div[role="dialog"] div[role="textbox"][contenteditable="true"]',
      'div[role="dialog"] div[contenteditable="true"]',
      'div[role="textbox"][contenteditable="true"]',
    ];
    for (const s of sels) {
      const el = document.querySelector(s);
      if (el && el.offsetParent !== null) return el;
    }
    return null;
  }

  function findPostButton() {
    const scope = document.querySelector('div[role="dialog"]') || document;
    const btns = scope.querySelectorAll('div[role="button"], button, [aria-label]');
    for (const b of btns) {
      const label = (b.getAttribute("aria-label") || b.textContent || "").trim();
      if (["投稿", "Post", "シェア", "Share"].includes(label)) {
        const disabled = b.getAttribute("aria-disabled") === "true" || b.disabled === true;
        if (!disabled && b.offsetParent !== null) return b;
      }
    }
    return null;
  }

  // ---- 本文流し込み（Reactが拾う形）---------------------------------------
  function insertTextReactSafe(editable, text) {
    editable.focus();
    // 既存内容をクリア
    document.execCommand("selectAll", false, null);
    document.execCommand("delete", false, null);
    // execCommand insertText は beforeinput/input を発火させ、Reactが値を認識する
    const ok = document.execCommand("insertText", false, text);
    if (!ok) {
      // フォールバック: 1行ずつ。改行は Enter ではなく <br> 相当で入れる
      for (const ch of text) {
        document.execCommand("insertText", false, ch === "\n" ? "\n" : ch);
      }
    }
    editable.dispatchEvent(new InputEvent("input", { bubbles: true }));
  }

  // ---- 投稿実行 -------------------------------------------------------------
  async function doPost(text, { post = false, log = console.log } = {}) {
    log("投稿欄を探索中...");
    const trigger = await waitFor(findComposerTrigger, { timeout: 6000 });
    if (!trigger) throw new Error("投稿欄が見つかりません（ページ最上部に居るか確認）");
    trigger.click();

    log("ダイアログ待機中...");
    const editable = await waitFor(findDialogEditable, { timeout: 8000 });
    if (!editable) throw new Error("本文入力欄が見つかりません");

    await sleep(400);
    log("本文を入力中...");
    insertTextReactSafe(editable, text);
    await sleep(800);

    if (!post) {
      log("✅ 下書き投入完了（プレビュー）。内容を確認して、問題なければ手動 or 「投稿実行」で送信。");
      return;
    }

    log("「投稿」ボタン待機中...");
    const btn = await waitFor(findPostButton, { timeout: 6000 });
    if (!btn) throw new Error("「投稿」ボタンが押せる状態になりません");
    btn.click();
    log("🎉 投稿を実行しました。");
  }

  // ---- UI -------------------------------------------------------------------
  function buildPanel() {
    if (document.getElementById("fbgp-panel")) return;
    const posts = window.FB_POSTS || [];

    const wrap = document.createElement("div");
    wrap.id = "fbgp-panel";
    wrap.style.cssText =
      "position:fixed;right:16px;bottom:16px;z-index:2147483647;width:360px;" +
      "background:#fff;border:1px solid #ccc;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.2);" +
      "font:13px/1.5 sans-serif;color:#111;overflow:hidden";

    wrap.innerHTML =
      '<div style="background:#1877f2;color:#fff;padding:8px 10px;font-weight:700;display:flex;justify-content:space-between;align-items:center">' +
      "<span>🏠 物件投稿ヘルパー</span>" +
      '<span id="fbgp-min" style="cursor:pointer">_</span></div>' +
      '<div id="fbgp-body" style="padding:10px">' +
      '<select id="fbgp-sel" style="width:100%;margin-bottom:6px"></select>' +
      '<textarea id="fbgp-text" style="width:100%;height:160px;box-sizing:border-box;resize:vertical"></textarea>' +
      '<div style="display:flex;gap:6px;margin-top:8px">' +
      '<button id="fbgp-preview" style="flex:1;padding:8px;cursor:pointer">プレビュー投入</button>' +
      '<button id="fbgp-post" style="flex:1;padding:8px;cursor:pointer;background:#1877f2;color:#fff;border:none;border-radius:5px">投稿実行</button>' +
      "</div>" +
      '<div id="fbgp-log" style="margin-top:8px;font-size:12px;color:#444;white-space:pre-wrap;max-height:80px;overflow:auto"></div>' +
      "</div>";
    document.body.appendChild(wrap);

    const sel = wrap.querySelector("#fbgp-sel");
    const ta = wrap.querySelector("#fbgp-text");
    const logEl = wrap.querySelector("#fbgp-log");
    const log = (m) => {
      logEl.textContent = m;
    };

    posts.forEach((p, i) => {
      const o = document.createElement("option");
      o.value = String(i);
      o.textContent = p.title || "物件 " + (i + 1);
      sel.appendChild(o);
    });
    if (posts.length) ta.value = posts[0].body;
    sel.addEventListener("change", () => {
      const p = posts[Number(sel.value)];
      if (p) ta.value = p.body;
    });

    wrap.querySelector("#fbgp-min").addEventListener("click", () => {
      const b = wrap.querySelector("#fbgp-body");
      b.style.display = b.style.display === "none" ? "block" : "none";
    });

    wrap.querySelector("#fbgp-preview").addEventListener("click", async () => {
      try {
        await doPost(ta.value, { post: false, log });
      } catch (e) {
        log("⚠️ " + e.message);
      }
    });
    wrap.querySelector("#fbgp-post").addEventListener("click", async () => {
      if (!confirm("このグループに公開投稿します。よろしいですか？")) return;
      try {
        await doPost(ta.value, { post: true, log });
      } catch (e) {
        log("⚠️ " + e.message);
      }
    });
  }

  const iv = setInterval(() => {
    if (document.body) {
      clearInterval(iv);
      buildPanel();
    }
  }, 500);
})();

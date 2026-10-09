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
  function isInsideExistingPost(el) {
    if (!el) return false;
    if (el.closest('[role="article"]')) return true;
    if (el.closest('[aria-label*="コメント"], [aria-label*="Comment"], [aria-label*="返信"], [aria-label*="Reply"]')) return true;
    return false;
  }

  function findComposerTrigger() {
    // 新規スレッド作成用のトップレベルcomposerだけを許可する。
    // 「テキストを入力」はFacebookで新規投稿とコメントの両方に使われるため、
    // 既存投稿（role=article）やコメント／返信領域の内側にある要素は必ず除外する。
    const labels = [
      "テキストを入力",
      "その気持ち、シェアしよう",
      "何を考えていますか",
      "Write something",
      "What's on your mind",
      "投稿を作成",
      "Create post",
    ];
    const nodes = document.querySelectorAll('button, [role="button"], [aria-label]');
    for (const n of nodes) {
      const txt = ((n.getAttribute("aria-label") || "") + " " + (n.textContent || "")).trim();
      if (!txt || txt.length > 80) continue;
      if (!labels.some((label) => txt.includes(label))) continue;

      const clickable = n.closest('button, [role="button"]') || n;
      if (!clickable || clickable.offsetParent === null) continue;
      if (isInsideExistingPost(clickable)) continue;

      const lower = txt.toLowerCase();
      if (
        lower.includes("返信") ||
        lower.includes("コメント") ||
        lower.includes("reply") ||
        lower.includes("comment")
      ) {
        continue;
      }
      return clickable;
    }
    return null;
  }

  function isSafeNewThreadElement(el) {
    if (!el || el.offsetParent === null) return false;
    if (el.closest("#fbgp-panel")) return false;
    if (isInsideExistingPost(el)) return false;

    let node = el;
    for (let i = 0; i < 6 && node; i += 1, node = node.parentElement) {
      const aria = (node.getAttribute?.("aria-label") || "").toLowerCase();
      if (
        aria.includes("コメント") ||
        aria.includes("返信") ||
        aria.includes("comment") ||
        aria.includes("reply")
      ) {
        return false;
      }
    }
    return true;
  }

  function findDialogEditable() {
    // 1) 新規投稿モーダル型
    const dialogs = document.querySelectorAll('div[role="dialog"]');
    for (const dialog of dialogs) {
      if (!isSafeNewThreadElement(dialog)) continue;
      const dialogText = (dialog.textContent || "").trim();
      if (
        (dialogText.includes("コメント") || dialogText.includes("返信")) &&
        !dialogText.includes("投稿を作成")
      ) {
        continue;
      }
      const candidates = dialog.querySelectorAll(
        'div[role="textbox"][contenteditable="true"], div[contenteditable="true"]'
      );
      for (const el of candidates) {
        if (isSafeNewThreadElement(el)) return el;
      }
    }

    // 2) 新規投稿インライン型
    const candidates = document.querySelectorAll(
      'div[role="textbox"][contenteditable="true"], div[contenteditable="true"]'
    );
    for (const el of candidates) {
      if (isSafeNewThreadElement(el)) return el;
    }
    return null;
  }

  function findComposerScope(editable) {
    if (!editable || !isSafeNewThreadElement(editable)) return null;

    const dialog = editable.closest('div[role="dialog"]');
    if (dialog && isSafeNewThreadElement(dialog)) return dialog;

    let node = editable.parentElement;
    for (let depth = 0; depth < 8 && node && node !== document.body; depth += 1, node = node.parentElement) {
      if (!isSafeNewThreadElement(node)) return null;
      const buttons = node.querySelectorAll('div[role="button"], button, [aria-label]');
      for (const b of buttons) {
        const label = (b.getAttribute("aria-label") || b.textContent || "").trim();
        if (["投稿", "Post", "シェア", "Share"].includes(label)) {
          return node;
        }
      }
    }
    return null;
  }

  function findPostButton(editable) {
    const scope = findComposerScope(editable);
    if (!scope) return null;
    const btns = scope.querySelectorAll('div[role="button"], button, [aria-label]');
    for (const b of btns) {
      if (!isSafeNewThreadElement(b)) continue;
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

  async function reportStage(taskId, stage) {
    if (!taskId) return;
    try {
      await chrome.runtime.sendMessage({ type: "FB_BRIDGE_EVENT", taskId, stage });
    } catch (_) {}
  }

  async function reportResult(taskId, result) {
    if (!taskId) return;
    const response = await chrome.runtime.sendMessage({
      type: "FB_BRIDGE_RESULT",
      taskId,
      result,
    });
    if (!response?.ok) throw new Error(response?.error || "result_report_failed");
  }

  async function notifyTaskDone(taskId, detail = "") {
    try { await chrome.runtime.sendMessage({ type: "FB_TASK_DONE", taskId, detail }); } catch (_) {}
  }

  function decodeBase64File(payload, name) {
    const raw = atob(payload.base64 || "");
    const bytes = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
    return new File([bytes], name, { type: payload.type || "application/octet-stream" });
  }

  async function attachTaskImages(task, log, editable) {
    if (!task || !task.allow_images || !task.image_count) return;
    const scope = findComposerScope(editable);
    if (!scope) throw new Error("新規投稿composerの範囲を特定できません");

    let input = scope.querySelector('input[type="file"]');
    if (!input) {
      const labels = ["写真・動画", "写真/動画", "Photo/video", "Photo/Video"];
      const buttons = scope.querySelectorAll('[role="button"], button');
      for (const button of buttons) {
        if (!isSafeNewThreadElement(button)) continue;
        const label = (button.getAttribute("aria-label") || button.textContent || "").trim();
        if (labels.some((value) => label.includes(value))) {
          button.click();
          break;
        }
      }
      input = await waitFor(() => scope.querySelector('input[type="file"]'), { timeout: 5000 });
    }
    if (!input) throw new Error("新規投稿composer内に画像アップロード欄が見つかりません");
    const dt = new DataTransfer();
    for (let i = 0; i < task.image_count; i += 1) {
      const payload = await chrome.runtime.sendMessage({ type: "FETCH_IMAGE", taskId: task.task_id, index: i });
      if (!payload?.ok) throw new Error(payload?.error || `画像${i + 1}取得失敗`);
      dt.items.add(decodeBase64File(payload, `property-${i + 1}.jpg`));
    }
    input.files = dt.files;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    log(`画像 ${dt.files.length}件を添付`);
    await sleep(2500);
  }

  function loginLooksBroken() {
    const url = location.href.toLowerCase();
    if (url.includes("/login") || url.includes("checkpoint") || url.includes("recover")) return true;
    return Boolean(document.querySelector('input[name="email"], input[name="pass"]'));
  }

  function normalizeText(value) {
    return (value || "").replace(/\s+/g, "");
  }

  function findPermalinkForBody(body) {
    const needle = normalizeText(body).slice(0, 64);
    if (!needle) return null;
    const articles = document.querySelectorAll('[role="article"], div[data-pagelet*="FeedUnit"]');
    for (const article of articles) {
      if (!normalizeText(article.textContent).includes(needle)) continue;
      const links = article.querySelectorAll('a[href]');
      for (const link of links) {
        const href = link.href || "";
        if (/facebook\.com\/(groups\/[^/]+\/posts\/|permalink\.php|story\.php)/i.test(href)) return href;
      }
    }
    return null;
  }

  async function verifyPublished(body, timeout = 18000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const permalink = findPermalinkForBody(body);
      if (permalink) return permalink;
      await sleep(1200);
    }
    return null;
  }

  // ---- 投稿実行 -------------------------------------------------------------
  async function doPost(text, { post = false, log = console.log, task = null } = {}) {
    let clickStarted = false;
    if (loginLooksBroken()) throw new Error("SESSION_EXPIRED");

    // 必ずグループのトップへ戻してから新規スレッドcomposerを探す。
    // コメント/返信欄への誤投稿は安全のため禁止する。
    try {
      window.scrollTo({ top: 0, behavior: "instant" });
    } catch (_) {
      window.scrollTo(0, 0);
    }
    await sleep(900);

    log("新規スレッド作成欄を探索中...");
    const trigger = await waitFor(findComposerTrigger, { timeout: 10000 });
    if (!trigger) {
      throw new Error("新規スレッド作成欄が見つかりません。コメント/返信欄への投稿は禁止しています");
    }
    trigger.click();

    log("新規投稿本文欄を待機中...");
    const editable = await waitFor(findDialogEditable, { timeout: 10000 });
    if (!editable) throw new Error("安全な新規投稿本文欄が見つかりません");
    if (task?.task_id) await reportStage(task.task_id, "composer_ready");

    await sleep(400);
    log("本文を入力中...");
    insertTextReactSafe(editable, text);
    await sleep(800);
    await attachTaskImages(task, log, editable);

    if (!post) {
      log("✅ 下書き投入完了（プレビュー）。");
      return { status: "preview" };
    }

    log("「投稿」ボタン待機中...");
    const btn = await waitFor(() => findPostButton(editable), { timeout: 8000 });
    if (!btn) throw new Error("「投稿」ボタンが押せる状態になりません");
    if (task?.task_id) await reportStage(task.task_id, "click_started");
    clickStarted = true;
    btn.click();
    log("投稿クリック完了。公開確認中...");
    await sleep(3500);
    if (loginLooksBroken()) {
      const err = new Error("SESSION_EXPIRED");
      err.afterClick = clickStarted;
      throw err;
    }
    const permalink = await verifyPublished(text);
    if (permalink) {
      log("✅ 公開投稿を確認しました。");
      return { status: "posted", permalink };
    }
    log("⚠️ 公開投稿を確認できませんでした。");
    return { status: "uncertain", error: "permalink_not_found" };
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

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!["FB_AUTO_POST", "FB_SESSION_PROBE"].includes(message?.type)) return false;
    const task = message.task || {};
    sendResponse({ accepted: true });
    void (async () => {
      let result;
      try {
        if (loginLooksBroken()) {
          result = { status: "session_expired", error: "facebook_login_required" };
        } else if (message.type === "FB_SESSION_PROBE") {
          result = { status: "session_ok" };
        } else {
          result = await doPost(task.body || "", { post: true, log: console.log, task });
          result = result || { status: "uncertain", error: "empty_result" };
        }
      } catch (error) {
        const text = String(error?.message || error || "unknown error");
        if (text.includes("SESSION_EXPIRED")) result = { status: "session_expired", error: text };
        else if (error?.afterClick) result = { status: "failed_after_click", error: text };
        else result = { status: "failed_before_click", error: text };
      }
      try { await reportResult(task.task_id, result); } finally { await notifyTaskDone(task.task_id); }
    })();
    return false;
  });

  let assignedTaskRunning = false;
  async function runAssignedTask() {
    if (assignedTaskRunning) return;
    const match = location.hash.match(/(?:^#|[&#])fbautoposter_task=([^&]+)/);
    const taskId = document.documentElement.dataset.fbAutoposterTask || (match ? decodeURIComponent(match[1]) : "");
    if (!taskId) return;
    assignedTaskRunning = true;
    let task;
    try {
      const response = await chrome.runtime.sendMessage({
        type: "FB_BRIDGE_GET_TASK",
        taskId,
      });
      if (!response?.ok) throw new Error(response?.error || "task_fetch_failed");
      task = response.task;
      if (task.status === "finished") { await notifyTaskDone(taskId); return; }
      if (task.stage === "click_started") {
        await reportResult(taskId, { status: "uncertain", error: "resume_after_click_guard" });
        await notifyTaskDone(taskId);
        return;
      }
      let result;
      if (loginLooksBroken()) result = { status: "session_expired", error: "facebook_login_required" };
      else if (task.action === "probe") result = { status: "session_ok" };
      else {
        result = await doPost(task.body || "", { post: true, log: console.log, task });
        result = result || { status: "uncertain", error: "empty_result" };
      }
      await reportResult(taskId, result);
    } catch (error) {
      const text = String(error?.message || error || "unknown error");
      let status = "failed_before_click";
      if (text.includes("SESSION_EXPIRED")) status = "session_expired";
      else if (error?.afterClick) status = "failed_after_click";
      let detail = text;
      try {
        await reportResult(taskId, { status, error: text });
      } catch (reportError) {
        detail = text + " | report_result_error=" + String(reportError?.message || reportError);
      }
      try { delete document.documentElement.dataset.fbAutoposterTask; } catch (_) {}
      await notifyTaskDone(taskId, detail);
      assignedTaskRunning = false;
      return;
    } finally {
      if (assignedTaskRunning) {
        try { delete document.documentElement.dataset.fbAutoposterTask; } catch (_) {}
        await notifyTaskDone(taskId);
        assignedTaskRunning = false;
      }
    }
  }

  setInterval(() => {
    if (!document.body) return;
    if (!document.getElementById("fbgp-panel")) buildPanel();
    void runAssignedTask();
  }, 500);
})();

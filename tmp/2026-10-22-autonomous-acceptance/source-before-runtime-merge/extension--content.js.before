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

  function findPostButtonCandidate(editable) {
    const scope = findComposerScope(editable);
    if (!scope) return null;
    // Facebook often puts a non-matching aria-label on the native Post
    // button even though its visible text is exactly "投稿".
    const btns = scope.querySelectorAll('button, [role="button"], [aria-label]');
    for (const b of btns) {
      if (!isSafeNewThreadElement(b)) continue;
      const labels = [b.getAttribute("aria-label"), b.innerText, b.textContent]
        .map((v) => String(v || "").trim().replace(/\s+/g, " "));
      if (labels.some((label) => ["投稿", "Post", "シェア", "Share"].includes(label))) {
        const clickable = b.closest('button, [role="button"]') || b;
        if (isSafeNewThreadElement(clickable)) return clickable;
      }
    }
    return null;
  }
  function findPostButton(editable) {
    const button = findPostButtonCandidate(editable);
    if (!button) return null;
    const disabled = button.getAttribute("aria-disabled") === "true" ||
      button.hasAttribute("disabled") || button.disabled === true;
    return !disabled && button.offsetParent !== null ? button : null;
  }
  function describePostButton(editable) {
    const scope = findComposerScope(editable);
    const button = findPostButtonCandidate(editable);
    return [
      "scope=" + !!scope,
      "candidate=" + !!button,
      "enabled=" + !!findPostButton(editable),
      "aria_disabled=" + (button?.getAttribute("aria-disabled") || ""),
      "native_disabled=" + !!button?.disabled,
      "visible=" + !!(button && button.offsetParent !== null)
    ].join(" ");
  }

  // ---- 本文流し込み（Reactが拾う形）---------------------------------------
  function contentLines(value) {
    return String(value || "").split("\n").map((l) => l.trim()).filter(Boolean);
  }

  function clearEditable(editable) {
    editable.focus();
    document.execCommand("selectAll", false, null);
    document.execCommand("delete", false, null);
  }

  // Facebook's composer is a Lexical editor: execCommand("insertText") with
  // "\n" silently drops every line break, which produced unreadable one-block
  // posts. A synthetic paste carries text/plain with newlines, and Lexical
  // turns each line into its own paragraph.
  function insertByPaste(editable, text) {
    clearEditable(editable);
    const dt = new DataTransfer();
    dt.setData("text/plain", text);
    const ev = new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true });
    editable.dispatchEvent(ev);
  }

  function insertByParagraphs(editable, text) {
    clearEditable(editable);
    const lines = String(text).split("\n");
    lines.forEach((line, i) => {
      if (line) document.execCommand("insertText", false, line);
      if (i < lines.length - 1) document.execCommand("insertParagraph", false, null);
    });
  }

  function layoutPreserved(editable, text) {
    const want = contentLines(text);
    const got = contentLines(editable.innerText);
    const flat = (v) => String(v || "").replace(/\s+/g, "");
    // Every non-empty source line must survive as its own line, and the
    // characters must match (Facebook may wrap hashtags/links in spans).
    return got.length >= want.length && flat(editable.innerText).includes(flat(text).slice(0, 40));
  }

  async function insertTextReactSafe(editable, text, { requireActiveButton = false } = {}) {
    insertByPaste(editable, text);
    await sleep(650);
    const pasted = layoutPreserved(editable, text);
    // A synthetic paste may change the DOM while Lexical still thinks the
    // composer is empty. Verify Facebook's actual submit state, not DOM alone.
    if (pasted && (!requireActiveButton || findPostButton(editable))) return "paste";
    insertByParagraphs(editable, text);
    await sleep(750);
    const paragraphLayout = layoutPreserved(editable, text);
    if (paragraphLayout && (!requireActiveButton || findPostButton(editable))) {
      return "paragraphs";
    }
    const diag = describePostButton(editable);
    clearEditable(editable);
    if (!paragraphLayout) {
      throw new Error("LAYOUT_LOST: 改行が消えました [" + diag + "]");
    }
    throw new Error("COMPOSER_STATE_NOT_COMMITTED: 本文は表示されていますが投稿ボタンが無効 [" + diag + "]");
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

  const PERMALINK_RE = /facebook\.com\/(groups\/[^/]+\/(posts|permalink)\/|permalink\.php|story\.php)/i;

  function articlesForBody(body) {
    const needle = normalizeText(body).slice(0, 48);
    if (!needle) return [];
    const articles = document.querySelectorAll('[role="article"], div[data-pagelet*="FeedUnit"]');
    return [...articles].filter((a) => normalizeText(a.textContent).includes(needle));
  }

  function permalinkIn(article) {
    for (const link of article.querySelectorAll("a[href]")) {
      const href = link.href || "";
      if (PERMALINK_RE.test(href)) return href.split("?")[0];
    }
    return null;
  }

  // Facebook fills the timestamp link's real href only on hover/focus, so the
  // post was often live while we reported "permalink_not_found".
  function revealLinks(article) {
    for (const link of article.querySelectorAll("a")) {
      for (const type of ["mouseover", "mouseenter", "focus", "focusin"]) {
        try {
          link.dispatchEvent(new MouseEvent(type, { bubbles: type !== "mouseenter", cancelable: true, view: window }));
        } catch (_) {}
      }
    }
  }

  function findPermalinkForBody(body) {
    for (const article of articlesForBody(body)) {
      const direct = permalinkIn(article);
      if (direct) return direct;
      revealLinks(article);
    }
    return null;
  }

  function pendingApprovalVisible() {
    const text = document.body?.innerText || "";
    return /(管理者の承認|承認待ち|承認されると|pending approval|submitted for approval)/i.test(text);
  }

  function jsonEscapeAscii(value) {
    return JSON.stringify(value).slice(1, -1).replace(/[\u007f-\uffff]/g,
      (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  }

  // Server-side lookup that does not depend on the (lazy, ranked) feed: the
  // group's "your posts" pages embed each post's text and id in page data.
  async function lookupOwnPost(body, groupId) {
    const lines = String(body || "").split("\n").map((l) => l.trim()).filter((l) => l.length >= 8);
    const probes = lines.slice(1, 4).map((l) => l.slice(0, 18));
    const diag = [];
    for (const kind of ["my_posted_content", "my_pending_content"]) {
      try {
        const res = await fetch(`/groups/${groupId}/${kind}`, { credentials: "include" });
        const html = await res.text();
        let idx = -1;
        for (const probe of probes) {
          for (const form of [probe, jsonEscapeAscii(probe)]) {
            idx = html.indexOf(form);
            if (idx >= 0) break;
          }
          if (idx >= 0) break;
        }
        diag.push(`${kind}:${res.status}:${html.length}:${idx >= 0 ? "hit" : "miss"}`);
        if (idx < 0) continue;
        if (kind === "my_pending_content") return { pendingApproval: true, diag };
        const windowText = html.slice(Math.max(0, idx - 20000), idx + 20000);
        const m = windowText.match(new RegExp(`groups(?:\\\\)?/${groupId}(?:\\\\)?/(?:posts|permalink)(?:\\\\)?/(\\d{6,})`))
          || windowText.match(/"post_id":"(\d{6,})"/) || windowText.match(/"story_fbid":"?(\d{6,})/);
        if (m) return { permalink: `https://www.facebook.com/groups/${groupId}/posts/${m[1]}/`, diag };
        return { foundArticle: true, diag };
      } catch (error) {
        diag.push(`${kind}:error:${String(error).slice(0, 60)}`);
      }
    }
    return { diag };
  }

  async function verifyPublished(body, timeout = 30000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const permalink = findPermalinkForBody(body);
      if (permalink) return { permalink };
      await sleep(1200);
    }
    if (pendingApprovalVisible()) return { pendingApproval: true };
    return { foundArticle: articlesForBody(body).length > 0 };
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
    const insertMode = await insertTextReactSafe(editable, text, { requireActiveButton: post || task?.action === "layout_check" });
    log(`本文入力方式: ${insertMode} [${describePostButton(editable)}]`);
    await sleep(800);
    await attachTaskImages(task, log, editable);

    if (!post) {
      const lines = contentLines(editable.innerText).length;
      const expected = contentLines(text).length;
      log(`✅ 下書き投入完了（プレビュー）。行数 ${lines}/${expected}`);
      const buttonDiagnostics = describePostButton(editable);
      if (task?.action === "layout_check") {
        // Leave nothing behind: empty the composer so closing it never prompts.
        clearEditable(editable);
        await sleep(300);
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      }
      return { status: "layout_ok", error: `mode=${insertMode} lines=${lines}/${expected} button=${buttonDiagnostics}` };
    }

    log("「投稿」ボタン待機中...");
    const btn = await waitFor(() => findPostButton(editable), { timeout: 8000 });
    if (!btn) throw new Error("「投稿」ボタンが押せる状態になりません [" + describePostButton(editable) + "]");
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
    const verified = await verifyPublished(text);
    if (verified.permalink) {
      log("✅ 公開投稿を確認しました。");
      return { status: "posted", permalink: verified.permalink };
    }
    log("⚠️ 公開投稿を確認できませんでした。");
    if (verified.pendingApproval) return { status: "uncertain", error: "pending_admin_approval" };
    const diag = verified.diag ? ` [${verified.diag.join(" ")}]` : "";
    return { status: "uncertain", error: (verified.foundArticle ? "article_visible_permalink_hidden" : "permalink_not_found") + diag };
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
      else if (task.action === "find_post") {
        const own = await lookupOwnPost(task.body || "", String(task.group_id || ""));
        result = own.permalink ? { status: "posted", permalink: own.permalink }
          : { status: "uncertain", error: (own.pendingApproval ? "pending_admin_approval " : "not_found ") + (own.diag || []).join(" ") };
      }
      else if (task.action === "layout_check") {
        result = await doPost(task.body || "", { post: false, log: console.log, task });
      } else {
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

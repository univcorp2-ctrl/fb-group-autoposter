const BRIDGE = "http://127.0.0.1:8766";
const ACTIVE_KEY = "fbAutoposterActiveTask";

const BRIDGE_TIMEOUT_MS = 15000;
const ACTIVE_MAX_AGE_MS = 20 * 60 * 1000;
const POLL_LOCK_MAX_MS = 90000;

class BridgeHttpError extends Error {
  constructor(path, status) {
    super(`bridge ${path} HTTP ${status}`);
    this.status = status;
  }
}

async function bridgeJson(path, options = {}) {
  // A hung localhost request used to keep `polling` true forever, silently
  // stopping every later alarm tick. Every bridge call is now bounded.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), BRIDGE_TIMEOUT_MS);
  try {
    const res = await fetch(BRIDGE + path, {
      cache: "no-store",
      ...options,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    if (res.status === 204) return null;
    if (!res.ok) throw new BridgeHttpError(path, res.status);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function heartbeat(reason) {
  try {
    const v = chrome.runtime.getManifest().version;
    await fetch(`${BRIDGE}/hello?v=${encodeURIComponent(v)}&reason=${encodeURIComponent(reason)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
  } catch (_) {}
}

async function postEvent(taskId, stage) {
  return bridgeJson("/event", {
    method: "POST",
    body: JSON.stringify({ task_id: taskId, stage }),
  });
}

async function postResult(taskId, result) {
  return bridgeJson("/result", {
    method: "POST",
    body: JSON.stringify({ task_id: taskId, ...result }),
  });
}
async function getActive() {
  const data = await chrome.storage.local.get(ACTIVE_KEY);
  return data[ACTIVE_KEY] || null;
}

async function setActive(state) {
  await chrome.storage.local.set({ [ACTIVE_KEY]: state });
}

async function clearActive() {
  await chrome.storage.local.remove(ACTIVE_KEY);
}

async function fetchImage(taskId, index) {
  const res = await fetch(`${BRIDGE}/image/${encodeURIComponent(taskId)}/${index}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`image HTTP ${res.status}`);
  const buf = await res.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return { base64: btoa(binary), type: res.headers.get("content-type") || "application/octet-stream" };
}

async function cleanupActive(state) {
  try {
    const tab = await chrome.tabs.get(state.tabId);
    const marker = `fbautoposter_task=${encodeURIComponent(state.taskId || "")}`;
    if ((tab?.url || "").includes(marker)) {
      await chrome.tabs.remove(state.tabId);
    }
  } catch (_) {}
  await clearActive();
}
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "FETCH_IMAGE") {
    fetchImage(message.taskId, message.index)
      .then((data) => sendResponse({ ok: true, ...data }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }
  if (message?.type === "FB_BRIDGE_GET_TASK") {
    bridgeJson(`/task/${encodeURIComponent(message.taskId)}`)
      .then((task) => sendResponse({ ok: true, task }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }
  if (message?.type === "FB_BRIDGE_EVENT") {
    postEvent(message.taskId, message.stage)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }
  if (message?.type === "FB_BRIDGE_RESULT") {
    postResult(message.taskId, message.result || {})
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }
  if (message?.type === "FB_TASK_DONE") {
    void (async () => {
      const state = await getActive();
      if (state?.taskId === message.taskId) {
        try {
          const status = await bridgeJson(`/status/${encodeURIComponent(message.taskId)}`);
          if (status?.status !== "finished") {
            await postResult(message.taskId, {
              status: status?.stage === "click_started" ? "uncertain" : "failed_before_click",
              error: String(message.detail || "content_done_without_result"),
            });
          }
        } catch (_) {}
        await cleanupActive(state);
        await runOneTask();
      }
    })().catch(recordBackgroundError);
    sendResponse({ ok: true });
    return false;
  }
  return false;
});

async function resumeActive() {
  const state = await getActive();
  if (!state) return false;
  let status;
  try {
    status = await bridgeJson(`/status/${encodeURIComponent(state.taskId)}`);
  } catch (error) {
    await chrome.storage.local.set({ fbAutoposterBridgeError: String(error?.message || error) });
    if (error?.status === 404) {
      // The bridge no longer knows this task (archived/cleaned). Holding it
      // forever blocked /next permanently; the bridge never replays it.
      await cleanupActive(state);
      return false;
    }
    if (Date.now() - Number(state.openedAt || 0) > ACTIVE_MAX_AGE_MS) {
      await cleanupActive(state);
      return false;
    }
    return true; // Keep ownership while offline; never orphan or replay an unknown task.
  }
  if (status?.status !== "finished" && Date.now() - Number(state.openedAt || 0) > ACTIVE_MAX_AGE_MS) {
    // Bridge lease (15 min) has already expired this task; free the slot.
    await cleanupActive(state);
    return false;
  }
  try {
    if (status?.status === "finished") {
      await cleanupActive(state);
      return false;
    }
    await chrome.tabs.get(state.tabId);
    return true;
  } catch (_) {
    await clearActive();
    return false;
  }
}
async function markTask(tabId) {
  const state = await getActive();
  if (!state || state.tabId !== tabId) return;
  await chrome.scripting.executeScript({
    target: { tabId },
    func: (taskId) => {
      document.documentElement.dataset.fbAutoposterTask = taskId;
    },
    args: [state.taskId],
  });
}

let polling = false;
let pollingSince = 0;
let nextPollAt = 0;
let bridgeFailures = 0;

async function recordBackgroundError(error) {
  try {
    await chrome.storage.local.set({ fbAutoposterBridgeError: String(error?.message || error), fbAutoposterBridgeErrorAt: Date.now() });
  } catch (_) {}
}

async function runOneTask() {
  if (polling && Date.now() - pollingSince > POLL_LOCK_MAX_MS) polling = false;
  if (polling || Date.now() < nextPollAt) return;
  polling = true;
  pollingSince = Date.now();
  try {
    await dispatchOneTask();
    bridgeFailures = 0;
  } catch (error) {
    bridgeFailures += 1;
    nextPollAt = Date.now() + Math.min(300000, 30000 * (2 ** Math.min(bridgeFailures-1, 4)));
    await recordBackgroundError(error);
  } finally {
    polling = false;
  }
}

async function dispatchOneTask() {
  if (await resumeActive()) return;
  const task = await bridgeJson("/next");
  await chrome.storage.local.set({ fbAutoposterBridgeError: "", fbAutoposterBridgeHealthyAt: Date.now() });
  if (!task) return;
  const marker = `fbautoposter_task=${encodeURIComponent(task.task_id)}`;
  const sep = task.group_url.includes("#") ? "&" : "#";
  const tab = await chrome.tabs.create({ url: `${task.group_url}${sep}${marker}`, active: false });
  await setActive({ taskId: task.task_id, tabId: tab.id, openedAt: Date.now() });
  await postEvent(task.task_id, "tab_opened");
  try {
    const current = await chrome.tabs.get(tab.id);
    if (current?.status === "complete") await markTask(tab.id);
  } catch (_) {}
}

chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.status === "complete") void markTask(tabId).catch(recordBackgroundError);
});

chrome.tabs.onRemoved.addListener((tabId) => {
  void (async () => {
    const state = await getActive();
    if (!state || state.tabId !== tabId) return;
    try {
      const status = await bridgeJson(`/status/${encodeURIComponent(state.taskId)}`);
      if (status?.status !== "finished") {
        await postResult(state.taskId, {
          status: status?.stage === "click_started" ? "uncertain" : "failed_before_click",
          error: "task tab was closed",
        });
      }
    } catch (_) {}
    await clearActive();
  })().catch(recordBackgroundError);
});

async function arm(reason = "wake") {
  void heartbeat(reason);
  const existing = await chrome.alarms.get("fb-autoposter-poll");
  if (!existing || reason === "installed" || reason === "startup") {
    await chrome.alarms.clear("fb-autoposter-poll");
    await chrome.alarms.create("fb-autoposter-poll", { periodInMinutes: 1, delayInMinutes: 0.5 });
  }
  await runOneTask();
}

chrome.runtime.onInstalled.addListener(() => { void arm("installed").catch(recordBackgroundError); });
chrome.runtime.onStartup.addListener(() => { void arm("startup").catch(recordBackgroundError); });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== "fb-autoposter-poll") return;
  void heartbeat(polling ? "alarm-busy" : "alarm");
  void runOneTask();
});
void arm("wake").catch(recordBackgroundError);

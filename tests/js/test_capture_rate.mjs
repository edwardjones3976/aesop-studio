import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const bgPath = path.join(repoRoot, "extension", "background.js");
const popupPath = path.join(repoRoot, "extension", "popup.js");

const EXT_ID = "aesop-bridge-ext-test-id";
const SAMPLE_PNG_B64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
const SAMPLE_DATA_URL = `data:image/png;base64,${SAMPLE_PNG_B64}`;

let captureCallTimestamps = [];
let captureDelayMs = 20;
let enforceStrictQuota = false;
let forceNextCaptureError = null;
let onMidCaptureHook = null;
let currentTab = {
  id: 42,
  windowId: 1,
  title: "Releases · microsoft/vscode",
  url: "https://github.com/microsoft/vscode/releases",
  active: true,
  status: "complete",
};
let tabUpdateCalls = [];
let mockPageScriptResult = null;

let cmdQueue = [];
let replyResolvers = new Map();
let recordedPushes = [];
let pushWaiters = [];
let pollFailCount = 0;
let capturePngQueue = null;
let forceNextPushError = null;
let pushHoldMs = 0;
let emptyCapturesRemaining = 0;

function recordPush(body) {
  const entry = { at: Date.now(), body };
  recordedPushes.push(entry);
  const waiters = pushWaiters.splice(0, pushWaiters.length);
  for (const w of waiters) w(entry);
}

globalThis.chrome = {
  runtime: {
    id: EXT_ID,
    onMessage: { addListener() {} },
  },
  storage: {
    local: {
      get(_keys, cb) {
        cb({});
      },
      set() {},
    },
  },
  alarms: {
    create() {},
    onAlarm: { addListener() {} },
  },
  tabs: {
    onUpdated: { addListener() {}, removeListener() {} },
    onActivated: { addListener() {} },
    async query() {
      return [{ ...currentTab }];
    },
    async get(id) {
      return { ...currentTab, id };
    },
    async update(id, props) {
      tabUpdateCalls.push({ id, props });
      if (props && props.active) {
        currentTab = { ...currentTab, active: true };
      }
      if (props && props.url) {
        currentTab = { ...currentTab, url: props.url, status: "complete" };
      }
      return { ...currentTab, id };
    },
    async captureVisibleTab() {
      const now = Date.now();
      captureCallTimestamps.push(now);
      if (emptyCapturesRemaining > 0) {
        emptyCapturesRemaining -= 1;
        return "";
      }
      if (!currentTab.active) {
        return "";
      }
      if (typeof onMidCaptureHook === "function") {
        const hook = onMidCaptureHook;
        onMidCaptureHook = null;
        hook();
      }
      if (forceNextCaptureError) {
        const err = forceNextCaptureError;
        forceNextCaptureError = null;
        throw new Error(err);
      }
      if (enforceStrictQuota) {
        const recent = captureCallTimestamps.filter((t) => now - t < 980);
        if (recent.length > 2) {
          throw new Error("This request exceeds the MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND quota.");
        }
      }
      await new Promise((r) => setTimeout(r, captureDelayMs));
      if (Array.isArray(capturePngQueue) && capturePngQueue.length) {
        const b64 = capturePngQueue.shift();
        if (!b64) return "";
        return `data:image/png;base64,${b64}`;
      }
      return SAMPLE_DATA_URL;
    },
  },
  scripting: {
    async executeScript({ func, args }) {
      if (typeof mockPageScriptResult === "function") {
        return [{ result: mockPageScriptResult(func, args) }];
      }
      return [
        {
          result: {
            ok: true,
            url: currentTab.url,
            title: currentTab.title,
            vw: 1366,
            vh: 854,
            elements: [],
            headings: [],
            links: [],
            forms: [],
            text: "sample text",
            main_text: "sample text",
          },
        },
      ];
    },
  },
  action: {
    setBadgeText() {},
    setBadgeBackgroundColor() {},
  },
  notifications: {
    create() {},
    clear() {},
    onButtonClicked: { addListener() {} },
  },
};

const bgCode = fs.readFileSync(bgPath, "utf-8");
vm.runInThisContext(bgCode, { filename: bgPath });

const {
  state,
  MIN_CAPTURE_INTERVAL_MS,
  RETRY_BACKOFF_MS,
  POLL_NETWORK_RESET_MS,
  kickFrameLoop,
  resetCaptureState,
  executeCommand,
  startBridgeLoop,
  pageScript,
  setStudioFetch,
} = globalThis.__aesopBridgeTest;

setStudioFetch(async (urlPath, _method = "GET", body = null) => {
  const u = String(urlPath);
  if (u.includes("/api/browser/bridge/poll")) {
    if (pollFailCount > 0) {
      pollFailCount -= 1;
      throw new Error("Simulated transient network failure");
    }
    const nextCmd = cmdQueue.shift() || null;
    if (!nextCmd) {
      await new Promise((r) => setTimeout(r, 10));
    }
    return { ok: true, cmd: nextCmd };
  }
  if (u.includes("/api/browser/bridge/push")) {
    if (forceNextPushError) {
      const err = forceNextPushError;
      forceNextPushError = null;
      throw new Error(err);
    }
    if (pushHoldMs > 0) {
      await new Promise((r) => setTimeout(r, pushHoldMs));
    }
    recordPush(body || {});
    const fseq = body && body.frame_seq != null ? body.frame_seq : recordedPushes.length;
    return { ok: true, frame_seq: fseq };
  }
  if (u.includes("/api/browser/bridge/reply")) {
    const res = (body && body.result) || {};
    const resolver = replyResolvers.get(body.cmd_id);
    if (resolver) {
      replyResolvers.delete(body.cmd_id);
      resolver(res);
    }
    return { ok: true };
  }
  return { ok: true };
});

assert.ok(MIN_CAPTURE_INTERVAL_MS >= 500, "MIN_CAPTURE_INTERVAL_MS must respect Chrome ~2/s capture limit");
assert.ok(RETRY_BACKOFF_MS >= 100 && RETRY_BACKOFF_MS <= 250, "RETRY_BACKOFF_MS must be brief (100-250ms)");

function assertMaxTwoCapturesPerSecond(timestamps) {
  for (let i = 0; i < timestamps.length; i++) {
    const winStart = timestamps[i];
    const inOneSec = timestamps.filter((t) => t >= winStart && t < winStart + 980);
    assert.ok(
      inOneSec.length <= 2,
      `captureVisibleTab called ${inOneSec.length} times within 1s window starting at ${winStart}`
    );
  }
}

// 1. Push transport (data lane): mock server holds each push 300 ms; 10 actions 200 ms apart must ack <= 100 ms;
// new frames arrive via push png >= 9/10 within 1 s; captures <= 2/s; png at most once per frame_seq.
{
  resetCaptureState();
  captureCallTimestamps = [];
  recordedPushes = [];
  pushWaiters = [];
  pushHoldMs = 300;
  captureDelayMs = 20;
  enforceStrictQuota = true;
  emptyCapturesRemaining = 0;
  currentTab = { ...currentTab, active: true };
  state.confirmed = true;
  state.token = "tok_test_rate_1234567890";
  state.port = 8770;
  state.paired = true;
  state.lastError = "";
  state.captureError = "";

  let framesViaPushWithin1s = 0;

  for (let i = 1; i <= 10; i++) {
    const seqBefore =
      recordedPushes.length > 0
        ? Math.max(...recordedPushes.map((p) => (p.body && p.body.frame_seq) || 0))
        : 0;
    const t0 = Date.now();
    const out = await executeCommand({ op: "scroll", dy: 350 });
    const ackMs = Date.now() - t0;
    assert.equal(out.ok, true);
    assert.equal(out.png, undefined, "command reply must never include a png");
    assert.ok(ackMs <= 100, `action ${i} reply must resolve within 100ms, took ${ackMs}ms`);

    let pushed = null;
    const deadline = t0 + 1000;
    while (Date.now() < deadline) {
      await kickFrameLoop();
      const hit = recordedPushes.find(
        (p) =>
          p.body &&
          p.body.png === SAMPLE_PNG_B64 &&
          (p.body.frame_seq || 0) > seqBefore &&
          p.at >= t0 - 50
      );
      if (hit) {
        pushed = hit;
        break;
      }
      await new Promise((r) => setTimeout(r, 25));
    }
    if (pushed) {
      framesViaPushWithin1s += 1;
      assert.ok(Date.now() - t0 <= 1000, `action ${i} frame push must land within 1000ms`);
    }

    if (i < 10) {
      await new Promise((r) => setTimeout(r, 200));
    }
  }

  assert.ok(
    framesViaPushWithin1s >= 9,
    `expected >= 9 frame pushes with png within 1s of action, got ${framesViaPushWithin1s}`
  );
  const pngSeqSeen = new Set();
  for (const p of recordedPushes) {
    const seq = p.body && p.body.frame_seq;
    if (p.body && p.body.png) {
      assert.ok(
        !pngSeqSeen.has(seq),
        `push must include png at most once per frame_seq (duplicate seq ${seq})`
      );
      pngSeqSeen.add(seq);
    }
  }
  assertMaxTwoCapturesPerSecond(captureCallTimestamps);

  const capsBeforeFrameOnly = captureCallTimestamps.length;
  const frameOnly = await executeCommand({ op: "frame" });
  assert.equal(frameOnly.png, SAMPLE_PNG_B64);
  assert.equal(
    captureCallTimestamps.length,
    capsBeforeFrameOnly,
    "frame op must return cached png without captureVisibleTab"
  );

  pushHoldMs = 0;
}

// 1b. Background-tab capture: empty captureVisibleTab sets captureError; loop activates tab once; clears on success.
{
  resetCaptureState();
  captureCallTimestamps = [];
  recordedPushes = [];
  tabUpdateCalls = [];
  emptyCapturesRemaining = 1;
  currentTab = {
    id: 42,
    windowId: 1,
    title: "Releases · microsoft/vscode",
    url: "https://github.com/microsoft/vscode/releases",
    active: false,
    status: "complete",
  };
  state.confirmed = true;
  state.token = "tok_test_rate_1234567890";
  state.port = 8770;
  state.paired = true;
  state.captureError = "";

  globalThis.__aesopBridgeTest.frameDirty = true;
  await kickFrameLoop();
  assert.equal(state.captureError, "Live view paused: bring the Chrome tab to front");
  assert.equal(
    tabUpdateCalls.filter((c) => c.props && c.props.active).length,
    1,
    "frame loop must activate the target tab once before retrying capture"
  );

  globalThis.__aesopBridgeTest.frameDirty = true;
  await kickFrameLoop();
  assert.equal(state.captureError, "");
  const withPng = recordedPushes.find((p) => p.body && p.body.png);
  assert.ok(withPng, "successful capture after activation must push png");
  emptyCapturesRemaining = 0;
  currentTab = { ...currentTab, active: true };
}

// 2. (iv) A capture that throws sets state.captureError (NOT state.lastError), exposes captureError in push & popup,
// maps unfocused/invisible window errors to "Live view paused: bring the Chrome window to front", and never stalls replies.
{
  resetCaptureState();
  captureCallTimestamps = [];
  recordedPushes = [];
  pushWaiters = [];
  enforceStrictQuota = false;
  state.confirmed = true;
  state.token = "tok_test_rate_1234567890";
  state.port = 8770;
  state.paired = true;
  state.lastError = "";
  state.captureError = "";

  // Case A: Window not visible/focused -> friendly pause message in state.captureError
  forceNextCaptureError = "Failed to capture tab: window is not visible or focused";
  const t0 = Date.now();
  const out = await executeCommand({ op: "scroll", dy: 400 });
  const elapsedAck = Date.now() - t0;
  assert.equal(out.ok, true);
  assert.ok(elapsedAck <= 100, `capture error must never delay command ack (took ${elapsedAck}ms)`);

  await globalThis.__aesopBridgeTest.kickFrameLoop();
  assert.equal(state.captureError, "Live view paused: bring the Chrome window to front");
  assert.equal(state.lastError, "", "capture failure must go into state.captureError, NOT state.lastError");
  assert.ok(recordedPushes.length >= 1, "push payload should still be sent with captureError");
  assert.equal(
    recordedPushes[recordedPushes.length - 1].body.captureError,
    "Live view paused: bring the Chrome window to front"
  );

  // Verify popup.js surfaces state.captureError when paired
  const popupElements = {
    dot: { className: "" },
    statusTitle: { textContent: "" },
    statusNote: { textContent: "" },
    confirmBox: { hidden: true },
    confirmPrompt: { textContent: "" },
    confirmApproveBtn: { addEventListener() {} },
    confirmRejectBtn: { addEventListener() {} },
    useTabBtn: { addEventListener() {} },
    pairBtn: { addEventListener() {} },
  };
  const popupCtx = vm.createContext({
    document: {
      getElementById(id) {
        return popupElements[id];
      },
    },
    chrome: {
      runtime: {
        sendMessage(_msg, cb) {
          if (cb)
            cb({
              paired: true,
              port: 8770,
              lastError: state.lastError,
              captureError: state.captureError,
            });
        },
      },
      tabs: {
        async query() {
          return [];
        },
      },
    },
  });
  const popupCode = fs.readFileSync(popupPath, "utf-8");
  vm.runInContext(popupCode, popupCtx, { filename: popupPath });
  assert.equal(popupElements.statusNote.textContent, "Live view paused: bring the Chrome window to front");

  // Case B: Push failure also goes into state.captureError (not state.lastError)
  resetCaptureState();
  forceNextPushError = "Push HTTP 503";
  await executeCommand({ op: "scroll", dy: 200 });
  await globalThis.__aesopBridgeTest.kickFrameLoop();
  assert.equal(state.captureError, "Push HTTP 503");
  assert.equal(state.lastError, "");
}

// 3. (v) A dirty flag set mid-capture produces exactly one more capture and settles cleanly.
{
  resetCaptureState();
  captureCallTimestamps = [];
  recordedPushes = [];
  pushWaiters = [];
  captureDelayMs = 30;
  enforceStrictQuota = true;
  state.confirmed = true;
  state.token = "tok_test_rate_1234567890";
  state.port = 8770;
  state.paired = true;

  // Set frameDirty = true mid-capture during the first captureVisibleTab call
  onMidCaptureHook = () => {
    globalThis.__aesopBridgeTest.frameDirty = true;
    kickFrameLoop();
  };

  globalThis.__aesopBridgeTest.frameDirty = true;
  await kickFrameLoop();

  assert.equal(
    captureCallTimestamps.length,
    2,
    `dirty flag set mid-capture must produce exactly 1 follow-up capture (total 2), got ${captureCallTimestamps.length}`
  );
  const gap = captureCallTimestamps[1] - captureCallTimestamps[0];
  assert.ok(
    gap >= MIN_CAPTURE_INTERVAL_MS - 15,
    `second capture must wait for ${MIN_CAPTURE_INTERVAL_MS}ms interval, got ${gap}ms`
  );
  assert.equal(globalThis.__aesopBridgeTest.frameDirty, false, "frameDirty must be false after loop settles");
}

// 4. Part B: click_ref clears stale off-viewport refs, activates inner/outer <a href>, and falls back to navigating to href
{
  const makeEl = ({ tag = "DIV", role = "", text = "", href = "", top = 100, left = 50, w = 120, h = 28, parentA = null, childA = null }) => {
    const attrs = new Map();
    if (role) attrs.set("role", role);
    if (href && tag === "A") attrs.set("href", href);
    const el = {
      tagName: tag,
      innerText: text,
      value: "",
      type: "",
      href: tag === "A" ? href : "",
      clicked: 0,
      getAttribute(k) {
        return attrs.has(k) ? attrs.get(k) : null;
      },
      setAttribute(k, v) {
        attrs.set(k, String(v));
      },
      removeAttribute(k) {
        attrs.delete(k);
      },
      getBoundingClientRect() {
        return { top, left, bottom: top + h, right: left + w, width: w, height: h };
      },
      closest(sel) {
        if (sel === "a[href]") return parentA;
        return null;
      },
      querySelector(sel) {
        if (sel === "a[href]") return childA;
        return null;
      },
      scrollIntoView() {},
      focus() {},
      dispatchEvent() {},
      click() {
        this.clicked += 1;
      },
    };
    return el;
  };

  const staleLink = makeEl({
    tag: "A",
    text: "Old Top Link",
    href: "https://github.com/microsoft/vscode/Old",
    top: -600,
  });
  staleLink.setAttribute("data-aesop-ref", "1");

  const releaseAnchor = makeEl({
    tag: "A",
    text: "1.143.1",
    href: "https://github.com/microsoft/vscode/releases/tag/1.143.1",
    top: 180,
  });
  const latestWrapper = makeEl({
    tag: "SPAN",
    role: "link",
    text: "Latest",
    top: 180,
    parentA: releaseAnchor,
  });

  const allInteractive = [staleLink, latestWrapper];

  const prevWindow = globalThis.window;
  const prevDocument = globalThis.document;
  const prevCSS = globalThis.CSS;
  try {
    globalThis.CSS = { escape: (s) => String(s) };
    globalThis.window = {
      innerWidth: 1366,
      innerHeight: 854,
      scrollY: 800,
      location: { href: "https://github.com/microsoft/vscode/releases" },
      getComputedStyle() {
        return { display: "block", visibility: "visible", opacity: "1" };
      },
    };
    globalThis.document = {
      title: "Releases · microsoft/vscode",
      documentElement: { scrollHeight: 2400 },
      body: { innerText: "Releases 1.143.1 Latest" },
      querySelectorAll(sel) {
        if (sel === "[data-aesop-ref]") {
          return allInteractive.filter((n) => n.getAttribute("data-aesop-ref") !== null);
        }
        if (sel === "h1, h2, h3, h4" || sel === "form") return [];
        if (sel === "a[href]") return [staleLink, releaseAnchor];
        return allInteractive;
      },
      querySelector(sel) {
        const m = String(sel).match(/^\[data-aesop-ref="(\d+)"\]$/);
        if (m) {
          return allInteractive.find((n) => n.getAttribute("data-aesop-ref") === m[1]) || null;
        }
        return this.body;
      },
    };

    const snap = pageScript({ op: "snapshot" });
    assert.equal(staleLink.getAttribute("data-aesop-ref"), null, "off-viewport stale ref must be cleared");
    assert.equal(snap.elements.length, 1);
    assert.equal(snap.elements[0].ref, 1);
    assert.equal(
      snap.elements[0].href,
      "https://github.com/microsoft/vscode/releases/tag/1.143.1",
      "wrapper inside <a href> must inherit resolved anchor href"
    );

    const clickOut = pageScript({ op: "click_ref", ref: 1 });
    assert.equal(clickOut.ok, true);
    assert.equal(releaseAnchor.clicked, 1, "click_ref on wrapper must activate the underlying <a> element");
    assert.equal(clickOut.clicked_href, "https://github.com/microsoft/vscode/releases/tag/1.143.1");

    // Verify executeCommand falls back to navigating to clicked_href when .click() leaves tab URL unchanged
    currentTab = {
      id: 42,
      windowId: 1,
      title: "Releases · microsoft/vscode",
      url: "https://github.com/microsoft/vscode/releases",
      active: true,
      status: "complete",
    };
    tabUpdateCalls = [];
    mockPageScriptResult = (_fn, [arg]) => {
      if (arg.op === "click_ref") {
        return {
          ok: true,
          url: currentTab.url,
          title: currentTab.title,
          clicked_href: "https://github.com/microsoft/vscode/releases/tag/1.143.1",
          pre_click_url: "https://github.com/microsoft/vscode/releases",
          elements: [],
        };
      }
      return {
        ok: true,
        url: currentTab.url,
        title: "Release 1.143.1 · microsoft/vscode",
        elements: [],
      };
    };

    const navResult = await executeCommand({ op: "click_ref", ref: 24 });
    assert.equal(navResult.ok, true);
    assert.equal(
      tabUpdateCalls.length,
      1,
      "executeCommand must fall back to chrome.tabs.update when click_ref on a link does not navigate"
    );
    assert.equal(tabUpdateCalls[0].props.url, "https://github.com/microsoft/vscode/releases/tag/1.143.1");
    assert.equal(navResult.url, "https://github.com/microsoft/vscode/releases/tag/1.143.1");
  } finally {
    globalThis.window = prevWindow;
    globalThis.document = prevDocument;
    globalThis.CSS = prevCSS;
    mockPageScriptResult = null;
  }
}

// 5. Real frame loop: captureVisibleTab supplies the png. No writes to latestFrame.
{
  const PNG_B = SAMPLE_PNG_B64.replace(/A/g, "B");
  assert.notEqual(PNG_B, SAMPLE_PNG_B64);
  resetCaptureState();
  captureCallTimestamps = [];
  recordedPushes = [];
  pushWaiters = [];
  capturePngQueue = [SAMPLE_PNG_B64, PNG_B, ""];
  captureDelayMs = 0;
  enforceStrictQuota = false;
  emptyCapturesRemaining = 0;
  pushHoldMs = 0;
  forceNextCaptureError = null;
  currentTab = {
    id: 42,
    windowId: 1,
    title: "Releases · microsoft/vscode",
    url: "https://github.com/microsoft/vscode/releases",
    active: true,
    status: "complete",
  };
  state.confirmed = true;
  state.token = "tok_test_rate_1234567890";
  state.port = 8770;
  state.paired = true;
  state.polling = false;
  state.lastError = "";
  state.captureError = "";

  globalThis.__aesopBridgeTest.frameDirty = true;
  await kickFrameLoop();
  assert.equal(recordedPushes.length, 1, "one kick must produce one push");
  assert.equal(recordedPushes[0].body.frame_seq, 1);
  assert.ok(recordedPushes[0].body.png && recordedPushes[0].body.png.length > 0);
  assert.equal(recordedPushes[0].body.png, SAMPLE_PNG_B64);

  const beforeSecond = recordedPushes.length;
  const second = await executeCommand({ op: "scroll", dy: 350 });
  assert.equal(second.ok, true);
  assert.equal(second.png, undefined, "command reply must never include a png");
  await kickFrameLoop();
  const secondPush = recordedPushes[beforeSecond];
  assert.ok(secondPush, "second action must push a frame");
  assert.equal(secondPush.body.frame_seq, 2);
  assert.equal(secondPush.body.png, PNG_B, "second push must carry the new capture");
  assert.notEqual(secondPush.body.png, recordedPushes[0].body.png);

  const beforeIdle = recordedPushes.length;
  globalThis.__aesopBridgeTest.frameDirty = true;
  await kickFrameLoop();
  const idlePush = recordedPushes[beforeIdle];
  assert.ok(idlePush, "a capture that returns no frame must still push state");
  assert.equal(idlePush.body.frame_seq, 2);
  assert.equal(
    Object.prototype.hasOwnProperty.call(idlePush.body, "png"),
    false,
    "a push with no new capture must omit the png key"
  );
  capturePngQueue = null;
}

// 6. Studio restart: poll network errors for >5s, then success, resets capture and re-pushes.
{
  resetCaptureState();
  captureCallTimestamps = [];
  recordedPushes = [];
  capturePngQueue = null;
  captureDelayMs = 0;
  enforceStrictQuota = false;
  emptyCapturesRemaining = 0;
  pollFailCount = 0;
  currentTab = { ...currentTab, active: true };
  state.confirmed = true;
  state.token = "tok_test_rate_1234567890";
  state.port = 8770;
  state.paired = true;
  state.polling = false;
  state.lastError = "";
  state.captureError = "";

  globalThis.__aesopBridgeTest.frameDirty = true;
  await kickFrameLoop();
  assert.equal(recordedPushes.at(-1).body.frame_seq, 1);

  const realNow = Date.now;
  pollFailCount = 1000;
  state.lastError = "";
  const loopP = startBridgeLoop();
  const armDeadline = realNow() + 2000;
  while (!String(state.lastError).includes("network") && realNow() < armDeadline) {
    await new Promise((r) => setTimeout(r, 20));
  }
  assert.match(String(state.lastError), /network/);
  const failedAt = realNow();
  Date.now = () => failedAt + POLL_NETWORK_RESET_MS + 1000;
  try {
    pollFailCount = 0;
    const before = recordedPushes.length;
    let recovered = null;
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 50));
      if (recordedPushes.length > before) {
        recovered = recordedPushes[before];
        break;
      }
    }
    assert.ok(recovered, "poll recovery after >5s network loss must re-push state");
    assert.equal(
      recovered.body.frame_seq,
      1,
      "resetCaptureState must restart frame_seq so the new Studio process is not stuck"
    );
    assert.ok(recovered.body.png && recovered.body.png.length > 0);
  } finally {
    Date.now = realNow;
    pollFailCount = 0;
    state.polling = false;
    await Promise.race([loopP, new Promise((r) => setTimeout(r, 500))]);
    resetCaptureState();
  }
}

console.log("test_capture_rate.mjs: all capture coalescing, rate-limit, latency, and click_ref assertions passed.");

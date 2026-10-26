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
let captureDelayMs = 25;
let enforceStrictQuota = false;
let forceNextCaptureError = null;
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
let frameSeq = 0;
let frameWaiters = [];
let serverLastError = "";

function advanceFrameSeq() {
  frameSeq += 1;
  const waiters = frameWaiters.splice(0, frameWaiters.length);
  for (const w of waiters) w(frameSeq);
}

let pollFailCount = 0;

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
      if (props && props.url) {
        currentTab = { ...currentTab, url: props.url, status: "complete" };
      }
      return { ...currentTab };
    },
    async captureVisibleTab() {
      const now = Date.now();
      captureCallTimestamps.push(now);
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

globalThis.fetch = async (url, opts = {}) => {
  const u = String(url);
  const body = opts && opts.body ? JSON.parse(opts.body) : null;
  if (u.includes("/api/browser/bridge/poll")) {
    const parsed = new URL(u);
    const le = parsed.searchParams.get("last_error");
    if (le) serverLastError = le;
    if (pollFailCount > 0) {
      pollFailCount -= 1;
      throw new Error("Simulated transient network failure");
    }
    const nextCmd = cmdQueue.shift() || null;
    if (!nextCmd) {
      await new Promise((r) => setTimeout(r, 15));
    }
    return {
      ok: true,
      status: 200,
      async json() {
        return { ok: true, cmd: nextCmd };
      },
    };
  }
  if (u.includes("/api/browser/bridge/push")) {
    if (body && (body.lastError || body.last_error)) {
      serverLastError = body.lastError || body.last_error;
    }
    if (body && body.png) {
      advanceFrameSeq();
    }
    return {
      ok: true,
      status: 200,
      async json() {
        return { ok: true, frame_seq: frameSeq };
      },
    };
  }
  if (u.includes("/api/browser/bridge/reply")) {
    const res = (body && body.result) || {};
    if (res.lastError || res.last_error) {
      serverLastError = res.lastError || res.last_error;
    }
    if (res.png) {
      advanceFrameSeq();
    }
    const resolver = replyResolvers.get(body.cmd_id);
    if (resolver) {
      replyResolvers.delete(body.cmd_id);
      resolver(res);
    }
    return {
      ok: true,
      status: 200,
      async json() {
        return { ok: true };
      },
    };
  }
  return {
    ok: true,
    status: 200,
    async json() {
      return { ok: true };
    },
  };
};

const bgCode = fs.readFileSync(bgPath, "utf-8");
vm.runInThisContext(bgCode, { filename: bgPath });

const {
  state,
  MIN_CAPTURE_INTERVAL_MS,
  RETRY_BACKOFF_MS,
  captureVisibleTabCoalesced,
  resetCaptureState,
  executeCommand,
  startBridgeLoop,
  pageScript,
} = globalThis.__aesopBridgeTest;

assert.ok(MIN_CAPTURE_INTERVAL_MS >= 500, "MIN_CAPTURE_INTERVAL_MS must respect Chrome ~2/s capture limit");
assert.ok(RETRY_BACKOFF_MS >= 100 && RETRY_BACKOFF_MS <= 250, "RETRY_BACKOFF_MS must be brief (100-250ms)");

// 1. Coalescing concurrent in-flight captures + rate-limiting rapid follow-up captures
{
  resetCaptureState();
  captureCallTimestamps = [];
  captureDelayMs = 40;
  enforceStrictQuota = true;

  // Fire 4 concurrent capture requests at t=0: all 4 must share a single in-flight captureVisibleTab call
  const [r1, r2, r3, r4] = await Promise.all([
    captureVisibleTabCoalesced(1),
    captureVisibleTabCoalesced(1),
    captureVisibleTabCoalesced(1),
    captureVisibleTabCoalesced(1),
  ]);
  assert.equal(r1, SAMPLE_PNG_B64);
  assert.equal(r2, SAMPLE_PNG_B64);
  assert.equal(r3, SAMPLE_PNG_B64);
  assert.equal(r4, SAMPLE_PNG_B64);
  assert.equal(captureCallTimestamps.length, 1, "concurrent captures must coalesce into 1 call");

  // Immediately fire 3 more capture requests during the cooldown window: must coalesce into 1 queued call >= MIN_CAPTURE_INTERVAL_MS later
  const [r5, r6, r7] = await Promise.all([
    captureVisibleTabCoalesced(1),
    captureVisibleTabCoalesced(1),
    captureVisibleTabCoalesced(1),
  ]);
  assert.equal(r5, SAMPLE_PNG_B64);
  assert.equal(r6, SAMPLE_PNG_B64);
  assert.equal(r7, SAMPLE_PNG_B64);
  assert.equal(captureCallTimestamps.length, 2, "cooldown burst must coalesce into a single second call");
  const interval = captureCallTimestamps[1] - captureCallTimestamps[0];
  assert.ok(
    interval >= MIN_CAPTURE_INTERVAL_MS - 15,
    `expected >= ${MIN_CAPTURE_INTERVAL_MS}ms between captures, got ${interval}ms`
  );
}

// 2. Quota error records state.lastError without stalling command ack, and popup.js surfaces it when paired
{
  resetCaptureState();
  state.confirmed = true;
  state.token = "tok_test_rate_1234567890";
  state.port = 8770;
  state.paired = true;
  state.lastError = "";
  forceNextCaptureError = "This request exceeds the MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND quota.";

  const t0 = Date.now();
  const out = await executeCommand({ op: "scroll", dy: 400 });
  const elapsedAck = Date.now() - t0;
  assert.equal(out.ok, true);
  assert.ok(elapsedAck <= 300, `capture error must never delay command ack (took ${elapsedAck}ms)`);
  assert.match(state.lastError, /MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND/);
  assert.match(out.lastError, /MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND/);

  // Verify popup.js surfaces state.lastError even when paired === true
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
          if (cb) cb({ paired: true, port: 8770, lastError: state.lastError });
        },
      },
      tabs: { async query() { return []; } },
    },
  });
  const popupCode = fs.readFileSync(popupPath, "utf-8");
  vm.runInContext(popupCode, popupCtx, { filename: popupPath });
  assert.match(popupElements.statusNote.textContent, /MAX_CAPTURE_VISIBLE_TAB_CALLS_PER_SECOND/);
}

// 3. 10 consecutive scroll actions through startBridgeLoop: ack <= 300ms and new frame <= 1000ms
{
  resetCaptureState();
  captureCallTimestamps = [];
  captureDelayMs = 20;
  enforceStrictQuota = true;
  state.confirmed = true;
  state.token = "tok_test_rate_1234567890";
  state.port = 8770;
  state.paired = true;
  state.lastError = "";
  state.polling = false;

  const loopPromise = startBridgeLoop();
  const ackTimes = [];
  const frameTimes = [];

  for (let i = 1; i <= 10; i++) {
    const startFrame = frameSeq;
    const cmdId = `cmd_scroll_${i}`;
    const t0 = Date.now();
    const ackPromise = new Promise((resolve) => {
      replyResolvers.set(cmdId, resolve);
    });
    const framePromise = new Promise((resolve) => {
      if (frameSeq > startFrame) {
        resolve(frameSeq);
      } else {
        frameWaiters.push(resolve);
      }
    });
    cmdQueue.push({ id: cmdId, op: "scroll", dy: 350 });

    await ackPromise;
    const ackMs = Date.now() - t0;
    ackTimes.push(ackMs);

    if (frameSeq <= startFrame) {
      await framePromise;
    }
    const frameMs = Date.now() - t0;
    frameTimes.push(frameMs);
  }

  // Test brief backoff on a real network error during poll
  pollFailCount = 1;
  const errCmdId = "cmd_after_net_err";
  const tErr0 = Date.now();
  const errAckPromise = new Promise((resolve) => {
    replyResolvers.set(errCmdId, resolve);
  });
  cmdQueue.push({ id: errCmdId, op: "scroll", dy: 100 });
  await errAckPromise;
  const errRecoveryMs = Date.now() - tErr0;
  assert.ok(errRecoveryMs < 500, `network retry backoff must be brief (<500ms, got ${errRecoveryMs}ms)`);

  state.polling = false;
  await loopPromise;

  const ackUnder300 = ackTimes.filter((ms) => ms <= 300).length;
  const frameUnder1000 = frameTimes.filter((ms) => ms <= 1000).length;
  assert.equal(ackUnder300, 10, `expected all 10 acks <= 300ms, got ${JSON.stringify(ackTimes)}`);
  assert.ok(frameUnder1000 >= 9, `expected >= 9/10 frames <= 1000ms, got ${JSON.stringify(frameTimes)}`);
  assert.equal(state.lastError, "Simulated transient network failure");
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

console.log("test_capture_rate.mjs: all capture coalescing, rate-limit, latency, and click_ref assertions passed.");

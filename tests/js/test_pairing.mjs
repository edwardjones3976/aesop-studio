import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const bgPath = path.join(repoRoot, "extension", "background.js");
const contentPairPath = path.join(repoRoot, "extension", "content_pair.js");

const EXT_ID = "aesop-bridge-ext-test-id";
const fetchCalls = [];
const notificationsCreated = [];
const storageData = {};
let onMessageListener = null;

globalThis.chrome = {
  runtime: {
    id: EXT_ID,
    onMessage: {
      addListener(fn) {
        onMessageListener = fn;
      },
    },
  },
  storage: {
    local: {
      get(_keys, cb) {
        cb({ ...storageData });
      },
      set(items) {
        Object.assign(storageData, items);
      },
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
      return [{ id: 42, windowId: 1, title: "Example", url: "https://example.org/", active: true }];
    },
    async get(id) {
      return { id, windowId: 1, title: "Example", url: "https://example.org/", active: true };
    },
    async captureVisibleTab() {
      return "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
    },
  },
  scripting: {
    async executeScript() {
      return [{ result: { ok: true, url: "https://example.org/", title: "Example", elements: [] } }];
    },
  },
  action: {
    setBadgeText() {},
    setBadgeBackgroundColor() {},
  },
  notifications: {
    create(id, opts) {
      notificationsCreated.push({ id, opts });
    },
    clear() {},
    onButtonClicked: { addListener() {} },
  },
};

globalThis.fetch = async (url, opts = {}) => {
  fetchCalls.push({ url, opts });
  if (String(url).includes("/api/browser/bridge/poll")) {
    // Stop polling after one cycle in tests so startBridgeLoop exits cleanly
    globalThis.__aesopBridgeTest.state.polling = false;
    return {
      ok: true,
      status: 200,
      async json() {
        return { ok: true, cmd: null };
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

// Load extension/background.js into this VM context
const bgCode = fs.readFileSync(bgPath, "utf-8");
vm.runInThisContext(bgCode, { filename: bgPath });

assert.ok(onMessageListener, "background.js must register chrome.runtime.onMessage listener");
assert.ok(globalThis.__aesopBridgeTest, "background.js must expose __aesopBridgeTest helpers");

const { state } = globalThis.__aesopBridgeTest;

function sendRuntimeMessage(msg, sender) {
  return new Promise((resolve) => {
    let settled = false;
    const asyncReply = onMessageListener(msg, sender, (resp) => {
      settled = true;
      resolve(resp);
    });
    if (!asyncReply && !settled) {
      resolve(undefined);
    }
  });
}

// 1. Rejects a foreign sender.id
{
  const res = await sendRuntimeMessage(
    { type: "AESOP_PAIR", port: 8765, token: "tok_valid_123456" },
    { id: "foreign-extension-id", origin: "http://127.0.0.1:8765", tab: { id: 10, url: "http://127.0.0.1:8765/" } }
  );
  assert.equal(res.ok, false);
  assert.match(res.error, /untrusted sender id/i);
  assert.equal(state.confirmed, false);
  assert.equal(state.pendingPair, null);
  assert.equal(fetchCalls.length, 0);
}

// 2. Rejects non-loopback or non-http origins
{
  const resEvil = await sendRuntimeMessage(
    { type: "AESOP_PAIR", port: 8765, token: "tok_valid_123456" },
    { id: EXT_ID, origin: "http://evil.example.com:8765", tab: { id: 10, url: "http://evil.example.com:8765/" } }
  );
  assert.equal(resEvil.ok, false);
  assert.match(resEvil.error, /untrusted sender/i);

  const resHttps = await sendRuntimeMessage(
    { type: "AESOP_PAIR", port: 8765, token: "tok_valid_123456" },
    { id: EXT_ID, origin: "https://127.0.0.1:8765", tab: { id: 10, url: "https://127.0.0.1:8765/" } }
  );
  assert.equal(resHttps.ok, false);
  assert.match(resHttps.error, /untrusted sender/i);
  assert.equal(state.pendingPair, null);
  assert.equal(fetchCalls.length, 0);
}

// 3. Rejects a pairing whose page-supplied port differs from the sender origin
{
  const resMismatch = await sendRuntimeMessage(
    { type: "AESOP_PAIR", port: 9999, token: "attacker_token" },
    { id: EXT_ID, origin: "http://127.0.0.1:8765", tab: { id: 10, url: "http://127.0.0.1:8765/" } }
  );
  assert.equal(resMismatch.ok, false);
  assert.match(resMismatch.error, /port does not match sender origin/i);
  assert.equal(state.confirmed, false);
  assert.equal(state.pendingPair, null);
  assert.equal(fetchCalls.length, 0);

  const resTabOriginMismatch = await sendRuntimeMessage(
    { type: "AESOP_PAIR", token: "attacker_token" },
    { id: EXT_ID, origin: "http://127.0.0.1:9999", tab: { id: 10, url: "http://127.0.0.1:8765/" } }
  );
  assert.equal(resTabOriginMismatch.ok, false);
  assert.match(resTabOriginMismatch.error, /mismatch/i);
}

// 4. First pairing requires explicit owner confirmation in extension UI (derives port from sender origin)
{
  const resFirst = await sendRuntimeMessage(
    { type: "AESOP_PAIR", token: "studio_persistent_token_A" },
    { id: EXT_ID, origin: "http://127.0.0.1:8765", tab: { id: 10, url: "http://127.0.0.1:8765/" } }
  );
  assert.equal(resFirst.ok, false);
  assert.equal(resFirst.pendingConfirmation, true);
  assert.equal(resFirst.port, 8765);
  assert.equal(resFirst.prompt, "Pair with Aesop Studio at 127.0.0.1:8765?");
  assert.equal(state.confirmed, false);
  assert.equal(state.paired, false);
  assert.equal(state.token, "");
  assert.ok(state.pendingPair);
  assert.equal(state.pendingPair.port, 8765);
  assert.equal(state.pendingPair.token, "studio_persistent_token_A");
  assert.equal(fetchCalls.length, 0, "must not contact server before owner confirms");
  assert.equal(notificationsCreated.length, 1);
  assert.equal(notificationsCreated[0].opts.message, "Pair with Aesop Studio at 127.0.0.1:8765?");
}

// 5. Ignores AESOP_PAIR messages while a confirmation is pending
{
  const resWhilePending = await sendRuntimeMessage(
    { type: "AESOP_PAIR", port: 8766, token: "attacker_override_attempt" },
    { id: EXT_ID, origin: "http://127.0.0.1:8766", tab: { id: 11, url: "http://127.0.0.1:8766/" } }
  );
  assert.equal(resWhilePending.ok, false);
  assert.equal(resWhilePending.pending, true);
  assert.equal(state.pendingPair.port, 8765);
  assert.equal(state.pendingPair.token, "studio_persistent_token_A");
}

// 6. Content script / tab cannot self-confirm AESOP_CONFIRM_PAIR; extension UI confirmation succeeds
{
  const tabConfirm = await sendRuntimeMessage(
    { type: "AESOP_CONFIRM_PAIR", approve: true },
    { id: EXT_ID, origin: "http://127.0.0.1:8765", tab: { id: 10, url: "http://127.0.0.1:8765/" } }
  );
  assert.equal(tabConfirm.ok, false);
  assert.equal(state.confirmed, false);

  const uiConfirm = await sendRuntimeMessage(
    { type: "AESOP_CONFIRM_PAIR", approve: true },
    { id: EXT_ID, url: `chrome-extension://${EXT_ID}/popup.html` }
  );
  assert.equal(uiConfirm.ok, true);
  assert.equal(uiConfirm.confirmed, true);
  assert.equal(state.confirmed, true);
  assert.equal(state.port, 8765);
  assert.equal(state.token, "studio_persistent_token_A");
  assert.equal(state.pendingPair, null);
  assert.ok(fetchCalls.length >= 1, "confirmed pairing pushes state to Studio");
  assert.ok(fetchCalls[0].url.startsWith("http://127.0.0.1:8765/api/browser/bridge/push"));
}

// 7. Silent re-pair is allowed ONLY for the SAME port AND SAME token already confirmed, and is rate-limited
{
  state.lastPairAttemptAt = 0;
  const silentOk = await sendRuntimeMessage(
    { type: "AESOP_PAIR", port: 8765, token: "studio_persistent_token_A" },
    { id: EXT_ID, origin: "http://127.0.0.1:8765", tab: { id: 10, url: "http://127.0.0.1:8765/" } }
  );
  assert.equal(silentOk.ok, true);
  assert.equal(silentOk.confirmed, true);
  assert.equal(state.pendingPair, null);

  // Immediate second AESOP_PAIR within PAIR_RATE_LIMIT_MS is rate-limited
  const rapidSecond = await sendRuntimeMessage(
    { type: "AESOP_PAIR", port: 8765, token: "studio_persistent_token_A" },
    { id: EXT_ID, origin: "http://127.0.0.1:8765", tab: { id: 10, url: "http://127.0.0.1:8765/" } }
  );
  assert.equal(rapidSecond.ok, false);
  assert.equal(rapidSecond.rateLimited, true);
}

// 8. Port change or token change never silently switches pairing; requires owner confirmation
{
  state.lastPairAttemptAt = 0;
  const portChanged = await sendRuntimeMessage(
    { type: "AESOP_PAIR", port: 8766, token: "studio_persistent_token_A" },
    { id: EXT_ID, origin: "http://127.0.0.1:8766", tab: { id: 12, url: "http://127.0.0.1:8766/" } }
  );
  assert.equal(portChanged.ok, false);
  assert.equal(portChanged.pendingConfirmation, true);
  assert.equal(portChanged.port, 8766);
  assert.equal(portChanged.prompt, "Pair with Aesop Studio at 127.0.0.1:8766?");
  // Existing pairing on 8765 is NOT switched silently
  assert.equal(state.port, 8765);
  assert.equal(state.token, "studio_persistent_token_A");

  // Reject the pending port change
  await sendRuntimeMessage(
    { type: "AESOP_CONFIRM_PAIR", approve: false },
    { id: EXT_ID, url: `chrome-extension://${EXT_ID}/popup.html` }
  );
  assert.equal(state.pendingPair, null);

  // Same port (8765) but different token (e.g. stray server on 8765 or rotated token) also requires confirmation
  state.lastPairAttemptAt = 0;
  const tokenChanged = await sendRuntimeMessage(
    { type: "AESOP_PAIR", port: 8765, token: "different_token_value" },
    { id: EXT_ID, origin: "http://127.0.0.1:8765", tab: { id: 10, url: "http://127.0.0.1:8765/" } }
  );
  assert.equal(tokenChanged.ok, false);
  assert.equal(tokenChanged.pendingConfirmation, true);
  assert.equal(state.token, "studio_persistent_token_A");
}

// 9. Static check on content_pair.js: verifies origin port check is present
{
  const cpCode = fs.readFileSync(contentPairPath, "utf-8");
  assert.match(cpCode, /window\.location\.port/);
  assert.match(cpCode, /port does not match page origin/);
}

console.log("test_pairing.mjs: all pairing security assertions passed.");

// Aesop Studio Browser Bridge (Manifest V3 Service Worker)
// Connects the owner's normal Chrome profile (and existing logins) to Aesop Studio over 127.0.0.1
// with pairing-token authentication. Never reads cookies, storage, or password values.
"use strict";

const PAIR_RATE_LIMIT_MS = 1000;
const MIN_CAPTURE_INTERVAL_MS = 500;
const RETRY_BACKOFF_MS = 150;

var frameDirty = false;
let captureInFlight = null;
let lastCaptureAt = 0;
let frameLoopPromise = null;
let frameLoopEpoch = 0;
let frameWaitTimer = null;
let frameWaitResolve = null;
let latestTab = null;
let latestSnapshot = null;
let latestFrame = { seq: 0, png: "" };
let commandInFlight = false;

let state = {
  port: 8765,
  token: "",
  confirmed: false,
  paired: false,
  targetTabId: null,
  lastError: "",
  captureError: "",
  frameDirty: false,
  polling: false,
  pushTimer: null,
  pendingPair: null,
  lastPairAttemptAt: 0,
};

chrome.storage.local.get(["port", "token", "confirmed", "targetTabId", "pendingPair"], (res) => {
  if (res.port) state.port = Number(res.port) || 8765;
  if (res.token && res.confirmed === true) {
    state.token = String(res.token);
    state.confirmed = true;
  }
  if (res.targetTabId) state.targetTabId = Number(res.targetTabId);
  if (res.pendingPair && typeof res.pendingPair === "object" && res.pendingPair.port && res.pendingPair.token) {
    state.pendingPair = res.pendingPair;
    updateActionBadge();
  }
  if (state.confirmed && state.token) {
    startBridgeLoop();
  }
});

chrome.alarms.create("aesop-keepalive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "aesop-keepalive" && state.confirmed && state.token && !state.polling) {
    startBridgeLoop();
  }
});

function saveState() {
  chrome.storage.local.set({
    port: state.port,
    token: state.token,
    confirmed: state.confirmed,
    targetTabId: state.targetTabId,
    pendingPair: state.pendingPair,
  });
}

function updateActionBadge() {
  if (!chrome.action || !chrome.action.setBadgeText) return;
  if (state.pendingPair && state.pendingPair.port) {
    chrome.action.setBadgeText({ text: "1" });
    if (chrome.action.setBadgeBackgroundColor) {
      chrome.action.setBadgeBackgroundColor({ color: "#FF916C" });
    }
  } else {
    chrome.action.setBadgeText({ text: "" });
  }
}

function isStudioUrl(url) {
  if (!url) return true;
  try {
    const u = new URL(url);
    if (
      (u.hostname === "127.0.0.1" || u.hostname === "localhost") &&
      String(u.port || "80") === String(state.port)
    ) {
      return true;
    }
    return !["http:", "https:"].includes(u.protocol);
  } catch (_e) {
    return true;
  }
}

async function listBrowseableTabs() {
  const tabs = await chrome.tabs.query({});
  return tabs
    .filter((t) => t.id && !isStudioUrl(t.url))
    .map((t) => ({
      id: t.id,
      windowId: t.windowId,
      title: String(t.title || "").slice(0, 160),
      url: String(t.url || "").slice(0, 500),
      active: !!t.active,
      selected: t.id === state.targetTabId,
    }));
}

async function getTargetTab(createIfMissing = false) {
  if (state.targetTabId) {
    try {
      const t = await chrome.tabs.get(state.targetTabId);
      if (t && !isStudioUrl(t.url)) return t;
    } catch (_e) {
      state.targetTabId = null;
    }
  }
  const all = await chrome.tabs.query({});
  const activeNonStudio = all.find((t) => t.active && !isStudioUrl(t.url));
  if (activeNonStudio) {
    state.targetTabId = activeNonStudio.id;
    saveState();
    return activeNonStudio;
  }
  const anyNonStudio = all.find((t) => !isStudioUrl(t.url));
  if (anyNonStudio) {
    state.targetTabId = anyNonStudio.id;
    saveState();
    return anyNonStudio;
  }
  if (!createIfMissing) return null;
  const created = await chrome.tabs.create({ url: "https://example.com", active: true });
  state.targetTabId = created.id;
  saveState();
  return created;
}

// In-page DOM + Accessibility snapshot and action executor.
// Injected via chrome.scripting.executeScript into the target tab.
function pageScript(payload) {
  const op = payload.op;
  const isPasswordField = (el) => {
    if (!el || !el.tagName) return false;
    const type = String(el.type || "").toLowerCase();
    const ac = String(el.getAttribute("autocomplete") || "").toLowerCase();
    const name = String(el.name || el.id || el.placeholder || el.getAttribute("aria-label") || "").toLowerCase();
    return (
      type === "password" ||
      ac.includes("password") ||
      /\b(password|passwd|passcode|pin)\b/i.test(name)
    );
  };
  const isPaymentField = (el) => {
    if (!el || !el.tagName) return false;
    const ac = String(el.getAttribute("autocomplete") || "").toLowerCase();
    const name = String(el.name || el.id || el.placeholder || el.getAttribute("aria-label") || "").toLowerCase();
    return (
      ac.startsWith("cc-") ||
      /\b(card[_\s-]?number|cvv|cvc|cc-number|cc-csc|credit[_\s-]?card)\b/i.test(name)
    );
  };
  const isCaptchaNode = (el) => {
    if (!el || !el.tagName) return false;
    const blob = [
      el.id,
      el.className,
      el.getAttribute("title"),
      el.getAttribute("aria-label"),
      el.getAttribute("data-sitekey"),
      el.src,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return /\b(captcha|recaptcha|hcaptcha|cf-turnstile|g-recaptcha)\b/i.test(blob);
  };
  const isPurchaseTrigger = (el) => {
    if (!el || !el.tagName) return false;
    const txt = String(
      el.innerText || el.value || el.getAttribute("aria-label") || el.title || ""
    )
      .trim()
      .toLowerCase();
    return /\b(buy now|place your order|place order|complete purchase|pay now|confirm payment|submit order|one-click buy)\b/i.test(
      txt
    );
  };

  const labelFor = (el) => {
    if (!el) return "";
    if (isPasswordField(el)) return "[password field]";
    const aria = el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("placeholder");
    if (aria && aria.trim()) return aria.trim().slice(0, 120);
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl && lbl.innerText) return lbl.innerText.trim().slice(0, 120);
    }
    const parentLbl = el.closest && el.closest("label");
    if (parentLbl && parentLbl.innerText) return parentLbl.innerText.trim().slice(0, 120);
    const txt = el.innerText || el.value || el.getAttribute("alt") || el.name || "";
    return String(txt).replace(/\s+/g, " ").trim().slice(0, 120);
  };

  const roleFor = (el) => {
    const r = el.getAttribute("role");
    if (r) return r.toLowerCase();
    const tag = el.tagName.toLowerCase();
    if (tag === "a") return "link";
    if (tag === "button") return "button";
    if (tag === "select") return "combobox";
    if (tag === "textarea") return "textbox";
    if (tag === "summary") return "button";
    if (tag === "input") {
      const t = String(el.type || "text").toLowerCase();
      if (["button", "submit", "reset"].includes(t)) return "button";
      if (t === "checkbox") return "checkbox";
      if (t === "radio") return "radio";
      if (t === "search") return "searchbox";
      return "textbox";
    }
    return tag;
  };

  const resolveAnchor = (node) => {
    if (!node) return null;
    if (
      node.tagName &&
      node.tagName.toLowerCase() === "a" &&
      (node.href || (node.getAttribute && node.getAttribute("href")))
    ) {
      return node;
    }
    if (node.closest) {
      const parentA = node.closest("a[href]");
      if (parentA) return parentA;
    }
    if (node.querySelector) {
      const childA = node.querySelector("a[href]");
      if (childA) return childA;
    }
    return null;
  };

  const resolveHref = (node) => {
    const a = resolveAnchor(node) || node;
    if (!a) return "";
    const raw = String(a.href || (a.getAttribute && a.getAttribute("href")) || "").trim();
    if (!raw) return "";
    if (/^https?:\/\//i.test(raw)) return raw;
    if (/^(javascript:|mailto:|tel:|data:|vbscript:)/i.test(raw)) return "";
    try {
      const base = window.location && window.location.href ? window.location.href : "https://localhost/";
      const resolved = new URL(raw, base).href;
      return /^https?:\/\//i.test(resolved) ? resolved : "";
    } catch (_e) {
      return "";
    }
  };

  const collectSnapshot = () => {
    const vw = window.innerWidth || 1366;
    const vh = window.innerHeight || 854;
    for (const old of document.querySelectorAll("[data-aesop-ref]")) {
      old.removeAttribute("data-aesop-ref");
    }
    const headings = [...document.querySelectorAll("h1, h2, h3, h4")]
      .slice(0, 35)
      .map((h) => ({
        level: Number(h.tagName.slice(1)),
        text: String(h.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160),
      }))
      .filter((h) => h.text);

    const sel = [
      "a[href]",
      "button",
      "input:not([type='hidden'])",
      "select",
      "textarea",
      "summary",
      "[role='button']",
      "[role='link']",
      "[role='tab']",
      "[role='menuitem']",
      "[role='searchbox']",
      "[role='checkbox']",
    ].join(",");

    const nodes = [...document.querySelectorAll(sel)];
    const elements = [];
    let refSeq = 1;
    for (const el of nodes) {
      if (elements.length >= 85) break;
      const rect = el.getBoundingClientRect();
      if (rect.width < 3 || rect.height < 3) continue;
      const style = window.getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") continue;
      if (rect.bottom < -200 || rect.top > vh + 600) continue;
      const pw = isPasswordField(el);
      const cap = isCaptchaNode(el);
      const pur = isPurchaseTrigger(el) || isPaymentField(el);
      const label = labelFor(el);
      const href = resolveHref(el);
      if (!label && !href && !["input", "textarea", "select"].includes(el.tagName.toLowerCase())) continue;
      const ref = refSeq++;
      el.setAttribute("data-aesop-ref", String(ref));
      elements.push({
        ref,
        role: roleFor(el),
        tag: el.tagName.toLowerCase(),
        type: String(el.type || "").toLowerCase(),
        label: label || href.slice(0, 80) || el.tagName.toLowerCase(),
        href: href.slice(0, 300),
        rect: {
          x: Math.round(rect.left + rect.width / 2),
          y: Math.round(rect.top + rect.height / 2),
          left: Math.round(rect.left),
          top: Math.round(rect.top),
          w: Math.round(rect.width),
          h: Math.round(rect.height),
        },
        in_viewport: rect.top >= 0 && rect.left >= 0 && rect.bottom <= vh && rect.right <= vw,
        is_password: pw,
        is_captcha: cap,
        is_purchase: pur,
      });
    }

    const forms = [...document.querySelectorAll("form")].slice(0, 12).map((f, idx) => {
      const controls = [...f.querySelectorAll("input:not([type='hidden']), select, textarea, button")]
        .slice(0, 15)
        .map((c) => ({
          ref: Number(c.getAttribute("data-aesop-ref") || 0) || null,
          role: roleFor(c),
          type: isPasswordField(c) ? "password" : String(c.type || "").toLowerCase(),
          label: labelFor(c),
          is_password: isPasswordField(c),
        }));
      return {
        index: idx + 1,
        name: String(f.getAttribute("aria-label") || f.name || f.id || `form-${idx + 1}`).slice(0, 80),
        fields: controls,
      };
    });

    const links = [...document.querySelectorAll("a[href]")]
      .slice(0, 40)
      .map((a) => ({
        ref: Number(a.getAttribute("data-aesop-ref") || 0) || null,
        text: String(a.innerText || a.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim().slice(0, 80),
        href: a.href,
      }))
      .filter((l) => l.text && l.href && l.href.startsWith("http"));

    const mainEl =
      document.querySelector("main, article, [role='main'], #readme, .markdown-body") || document.body;
    const textCap = op === "text" || op === "find" ? 16000 : 1800;
    const mainText = String((mainEl && mainEl.innerText) || "").slice(0, textCap);
    const fullText = String((document.body && document.body.innerText) || "").slice(0, textCap);

    return {
      ok: true,
      url: window.location.href,
      title: document.title || "",
      vw,
      vh,
      scrollY: Math.round(window.scrollY || 0),
      docH: Math.round((document.documentElement && document.documentElement.scrollHeight) || vh),
      headings,
      elements,
      forms,
      links,
      main_text: mainText,
      text: fullText,
    };
  };

  const findByRef = (ref) => {
    const wantHref = payload.href && /^https?:\/\//i.test(String(payload.href)) ? String(payload.href) : "";
    const wantLabel = String(payload.label || "").trim().toLowerCase();
    let el = document.querySelector(`[data-aesop-ref="${CSS.escape(String(ref))}"]`);
    if (el && wantHref) {
      const elHref = resolveHref(el);
      if (elHref && elHref !== wantHref) {
        el = null;
      }
    }
    if (!el && wantHref) {
      for (const a of document.querySelectorAll("a[href]")) {
        if (resolveHref(a) === wantHref) {
          el = a;
          break;
        }
      }
    }
    if (!el) {
      collectSnapshot();
      el = document.querySelector(`[data-aesop-ref="${CSS.escape(String(ref))}"]`);
    }
    if (!el && wantLabel) {
      for (const cand of document.querySelectorAll("a[href], button, [role='link'], [role='button']")) {
        if (labelFor(cand).toLowerCase() === wantLabel) {
          el = cand;
          break;
        }
      }
    }
    return el;
  };

  const guardAgentTarget = (el, isTyping) => {
    if (!payload.agent || !el) return null;
    if (isPasswordField(el)) {
      return "refused: a provider cannot type into a password field";
    }
    if (isCaptchaNode(el) || (el.closest && isCaptchaNode(el.closest("iframe, div, form")))) {
      return "refused: a provider cannot solve CAPTCHAs";
    }
    if (isPurchaseTrigger(el) || isPaymentField(el)) {
      return "refused: a provider cannot make purchases or enter payment details";
    }
    if (isTyping && el.type === "password") {
      return "refused: a provider cannot type into a password field";
    }
    return null;
  };

  try {
    if (op === "snapshot" || op === "ping" || op === "text" || op === "links") {
      return collectSnapshot();
    }
    if (op === "click_ref") {
      const el = findByRef(payload.ref);
      if (!el) return { ok: false, error: `element ref #${payload.ref} not found on page`, ...collectSnapshot() };
      const anchor = resolveAnchor(el);
      const targetEl = anchor || el;
      const err = guardAgentTarget(el, false) || (anchor ? guardAgentTarget(anchor, false) : null);
      if (err) return { ok: false, error: err, ...collectSnapshot() };
      const preClickUrl = window.location.href;
      const targetHref =
        resolveHref(targetEl) ||
        (payload.href && /^https?:\/\//i.test(String(payload.href)) ? String(payload.href) : "");
      if (targetEl.scrollIntoView) {
        targetEl.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
      }
      if (targetEl.focus) targetEl.focus();
      const rect = targetEl.getBoundingClientRect
        ? targetEl.getBoundingClientRect()
        : { left: 0, top: 0, width: 0, height: 0 };
      const cx = Math.round(rect.left + (rect.width || 0) / 2);
      const cy = Math.round(rect.top + (rect.height || 0) / 2);
      if (typeof MouseEvent === "function" && targetEl.dispatchEvent) {
        for (const evType of ["pointerdown", "mousedown", "pointerup", "mouseup"]) {
          targetEl.dispatchEvent(
            new MouseEvent(evType, { bubbles: true, cancelable: true, clientX: cx, clientY: cy, view: window })
          );
        }
      }
      if (typeof targetEl.click === "function") {
        targetEl.click();
      } else if (typeof MouseEvent === "function" && targetEl.dispatchEvent) {
        targetEl.dispatchEvent(
          new MouseEvent("click", { bubbles: true, cancelable: true, clientX: cx, clientY: cy, view: window })
        );
      }
      if (targetEl !== el && typeof el.click === "function") {
        try {
          el.click();
        } catch (_e) {}
      }
      const snap = collectSnapshot();
      return { ...snap, clicked_href: targetHref, pre_click_url: preClickUrl };
    }
    if (op === "fill_ref") {
      const el = findByRef(payload.ref);
      if (!el) return { ok: false, error: `element ref #${payload.ref} not found on page`, ...collectSnapshot() };
      const err = guardAgentTarget(el, true);
      if (err) return { ok: false, error: err, ...collectSnapshot() };
      el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
      el.focus && el.focus();
      if ("value" in el) {
        el.value = String(payload.text || "").slice(0, 2000);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (payload.submit && el.form) {
        if (payload.agent && isPurchaseTrigger(el.form)) {
          return { ok: false, error: "refused: a provider cannot make purchases or enter payment details", ...collectSnapshot() };
        }
        el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit();
      }
      return collectSnapshot();
    }
    if (op === "click") {
      const x = Number(payload.x || 0);
      const y = Number(payload.y || 0);
      const el = document.elementFromPoint(x, y);
      if (el) {
        const err = guardAgentTarget(el, false);
        if (err) return { ok: false, error: err, ...collectSnapshot() };
        el.focus && el.focus();
        for (const evType of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
          el.dispatchEvent(
            new MouseEvent(evType, { bubbles: true, cancelable: true, clientX: x, clientY: y, view: window })
          );
        }
        if (el.tagName === "A" && el.href && el.href.startsWith("http") && el.target !== "_blank") {
          window.location.href = el.href;
        }
      }
      return collectSnapshot();
    }
    if (op === "type") {
      const el = document.activeElement || document.body;
      const err = guardAgentTarget(el, true);
      if (err) return { ok: false, error: err, ...collectSnapshot() };
      const txt = String(payload.text || "").slice(0, 2000);
      if (el && "value" in el) {
        const start = typeof el.selectionStart === "number" ? el.selectionStart : el.value.length;
        const end = typeof el.selectionEnd === "number" ? el.selectionEnd : el.value.length;
        el.value = el.value.slice(0, start) + txt + el.value.slice(end);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else if (el && el.isContentEditable) {
        document.execCommand("insertText", false, txt);
      }
      return collectSnapshot();
    }
    if (op === "key") {
      const k = String(payload.key || "Enter").slice(0, 40);
      const el = document.activeElement || document.body;
      const err = guardAgentTarget(el, k.length === 1);
      if (err) return { ok: false, error: err, ...collectSnapshot() };
      if (k === "Backspace" && el && "value" in el) {
        el.value = el.value.slice(0, -1);
        el.dispatchEvent(new Event("input", { bubbles: true }));
      } else if (k === "Enter" && el && el.form) {
        const ferr = guardAgentTarget(el.form, false);
        if (ferr) return { ok: false, error: ferr, ...collectSnapshot() };
        el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit();
      } else if (el) {
        el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));
        el.dispatchEvent(new KeyboardEvent("keyup", { key: k, bubbles: true }));
      }
      return collectSnapshot();
    }
    if (op === "scroll") {
      const dy = Number(payload.dy || 600);
      window.scrollBy({ top: dy, left: 0, behavior: "instant" });
      return collectSnapshot();
    }
    if (op === "find") {
      const snap = collectSnapshot();
      const q = String(payload.query || "").trim().toLowerCase();
      if (!q) return { ...snap, matches: [] };
      const lines = (snap.text || "").split(/\r?\n/);
      const matches = [];
      for (let i = 0; i < lines.length && matches.length < 25; i++) {
        if (lines[i].toLowerCase().includes(q)) {
          matches.push({ line: i + 1, snippet: lines[i].trim().slice(0, 220) });
        }
      }
      const elMatches = (snap.elements || []).filter(
        (e) => (e.label || "").toLowerCase().includes(q) || (e.href || "").toLowerCase().includes(q)
      );
      return { ...snap, matches, element_matches: elMatches.slice(0, 20) };
    }
    if (op === "back") {
      window.history.back();
      return collectSnapshot();
    }
    if (op === "forward") {
      window.history.forward();
      return collectSnapshot();
    }
    if (op === "reload") {
      window.location.reload();
      return collectSnapshot();
    }
    return collectSnapshot();
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e).slice(0, 300), url: window.location.href, title: document.title || "" };
  }
}

function formatCaptureError(err) {
  const raw = String(err && err.message ? err.message : err).slice(0, 240);
  if (
    /\b(not\s+visible|invisible|not\s+focused|unfocused|minimized|hidden|occluded|no\s+active\s+web\s+contents|no\s+current\s+window|window.*front|background)\b/i.test(
      raw
    )
  ) {
    return "Live view paused: bring the Chrome window to front";
  }
  return raw;
}

function runSingleCapture(windowId) {
  if (captureInFlight) return captureInFlight;
  lastCaptureAt = Date.now();
  const p = (async () => {
    try {
      const dataUrl = await chrome.tabs.captureVisibleTab(windowId, { format: "png" });
      if (dataUrl && typeof dataUrl === "string" && dataUrl.startsWith("data:image/png;base64,")) {
        state.captureError = "";
        return dataUrl.slice("data:image/png;base64,".length);
      }
      return "";
    } catch (e) {
      state.captureError = formatCaptureError(e);
      return "";
    } finally {
      captureInFlight = null;
    }
  })();
  captureInFlight = p;
  return p;
}

function waitFrameInterval(ms) {
  return new Promise((resolve) => {
    frameWaitResolve = resolve;
    frameWaitTimer = setTimeout(() => {
      frameWaitTimer = null;
      frameWaitResolve = null;
      resolve();
    }, ms);
  });
}

function buildPushPayload(snap, curTab, tabs) {
  const s = snap && typeof snap === "object" ? snap : {};
  const t = curTab && typeof curTab === "object" ? curTab : {};
  const payload = {
    ok: true,
    url: s.url || t.url || "",
    title: String(s.title || t.title || "").slice(0, 200),
    vw: s.vw || 1366,
    vh: s.vh || 854,
    scrollY: s.scrollY || 0,
    docH: s.docH || s.vh || 854,
    headings: Array.isArray(s.headings) ? s.headings.slice(0, 20) : [],
    elements: Array.isArray(s.elements) ? s.elements.slice(0, 150) : [],
    forms: Array.isArray(s.forms) ? s.forms.slice(0, 6) : [],
    links: Array.isArray(s.links) ? s.links.slice(0, 20) : [],
    main_text: String(s.main_text || "").slice(0, 6000),
    text: String(s.text || "").slice(0, 6000),
    tabs: Array.isArray(tabs) ? tabs.slice(0, 12) : [],
    tab_id: t.id || null,
    frame_seq: latestFrame.seq,
    captureError: state.captureError || "",
    lastError: state.lastError || "",
    last_error: state.lastError || "",
  };
  if (JSON.stringify(payload).length > 7600) {
    payload.links = payload.links.slice(0, 10);
    payload.text = payload.text.slice(0, 600);
    payload.main_text = payload.main_text.slice(0, 600);
  }
  if (JSON.stringify(payload).length > 7600) {
    payload.elements = payload.elements.slice(0, 25);
  }
  return payload;
}

function kickFrameLoop(tabHint = null, snapHint = null) {
  if (tabHint && tabHint.id) latestTab = tabHint;
  if (snapHint && typeof snapHint === "object") latestSnapshot = snapHint;
  if (frameLoopPromise) return frameLoopPromise;
  const epoch = frameLoopEpoch;
  frameLoopPromise = (async () => {
    try {
      do {
        while (true) {
          if (epoch !== frameLoopEpoch) break;
          if (captureInFlight) {
            try {
              await captureInFlight;
            } catch (_e) {}
            if (epoch !== frameLoopEpoch) break;
          }
          const now = Date.now();
          const elapsed = lastCaptureAt === 0 ? MIN_CAPTURE_INTERVAL_MS : now - lastCaptureAt;
          if (elapsed < MIN_CAPTURE_INTERVAL_MS) {
            const waitMs = Math.max(1, MIN_CAPTURE_INTERVAL_MS - elapsed);
            await waitFrameInterval(waitMs);
            continue;
          }
          break;
        }
        if (epoch !== frameLoopEpoch) break;
        if (!frameDirty && !state.frameDirty) break;
        frameDirty = false;
        state.frameDirty = false;

        const tab = latestTab && latestTab.id ? latestTab : await getTargetTab(false);
        if (epoch !== frameLoopEpoch) break;
        let png = "";
        if (tab && tab.id) {
          png = await runSingleCapture(tab.windowId);
        }
        if (epoch !== frameLoopEpoch) break;
        if (png) {
          latestFrame = { seq: latestFrame.seq + 1, png };
        }
        if (state.confirmed && state.token && state.port) {
          try {
            const curTab = (latestTab && latestTab.id ? latestTab : tab) || {};
            const snap = latestSnapshot || {};
            const tabs = await listBrowseableTabs();
            const pushBody = buildPushPayload(snap, curTab, tabs);
            await studioFetch("/api/browser/bridge/push?lane=data", "POST", pushBody);
            state.paired = true;
          } catch (pushErr) {
            state.captureError = String(
              pushErr && pushErr.message ? pushErr.message : pushErr
            ).slice(0, 240);
          }
        }
      } while (frameDirty || state.frameDirty);
    } finally {
      if (epoch === frameLoopEpoch) {
        frameLoopPromise = null;
      }
    }
  })();
  return frameLoopPromise;
}

function resetCaptureState() {
  frameLoopEpoch += 1;
  frameDirty = false;
  state.frameDirty = false;
  state.captureError = "";
  if (frameWaitTimer) {
    clearTimeout(frameWaitTimer);
    frameWaitTimer = null;
  }
  if (frameWaitResolve) {
    const r = frameWaitResolve;
    frameWaitResolve = null;
    r();
  }
  captureInFlight = null;
  lastCaptureAt = 0;
  frameLoopPromise = null;
  latestTab = null;
  latestSnapshot = null;
  latestFrame = { seq: 0, png: "" };
}

async function captureAndSnapshot(tab, op = "snapshot", extra = {}, opts = {}) {
  if (!tab || !tab.id) {
    return {
      ok: false,
      error: "no active browser tab",
      captureError: state.captureError || "",
      lastError: state.lastError || "",
      last_error: state.lastError || "",
      tabs: await listBrowseableTabs(),
    };
  }
  let snap = {
    ok: true,
    url: tab.url || "",
    title: tab.title || "",
    vw: 1366,
    vh: 854,
    elements: [],
    headings: [],
    links: [],
    forms: [],
    text: "",
    main_text: "",
  };
  if (tab.url && /^https?:/i.test(tab.url)) {
    try {
      const results = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: pageScript,
        args: [{ op, ...extra }],
      });
      if (results && results[0] && results[0].result) {
        snap = results[0].result;
      }
    } catch (e) {
      const errMsg = String(e && e.message ? e.message : e).slice(0, 240);
      snap.error = errMsg;
      state.lastError = errMsg;
    }
  }
  latestTab = tab;
  latestSnapshot = snap;
  if (!opts || !opts.skipCapture) {
    frameDirty = true;
    state.frameDirty = true;
    kickFrameLoop();
  }
  const tabs = await listBrowseableTabs();
  return {
    ...snap,
    tabs,
    tab_id: tab.id,
    captureError: state.captureError || "",
    lastError: state.lastError || "",
    last_error: state.lastError || "",
  };
}

async function executeCommand(cmd) {
  const op = cmd.op;
  try {
    if (op === "frame" || op === "shot") {
      const snap = latestSnapshot || {};
      return {
        ok: true,
        png: latestFrame.png || "",
        frame_seq: latestFrame.seq || 0,
        vw: snap.vw || 1366,
        vh: snap.vh || 854,
        captureError: state.captureError || "",
      };
    }
    if (op === "tabs") {
      return { ok: true, tabs: await listBrowseableTabs(), tab_id: state.targetTabId };
    }
    if (op === "switch_tab") {
      const tid = Number(cmd.tab_id);
      const t = await chrome.tabs.get(tid);
      if (!t || isStudioUrl(t.url)) {
        return { ok: false, error: "cannot switch to that tab" };
      }
      state.targetTabId = tid;
      saveState();
      await chrome.tabs.update(tid, { active: true });
      await new Promise((r) => setTimeout(r, 20));
      return await captureAndSnapshot(t, "snapshot");
    }
    if (op === "new_tab") {
      let url = String(cmd.url || "https://example.com").trim();
      if (url && !url.includes("://")) url = "https://" + url;
      if (!/^https?:\/\//i.test(url)) {
        return { ok: false, error: "only http(s) pages are allowed" };
      }
      const created = await chrome.tabs.create({ url, active: true });
      state.targetTabId = created.id;
      saveState();
      await waitForTabLoad(created.id, 8000);
      const updated = await chrome.tabs.get(created.id);
      return await captureAndSnapshot(updated, "snapshot");
    }
    if (op === "close_tab") {
      const tid = Number(cmd.tab_id || state.targetTabId);
      if (tid) {
        try {
          await chrome.tabs.remove(tid);
        } catch (_e) {}
      }
      if (state.targetTabId === tid) state.targetTabId = null;
      const next = await getTargetTab(false);
      return next ? await captureAndSnapshot(next, "snapshot") : { ok: true, tabs: await listBrowseableTabs() };
    }
    if (op === "navigate") {
      let url = String(cmd.url || "").trim();
      if (!url) return { ok: false, error: "no url" };
      if (!url.includes("://")) url = "https://" + url;
      if (!/^https?:\/\//i.test(url)) {
        return { ok: false, error: "only http(s) pages are allowed" };
      }
      let tab = await getTargetTab(true);
      await chrome.tabs.update(tab.id, { url, active: true });
      await waitForTabLoad(tab.id, 12000);
      tab = await chrome.tabs.get(tab.id);
      return await captureAndSnapshot(tab, "snapshot");
    }

    const tab = await getTargetTab(true);
    const beforeUrl = (tab && tab.url) || "";
    const needsSettle = ["click", "click_ref", "fill_ref", "key", "back", "forward", "reload"].includes(op);
    const out = await captureAndSnapshot(tab, op, cmd, { skipCapture: needsSettle });
    if (needsSettle) {
      await new Promise((r) => setTimeout(r, 20));
      let refreshed = await chrome.tabs.get(tab.id);
      if (op === "click_ref" && out && out.ok !== false) {
        if (refreshed && refreshed.status === "loading") {
          await waitForTabLoad(tab.id, 8000);
          refreshed = await chrome.tabs.get(tab.id);
        } else if (out.clicked_href && /^https?:\/\//i.test(out.clicked_href)) {
          const preUrl = out.pre_click_url || beforeUrl;
          const curUrl = (refreshed && refreshed.url) || out.url || beforeUrl;
          const sameDocHash =
            out.clicked_href.includes("#") &&
            out.clicked_href.split("#")[0] === preUrl.split("#")[0];
          if (curUrl === preUrl && out.clicked_href !== preUrl && !sameDocHash) {
            await chrome.tabs.update(tab.id, { url: out.clicked_href });
            await waitForTabLoad(tab.id, 8000);
            refreshed = await chrome.tabs.get(tab.id);
          }
        }
      }
      const after = await captureAndSnapshot(refreshed, "snapshot");
      return {
        ...after,
        ok: out.ok !== false,
        error: out.error || after.error || "",
        clicked_href: out.clicked_href || "",
      };
    }
    return out;
  } catch (e) {
    const errMsg = String(e && e.message ? e.message : e).slice(0, 300);
    state.lastError = errMsg;
    return { ok: false, error: errMsg, captureError: state.captureError || "", lastError: errMsg, last_error: errMsg };
  }
}

function waitForTabLoad(tabId, timeoutMs = 8000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      clearTimeout(probeTimer);
      if (chrome.tabs && chrome.tabs.onUpdated && chrome.tabs.onUpdated.removeListener) {
        chrome.tabs.onUpdated.removeListener(listener);
      }
      resolve();
    };
    const timer = setTimeout(finish, timeoutMs);
    function listener(tid, info) {
      if (tid === tabId && info && info.status === "complete") {
        setTimeout(finish, 20);
      }
    }
    if (chrome.tabs && chrome.tabs.onUpdated && chrome.tabs.onUpdated.addListener) {
      chrome.tabs.onUpdated.addListener(listener);
    }
    const probeTimer = setTimeout(async () => {
      try {
        const t = await chrome.tabs.get(tabId);
        if (!t || !t.status || t.status === "complete") {
          finish();
        }
      } catch (_e) {
        finish();
      }
    }, 20);
  });
}

// Separate connections for poll vs everything else: use keepalive: false, cache: "no-store",
// and distinct query markers (?lane=poll vs ?lane=data) so HTTP/1.1 connections to Studio's
// ThreadingHTTPServer are never coalesced and a poll fetch cannot queue behind an in-flight push.
async function defaultStudioFetch(path, method = "GET", body = null) {
  if (!state.confirmed || !state.token || !state.port) throw new Error("Missing confirmed pairing token");
  const headers = {
    "X-Aesop-Bridge-Token": state.token,
  };
  if (body !== null) {
    headers["Content-Type"] = "application/json";
  }
  const rawPath = String(path || "");
  const isPoll = rawPath.includes("/api/browser/bridge/poll");
  const lane = isPoll ? "poll" : "data";
  const fullPath = rawPath.includes("lane=")
    ? rawPath
    : `${rawPath}${rawPath.includes("?") ? "&" : "?"}lane=${lane}`;
  const resp = await fetch(`http://127.0.0.1:${state.port}${fullPath}`, {
    method,
    headers,
    body: body !== null ? JSON.stringify(body) : undefined,
    keepalive: false,
    cache: "no-store",
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return await resp.json();
}

var studioFetch = globalThis.studioFetch || defaultStudioFetch;

async function pushCurrentTabState() {
  if (!state.confirmed || !state.token || !state.port || commandInFlight) return;
  try {
    const tab = await getTargetTab(false);
    if (tab && tab.id) {
      await captureAndSnapshot(tab, "snapshot", {}, { skipCapture: true });
    } else {
      latestTab = null;
      latestSnapshot = null;
    }
    frameDirty = true;
    state.frameDirty = true;
    await kickFrameLoop();
  } catch (e) {
    state.captureError = String(e && e.message ? e.message : e).slice(0, 240);
  }
}

async function startBridgeLoop() {
  if (state.polling || !state.confirmed || !state.token || !state.port) return;
  state.polling = true;
  if (!state.paired) {
    pushCurrentTabState();
  }
  while (state.confirmed && state.token && state.polling) {
    try {
      const errParam = state.lastError ? `&last_error=${encodeURIComponent(state.lastError)}` : "";
      const res = await studioFetch(`/api/browser/bridge/poll?lane=poll&wait=1${errParam}`, "GET");
      state.paired = true;
      if (res && res.cmd && res.cmd.id) {
        commandInFlight = true;
        let out;
        try {
          out = await executeCommand(res.cmd);
        } catch (cmdErr) {
          const msg = String(cmdErr && cmdErr.message ? cmdErr.message : cmdErr).slice(0, 240);
          state.lastError = msg;
          out = { ok: false, error: msg, captureError: state.captureError || "", lastError: msg, last_error: msg };
        } finally {
          commandInFlight = false;
        }
        try {
          await studioFetch("/api/browser/bridge/reply?lane=data", "POST", {
            cmd_id: res.cmd.id,
            result: out,
          });
        } catch (replyErr) {
          state.lastError = String(replyErr && replyErr.message ? replyErr.message : replyErr).slice(0, 240);
          await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS));
          try {
            await studioFetch("/api/browser/bridge/reply?lane=data", "POST", {
              cmd_id: res.cmd.id,
              result: { ...out, lastError: state.lastError, last_error: state.lastError },
            });
          } catch (_e2) {}
        }
      }
    } catch (e) {
      state.lastError = String(e && e.message ? e.message : e).slice(0, 240);
      await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS));
    }
  }
  state.polling = false;
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (state.paired && !commandInFlight && tabId === state.targetTabId && changeInfo.status === "complete") {
    clearTimeout(state.pushTimer);
    state.pushTimer = setTimeout(() => {
      if (!commandInFlight) {
        frameDirty = true;
        state.frameDirty = true;
        kickFrameLoop();
      }
    }, 150);
  }
});

chrome.tabs.onActivated.addListener(async (activeInfo) => {
  if (!state.paired || commandInFlight) return;
  try {
    const t = await chrome.tabs.get(activeInfo.tabId);
    if (t && !isStudioUrl(t.url)) {
      state.targetTabId = t.id;
      latestTab = t;
      saveState();
      clearTimeout(state.pushTimer);
      state.pushTimer = setTimeout(() => {
        if (!commandInFlight) {
          frameDirty = true;
          state.frameDirty = true;
          kickFrameLoop();
        }
      }, 120);
    }
  } catch (_e) {}
});

function parseLoopbackHttpOrigin(rawUrl) {
  if (!rawUrl || typeof rawUrl !== "string") return null;
  try {
    const u = new URL(rawUrl);
    if (u.protocol !== "http:") return null;
    if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") return null;
    const port = u.port ? Number(u.port) : 80;
    if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
    return {
      protocol: u.protocol,
      hostname: u.hostname,
      port,
      origin: `http://127.0.0.1:${port}`,
    };
  } catch (_e) {
    return null;
  }
}

function validatePairSender(sender, msg) {
  const myId = chrome && chrome.runtime && chrome.runtime.id;
  if (!sender || typeof sender !== "object" || !myId || sender.id !== myId) {
    return { ok: false, error: "untrusted sender id" };
  }
  const tabUrl = sender.tab && typeof sender.tab.url === "string" ? sender.tab.url : "";
  const originUrl = typeof sender.origin === "string" ? sender.origin : "";
  if (!tabUrl && !originUrl) {
    return { ok: false, error: "missing sender tab origin" };
  }
  const parsedTab = tabUrl ? parseLoopbackHttpOrigin(tabUrl) : null;
  const parsedOrigin = originUrl ? parseLoopbackHttpOrigin(originUrl) : null;
  if (tabUrl && !parsedTab) {
    return { ok: false, error: "untrusted sender tab url" };
  }
  if (originUrl && !parsedOrigin) {
    return { ok: false, error: "untrusted sender origin" };
  }
  if (
    parsedTab &&
    parsedOrigin &&
    (parsedTab.port !== parsedOrigin.port || parsedTab.hostname !== parsedOrigin.hostname)
  ) {
    return { ok: false, error: "sender tab and origin mismatch" };
  }
  const derived = parsedOrigin || parsedTab;
  if (msg && msg.port !== undefined && msg.port !== null && msg.port !== "") {
    if (Number(msg.port) !== derived.port) {
      return { ok: false, error: "port does not match sender origin" };
    }
  }
  return { ok: true, port: derived.port, origin: derived.origin };
}

function isExtensionUiSender(sender) {
  const myId = chrome && chrome.runtime && chrome.runtime.id;
  if (!sender || typeof sender !== "object" || !myId || sender.id !== myId) {
    return false;
  }
  if (sender.tab) {
    return false;
  }
  return true;
}

function notifyPendingPair(pending) {
  updateActionBadge();
  if (chrome.notifications && chrome.notifications.create) {
    try {
      chrome.notifications.create("aesop-pair-confirm", {
        type: "basic",
        iconUrl:
          "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
        title: "Aesop Studio Browser Bridge",
        message: pending.prompt,
        buttons: [{ title: "Confirm Pairing" }, { title: "Reject" }],
        requireInteraction: true,
      });
    } catch (_e) {}
  }
}

async function approvePendingPair() {
  if (!state.pendingPair) {
    return { ok: false, error: "no pending pairing confirmation" };
  }
  const pending = state.pendingPair;
  state.pendingPair = null;
  state.port = pending.port;
  state.token = pending.token;
  state.confirmed = true;
  state.lastPairAttemptAt = 0;
  saveState();
  updateActionBadge();
  await pushCurrentTabState();
  if (!state.polling) startBridgeLoop();
  return { ok: state.paired, paired: state.paired, confirmed: true, port: state.port, error: state.lastError };
}

function rejectPendingPair() {
  state.pendingPair = null;
  saveState();
  updateActionBadge();
  return { ok: true, cancelled: true };
}

if (chrome.notifications && chrome.notifications.onButtonClicked) {
  chrome.notifications.onButtonClicked.addListener((notifId, btnIdx) => {
    if (notifId !== "aesop-pair-confirm") return;
    if (btnIdx === 0) {
      approvePendingPair();
    } else {
      rejectPendingPair();
    }
    if (chrome.notifications.clear) {
      chrome.notifications.clear("aesop-pair-confirm");
    }
  });
}

async function handlePairRequest(msg, sender) {
  const check = validatePairSender(sender, msg);
  if (!check.ok) {
    return { ok: false, error: check.error };
  }
  const originPort = check.port;
  const token = String((msg && msg.token) || "").trim();
  if (!token) {
    return { ok: false, error: "missing pairing token" };
  }

  // Ignore AESOP_PAIR messages while a confirmation is pending
  if (state.pendingPair) {
    return {
      ok: false,
      pending: true,
      port: state.pendingPair.port,
      prompt: state.pendingPair.prompt,
      error: "confirmation already pending",
    };
  }

  // Rate-limit AESOP_PAIR attempts
  const now = Date.now();
  if (state.lastPairAttemptAt > 0 && now - state.lastPairAttemptAt < PAIR_RATE_LIMIT_MS) {
    return {
      ok: false,
      rateLimited: true,
      error: "rate limited",
    };
  }
  state.lastPairAttemptAt = now;

  // Silent re-pair is allowed ONLY for the exact SAME port AND SAME token already confirmed
  if (state.confirmed && state.port === originPort && state.token === token) {
    await pushCurrentTabState();
    if (!state.polling) startBridgeLoop();
    return { ok: state.paired, paired: state.paired, confirmed: true, port: state.port, error: state.lastError };
  }

  // First pairing, any port change, or any token change requires explicit owner confirmation in extension UI
  const prompt = `Pair with Aesop Studio at 127.0.0.1:${originPort}?`;
  state.pendingPair = {
    port: originPort,
    token,
    origin: check.origin,
    prompt,
    requestedAt: now,
  };
  saveState();
  notifyPendingPair(state.pendingPair);
  return {
    ok: false,
    pendingConfirmation: true,
    port: originPort,
    prompt,
    error: "owner confirmation required in extension",
  };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg !== "object") return false;
  if (msg.type === "AESOP_PAIR") {
    handlePairRequest(msg, sender).then((res) => sendResponse(res));
    return true;
  }
  if (msg.type === "AESOP_CONFIRM_PAIR") {
    if (!isExtensionUiSender(sender)) {
      sendResponse({ ok: false, error: "confirmation must come from extension UI" });
      return false;
    }
    if (msg.approve) {
      approvePendingPair().then((res) => sendResponse(res));
      return true;
    }
    sendResponse(rejectPendingPair());
    return false;
  }
  if (msg.type === "AESOP_MANUAL_PAIR") {
    if (!isExtensionUiSender(sender)) {
      sendResponse({ ok: false, error: "manual pairing must come from extension UI" });
      return false;
    }
    const port = Number(msg.port || 8765);
    const token = String(msg.token || "").trim();
    if (!Number.isInteger(port) || port < 1 || port > 65535 || !token) {
      sendResponse({ ok: false, error: "invalid port or token" });
      return false;
    }
    state.pendingPair = null;
    state.port = port;
    state.token = token;
    state.confirmed = true;
    state.lastPairAttemptAt = 0;
    saveState();
    updateActionBadge();
    pushCurrentTabState().then(() => {
      if (!state.polling) startBridgeLoop();
      sendResponse({ ok: state.paired, confirmed: true, port: state.port, error: state.lastError });
    });
    return true;
  }
  if (msg.type === "AESOP_STATUS") {
    listBrowseableTabs().then((tabs) => {
      sendResponse({
        paired: state.paired,
        confirmed: state.confirmed,
        port: state.port,
        hasToken: !!state.token,
        targetTabId: state.targetTabId,
        lastError: state.lastError,
        captureError: state.captureError,
        pendingPair: state.pendingPair
          ? {
              port: state.pendingPair.port,
              origin: state.pendingPair.origin,
              prompt: state.pendingPair.prompt,
            }
          : null,
        tabs,
      });
    });
    return true;
  }
  if (msg.type === "AESOP_USE_TAB") {
    if (!isExtensionUiSender(sender)) {
      sendResponse({ ok: false, error: "untrusted sender" });
      return false;
    }
    state.targetTabId = Number(msg.tabId) || null;
    saveState();
    pushCurrentTabState().then(() => {
      sendResponse({ ok: true, targetTabId: state.targetTabId });
    });
    return true;
  }
  return false;
});

globalThis.__aesopBridgeTest = {
  state,
  PAIR_RATE_LIMIT_MS,
  MIN_CAPTURE_INTERVAL_MS,
  RETRY_BACKOFF_MS,
  parseLoopbackHttpOrigin,
  validatePairSender,
  handlePairRequest,
  approvePendingPair,
  rejectPendingPair,
  formatCaptureError,
  runSingleCapture,
  kickFrameLoop,
  resetCaptureState,
  captureAndSnapshot,
  executeCommand,
  pushCurrentTabState,
  startBridgeLoop,
  pageScript,
  get frameDirty() {
    return frameDirty;
  },
  set frameDirty(v) {
    frameDirty = !!v;
    state.frameDirty = !!v;
  },
  get latestFrame() {
    return latestFrame;
  },
  setStudioFetch(fn) {
    studioFetch = fn || defaultStudioFetch;
  },
};

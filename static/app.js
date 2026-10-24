"use strict";
// The DOM prints a skipped child (null/undefined/false) as text ("null"); drop them everywhere, as h() already does.
for (const P of [Element.prototype, DocumentFragment.prototype]) for (const m of ["replaceChildren", "append", "prepend"]) {
  const orig = P[m]; P[m] = function (...kids) { return orig.apply(this, kids.filter((k) => k !== null && k !== undefined && k !== false)); };
}
// All untrusted text is rendered with textContent via h(); never assign raw HTML.
const S = { csrf: "", routes: {}, projects: [], project: null, tab: "chat", conv: null, convTitle: "", global: null, poll: null,
  streams: {}, streamUpd: {}, streamConv: null, chatGen: 0, msgSig: "", taskSel: null, preview: null,
  itab: "preview", inspPref: true, ov: null, lay: { tab: "chat", w: {} }, activity: "" };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) el.append(k instanceof Node ? k : String(k));
  return el;
}
const $ = (id) => document.getElementById(id);
const fmtTime = (t) => (t ? new Date(t * 1000).toLocaleString() : "—");
const fmtClock = (t) => {
  if (!t) return "";
  const d = new Date(t * 1000); const now = new Date();
  return d.toDateString() === now.toDateString() ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};
// Real sub-cent spend must never read as $0.00: show 6 decimals below one cent, "<$0.000001" below that.
const fineUsd = (v) => (v === 0 ? "$0.00" : v < 0.000001 ? "<$0.000001" : v < 0.01 ? `$${v.toFixed(6)}` : `$${v.toFixed(2)}`);
const usd = (v) => (typeof v === "number" && isFinite(v) ? fineUsd(Math.abs(v)) .replace("$", v < 0 ? "-$" : "$") : "—");
const fmtCost = (v) => fineUsd(v);
const tone = (s) => {
  s = String(s);
  if (/^proposed$/i.test(s)) return "info";
  if (/DISABLED|unread/i.test(s)) return "warn";
  return /COMPLETED|READY_INCLUDED|READY_METERED|generated|cited|read|saved|current|ok/i.test(s) ? "ok"
    : /FAILED|BLOCKED|UNAVAILABLE|failed|unavailable|unsupported|malformed|too_large|encrypted|conflict|bad/i.test(s) ? "bad"
    : /RUNNING|STARTING|RESERVED|submitted|AUTH|HANDOFF|DISABLED|UNKNOWN|INTERRUPTED|stale|unread|SIMULATED/i.test(s) ? "warn" : "";
};
const statePill = (s) => h("span", { class: "pill " + tone(s) }, s);
const DONE = ["COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED", "BLOCKED_OWNER", "EFFECT_UNKNOWN"];
const USABLE = ["READY_INCLUDED", "SIMULATED", "READY_METERED"];
const usableRoutes = () => Object.entries(S.routes).filter(([, r]) => USABLE.includes(r.state));
const isMetered = (r) => !!r && /METERED/.test(r.state || "");
// The access route is always shown next to the provider so billing is never ambiguous.
const access = (state) => state === "READY_INCLUDED" ? "official CLI · plan quota"
  : /^READY_METERED/.test(state || "") ? "separately billed API"
  : state === "HANDOFF_ONLY" ? "native-site handoff"
  : state === "SIMULATED" ? "simulated test route" : "unavailable";
const hashIdx = (s, n) => { let x = 0; for (const c of String(s)) x = (x * 31 + c.charCodeAt(0)) >>> 0; return x % n; };
const initials = (s) => { const w = String(s || "?").trim().split(/[\s_\-.]+/).filter(Boolean); return ((w[0] || "?")[0] + (w.length > 1 ? w[1][0] : (w[0] || "").slice(1, 2))).toUpperCase(); };
const WS = { chat: "Chat", agent: "Build", memory: "Memory", artifacts: "Saved" }; // research lives inside Chat
const GL = { providers: "Providers", evidence: "Evidence" };

// ---------- icons (inline SVG via createElementNS; no markup strings) ----------
const SVGNS = "http://www.w3.org/2000/svg";
const ICONS = {
  plus: "M12 5v14M5 12h14", image: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15.5 8.5h.01", chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5", terminal: "M4 17l6-5-6-5M12 19h8",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4", layers: "M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5",
  bookmark: "M6 3h12v18l-6-4-6 4z", providers: "M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5",
  evidence: "M3 21h18M6 17v-5M11 17V6M16 17v-8M21 17v-3",
  settings: "M4 7h9M17 7h3M4 17h3M11 17h9M17 7a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM11 17a2 2 0 1 1-4 0 2 2 0 0 1 4 0z",
  send: "M12 19V5M5 12l7-7 7 7", eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  clip: "M21 11l-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z", check: "M5 12l5 5L20 7", x: "M6 6l12 12M18 6L6 18",
  alert: "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  info: "M12 16v-4M12 8h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0z", refresh: "M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16", download: "M12 4v12M7 11l5 5 5-5M4 20h16", menu: "M4 6h16M4 12h16M4 18h16",
  archive: "M3 4h18v4H3zM5 8v12h14V8M10 12h4", stop: "M7 7h10v10H7z", sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
  clock: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z", link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z", db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  dollar: "M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6", note: "M4 4h16v16H4zM8 9h8M8 13h8M8 17h5",
  help: "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0z",
  panel: "M3 4h18v16H3zM15 4v16", more: "M12 5h.01M12 12h.01M12 19h.01", users: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8", diff: "M12 3v12M6 9h12M6 21h12", trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3", list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
};
function icon(name, cls = "") {
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", ("ico " + cls).trim());
  s.setAttribute("aria-hidden", "true"); s.setAttribute("focusable", "false");
  const p = document.createElementNS(SVGNS, "path"); p.setAttribute("d", ICONS[name] || ICONS.info); s.append(p);
  return s;
}
function decorateIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => { if (!el.querySelector(":scope > svg")) el.prepend(icon(el.dataset.icon)); });
}

// ---------- building blocks ----------
function empty(ico, title, text, ...actions) {
  const one = text ? String(text).split(/(?<=[.!?])\s+/)[0] : "";
  return h("div", { class: "empty" }, h("div", { class: "eico" }, icon(ico)),
    h("div", { class: "et" }, title ? h("strong", {}, title) : null, one ? h("p", {}, one) : null, actions.length ? h("div", { class: "row" }, actions[0]) : null));
}
function section(title, desc, ...kids) {
  return h("section", { class: "section" }, h("div", { class: "section-head" }, h("h2", {}, title), desc ? h("p", {}, desc) : null), ...kids);
}
function table(headers, rows, caption) {
  return h("div", { class: "tablewrap" }, h("table", {}, caption ? h("caption", {}, caption) : null,
    h("thead", {}, h("tr", {}, ...headers.map((x) => h("th", {}, x)))), h("tbody", {}, ...rows)));
}
function btn(label, onclick, cls = "", ico) { return h("button", { class: "btn " + cls, type: "button", onclick }, ico ? icon(ico) : null, label); }
function routeDot(id) { const r = S.routes[id]; return h("span", { class: "dot " + (r ? tone(r.state) : ""), "aria-hidden": "true" }); }
// Owner naming rule: routes are always titled by display_name (e.g. "Codex API"), never by raw route ids.
function routeName(id) { const r = id && S.routes[id]; return r && r.display_name ? r.display_name : id || ""; }
function routeLabel(route) { const [rid, ...rest] = String(route || "").split("/"); return routeName(rid) + (rest.length ? " · " + rest.join("/") : ""); }
function routeTag(r) { return r ? h("span", { class: "tag " + (isMetered(r) ? "billed" : "route") }, access(r.state)) : null; }

// Origin key: delivered once in the launch redirect fragment, kept in sessionStorage, sent on every API call.
function takeKey() {
  const m = /(?:^#|&)k=([^&]+)/.exec(location.hash || "");
  if (m) {
    try { localStorage.setItem("aesop.key", decodeURIComponent(m[1])); } catch { /* storage blocked */ }
    try { history.replaceState(null, "", location.pathname + location.search); } catch { /* ignore */ }
  }
}
// The origin key persists in this origin's localStorage (other ports/sites cannot read it), so Studio stays signed
// in across tabs and browser restarts; the server-side session lasts 30 days and renews on use.
function apiKey() { try { return localStorage.getItem("aesop.key") || sessionStorage.getItem("aesop.key") || ""; } catch { return ""; } }
function signInCard() {
  navBump();
  $("view").replaceChildren(h("div", { class: "empty welcome" }, h("div", { class: "eico" }, icon("shield")), h("div", { class: "et" }, h("strong", {}, "Sign-in needed"),
    h("p", {}, "Reopen Studio from its launch link (start.ps1 opens one for you). This keeps other websites and local programs from using your Studio."))));
}
function authFail() { signInCard(); banner("Studio session not recognised. Reopen Studio from its launch link.", "bad"); }
async function api(method, path, body, raw, retried) {
  if (method !== "GET" && !retried) {
    try { return await api(method, path, body, raw, true); }
    catch (e) {
      // A newer sign-in (another tab, or reopening Studio) replaced this tab's session: the cookie and key are
      // shared, but this tab still held the old CSRF token. Fetch the current one and retry once.
      if (e.status !== 403 || !/CSRF/i.test(e.message)) throw e;
      const s = await api("GET", "/api/session"); S.csrf = s.csrf;
      return api(method, path, body, raw, true);
    }
  }
  const opts = { method, headers: { "X-Aesop-Key": apiKey() }, credentials: "same-origin" };
  if (method !== "GET") opts.headers["X-CSRF-Token"] = S.csrf;
  if (raw) { opts.body = raw.data; opts.headers["X-Filename"] = encodeURIComponent(raw.name); }
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, opts);
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    if (r.status === 401 && S.csrf) authFail();
    const e = new Error((data && data.error) || data.extract_note || r.statusText); e.status = r.status; e.data = data; throw e;
  }
  return data;
}
// Downloads must carry the key header, so they go through fetch + blob instead of a plain link.
async function download(path, fallbackName) {
  const r = await fetch(path, { headers: { "X-Aesop-Key": apiKey() }, credentials: "same-origin" });
  if (!r.ok) { if (r.status === 401) authFail(); let msg = r.statusText; try { const d = await r.json(); msg = d.error || msg; } catch { /* not json */ } throw new Error(msg); }
  const cd = r.headers.get("Content-Disposition") || ""; const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  let name = fallbackName; if (m) { try { name = decodeURIComponent(m[1]); } catch { name = m[1]; } }
  const url = URL.createObjectURL(await r.blob());
  const a = h("a", { href: url, download: name, class: "sr-only" }, "download");
  (document.querySelector("dialog[open]") || document.body).append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  banner(`Downloaded ${name}.`, "ok");
}
const dlBtn = (label, path, name, cls = "ghost") => abtn(label, () => guard(() => download(path, name)), cls, "download");
let bannerTimer = null;
function banner(msg, kind = "") {
  const b = $("banner");
  clearTimeout(bannerTimer);
  if (!msg) { b.hidden = true; return; }
  b.className = "banner " + kind;
  b.replaceChildren(icon(kind === "ok" ? "check" : kind === "bad" ? "alert" : "info", "bico"), h("div", { class: "btxt" }, msg),
    h("button", { class: "iconbtn bclose", type: "button", "aria-label": "Dismiss message", onclick: () => { b.hidden = true; } }, icon("x", "sm")));
  b.hidden = false;
  if (kind === "ok") bannerTimer = setTimeout(() => { b.hidden = true; }, 6500);
}
async function guard(fn) { try { banner(""); return await fn(); } catch (e) { banner(e.message, "bad"); } }
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* optional */ } }
function loadJSON(k, d) { try { const v = JSON.parse(localStorageGet(k) || "null"); return v && typeof v === "object" ? v : d; } catch { return d; } }

// ---------- dialogs ----------
function dialog(title, fields, submitLabel = "Save") {
  const d = $("dlg");
  if (d.open) { banner("Finish or cancel the open dialog first."); return Promise.resolve(null); }
  return new Promise((resolve) => {
    const f = $("dlgForm"); const opener = document.activeElement;
    f.replaceChildren(h("h2", { id: "dlgTitle" }, title), ...fields.map((fd) => h("div", { class: "field" }, h("label", {}, fd.label,
      fd.type === "select" ? h("select", { name: fd.name }, ...fd.options.map((o) => h("option", { value: o.value, selected: o.value === fd.value }, o.label)))
      : fd.type === "textarea" ? h("textarea", { name: fd.name, class: fd.tall ? "tall" : null, readonly: fd.readonly }, fd.value || "")
      : h("input", { name: fd.name, value: fd.value || "", type: fd.type || "text", required: fd.required, placeholder: fd.placeholder || "" })),
      fd.help ? h("p", { class: "muted" }, fd.help) : null)),
      h("div", { class: "actions" }, h("button", { class: "btn primary", value: "ok" }, submitLabel),
        submitLabel === "Close" ? null : h("button", { class: "btn ghost", value: "cancel", formnovalidate: true }, "Cancel")));
    d.onclose = () => {
      if (opener && opener.isConnected && opener.focus) opener.focus();
      if (d.returnValue !== "ok") return resolve(null);
      resolve(Object.fromEntries(new FormData(f).entries()));
    };
    d.returnValue = ""; d.showModal();
  });
}
function showShortcuts() {
  const rows = [[["Ctrl", "K"], "Open the command palette"], [["Ctrl", "Enter"], "Send message / start task"], [["Ctrl", "1"], "Chat"], [["Ctrl", "2"], "Build"],
    [["Ctrl", "3"], "Research notebook (in Chat)"], [["Esc"], "Close a dialog, drawer or sheet"], [["?"], "Show this list"], [["←", "→"], "Resize a focused panel divider"]];
  if ($("dlg").open || $("rtDlg").open) return Promise.resolve(null);
  const done = dialog("Keyboard shortcuts", [], "Close");
  $("dlgForm").insertBefore(h("dl", { class: "keylist" }, ...rows.flatMap(([k, d]) => [h("dt", {}, ...k.map((x) => h("kbd", {}, x))), h("dd", {}, d)])), $("dlgForm").querySelector(".actions"));
  return done;
}

// ---------- layout: breakpoints, docking, overlays, resizable panes ----------
const BOUNDS = { wide: { e: [200, 320, 248], i: [380, 480, 400], cmin: 620 }, std: { e: [180, 300, 220], i: [300, 420, 320], cmin: 480 }, lap: { e: [180, 280, 208] } };
function mode() {
  const w = window.innerWidth;
  return w >= 1600 ? "wide" : w >= 1280 ? "std" : w >= 1024 ? "lap" : w >= 768 ? "tab" : "mob";
}
const layKey = () => "aesop.ws." + (S.project ? S.project.id : "_");
function saveLay() { localStorageSet(layKey(), JSON.stringify(S.lay)); }
function paneW(kind) {
  const m = mode(); const b = BOUNDS[m] && BOUNDS[m][kind]; if (!b) return null;
  const v = S.lay.w && S.lay.w[m] && S.lay.w[m][kind];
  return Math.min(b[1], Math.max(b[0], typeof v === "number" ? v : b[2]));
}
function canDock() {
  const m = mode(); if (m !== "wide" && m !== "std") return false;
  const app = $("app"); const cs = getComputedStyle(app);
  const rail = parseFloat(cs.getPropertyValue("--rail")) || 64; const gap = parseFloat(cs.getPropertyValue("--gap")) || 10;
  return window.innerWidth - rail - paneW("e") - paneW("i") - gap * 4 >= BOUNDS[m].cmin;
}
function layout() {
  const app = $("app"); const m = mode();
  const expDock = m === "wide" || m === "std" || m === "lap";
  const inspDock = S.inspPref && canDock();
  const wasDocked = app.classList.contains("insp-docked");
  app.classList.toggle("exp-docked", expDock); app.classList.toggle("exp-overlay", !expDock);
  app.classList.toggle("insp-docked", inspDock);
  if (S.ov && ((S.ov.name === "explorer" && expDock) || (S.ov.name === "inspector" && inspDock))) closeOverlay(false);
  const e = paneW("e"), i = paneW("i");
  if (e) app.style.setProperty("--explorer-w", e + "px"); else app.style.removeProperty("--explorer-w");
  if (i) app.style.setProperty("--inspector-w", i + "px"); else app.style.removeProperty("--inspector-w");
  for (const [id, kind] of [["explorerSep", "e"], ["inspectorSep", "i"]]) {
    const b = BOUNDS[m] && BOUNDS[m][kind]; const sep = $(id);
    if (b) { sep.setAttribute("aria-valuemin", b[0]); sep.setAttribute("aria-valuemax", b[1]); sep.setAttribute("aria-valuenow", paneW(kind)); }
  }
  syncToggles();
  if (inspDock && !wasDocked && S.csrf) renderInspector();
}
function setPaneW(kind, v, persist) {
  const m = mode(); const b = BOUNDS[m] && BOUNDS[m][kind]; if (!b) return;
  S.lay.w = S.lay.w || {}; S.lay.w[m] = S.lay.w[m] || {};
  S.lay.w[m][kind] = Math.round(Math.min(b[1], Math.max(b[0], v)));
  layout(); if (persist) saveLay();
}
function setupSeparator(id, kind) {
  const sep = $(id); const pane = kind === "e" ? $("explorer") : $("inspector");
  sep.addEventListener("pointerdown", (ev) => {
    ev.preventDefault(); sep.setPointerCapture(ev.pointerId); sep.classList.add("drag");
    const move = (e2) => { const r = pane.getBoundingClientRect(); setPaneW(kind, kind === "e" ? e2.clientX - r.left : r.right - e2.clientX, false); };
    const up = () => { sep.classList.remove("drag"); sep.removeEventListener("pointermove", move); sep.removeEventListener("pointerup", up); sep.removeEventListener("pointercancel", up); saveLay(); };
    sep.addEventListener("pointermove", move); sep.addEventListener("pointerup", up); sep.addEventListener("pointercancel", up);
  });
  sep.addEventListener("keydown", (ev) => {
    const b = BOUNDS[mode()] && BOUNDS[mode()][kind]; if (!b) return;
    const cur = paneW(kind); const step = ev.shiftKey ? 32 : 8; const grow = kind === "e" ? 1 : -1;
    let v = null;
    if (ev.key === "ArrowRight") v = cur + step * grow; else if (ev.key === "ArrowLeft") v = cur - step * grow;
    else if (ev.key === "Home") v = b[0]; else if (ev.key === "End") v = b[1];
    if (v === null) return; ev.preventDefault(); setPaneW(kind, v, true);
  });
}
const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
const focusables = (el) => [...el.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null || x === document.activeElement);
function openOverlay(name, opener) {
  closeOverlay(false);
  const el = $(name); S.ov = { name, opener: opener || document.activeElement };
  $("app").classList.add(name === "explorer" ? "exp-open" : "insp-open");
  $("scrim").hidden = false; el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "true");
  syncToggles();
  setTimeout(() => { const f = focusables(el)[0]; (f || el).focus(); }, 30);
}
function closeOverlay(restore = true) {
  if (!S.ov) return;
  const { name, opener } = S.ov; S.ov = null; const el = $(name);
  $("app").classList.remove(name === "explorer" ? "exp-open" : "insp-open");
  $("scrim").hidden = true; el.removeAttribute("role"); el.removeAttribute("aria-modal");
  syncToggles();
  if (restore && opener && opener.isConnected && opener.focus) opener.focus();
}
function inspectorVisible() { return $("app").classList.contains("insp-docked") || (S.ov && S.ov.name === "inspector"); }
function syncToggles() {
  $("inspectorBtn").setAttribute("aria-expanded", inspectorVisible() ? "true" : "false");
  $("explorerBtn").setAttribute("aria-expanded", S.ov && S.ov.name === "explorer" ? "true" : "false");
}
function setInspPref(v) { S.inspPref = v; localStorageSet("aesop.inspector", v ? "1" : "0"); layout(); }
function toggleInspector(opener) {
  if (S.ov && S.ov.name === "inspector") { closeOverlay(); return; }
  const m = mode();
  if ((m === "wide" || m === "std") && $("app").classList.contains("insp-docked")) { setInspPref(false); return; }
  if (m === "wide" || m === "std") setInspPref(true);
  if (!inspectorVisible()) openOverlay("inspector", opener);
  renderInspector();
}
function openInspector(tab, opener) {
  setItab(tab);
  if (!inspectorVisible()) {
    if (canDock()) setInspPref(true); else openOverlay("inspector", opener);
  }
  renderInspector();
}
function setupShell() {
  decorateIcons();
  S.inspPref = localStorageGet("aesop.inspector") !== "0";
  const it = localStorageGet("aesop.itab"); if (["preview", "files", "changes", "terminal", "logs"].includes(it)) S.itab = it;
  setupSeparator("explorerSep", "e"); setupSeparator("inspectorSep", "i");
  $("explorerBtn").onclick = (e) => (S.ov && S.ov.name === "explorer" ? closeOverlay() : openOverlay("explorer", e.currentTarget));
  $("explorerClose").onclick = () => closeOverlay();
  $("inspectorBtn").onclick = (e) => toggleInspector(e.currentTarget);
  $("inspectorClose").onclick = () => { if (S.ov && S.ov.name === "inspector") closeOverlay(); else { setInspPref(false); $("inspectorBtn").focus(); } };
  document.querySelectorAll("#itabs [data-itab]").forEach((b) => { b.id = "itab-" + b.dataset.itab; });
  $("scrim").onclick = () => closeOverlay();
  $("paletteBtn").onclick = openPalette;
  $("helpBtn").onclick = showShortcuts;
  document.querySelectorAll("#itabs [data-itab]").forEach((b) => (b.onclick = () => { setItab(b.dataset.itab); renderInspector(); }));
  $("itabs").addEventListener("keydown", (e) => {
    if (!["ArrowRight", "ArrowLeft"].includes(e.key)) return;
    const tabs = [...document.querySelectorAll("#itabs [data-itab]")]; const i = tabs.findIndex((t) => t.dataset.itab === S.itab);
    const n = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length]; setItab(n.dataset.itab); renderInspector(); n.focus();
  });
  setItab(S.itab);
  let rt = null; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(layout, 60); });
  document.addEventListener("keydown", globalKeys);
  layout();
}
function isTyping(t) { return !!(t && t.closest && t.closest("input:not([type=checkbox]):not([type=radio]):not([type=file]), textarea, [contenteditable='true']")); }
function globalKeys(e) {
  const dlgOpen = !!document.querySelector("dialog[open]");
  if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K")) { e.preventDefault(); if (!dlgOpen) openPalette(); return; }
  if (dlgOpen) return;
  if (e.key === "Escape" && S.ov) { e.preventDefault(); closeOverlay(); return; }
  if (e.key === "Tab" && S.ov) {
    const el = $(S.ov.name); const f = focusables(el); if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (!el.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    return;
  }
  if (isTyping(e.target)) return;
  if (e.ctrlKey && !e.altKey && !e.shiftKey && ["1", "2", "3"].includes(e.key) && S.project) {
    e.preventDefault();
    if (e.key === "3") { openResearch(); return; }
    setTab(["chat", "agent"][Number(e.key) - 1]); return;
  }
  if (e.key === "?" && !e.ctrlKey && !e.altKey) { e.preventDefault(); showShortcuts(); }
}

// ---------- breadcrumb + route indicator ----------
function crumbs() {
  const parts = S.global ? ["Studio", GL[S.global]] : S.project ? [S.project.name, WS[S.tab] || "", S.activity] : ["Studio", "Welcome"];
  $("crumbs").replaceChildren(...parts.filter(Boolean).map((p, i, a) => h("li", i === a.length - 1 ? { "aria-current": "page" } : {}, h("span", {}, p))));
}
function setActivity(a) { S.activity = a || ""; crumbs(); }
function routeIndicator() {
  const el = $("routeInd"); const p = S.project;
  if (!p) { el.hidden = true; return; }
  const r = S.routes[p.provider_default];
  el.hidden = false;
  el.setAttribute("title", p.provider_default ? `${routeName(p.provider_default)}: ${r ? r.state : "unknown"}` : "No default provider chosen");
  el.replaceChildren(p.provider_default ? routeDot(p.provider_default) : h("span", { class: "dot" }), h("b", {}, routeName(p.provider_default) || "No provider"),
    h("span", { class: "rt" }, r ? access(r.state) : p.provider_default ? "unavailable" : "choose one in the workspace header"));
}

// ---------- command palette ----------
let PAL = { items: [], sel: 0, opener: null };
function paletteItems() {
  const it = [];
  if (S.project) for (const [k, v] of Object.entries(WS)) it.push({ g: "Workspace", ico: { chat: "chat", agent: "terminal", memory: "layers", artifacts: "bookmark" }[k], label: `Go to ${v}`, key: { chat: "Ctrl 1", agent: "Ctrl 2" }[k], run: () => setTab(k) });
  if (S.project) it.push({ g: "Workspace", ico: "search", label: "Open the research notebook (in Chat)", key: "Ctrl 3", run: () => openResearch() });
  for (const p of S.projects) it.push({ g: "Project", ico: "folder", label: `Switch to ${p.name}`, hint: p.root, run: () => openProject(p.id) });
  it.push({ g: "Action", ico: "plus", label: "New project", run: newProject });
  if (S.project) it.push({ g: "Action", ico: "users", label: "Start a roundtable", run: () => openRoundtable(PAL.opener, { mode: "general", roster: rtStoredSel(S.project.id) }) });
  if (S.project) it.push({ g: "Action", ico: "shield", label: "Start a War Room", run: () => openRoundtable(PAL.opener, { mode: "war_room" }) });
  if (S.project) it.push({ g: "Action", ico: "chat", label: "New conversation", run: () => { const pid = S.project.id; guard(async () => { const c = await api("POST", `/api/projects/${pid}/conversations`, {}); if (S.project && S.project.id === pid) { S.conv = c.id; setTab("chat"); } }); } });
  it.push({ g: "Studio", ico: "providers", label: "Open Providers", run: () => openGlobal("providers") });
  it.push({ g: "Studio", ico: "evidence", label: "Open Evidence", run: () => openGlobal("evidence") });
  it.push({ g: "View", ico: "panel", label: "Toggle inspector", run: () => toggleInspector($("inspectorBtn")) });
  for (const t of ["preview", "files", "changes", "terminal", "logs"]) it.push({ g: "View", ico: "panel", label: `Inspector: ${t[0].toUpperCase() + t.slice(1)}`, run: () => openInspector(t, $("inspectorBtn")) });
  if (S.project) it.push({ g: "Action", ico: "users", label: "Roundtable history", run: async () => { await setTab("artifacts"); const el = $("rtHistory"); if (el) el.scrollIntoView({ block: "start" }); } });
  it.push({ g: "Help", ico: "help", label: "Keyboard shortcuts", key: "?", run: showShortcuts });
  return it;
}
function openPalette() {
  if (document.querySelector("dialog[open]")) return;
  closeOverlay(false);
  const d = $("palette"); const input = $("palInput");
  PAL = { items: paletteItems(), sel: 0, opener: document.activeElement };
  input.value = ""; drawPalette(); d.showModal(); input.focus();
}
function filteredPal() {
  const q = $("palInput").value.trim().toLowerCase();
  return q ? PAL.items.filter((x) => (x.label + " " + x.g + " " + (x.hint || "")).toLowerCase().includes(q)) : PAL.items;
}
function drawPalette() {
  const list = $("palList"); const items = filteredPal(); PAL.sel = Math.min(PAL.sel, Math.max(0, items.length - 1));
  list.replaceChildren(...(items.length ? items.map((x, i) => h("li", { role: "option", id: "pal-" + i, "aria-selected": i === PAL.sel ? "true" : "false",
    onclick: () => runPal(x), onmousemove: () => { if (PAL.sel !== i) { PAL.sel = i; drawPalette(); } } },
  icon(x.ico), h("span", { class: "pl" }, x.label), h("span", { class: "pk" }, x.key || x.g))) : [h("li", { class: "pal-empty", role: "option", "aria-disabled": "true" }, "No matching command")]));
  $("palInput").setAttribute("aria-activedescendant", items.length ? "pal-" + PAL.sel : "");
  const cur = $("pal-" + PAL.sel); if (cur) cur.scrollIntoView({ block: "nearest" });
}
function runPal(x) { $("palette").close(); setTimeout(() => x.run(), 0); }
function setupPalette() {
  const d = $("palette"); const input = $("palInput");
  input.addEventListener("input", () => { PAL.sel = 0; drawPalette(); });
  input.addEventListener("keydown", (e) => {
    const items = filteredPal();
    if (e.key === "ArrowDown") { e.preventDefault(); PAL.sel = (PAL.sel + 1) % Math.max(1, items.length); drawPalette(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); PAL.sel = (PAL.sel - 1 + items.length) % Math.max(1, items.length); drawPalette(); }
    else if (e.key === "Enter") { e.preventDefault(); if (items[PAL.sel]) runPal(items[PAL.sel]); }
  });
  d.addEventListener("click", (e) => { if (e.target === d) d.close(); });
  d.addEventListener("close", () => { const o = PAL.opener; if (o && o.isConnected && o.focus && document.activeElement === document.body) o.focus(); });
}

// ---------- roundtable (design-ready, NON-EXECUTING: Start is always disabled) ----------
const RT_OUTCOMES = ["architecture review", "adversarial challenge", "code design", "research synthesis", "creative ideation", "incident diagnosis"];
const RT_TIME = { general: [[5, 10, 15, 20, 30], 15], war_room: [[4, 6, 8, 10], 8] };
const RT_WINDOWS = [15, 30, 45];
const RT_CLASS = { admin: "admin", speaker: "speaker", research: "research-only", review: "review-only" };
const RT_MODES = { general: "General Roundtable", war_room: "Admin War Room" };
const RT_FILTERS = [["all", "All"], ["speakers", "Speakers"], ["research", "Research"], ["review", "Review"], ["ready", "Ready only"]];
const RT_NOT_LIVE = "Live sessions are off. Use the Live switch at the top of this window.";
const LIVE_END = ["COMPLETED", "STOPPED", "FAILED", "INTERRUPTED"];
let RT = null;

function rtBlank() {
  return { mode: "general", objective: "", deliverable: "", outcome_type: RT_OUTCOMES[0], time_limit_min: 15, response_window_s: 30,
    max_turns: "", max_msgs: "", cost_cap: "", research: true, max_research: "", ack: false, roster: new Set() };
}
function rtFromRecord(r) {
  const mode = RT_TIME[r.mode] ? r.mode : "general"; const c = r.caps || {};
  const s = (v) => (v === null || v === undefined ? "" : String(v));
  return { mode, objective: r.objective || "", deliverable: r.deliverable || "", outcome_type: r.outcome_type || RT_OUTCOMES[0],
    time_limit_min: r.time_limit_min || RT_TIME[mode][1], response_window_s: r.response_window_s || 30,
    max_turns: s(c.max_turns), max_msgs: s(c.max_messages_per_speaker), cost_cap: s(c.cost_cap_usd), ack: !!r.sharing_ack,
    research: c.research !== false, max_research: s(c.max_research),
    roster: new Set((r.roster || []).map((x) => (typeof x === "string" ? x : x.lane))) };
}
const rtLane = (id) => RT.lanes.find((l) => l.id === id);
const rtSelected = () => [...RT.f.roster].map(rtLane).filter(Boolean);
const rtQualified = () => rtSelected().filter((l) => l.counts_as_speaker && l.lane_class !== "research" && l.lane_class !== "review");
function rtBlockedReason(l) {
  if (RT.f.mode === "war_room" && l.lane_class !== "admin") return "Admin War Room accepts admin lanes only.";
  if (l.readiness === "NOT_DETECTED") return "Not detected on this machine.";
  if (l.readiness === "BLOCKED_POLICY") return "Blocked by policy.";
  return "";
}
// Announce inside the modal (outside content is inert while it is open) and through the app's aria-live banner.
function rtSay(msg, kind = "") {
  const el = $("rtStatus"); if (el) { el.className = "rt-status " + kind; el.textContent = msg; }
  banner(msg, kind);
}
function setupRoundtable() {
  $("rtDlg").addEventListener("close", () => {
    if (!RT) return;
    clearTimeout(RT.timer); clearTimeout(RT.compareTimer); clearInterval(RT.liveTimer); const o = RT.opener; RT = null;
    if (o && o.isConnected && o.focus) o.focus();
  });
}
const rtCompareData = () => {
  const c = RT && RT.compare;
  return c && typeof c === "object" && !Array.isArray(c) ? c : null;
};
function rtCanCompare() {
  if (!RT || !RT.live || !RT.f.ack || rtQualified().length < 2) return false;
  const live = (RT.rec && RT.rec.live_status) || "DRAFT";
  if (live !== "DRAFT") return false;
  const cmp = rtCompareData();
  return !(cmp && cmp.status === "RUNNING");
}
function rtCompareRender() {
  if (!RT || !RT.el.compare) return;
  const cmp = rtCompareData();
  const kids = [h("h3", { id: "rtCmpH" }, "Side-by-side compare"),
    h("p", { class: "muted" }, "Sends the objective once to up to four qualified speakers (read-only chat). Live roundtables must be on; nothing here is executed.")];
  const run = abtn("Run compare", () => rtCompareRun(), "sm", "layers");
  run.disabled = !rtCanCompare();
  kids.push(h("div", { class: "row" }, run));
  if (cmp && cmp.status === "BLOCKED" && (cmp.block_reasons || []).length) {
    kids.push(h("div", { class: "note bad" }, icon("alert"), h("ul", {}, ...cmp.block_reasons.map((r) => h("li", {}, r)))));
  } else if (cmp) {
    kids.push(h("p", { class: "faint" }, `Status: ${cmp.status}${cmp.ended_at ? " · " + fmtTime(cmp.ended_at) : ""}`));
    if (cmp.error) kids.push(h("p", { class: "muted" }, cmp.error));
    for (const r of cmp.results || []) {
      kids.push(h("div", { class: "rt-answer" },
        h("div", { class: "card-head" }, h("strong", {}, r.name || r.lane), statePill(r.state || "—"),
          h("span", { class: "faint" }, r.latency_s != null ? `${r.latency_s}s` : "")),
        r.error ? h("p", { class: "muted" }, r.error) : null,
        h("pre", { class: "out" }, r.text || "(no text returned)")));
    }
  }
  RT.el.compare.replaceChildren(...kids);
}
async function rtCompareRun() {
  const s = RT; if (!s || !rtCanCompare()) { rtSay("Compare is not available yet. Turn live roundtables on, acknowledge sharing, pick at least two speakers, and save."); return; }
  const rec = await rtSave(true); if (!rec || RT !== s || s.rec.id !== rec.id) return;
  const gen = ++s.compareGen;
  try {
    const out = await api("POST", `/api/roundtables/${rec.id}/compare`, { confirm: true });
    if (RT !== s || s.compareGen !== gen || !s.rec || s.rec.id !== rec.id) return;
    s.compare = out;
    rtCompareRender();
    if (out.status === "RUNNING") rtComparePoll();
    else rtSay(out.status === "COMPLETED" ? "Side-by-side compare finished." : `Compare ${String(out.status).toLowerCase()}.`, out.status === "COMPLETED" ? "ok" : "");
  } catch (e) {
    if (RT !== s) return;
    if (e.data && e.data.status === "BLOCKED") { s.compare = e.data; rtCompareRender(); }
    rtSay(e.message, "bad");
  }
}
async function rtComparePoll() {
  const s = RT; if (!s || !s.rec) return;
  const gen = s.compareGen; const rid = s.rec.id;
  clearTimeout(s.compareTimer);
  try {
    const rec = await api("GET", `/api/roundtables/${rid}`);
    if (RT !== s || s.compareGen !== gen || !s.rec || s.rec.id !== rid) return;
    s.rec = rec;
    s.compare = rec.compare;
    rtCompareRender();
    const st = rtCompareData()?.status;
    if (st === "RUNNING") s.compareTimer = setTimeout(() => rtComparePoll(), 1500);
    else if (st === "COMPLETED") rtSay("Side-by-side compare finished.", "ok");
  } catch {
    if (RT === s) s.compareTimer = setTimeout(() => rtComparePoll(), 3000);
  }
}
const RT_ADMINS = [["openai", "Codex"], ["claude", "Claude Code"], ["cursor", "Cursor"]];
function rtApplyMode(f, mode, roster) {
  f.mode = mode;
  if (mode === "war_room") { f.time_limit_min = 8; f.response_window_s = 30; f.roster = new Set(RT_ADMINS.map(([id]) => id)); }
  else { f.time_limit_min = RT_TIME.general[1]; if (roster) f.roster = new Set(roster); }
}
async function openRoundtable(opener, opts = {}) {
  if (!S.project) { banner("Open a project first to configure a roundtable."); return; }
  if ($("dlg").open || $("rtDlg").open) return;
  closeOverlay(false);
  const s = RT = { opener: opener || document.activeElement, pid: S.project.id, lanes: [], gates: [], example: [], discovered: null, drafts: [], rec: null, pre: null, preStale: false,
    compare: null, compareGen: 0, compareTimer: null,
    f: rtBlank(), filter: "all", q: "", timer: null, loading: true, err: "", el: {}, gen: 0 };
  rtApplyMode(s.f, opts.mode === "war_room" ? "war_room" : "general", opts.roster);
  rtBuild(); $("rtDlg").showModal(); $("rtObjective").focus();
  try {
    const [lanes, drafts, rsr] = await Promise.all([api("GET", "/api/roundtable/lanes"), api("GET", `/api/projects/${s.pid}/roundtables`),
      api("GET", "/api/roundtable/researcher").catch(() => null)]);
    if (RT !== s) return;
    s.researcher = rsr;
    s.lanes = lanes.lanes || []; s.gates = lanes.mission_gates || []; s.example = lanes.documented_example || [];
    s.discovered = lanes.discovered_at || null; s.live = !!lanes.live_authorized; s.drafts = Array.isArray(drafts) ? drafts : [];
  } catch (e) { if (RT === s) s.err = e.message; }
  if (RT !== s) return;
  s.loading = false; rtResearchRender(); rtLanesRender(); rtRefresh(); rtGatesRender(); rtSideRender(); rtDraftsRender(); rtStartRender(); rtLiveRender();
  if (!s.err && !s.live) await rtSetLive(true, true); // opening Roundtable / War Room is the go-ahead; it switches off 30 s after a session
  clearInterval(s.liveTimer);
  s.liveTimer = setInterval(async () => {
    if (RT !== s) { clearInterval(s.liveTimer); return; }
    try { const r = await api("GET", "/api/roundtable/live-authorization"); if (RT === s && !!r.live_authorized !== !!s.live) rtLiveApply(!!r.live_authorized); } catch { /* next tick */ }
  }, 4000);
}
const RT_LIVE_GATE = "LIVE_ROUNDTABLES_OFF";
function rtLiveApply(on) {
  const s = RT; if (!s) return;
  s.live = on;
  s.gates = on ? (s.gates || []).filter((g) => g.code !== RT_LIVE_GATE)
    : (s.gates || []).some((g) => g.code === RT_LIVE_GATE) ? s.gates : [...(s.gates || []), { code: RT_LIVE_GATE, reason: RT_NOT_LIVE }];
  if (s.pre && !on) s.preStale = true;
  rtLiveRender(); rtGatesRender(); rtStartRender(); rtSideRender();
}
function rtLiveRender() {
  const s = RT; if (!s || !s.el || !s.el.liveSw) return;
  s.el.liveSw.setAttribute("aria-checked", s.live ? "true" : "false");
  s.el.liveState.textContent = s.loading ? "…" : s.live ? "On" : "Off";
}
async function rtSetLive(on, auto) {
  const s = RT; if (!s) return false;
  try {
    const r = await api("POST", "/api/roundtable/live-authorization", { enabled: !!on });
    if (RT !== s) return false;
    rtLiveApply(!!r.live_authorized);
    if (!auto) rtSay(`Live sessions turned ${r.live_authorized ? "on" : "off"}.`, "ok");
    else if (r.live_authorized) rtSay("Live sessions are on (they switch off by themselves 30 s after a session ends).");
    return !!r.live_authorized;
  } catch (e) { if (RT === s) rtSay(e.message, "bad"); return false; }
}
// Any edit after a preflight makes its pass/fail list out of date until the next check.
function rtStale() {
  if (!RT) return;
  if (RT.pre && !RT.preStale) { RT.preStale = true; rtSideRender(); rtStartRender(); }
  if (rtCompareData() && rtCompareData().status === "COMPLETED") { RT.compare = null; rtCompareRender(); }
}
// Buttons that start a request are disabled until it settles, so double clicks never send twice.
function abtn(label, fn, cls = "", ico) {
  const b = btn(label, async (e) => {
    if (b.disabled) return;
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try { await fn(e); } finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  }, cls, ico);
  return b;
}
// ---------- deletion ----------
const DEL_SENTENCE = { conv: "Delete this conversation and its messages? This can't be undone.",
  rt: "Delete this roundtable session and its events? This can't be undone." };
const confirmDelete = async (kind) => !!(await dialog(DEL_SENTENCE[kind], [], "Delete"));
async function deleteConversation(pid, cid) {
  if (!(await confirmDelete("conv"))) return;
  await guard(async () => {
    let order = [];
    try { order = (await api("GET", `/api/projects/${pid}/conversations`)).map((c) => c.id); } catch { /* best effort */ }
    const r = await api("POST", `/api/projects/${pid}/conversations/${cid}/delete`);
    if (!S.project || S.project.id !== pid) return;
    if (S.conv === cid) { const i = order.indexOf(cid); const rest = order.filter((x) => x !== cid); S.conv = rest.length ? rest[Math.min(Math.max(i, 0), rest.length - 1)] : null; }
    delete chatChips[cid];
    banner((r && r.note) || "Conversation deleted.", "ok");
    await refresh("chat");
    const focusEl = document.querySelector('.convstrip [aria-current="true"]') || document.querySelector("#view .empty .btn");
    if (focusEl && focusEl.focus) focusEl.focus();
  });
}
// Deletes one roundtable record. A 409 (running/paused) is reported as busy instead of thrown.
async function rtDeleteOne(id) {
  try { const r = await api("POST", `/api/roundtables/${id}/delete`); rtForget(id); return { ok: true, r }; }
  catch (e) { if (e.status === 409) return { ok: false, busy: true, msg: `${e.message} Stop the session first, then delete it.` }; throw e; }
}
// If the deleted record is open in the modal (draft or room), drop it and return to a blank form.
function rtForget(id) {
  const s = RT; if (!s) return;
  s.drafts = s.drafts.filter((d) => d.id !== id);
  if ((s.rec && s.rec.id === id) || s.roomId === id) {
    clearTimeout(s.timer); s.gen++; s.rec = null; s.roomId = null; s.pre = null; s.preStale = false;
    const mode = s.f.mode; s.f = rtBlank(); rtApplyMode(s.f, mode);
    rtBuild("rtObjective"); rtLanesRender(); rtRefresh(); rtGatesRender(); rtSideRender(); rtStartRender();
  }
  if (s.el.drafts && s.el.drafts.isConnected) rtDraftsRender();
}
function delBtn(label, aria, fn) { const b = abtn(label, fn, "ghost danger sm del", "trash"); b.setAttribute("aria-label", aria); return b; }
function rtBuild(focusId) {
  const f = RT.f; const el = RT.el = {};
  $("rtDlg").classList.remove("rooming");
  const fld = (id, label, control, help) => h("div", { class: "field" }, h("label", { for: id }, label), control, help ? h("p", { class: "faint", id: id + "-help" }, help) : null);
  // participants
  const search = h("input", { id: "rtSearch", type: "search", placeholder: "Search lanes…", value: RT.q, oninput: (e) => { RT.q = e.target.value; rtLanesRender(); } });
  const setFilter = (k, focus) => {
    RT.filter = k;
    filters.querySelectorAll("button").forEach((b) => { const on = b.dataset.f === k; b.setAttribute("aria-checked", on ? "true" : "false"); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus(); });
    rtLanesRender();
  };
  const filters = h("div", { class: "seg", role: "radiogroup", "aria-label": "Filter lanes" }, ...RT_FILTERS.map(([k, label]) => h("button", { type: "button", role: "radio", "data-f": k,
    "aria-checked": RT.filter === k ? "true" : "false", tabindex: RT.filter === k ? "0" : "-1", onclick: () => setFilter(k, false),
    onkeydown: (e) => {
      const keys = RT_FILTERS.map(([x]) => x); const i = keys.indexOf(RT.filter); let n = null;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") n = keys[(i + 1) % keys.length];
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = keys[(i - 1 + keys.length) % keys.length];
      else if (e.key === "Home") n = keys[0]; else if (e.key === "End") n = keys[keys.length - 1];
      if (n === null) return; e.preventDefault(); setFilter(n, true);
    } }, label)));
  el.lanes = h("div", { class: "rt-lanes", role: "group", "aria-label": "Provider lanes" });
  el.counter = h("p", { class: "rt-counter", "aria-live": "polite" });
  el.example = h("p", { class: "faint" });
  const part = f.mode === "war_room"
    ? h("section", { class: "rt-col rt-part", "aria-labelledby": "rtPartH" }, h("h3", { id: "rtPartH" }, "Administrators"),
      h("p", { class: "faint" }, "The War Room roster is fixed to the three administrator lanes."), el.counter, el.lanes)
    : h("section", { class: "rt-col rt-part", "aria-labelledby": "rtPartH" }, h("h3", { id: "rtPartH" }, "Participants"),
      h("div", { class: "field" }, h("label", { for: "rtSearch", class: "sr-only" }, "Search lanes"), search), filters, el.counter, el.lanes, el.example);
  // centre
  el.gates = h("div");
  const objective = h("textarea", { id: "rtObjective", required: true, "aria-required": "true", placeholder: "What should the roundtable decide or produce?",
    oninput: (e) => { f.objective = e.target.value; rtResetAck(); rtRefresh(); rtStale(); } }, f.objective);
  const outcome = h("select", { id: "rtOutcome", onchange: (e) => { f.outcome_type = e.target.value; rtStale(); } }, ...RT_OUTCOMES.map((o) => h("option", { value: o, selected: o === f.outcome_type }, o)));
  const deliverable = h("input", { id: "rtDeliverable", value: f.deliverable, placeholder: "e.g. a ranked list of risks with mitigations", oninput: (e) => { f.deliverable = e.target.value; rtStale(); } });
  const [times] = RT_TIME[f.mode];
  const time = h("select", { id: "rtTime", onchange: (e) => { f.time_limit_min = Number(e.target.value); rtStale(); } }, ...times.map((t) => h("option", { value: String(t), selected: t === Number(f.time_limit_min) }, `${t} min`)));
  const win = f.mode === "war_room" ? h("select", { id: "rtWindow", onchange: (e) => { f.response_window_s = Number(e.target.value); rtStale(); } }, ...RT_WINDOWS.map((t) => h("option", { value: String(t), selected: t === Number(f.response_window_s) }, `${t} s`))) : null;
  const num = (id, key, ph, step) => h("input", { id, type: "number", min: "0", step: step || "1", value: f[key], placeholder: ph, oninput: (e) => { f[key] = e.target.value; rtStale(); } });
  el.sharePrev = h("div", { class: "rt-share-prev" });
  el.ack = h("input", { id: "rtAck", type: "checkbox", required: true, "aria-required": "true", onchange: (e) => { f.ack = e.target.checked; rtRefresh(); rtStale(); } });
  el.ack.checked = f.ack;
  el.drafts = h("div", { class: "section" });
  const main = h("section", { class: "rt-col rt-main", "aria-label": "Roundtable setup" }, el.gates,
    fld("rtObjective", "Objective (required)", objective),
    h("div", { class: "rt-row2" }, fld("rtOutcome", "Outcome type", outcome), fld("rtDeliverable", "Desired deliverable", deliverable)),
    h("div", { class: "rt-row3" }, fld("rtTime", f.mode === "war_room" ? "Time limit (War Room)" : "Time limit", time), win ? fld("rtWindow", "Response window", win) : null),
    h("fieldset", { class: "rt-caps" }, h("legend", {}, "Caps"), h("div", { class: "rt-row3" }, fld("rtTurns", "Max turns", num("rtTurns", "max_turns", "e.g. 12")),
      fld("rtMsgs", "Max messages per speaker", num("rtMsgs", "max_msgs", "e.g. 3")), fld("rtCost", "Cost cap (USD)", num("rtCost", "cost_cap", "0.00", "0.01")))),
    (el.research = h("fieldset", { class: "rt-caps rt-research" })),
    h("section", { class: "card rt-share", "aria-labelledby": "rtShareH" }, h("h3", { id: "rtShareH" }, "External-sharing preview"),
      h("p", { class: "muted" }, "This is exactly what would leave this machine, and who would receive it. Changing the objective or the roster clears your confirmation."),
      el.sharePrev, h("label", { class: "rt-ack", for: "rtAck" }, el.ack, h("span", {}, "I've reviewed what would be shared"))),
    (el.compare = h("section", { class: "section rt-compare", "aria-labelledby": "rtCmpH" })),
    h("section", { class: "section", "aria-labelledby": "rtTransH" }, h("h3", { id: "rtTransH" }, "Transcript preview"),
      empty("chat", "No transcript yet", "The transcript appears in the live room once a session starts. Start needs a current, passing preflight.")),
    el.drafts);
  // right column
  el.side = h("section", { class: "rt-col rt-side", "aria-labelledby": "rtPreH" });
  // footer
  el.startWhy = h("p", { class: "rt-why", id: "rtStartWhy" });
  el.exportBtn = abtn("Export planning packet", rtExport, "", "download");
  const start = el.start = h("button", { type: "button", class: "btn rt-start", "aria-disabled": "true", "aria-describedby": "rtStartWhy",
    onclick: () => rtStart() }, icon("send"), "Start");
  const foot = h("div", { class: "rt-foot" },
    h("div", { class: "row" }, (el.saveBtn = abtn("Save draft", () => rtSave(false), "primary", "check")), abtn("Check preflight", rtPreflight, "", "shield"), el.exportBtn),
    h("div", { class: "rt-startgrp" }, start, el.startWhy));
  $("rtIn").replaceChildren(
    h("header", { class: "rt-head" }, h("div", { class: "ttl" }, icon("users"), h("div", {}, h("h2", { id: "rtTitle" }, f.mode === "war_room" ? "War Room" : "Roundtable"),
      (el.liveNote = h("p", { class: "faint" })))),
      h("div", { class: "row rt-livectl" },
        h("span", { id: "rtLiveLbl", class: "rt-livelbl" }, "Live"),
        (el.liveState = h("span", { class: "faint rt-livestate" })),
        (el.liveSw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": "false", "aria-labelledby": "rtLiveLbl",
          title: "Live sessions let the chosen providers talk to each other. On when you open this window; off 30 s after a session ends.",
          onclick: () => rtSetLive(el.liveSw.getAttribute("aria-checked") !== "true") }, h("span", { class: "knob" }))),
        h("button", { type: "button", class: "iconbtn", "aria-label": "Close roundtable", onclick: () => $("rtDlg").close() }, icon("x")))),
    h("div", { id: "rtStatus", class: "rt-status", role: "status", "aria-live": "polite" }),
    (el.body = h("div", { class: "rt-body" }, (el.part = part), main, el.side)), (el.foot = foot));
  rtResearchRender(); rtLanesRender(); rtRefresh(); rtGatesRender(); rtSideRender(); rtStartRender(); rtDraftsRender(); rtCompareRender(); rtLiveRender();
  if (focusId && $(focusId)) $(focusId).focus();
}
// Researcher: an on-call public web search lane any speaker (or the owner) can call during a session.
function rtResearchRender() {
  const el = RT.el; if (!el.research) return; const f = RT.f; const st = RT.researcher;
  const avail = !!(st && st.available);
  const box = h("input", { id: "rtResearch", type: "checkbox", disabled: !avail, "aria-describedby": "rtResearchHelp",
    onchange: (e) => { f.research = e.target.checked; rtResetAck(); rtRefresh(); rtStale(); } });
  box.checked = avail && f.research;
  const cap = h("input", { id: "rtResearchCap", type: "number", min: "0", max: "20", step: "1", value: f.max_research, placeholder: "8",
    disabled: !avail, oninput: (e) => { f.max_research = e.target.value; rtStale(); } });
  el.research.replaceChildren(h("legend", {}, "Researcher"),
    h("label", { class: "rt-ack", for: "rtResearch" }, box, h("span", {}, icon("search"), avail ? ` Researcher on call (${st.names.join(" + ")} web search)` : " Researcher unavailable")),
    h("div", { class: "rt-row3" }, h("div", { class: "field" }, h("label", { for: "rtResearchCap" }, "Max lookups per session"), cap)),
    h("p", { class: "faint", id: "rtResearchHelp" }, avail
      ? `Speakers call it with a line "RESEARCH: <question>"; you can also ask it from the live room. Sources land in the timeline for everyone to cite. Only the question text is sent, never the transcript. ${st.used_today || 0}/${st.daily_cap} lookups used today.`
      : (st && st.note) || (RT.loading ? "Checking the Researcher…" : "Researcher status could not be loaded.")));
}
function rtResetAck() { if (RT.f.ack) { RT.f.ack = false; if (RT.el.ack) RT.el.ack.checked = false; } }
function rtLanesRender() {
  const el = RT.el;
  el.example.textContent = RT.example.length ? `Documented example roster: ${RT.example.join(", ")}` : "";
  if (RT.loading) { el.lanes.replaceChildren(h("p", { class: "muted" }, "Checking lanes…")); return; }
  if (RT.err) { el.lanes.replaceChildren(h("div", { class: "note bad" }, icon("alert"), h("span", {}, `Lanes could not be loaded: ${RT.err}`))); return; }
  if (RT.f.mode === "war_room") {
    el.lanes.replaceChildren(h("ul", { class: "rt-admins" }, ...RT_ADMINS.map(([id, name]) => {
      const l = rtLane(id);
      return h("li", { class: "lane" }, h("div", { class: "lbody" }, h("div", { class: "lname" }, h("strong", {}, name), h("span", { class: "tag lc-admin" }, "admin")),
        h("div", { class: "lmeta" }, statePill(l ? l.readiness : "NOT_DETECTED"), h("span", {}, (l && l.route_type) || "no route")),
        l && (l.reasons || []).length ? h("p", { class: "faint" }, l.reasons[0]) : null));
    })));
    return;
  }
  if (!RT.lanes.length) { el.lanes.replaceChildren(empty("users", "No lanes reported", "The lane discovery endpoint returned no lanes on this machine.")); return; }
  const q = RT.q.trim().toLowerCase();
  const shown = RT.lanes.filter((l) => {
    if (RT.filter === "speakers" && !(l.lane_class === "speaker" || l.lane_class === "admin")) return false;
    if (RT.filter === "research" && l.lane_class !== "research") return false;
    if (RT.filter === "review" && l.lane_class !== "review") return false;
    if (RT.filter === "ready" && l.readiness !== "VERIFIED_READY") return false;
    return !q || [l.name, l.id, l.route_type, l.lane_class, l.readiness].join(" ").toLowerCase().includes(q);
  });
  el.lanes.replaceChildren(...(shown.length ? shown.map((l) => {
    const block = rtBlockedReason(l); const cid = "rtl-" + l.id; const rid = cid + "-why";
    const cb = h("input", { type: "checkbox", id: cid, disabled: !!block, "aria-describedby": rid,
      onchange: (e) => { if (e.target.checked) RT.f.roster.add(l.id); else RT.f.roster.delete(l.id); rtResetAck(); rtRefresh(); rtStale(); } });
    cb.checked = RT.f.roster.has(l.id);
    const reasons = [block, ...(l.reasons || [])].filter(Boolean);
    return h("div", { class: "lane" + (block ? " off" : "") },
      h("label", { class: "lck", for: cid }, cb, h("span", { class: "sr-only" }, `Select ${l.name}`)),
      h("div", { class: "lbody" },
        h("div", { class: "lname" }, h("label", { for: cid }, l.name), h("span", { class: "tag lc-" + l.lane_class }, RT_CLASS[l.lane_class] || l.lane_class)),
        h("div", { class: "lmeta" }, statePill(l.readiness), h("span", {}, l.route_type || "no route"),
          h("span", {}, l.conversation_support === "in_app_verified" ? "in-app conversation verified" : l.conversation_support === "adapter_missing" ? "conversation adapter missing" : "no conversation support"),
          h("span", {}, `cost: ${l.cost_visibility || "unknown"}`)),
        h("ul", { class: "lwhy", id: rid }, ...(reasons.length ? reasons.map((r) => h("li", {}, r)) : [h("li", {}, l.detection || "No ineligibility reasons reported.")]))));
  }) : [h("p", { class: "muted" }, "No lanes match this search or filter.")]));
}
function rtRefresh() {
  const el = RT.el; const f = RT.f; const sel = rtSelected();
  el.counter.textContent = `${sel.length} selected · ${rtQualified().length} qualified speakers ${f.mode === "general" ? "(General needs ≥4)" : "(War Room: admin lanes only)"}`;
  el.sharePrev.replaceChildren(
    h("div", { class: "faint" }, "Exact text that would be shared"),
    h("pre", { class: "out" }, f.objective.trim() ? f.objective : "(objective is empty)"),
    h("div", { class: "faint" }, "Selected lanes that would receive it"),
    sel.length ? h("ul", { class: "rt-recips" }, ...sel.map((l) => h("li", {}, h("strong", {}, l.name), ` · ${l.route_type || "no route"} · ${RT_CLASS[l.lane_class] || l.lane_class}`)),
      RT.researcher && RT.researcher.available && f.research ? h("li", {}, h("strong", {}, "Researcher"), ` · ${RT.researcher.names.join(" + ")} · receives only the research questions, not the objective or transcript`) : null) : h("p", { class: "muted" }, "No lanes selected; nothing would be shared."));
  rtCompareRender();
}
function rtGatesRender() {
  const g = RT.gates;
  RT.el.gates.replaceChildren(...(g.length ? [h("div", { class: "note bad rt-gates", role: "note" }, icon("alert"), h("div", {}, h("strong", {}, "Mission gates: a live roundtable cannot start"),
    h("ul", {}, ...g.map((x) => h("li", {}, h("code", {}, x.code), " ", x.reason)))))] : []));
}
function rtSideRender() {
  const p = RT.pre;
  const kids = [h("h3", { id: "rtPreH" }, "Preflight")];
  if (!p) kids.push(h("p", { class: "muted" }, "Not checked yet. Check preflight saves the draft and lists every check with pass or fail."));
  else {
    const checks = p.checks || [];
    if (RT.preStale) kids.push(h("div", { class: "note" }, icon("alert"), h("span", {}, "Out of date: the draft was edited since this check. Run Check preflight again.")));
    const box = h("div", { class: "section" + (RT.preStale ? " stale" : "") },
      h("p", { class: "muted" }, `${RT.preStale ? "Last check: " : ""}${checks.filter((c) => c.pass).length} of ${checks.length} checks pass · ${p.selected ?? "—"} selected · ${p.qualified_speakers ?? "—"} qualified speakers · start allowed: ${p.start_allowed ? "yes" : "no"}`),
      h("ul", { class: "rt-checks" }, ...checks.map((c) => h("li", { class: c.pass ? "ok" : "bad" }, icon(c.pass ? "check" : "x"),
        h("div", {}, h("strong", {}, c.label), h("span", { class: "sr-only" }, c.pass ? " passed" : " failed"), c.detail ? h("p", { class: "faint" }, c.detail) : null)))));
    if ((p.block_reasons || []).length) box.append(h("div", { class: "note bad" }, icon("alert"), h("div", {}, h("strong", {}, "Block reasons"), h("ul", {}, ...p.block_reasons.map((r) => h("li", {}, r))))));
    kids.push(box);
  }
  if (RT.discovered) kids.push(h("p", { class: "faint" }, `Lanes discovered ${fmtTime(RT.discovered)}.`));
  RT.el.side.replaceChildren(...kids);
}
function rtStartRender() {
  RT.el.liveNote.textContent = RT.live ? "Live sessions are on. Compare and Start contact providers only after preflight passes." : "Live sessions are off: flip the Live switch to run compare or start a session. Planning and drafts work while off.";
  rtLiveRender();
  const ok = rtCanStart();
  RT.el.start.setAttribute("aria-disabled", ok ? "false" : "true");
  RT.el.start.classList.toggle("primary", ok); RT.el.saveBtn.classList.toggle("primary", !ok);
  if (ok) { RT.el.startWhy.textContent = "Ready: the current preflight passed. Start opens the live room."; return; }
  const fresh = RT.pre && !RT.preStale && (RT.pre.block_reasons || []).length;
  const reasons = fresh ? RT.pre.block_reasons : !RT.live ? [RT_NOT_LIVE] : RT.gates.length ? RT.gates.map((g) => g.reason)
    : [RT.pre && RT.preStale ? "The draft changed since the last preflight; run Check preflight again." : "Run Check preflight; Start needs a current, passing preflight."];
  RT.el.startWhy.textContent = `Start disabled: ${reasons[0]}${reasons.length > 1 ? ` (+${reasons.length - 1} more${fresh ? " in preflight" : ""})` : ""}`;
}
function rtDraftsRender() {
  const d = RT.drafts;
  RT.el.drafts.replaceChildren(h("h3", {}, "Saved drafts", h("span", { class: "count" }, String(d.length))),
    d.length ? h("ul", { class: "rt-drafts" }, ...d.map((r) => h("li", { "aria-current": RT.rec && RT.rec.id === r.id ? "true" : "false" },
      h("div", { class: "dtxt" }, h("strong", {}, `${RT_MODES[r.mode] || r.mode} · ${(r.objective || "(no objective)").slice(0, 90)}`),
        h("span", { class: "faint" }, `${r.id} · updated ${fmtTime(r.updated || r.created)}`)),
      statePill(r.live_status || r.status || "DRAFT"), abtn("Open", () => rtOpenDraft(r.id), "sm"),
      r.live_status && r.live_status !== "DRAFT" ? abtn(LIVE_END.includes(r.live_status) ? "View record" : "Open room", () => rtRoom(r.id, LIVE_END.includes(r.live_status)), "ghost sm", "chat") : null,
      delBtn("Delete", `Delete roundtable ${r.id}`, async () => {
        const s = RT; if (!s || !(await confirmDelete("rt")) || RT !== s) return;
        const i = s.drafts.findIndex((x) => x.id === r.id);
        try {
          const res = await rtDeleteOne(r.id); if (RT !== s) return;
          if (!res.ok) { rtSay(res.msg, "bad"); return; }
          rtSay((res.r && res.r.note) || `Deleted ${r.id}.`, "ok");
          const lis = s.el.drafts.querySelectorAll(".rt-drafts li");
          const li = lis[Math.min(Math.max(i, 0), lis.length - 1)];
          const f = (li && li.querySelector(".btn")) || $("rtObjective"); if (f) f.focus();
        } catch (err) { if (RT === s) rtSay(err.message, "bad"); }
      }))))
      : h("p", { class: "muted" }, "No drafts saved for this project yet."));
  RT.el.drafts.querySelectorAll(".rt-drafts li").forEach((li, i) => {
    const [open, room] = li.querySelectorAll(".btn");
    if (open) open.setAttribute("aria-label", `Open draft ${d[i].id}`);
    if (room) room.setAttribute("aria-label", `${room.textContent.trim()} for ${d[i].id}`);
  });
}
function rtBody() {
  const f = RT.f; const num = (v) => (v === "" || v === null || v === undefined || !isFinite(Number(v)) ? null : Number(v));
  return { ...(RT.rec ? { id: RT.rec.id } : {}), mode: f.mode, objective: f.objective, deliverable: f.deliverable, outcome_type: f.outcome_type,
    time_limit_min: Number(f.time_limit_min), response_window_s: f.mode === "war_room" ? Number(f.response_window_s) : null, roster: [...f.roster],
    sharing_ack: !!f.ack, caps: { max_turns: num(f.max_turns), max_messages_per_speaker: num(f.max_msgs), cost_cap_usd: num(f.cost_cap),
      research: !!f.research, max_research: num(f.max_research) } };
}
// Every response is applied only to the modal session and draft generation that sent it.
async function rtSave(quiet) {
  const s = RT; if (!s) return null;
  if (!s.f.objective.trim()) { rtSay("Add an objective first; it is required.", "bad"); $("rtObjective").focus(); return null; }
  const gen = s.gen; const body = rtBody();
  try {
    const rec = await api("POST", `/api/projects/${s.pid}/roundtables`, body);
    if (RT !== s || s.gen !== gen) return null;
    s.rec = rec; if (rec.preflight) { s.pre = rec.preflight; s.preStale = false; }
    try { const d = await api("GET", `/api/projects/${s.pid}/roundtables`); if (RT === s && s.gen === gen) s.drafts = d; } catch { /* list refresh is best-effort */ }
    if (RT !== s || s.gen !== gen) return null;
    rtSideRender(); rtStartRender(); rtDraftsRender();
    if (!quiet) rtSay(`Draft ${rec.id} saved locally. Nothing was sent anywhere.`, "ok");
    return rec;
  } catch (e) { if (RT === s) rtSay(e.message, "bad"); return null; }
}
async function rtPreflight() {
  const s = RT; const rec = await rtSave(true); if (!rec || RT !== s) return;
  const gen = s.gen;
  try {
    const p = await api("POST", `/api/roundtables/${rec.id}/preflight`);
    if (RT !== s || s.gen !== gen || !s.rec || s.rec.id !== rec.id) return;
    s.pre = p; s.preStale = false; rtSideRender(); rtStartRender();
    const checks = p.checks || [];
    rtSay(`Preflight: ${checks.filter((c) => c.pass).length} of ${checks.length} checks pass. ${p.start_allowed ? "Start is available." : "Start stays disabled until the block reasons are resolved."}`, "");
  } catch (e) { if (RT === s) rtSay(e.message, "bad"); }
}
async function rtExport() {
  // Always save first so the packet matches the form on screen, not an older saved version.
  const s = RT; const rec = await rtSave(true); if (!rec || RT !== s) return;
  try { await download(`/api/roundtables/${rec.id}/export`, `roundtable-${rec.id}.json`); if (RT === s) rtSay("Saved the current form and downloaded the planning packet (JSON).", "ok"); }
  catch (e) { if (RT === s) rtSay(e.message, "bad"); }
}
// ---------- live roundtable ----------
const rtCanStart = () => !!(RT && RT.live && RT.rec && RT.pre && !RT.preStale && RT.pre.start_allowed === true);
async function rtStart() {
  const s = RT; if (!s) return;
  if (!s.live && s.rec) { // the switch went off after the last session: turn it back on and re-check
    if (!(await rtSetLive(true, true)) || RT !== s) return;
    await rtPreflight(); if (RT !== s) return;
  }
  if (!rtCanStart()) { rtSay(`Start is disabled. ${s.el.startWhy.textContent}`); return; }
  if (s.starting) return; s.starting = true;
  try {
    const r = await api("POST", `/api/roundtables/${s.rec.id}/start`);
    if (RT !== s) return;
    rtSay(`Roundtable started (${(r.status && r.status.live_status) || r.status || "running"}).`, "ok");
    rtRoom(s.rec.id, false);
  } catch (e) {
    if (RT !== s) return;
    if (e.data && e.data.block_reasons) { s.pre = { ...(s.pre || {}), start_allowed: false, block_reasons: e.data.block_reasons }; rtSideRender(); rtStartRender(); }
    rtSay(e.message, "bad");
  } finally { s.starting = false; }
}
const fmtS = (v) => { if (typeof v !== "number" || !isFinite(v)) return "—"; const t = Math.max(0, Math.round(v)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
const SP_LABEL = { idle: "idle", working: "working…", stalled: "stalled", disconnected: "disconnected", budget_exhausted: "budget exhausted" };
const SP_TONE = { idle: "", working: "info", stalled: "warn", disconnected: "bad", budget_exhausted: "bad" };
// Inline formatting: **bold**, `code`, @mentions and [E#] references (clickable). Everything stays textContent.
function rtText(t, room) {
  const out = []; const re = /(https?:\/\/[^\s<>()"']+[^\s<>()"'.,;:!?]|\*\*[^*\n]+\*\*|`[^`\n]+`|@[\w.-]+|\[E\d+(?:\s*[–-]\s*E?\d+)?(?:,\s*E\d+(?:\s*[–-]\s*E?\d+)?)*\]|(?<![\w*])\*(?!\s)[^*\n]+?\*(?![\w*])|(?<![\w_])_(?!\s)[^_\n]+?_(?![\w_]))/g; let last = 0; let m;
  while ((m = re.exec(t))) {
    if (m.index > last) out.push(t.slice(last, m.index));
    const tok = m[1];
    if (/^https?:/.test(tok)) out.push(h("a", { href: tok, target: "_blank", rel: "noopener noreferrer nofollow", class: "evlink" }, tok.replace(/^https?:\/\/(www\.)?/, "").slice(0, 70)));
    else if (tok.startsWith("**")) out.push(h("strong", {}, tok.slice(2, -2)));
    else if (tok[0] === "`") out.push(h("code", {}, tok.slice(1, -1)));
    else if (tok[0] === "@") out.push(h("span", { class: "mention" }, tok));
    else if (tok[0] === "*" || tok[0] === "_") out.push(h("em", {}, tok.slice(1, -1)));
    else if (room) { // [E4] / [E2–E7] / [E4, E5]: every label becomes its own jump link
      out.push("[");
      tok.slice(1, -1).split(/(E\d+)/).forEach((part) => {
        if (/^E\d+$/.test(part)) out.push(h("button", { type: "button", class: "eref linkish", title: `Jump to ${part}`, onclick: () => rtJump(room, part) }, part));
        else if (part) out.push(h("span", { class: "eref" }, part));
      });
      out.push("]");
    }
    else out.push(h("span", { class: "eref" }, tok));
    last = m.index + tok.length;
  }
  if (last < t.length) out.push(t.slice(last));
  return out;
}
// Light, safe block formatting for provider text: headings, bullet/numbered lists, quotes, code fences, paragraphs.
function rtMd(src, room) {
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n"); const out = []; let para = [], list = null, code = null;
  const flushP = () => { if (para.length) { out.push(h("p", {}, ...rtText(para.join(" "), room))); para = []; } };
  const flushL = () => { if (list) { out.push(list); list = null; } };
  for (const raw of lines) {
    if (code) { if (/^\s*```/.test(raw)) { out.push(h("pre", { class: "evcode" }, code.join("\n"))); code = null; } else code.push(raw); continue; }
    if (/^\s*```/.test(raw)) { flushP(); flushL(); code = []; continue; }
    const line = raw.trimEnd();
    if (!line.trim()) { flushP(); flushL(); continue; }
    let m;
    if ((m = /^\s*(#{1,6})\s+(.*)$/.exec(line))) { flushP(); flushL(); out.push(h(m[1].length <= 2 ? "h4" : "h5", {}, ...rtText(m[2].replace(/\s*#+$/, ""), room))); continue; }
    if ((m = /^\s*([-*+]|\d+[.)])\s+(.*)$/.exec(line))) {
      flushP(); const tag = /\d/.test(m[1]) ? "ol" : "ul";
      if (!list || list.tagName.toLowerCase() !== tag) { flushL(); list = h(tag, {}); }
      list.append(h("li", {}, ...rtText(m[2], room))); continue;
    }
    if ((m = /^\s*>\s?(.*)$/.exec(line))) { flushP(); flushL(); out.push(h("blockquote", {}, ...rtText(m[1], room))); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flushP(); flushL(); out.push(h("hr", {})); continue; }
    if (list && /^\s{2,}\S/.test(raw)) { list.lastChild.append(" ", ...rtText(line.trim(), room)); continue; }
    flushL(); para.push(line.trim());
  }
  if (code) out.push(h("pre", { class: "evcode" }, code.join("\n")));
  flushP(); flushL();
  return out;
}
function rtJump(room, label) {
  const t = room.byLabel[label]; if (!t) return;
  if (t.li.classList.contains("filtered")) rtFilter(room, null);
  t.li.scrollIntoView({ block: "center", behavior: "smooth" }); t.li.focus({ preventScroll: true });
  t.li.classList.add("flash"); setTimeout(() => t.li.classList.remove("flash"), 1600);
}
const RT_KIND = { opening: "Opening", closing: "Closing", system: "Studio", memo: "Memo", gap: "Gap", research: "Sources", owner: "Owner answers" };
const RT_CLAMP_CHARS = 1100, RT_CLAMP_LINES = 16;
const rtTint = (room, k) => { if (!k) return null; if (k === "researcher") return "r"; if (k === "owner") return "o"; if (!(k in room.tints)) room.tints[k] = Object.keys(room.tints).length % 6; return room.tints[k]; };
// Feed items are threaded: replies link to the event they answer; passes are compact and can be hidden.
function rtEvent(ev, sps, room) {
  const sp = sps[ev.speaker]; const name = ev.speaker === "owner" ? "You" : sp ? sp.name : ev.speaker || (ev.kind === "system" ? "Studio" : ev.kind);
  const label = ev.label || `E${ev.seq}`;
  const tint = rtTint(room, ev.speaker);
  const li = h("li", { class: "ev ev-" + ev.kind + (tint !== null ? " sp" + tint : ""), id: `rtev-${room.id}-${label}`, tabindex: "-1", "data-sp": ev.speaker || "" });
  room.byLabel[label] = { li, name };
  if (ev.kind === "pass") {
    li.append(h("span", { class: "evp" }, h("code", {}, label), ` ${name} passed`, ev.content ? ` · ${ev.content}` : ""));
    return rtApplyFilter(room, li);
  }
  const refs = Array.isArray(ev.reply_to) ? ev.reply_to : ev.reply_to ? [ev.reply_to] : [];
  const replies = refs.map((r) => { const tgt = room.byLabel[r];
    return h("button", { type: "button", class: "linkish evr", onclick: () => rtJump(room, r) }, `↳ replying to ${r}${tgt ? " · " + tgt.name : ""}`); });
  if (ev.kind === "owner") replies.length = 0; // the note cites its questions inline
  else if (refs.length) li.classList.add("reply");
  const mentions = (ev.mentions || []).map((m) => { const ms = sps[m]; return h("span", { class: "tag mention" }, `@${ms ? ms.name : m}`); });
  const text = String(ev.content || "");
  const body = h("div", { class: "evb" }, ...rtMd(text, room));
  const long = ev.kind !== "owner" && text.length > RT_CLAMP_CHARS || text.split("\n").length > RT_CLAMP_LINES;
  let more = null;
  if (long) {
    more = h("button", { type: "button", class: "linkish evmore", "aria-expanded": "false" }, "Show full message");
    const set = (open) => { body.classList.toggle("clamped", !open); more.setAttribute("aria-expanded", open ? "true" : "false"); more.textContent = open ? "Show less" : "Show full message"; };
    more.addEventListener("click", () => { const open = body.classList.contains("clamped"); set(open); if (!open) li.scrollIntoView({ block: "nearest" }); });
    li._clamp = set; set(!room.collapse);
  }
  const kind = RT_KIND[ev.kind];
  li.append(...replies,
    h("div", { class: "evh" },
      ev.speaker === "researcher" ? h("span", { class: "evav", "aria-hidden": "true" }, icon("search")) : h("span", { class: "evav", "aria-hidden": "true" }, ev.kind === "system" ? "AS" : ev.speaker === "owner" ? "You" : initials(name)),
      h("strong", { class: "evname" }, name), kind ? h("span", { class: "evkind" + (ev.kind === "gap" ? " warn" : "") }, kind) : null, ...mentions,
      h("span", { class: "evmeta" }, h("code", {}, label), ev.latency_s != null ? ` · ${ev.latency_s}s` : "", ev.seen_label ? ` · saw up to ${ev.seen_label}` : "")),
    body);
  if (more) li.append(more);
  return rtApplyFilter(room, li);
}
function rtApplyFilter(room, li) { li.classList.toggle("filtered", !!room.only && li.dataset.sp !== room.only); return li; }
function rtFilter(room, key) {
  room.only = key && room.only !== key ? key : null;
  room.feed.querySelectorAll("li.ev").forEach((li) => rtApplyFilter(room, li));
  room.feed.classList.toggle("filtering", !!room.only);
  room.chips.querySelectorAll("button[data-sp]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.sp === room.only ? "true" : "false"));
  room.showAll.hidden = !room.only;
}
function rtDivider(text) { return h("li", { class: "evdiv", role: "presentation" }, h("span", {}, text)); }
function rtCoverage(c) {
  if (!c) return h("p", { class: "muted" }, "No coverage summary was returned.");
  if (typeof c === "string") return h("div", { class: "note" }, icon("info"), h("span", {}, c));
  const valid = c.valid; const text = c.summary || "";
  const head = valid === true ? "Coverage: valid roundtable" : valid === false ? "Coverage: NOT a valid four-provider roundtable" : "Coverage summary";
  return h("div", { class: "note rt-cov " + (valid === true ? "ok" : "bad"), role: "status" }, icon(valid === true ? "check" : "alert"),
    text ? h("details", {}, h("summary", {}, h("strong", {}, head)), h("p", {}, text)) : h("strong", {}, head));
}
const rtPref = (k, d) => { try { const v = localStorage.getItem("aesop.rt." + k); return v === null ? d : v === "1"; } catch { return d; } };
const rtSetPref = (k, v) => { try { localStorage.setItem("aesop.rt." + k, v ? "1" : "0"); } catch { /* storage unavailable */ } };
// The room takes over the whole window: a wide reading column for the conversation and a memo column beside it.
function rtRoom(id, readOnly) {
  const s = RT; if (!s) return;
  clearTimeout(s.timer); const gen = ++s.gen; s.roomId = id;
  const room = { after: 0, id, byLabel: {}, phase: null, opened: false, closed: false, passes: 0, tints: {}, only: null, collapse: rtPref("collapse", true) };
  const clock = h("span", { class: "rt-clock" }, "—"); const stPill = h("span"); const roundLinks = h("span", { class: "rt-roundlinks" });
  const chips = room.chips = h("div", { class: "rt-chips", role: "group", "aria-label": "Speakers (select one to show only their messages)" });
  const feed = room.feed = h("ol", { class: "rt-feed" + (rtPref("big", false) ? " big" : ""), "aria-label": "Roundtable feed", tabindex: "0" });
  const announce = h("div", { class: "sr-only", "aria-live": "polite" });
  const memo = h("div", { class: "rt-memo" }); const cov = h("div");
  const ctl = (label, op, ico) => abtn(label, async () => {
    try { const r = await api("POST", `/api/roundtables/${id}/${op}`); if (RT === s) rtSay(`${label}: ${(r.status && r.status.live_status) || r.live_status || r.status || "requested"}.`); }
    catch (e) { if (RT === s) rtSay(e.message, "bad"); }
  }, "sm", ico);
  const pauseBtn = ctl("Pause", "pause", "clock"), resumeBtn = ctl("Resume", "resume", "send"), stopBtn = ctl("Stop", "stop", "stop");
  stopBtn.classList.add("danger");
  const exportBtn = abtn("Export record", async () => { try { await download(`/api/roundtables/${id}/record`, `roundtable-record-${id}.json`); } catch (e) { rtSay(e.message, "bad"); } }, "ghost sm", "download");
  const toggle = (label, on, fn) => { const b = h("button", { type: "button", class: "btn ghost sm", "aria-pressed": on ? "true" : "false" }, label);
    b.addEventListener("click", () => { const v = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", v ? "true" : "false"); fn(v); }); return b; };
  const passBtn = toggle("Show passes (0)", false, (v) => { feed.classList.toggle("show-pass", v); });
  passBtn.hidden = true;
  const clampBtn = toggle("Expand all", !room.collapse, (v) => {
    room.collapse = !v; rtSetPref("collapse", room.collapse);
    feed.querySelectorAll("li.ev").forEach((li) => li._clamp && li._clamp(v)); });
  const bigBtn = toggle("Larger text", feed.classList.contains("big"), (v) => { feed.classList.toggle("big", v); rtSetPref("big", v); });
  const memoBtn = toggle("Memo panel", rtPref("memo", true), (v) => { s.el.body.classList.toggle("memo-off", !v); rtSetPref("memo", v); });
  room.showAll = h("button", { type: "button", class: "btn ghost sm", hidden: true, onclick: () => rtFilter(room, null) }, "Show everyone");
  const back = btn("Back to setup", () => { clearTimeout(s.timer); s.gen++; rtBuild(); }, "ghost sm");
  const fu = h("section", { class: "rt-fu", hidden: true, "aria-label": "Follow-up: questions for you" });
  const followBtn = h("button", { type: "button", class: "btn sm rt-followbtn", hidden: true, "aria-expanded": "false" }, icon("chat"), "Follow-up");
  followBtn.addEventListener("click", () => {
    const open = fu.hidden; fu.hidden = !open; feedwrap.hidden = open; viewctl.hidden = open;
    followBtn.setAttribute("aria-expanded", open ? "true" : "false");
    followBtn.replaceChildren(icon(open ? "chat" : "chat"), open ? "Back to conversation" : "Follow-up");
    if (open && !fu.dataset.loaded) rtFollowLoad(s, gen, id, fu, room, () => tick(), false);
  });
  const latest = h("button", { type: "button", class: "btn sm rt-latest", hidden: true, onclick: () => { feed.scrollTo({ top: feed.scrollHeight, behavior: "smooth" }); } }, "Jump to latest ↓");
  feed.addEventListener("scroll", () => { latest.hidden = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80; });
  pauseBtn.hidden = resumeBtn.hidden = stopBtn.hidden = true;
  let feedwrap, viewctl;
  const askIn = h("input", { id: "rtAskQ", type: "search", maxlength: "300", placeholder: "Ask the Researcher, e.g. current Bid Whist tournament scoring rules", "aria-label": "Research question" });
  const askBtn = abtn("Research", async () => {
    const q = askIn.value.trim(); if (q.length < 4) { rtSay("Type a research question first.", "bad"); askIn.focus(); return; }
    try { const r = await api("POST", `/api/roundtables/${id}/research`, { query: q });
      if (RT === s) { rtSay(r.queued ? `Researcher is looking up: ${q}` : `Not sent: ${r.reason}`, r.queued ? "ok" : "bad"); if (r.queued) askIn.value = ""; } }
    catch (e) { if (RT === s) rtSay(e.message, "bad"); }
  }, "sm", "search");
  const ask = h("form", { class: "rt-ask", hidden: true, onsubmit: (e) => { e.preventDefault(); askBtn.click(); } }, askIn, askBtn);
  const main = h("section", { class: "rt-col rt-main rt-room", "aria-label": "Live room" },
    h("div", { class: "rt-roomhead" },
      h("div", { class: "ttl" }, h("h3", {}, readOnly ? "Roundtable record" : "Live room"), stPill, clock, roundLinks),
      h("div", { class: "row rt-roomctl" }, pauseBtn, resumeBtn, stopBtn, exportBtn, followBtn, back)),
    h("div", { class: "rt-bar" }, chips,
      (viewctl = h("div", { class: "row rt-viewctl", role: "toolbar", "aria-label": "Reading options" }, room.showAll, clampBtn, bigBtn, passBtn, memoBtn))),
    cov, (feedwrap = h("div", { class: "rt-feedwrap" }, feed, latest)), fu, ask, announce);
  const side = h("section", { class: "rt-col rt-side", "aria-label": "Memo" }, memo);
  $("rtDlg").classList.add("rooming");
  s.el.body.classList.toggle("memo-off", !rtPref("memo", true));
  s.el.body.replaceChildren(main, side); s.el.foot.hidden = true;
  memo.replaceChildren(h("h3", {}, "Memo"), h("p", { class: "muted" }, "The memo appears here when the session writes one."));
  let pending = 0, lastSay = 0, memoSig = "", chipSig = "";
  const tick = async () => {
    if (RT !== s || s.gen !== gen) return;
    let d;
    try { d = await api("GET", `/api/roundtables/${id}/live?after=${room.after}`); }
    catch (e) { if (RT === s && s.gen === gen) { rtSay(e.message, "bad"); s.timer = setTimeout(tick, 3000); } return; }
    if (RT !== s || s.gen !== gen) return;
    const st = d.status || {}; const sps = st.speakers || {}; room.sps = sps;
    Object.keys(sps).forEach((k) => rtTint(room, k));
    const lsig = JSON.stringify([st.follow_up_of, st.next_round]);
    if (lsig !== room.linkSig) {
      room.linkSig = lsig;
      roundLinks.replaceChildren(
        st.follow_up_of ? h("button", { type: "button", class: "linkish rt-roundlink", onclick: () => rtRoom(st.follow_up_of, true) }, "← Follow-up of the previous round") : null,
        st.next_round ? h("button", { type: "button", class: "linkish rt-roundlink", onclick: () => rtRoom(st.next_round.id, LIVE_END.includes(st.next_round.live_status)) },
          `Follow-up round (${String(st.next_round.live_status || "draft").toLowerCase()}) →`) : null);
    }
    const stick = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
    for (const ev of d.events || []) {
      if (ev.seq <= room.after) continue; room.after = ev.seq;
      if (ev.kind === "opening" && !room.opened) { room.opened = true; feed.append(rtDivider("Openings (independent)")); }
      else if (ev.kind === "closing" && !room.closed) { room.closed = true; feed.append(rtDivider("Closing statements")); }
      else if (ev.phase && ev.phase !== room.phase && room.phase !== null && !["opening", "closing", "pass"].includes(ev.kind)) feed.append(rtDivider(ev.phase === "followup" ? "Your follow-up" : ev.phase === "research" ? "Research" : `Phase: ${ev.phase}`));
      if (ev.phase && ev.kind !== "pass") room.phase = ev.phase;
      feed.append(rtEvent(ev, sps, room));
      if (ev.kind === "pass") { room.passes++; passBtn.hidden = false; passBtn.textContent = `Show passes (${room.passes})`; } else pending++;
    }
    if (stick && !readOnly) feed.scrollTop = feed.scrollHeight;
    latest.hidden = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80;
    if (pending && Date.now() - lastSay > 4000) { announce.textContent = `${pending} new item${pending > 1 ? "s" : ""} in the roundtable feed.`; pending = 0; lastSay = Date.now(); }
    clock.textContent = `${fmtS(st.elapsed_s)} elapsed · ${fmtS(st.remaining_s)} left of ${fmtS(st.limit_s)}`;
    stPill.replaceChildren(statePill(st.live_status || "—"));
    const sig = JSON.stringify(sps);
    if (sig !== chipSig) {
      chipSig = sig;
      chips.replaceChildren(...Object.entries(sps).map(([k, v]) => h("button", { type: "button", class: "rt-chip sp" + rtTint(room, k), "data-sp": k, "aria-pressed": room.only === k ? "true" : "false",
        title: `Show only ${v.name || k}`, onclick: () => rtFilter(room, k) },
        h("span", { class: "evav", "aria-hidden": "true" }, k === "researcher" ? icon("search") : initials(v.name || k)),
        h("span", { class: "rt-chipt" }, h("strong", {}, v.name || k),
          h("span", { class: "faint" }, v.role === "researcher" ? `${SP_LABEL[v.state] || v.state} · ${v.lookups || 0}/${v.cap} lookups` : `${SP_LABEL[v.state] || v.state || "unknown"} · ${v.turns || 0} turns${v.last_latency_s != null ? ` · ${v.last_latency_s}s` : ""}${typeof v.cost_usd === "number" ? ` · ${fmtCost(v.cost_usd)}` : ""}`)),
        h("span", { class: "dot " + (SP_TONE[v.state] || ""), "aria-hidden": "true" }))));
    }
    const ms = st.memo ? (typeof st.memo === "string" ? st.memo : JSON.stringify(st.memo, null, 1)) : "";
    if (ms && ms !== memoSig) { memoSig = ms; memo.replaceChildren(h("h3", {}, "Memo"), typeof st.memo === "string" ? h("div", { class: "evb rt-memob" }, ...rtMd(ms, room)) : h("pre", { class: "out" }, ms)); }
    const ended = LIVE_END.includes(st.live_status);
    const focused = document.activeElement;
    pauseBtn.hidden = readOnly || ended || st.live_status === "PAUSED";
    resumeBtn.hidden = readOnly || ended || st.live_status !== "PAUSED";
    stopBtn.hidden = readOnly || ended;
    ask.hidden = readOnly || ended || !sps.researcher;
    if (focused && focused.hidden) [resumeBtn, pauseBtn, exportBtn].find((b) => !b.hidden).focus();
    if (ended) { cov.replaceChildren(rtCoverage(st.coverage)); followBtn.hidden = false; if (!room.endSaid) { room.endSaid = true; rtSay(`Session ${st.live_status.toLowerCase()}.`); } return; }
    s.timer = setTimeout(tick, 1000);
  };
  tick();
}
// Follow-up (after a session ends): the speakers' questions for the owner, condensed and pre-filled; answers are
// appended to the same record as an "Owner answers" note. Nothing is sent to the speakers.
function rtAskers(list) {
  const who = (list || []).filter(Boolean); const people = who.filter((x) => x !== "Memo");
  if (!who.length) return null;
  return h("span", {}, people.length ? `asked by ${people.join(", ")}${who.length > people.length ? " · in the memo" : ""}` : "from the memo");
}
async function rtFollowLoad(s, gen, id, fu, room, refreshFeed, refresh) {
  const alive = () => RT === s && s.gen === gen;
  fu.dataset.loaded = "1";
  fu.replaceChildren(h("div", { class: "rt-fu-head" }, h("h4", {}, "Follow-up"), h("span", { class: "faint" }, "Gathering the speakers' questions for you and pre-filling answers… (about 10–40 s)")),
    h("div", { class: "rt-fu-skel", "aria-hidden": "true" }, h("span"), h("span"), h("span")));
  let d;
  try { d = await api("GET", `/api/roundtables/${id}/followup${refresh ? "?refresh=1" : ""}`); }
  catch (e) { if (alive()) { delete fu.dataset.loaded; fu.replaceChildren(h("div", { class: "note bad" }, icon("alert"), h("span", {}, e.message)), btn("Try again", () => rtFollowLoad(s, gen, id, fu, room, refreshFeed, true), "sm")); } return; }
  if (!alive()) return;
  const prev = d.previous || null; const prevBy = {};
  if (prev) for (const a of prev.answers || []) prevBy[a.question.toLowerCase()] = a.answer;
  const qs = d.questions || [];
  const rows = qs.map((q, i) => {
    const had = prevBy[q.question.toLowerCase()];
    const ta = h("textarea", { id: `rtFuA${i}`, rows: "2", maxlength: "1000", placeholder: "Your answer (leave empty to skip)", "aria-describedby": `rtFuH${i}` });
    ta.value = had != null ? had : (q.suggested || "");
    const skip = h("input", { type: "checkbox", id: `rtFuS${i}` });
    skip.addEventListener("change", () => { ta.disabled = skip.checked; card.classList.toggle("skipped", skip.checked); });
    const refs = (q.refs || []).map((r) => h("button", { type: "button", class: "eref linkish", title: `Show ${r} in the conversation`, onclick: () => {
      fu.hidden = true; fu.parentNode.querySelector(".rt-feedwrap").hidden = false; fu.parentNode.querySelector(".rt-viewctl").hidden = false;
      const fb = fu.parentNode.querySelector(".rt-followbtn"); fb.setAttribute("aria-expanded", "false"); fb.replaceChildren(icon("chat"), "Follow-up");
      rtJump(room, r); } }, r));
    const hint = had != null ? "your saved answer" : q.suggested ? `suggested${q.basis ? " · " + q.basis : ""} — edit if it's wrong` : "no suggestion: the speakers didn't settle this";
    const card = h("li", { class: "rt-fu-q" },
      h("label", { for: `rtFuA${i}`, class: "rt-fu-qt" }, h("span", { class: "rt-fu-n" }, String(i + 1)), q.question),
      h("div", { class: "rt-fu-meta" }, rtAskers(q.asked_by), ...refs),
      ta, h("div", { class: "rt-fu-foot" }, h("span", { class: "faint", id: `rtFuH${i}` }, hint),
        h("label", { class: "rt-fu-skip", for: `rtFuS${i}` }, skip, h("span", {}, "Skip"))));
    card._get = () => ({ question: q.question, answer: skip.checked ? "" : ta.value.trim(), refs: q.refs || [] });
    return card;
  });
  const note = h("textarea", { id: "rtFuNote", rows: "2", maxlength: "2000", placeholder: "Anything else the speakers should know next time (optional)" });
  if (prev && prev.note) note.value = prev.note;
  const people = Object.values(room.sps || {}).filter((v) => v.role !== "researcher").map((v) => v.name);
  const save = abtn("Complete", async () => {
    const answers = rows.map((r) => r._get()).filter((a) => a.answer);
    if (!answers.length && !note.value.trim()) { rtSay("Answer at least one question or add a note.", "bad"); return; }
    rtSay(`Saving your answers and starting the follow-up round with ${people.length || "the same"} speakers…`);
    try {
      const r = await api("POST", `/api/roundtables/${id}/followup`, { answers, note: note.value.trim() });
      if (!alive()) return;
      if (r.unchanged && r.retried) {
        if (r.round.started) { rtSay("Your answers were already saved; the follow-up round has now started.", "ok"); rtRoom(r.round.id, false); }
        else rtSay(`Your answers were already saved. The follow-up round still could not start: ${r.round.block_reasons.join(" ")}`, "bad");
        return;
      }
      if (r.unchanged) {
        rtSay("Nothing changed since you completed this, so nothing was saved again. Opening the follow-up round.");
        if (r.round) rtRoom(r.round.id, LIVE_END.includes(r.round.live_status));
        return;
      }
      const what = `${r.replaced ? "Replaced your earlier answers" : "Saved your answers"} (${r.saved}) on this record${r.withdrawn ? " and removed the round built on the old ones" : ""}.`;
      if (r.round && r.round.started) { rtSay(`${what} Follow-up round started with the same speakers.`, "ok"); rtRoom(r.round.id, false); return; }
      rtSay(`${what} The follow-up round could not start: ${(r.round && r.round.block_reasons || []).join(" ") || "preflight did not pass"} Fix that, then press Complete again to start it (your answers stay saved once).`, "bad");
      refreshFeed(); rtFollowLoad(s, gen, id, fu, room, refreshFeed, false);
    } catch (e) { if (alive()) rtSay(e.message, "bad"); }
  }, "primary", "send");
  const source = d.condensed_by ? `Condensed by ${d.condensed_by} from ${d.candidates} question${d.candidates === 1 ? "" : "s"} in the transcript and memo.`
    : d.candidates ? `${d.candidates} question${d.candidates === 1 ? "" : "s"} found in the transcript and memo${d.note ? ` (${d.note})` : ""}.` : "";
  fu.replaceChildren(
    h("div", { class: "rt-fu-head" }, h("h4", {}, qs.length ? `Follow-up · ${qs.length} question${qs.length === 1 ? "" : "s"} for you` : "Follow-up"),
      btn("Refresh", () => rtFollowLoad(s, gen, id, fu, room, refreshFeed, true), "ghost sm")),
    h("p", { class: "faint" }, `${source} Pre-filled answers come from what the speakers assumed or agreed.`),
    qs.length ? h("ol", { class: "rt-fu-list" }, ...rows) : h("p", { class: "muted" }, "The speakers didn't leave any questions for you. You can still add a note to the record."),
    h("div", { class: "field" }, h("label", { for: "rtFuNote" }, "Note (optional)"), note),
    h("div", { class: "row rt-fu-actions" }, save,
      h("span", { class: "faint" }, prev
        ? `Completed ${fmtTime(prev.saved_at)}. Complete again only saves if your answers changed; the earlier answers and their round are then replaced.`
        : `Saves your answers to this record once, then runs one more full round with the same speakers${people.length ? ` (${people.join(", ")})` : ""}, who receive your answers.`)));
}
async function rtOpenDraft(id) {
  const s = RT; if (!s) return;
  const gen = ++s.gen; // invalidates any save or preflight still in flight for the previous draft
  try {
    const rec = await api("GET", `/api/roundtables/${id}`);
    if (RT !== s || s.gen !== gen) return;
    clearTimeout(s.timer);
    s.rec = rec; s.f = rtFromRecord(rec); if (s.f.mode === "war_room") s.f.roster = new Set(RT_ADMINS.map(([x]) => x)); s.pre = rec.preflight || null; s.preStale = false;
    s.compare = Array.isArray(rec.compare) ? null : rec.compare;
    s.compareGen++;
    rtBuild("rtObjective");
    rtSay(`Opened draft ${rec.id}.`);
  } catch (e) { if (RT === s) rtSay(e.message, "bad"); }
}

// ---------- Roundtable dropdown (chat toolbar) ----------
const rtSelKey = (pid) => "aesop.rt.sel." + pid;
function rtStoredSel(pid) { try { const v = JSON.parse(localStorage.getItem(rtSelKey(pid)) || "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; } catch { return []; } }
function rtStoreSel(pid, ids) { try { localStorage.setItem(rtSelKey(pid), JSON.stringify(ids)); } catch { /* storage unavailable */ } }
function rtMenu() {
  const pid = S.project.id; let sel = new Set(rtStoredSel(pid)); let open = false;
  const trig = h("button", { type: "button", class: "btn rt-entry", id: "rtMenuBtn", "aria-haspopup": "true", "aria-expanded": "false", "aria-controls": "rtMenuPop" },
    icon("users"), "Roundtable");
  const pop = h("div", { class: "menu rt-pop", id: "rtMenuPop", role: "group", "aria-label": "Roundtable speakers", hidden: true });
  const count = h("p", { class: "rt-pop-count", "aria-live": "polite" });
  const list = h("div", { class: "rt-pop-list" });
  const setup = h("button", { type: "button", class: "menuitem rt-pop-setup", onclick: () => { close(false); openRoundtable(trig, { mode: "general", roster: [...sel] }); } }, icon("users"), "Set up roundtable…");
  pop.append(count, list, setup);
  const upd = () => { count.textContent = `${sel.size} selected · needs ≥4`; };
  const items = () => [...pop.querySelectorAll("input:not([disabled]), .rt-pop-setup")];
  const row = (l, enabled, why) => {
    const cid = "rtm-" + l.id;
    const cb = h("input", { type: "checkbox", id: cid, disabled: !enabled, "aria-describedby": cid + "-d",
      onchange: (e) => { if (e.target.checked) sel.add(l.id); else sel.delete(l.id); rtStoreSel(pid, [...sel]); upd(); } });
    cb.checked = enabled && sel.has(l.id);
    return h("label", { class: "rt-pop-row" + (enabled ? "" : " off"), for: cid }, cb,
      h("span", { class: "rt-pop-txt" }, h("span", { class: "rt-pop-name" }, l.name),
        h("span", { class: "faint", id: cid + "-d" }, why || `${l.readiness || "unknown"} · ${l.route_type || "no route"}`)));
  };
  const load = async () => {
    list.replaceChildren(h("p", { class: "muted" }, "Checking lanes…"));
    let lanes = [];
    try { lanes = (await api("GET", "/api/roundtable/lanes")).lanes || []; } catch (e) { list.replaceChildren(h("p", { class: "muted" }, e.message)); return; }
    const isConv = (l) => l.lane_class === "admin" || l.lane_class === "speaker";
    const conv = lanes.filter(isConv); const other = lanes.filter((l) => !isConv(l));
    const ok = new Set(conv.filter((l) => l.counts_as_speaker).map((l) => l.id));
    sel = new Set([...sel].filter((id) => ok.has(id)));
    list.replaceChildren(
      ...conv.map((l) => row(l, ok.has(l.id), ok.has(l.id) ? "" : ((l.reasons || [])[0] || "Not ready"))),
      other.length ? h("div", { class: "rt-pop-group", role: "group", "aria-label": "Not speakers" }, h("p", { class: "rt-pop-gh" }, "Not speakers"),
        ...other.map((l) => row(l, false, `${RT_CLASS[l.lane_class] || l.lane_class} · ${l.route_type || "no route"}`))) : null);
    upd();
  };
  const outside = (e) => { if (!wrap.contains(e.target)) close(false); };
  function close(focus) {
    if (!open) return; open = false; pop.hidden = true; trig.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", outside, true);
    if (focus) trig.focus();
  }
  const show = async () => {
    open = true; pop.hidden = false; trig.setAttribute("aria-expanded", "true"); upd();
    document.addEventListener("pointerdown", outside, true);
    await load(); if (open) { const f = items()[0]; if (f) f.focus(); }
  };
  trig.addEventListener("click", () => (open ? close(true) : show()));
  trig.addEventListener("keydown", (e) => { if (e.key === "ArrowDown" && !open) { e.preventDefault(); show(); } });
  pop.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); return; }
    const it = items(); const i = it.indexOf(document.activeElement); let n = null;
    if (e.key === "ArrowDown") n = (i + 1) % it.length; else if (e.key === "ArrowUp") n = (i - 1 + it.length) % it.length;
    else if (e.key === "Home") n = 0; else if (e.key === "End") n = it.length - 1;
    if (n === null || !it.length) return; e.preventDefault(); it[n].focus();
  });
  const wrap = h("div", { class: "menuwrap rt-menuwrap" }, trig, pop);
  return wrap;
}

// ---------- boot ----------
// Navigation token: every project/view switch bumps navGen and viewGen. Async work checks its token before touching state or the DOM.
S.navGen = 0; S.viewGen = 0;
function navBump() { S.navGen++; S.viewGen++; clearInterval(S.poll); }
const RENDER = { chat: () => renderChat(), agent: (sel) => renderAgent(sel), memory: () => renderMemory(), artifacts: () => renderArtifacts() };
function errorView(msg, retry) {
  return h("div", { class: "note bad", role: "alert" }, icon("alert"), h("div", { class: "section" }, h("span", {}, msg), retry ? h("div", {}, btn("Retry", retry, "sm", "refresh")) : null));
}
// Run a workspace render; a failure replaces the stale view with an error for the active tab only.
function runRender(tab, fn) {
  const p = fn(); const g = S.viewGen;
  return Promise.resolve(p).catch((e) => {
    if (g === S.viewGen && S.tab === tab && !S.global) $("view").replaceChildren(errorView(`Could not load ${WS[tab]}: ${e.message}`, () => setTab(tab)));
    banner(e.message, "bad");
  });
}
// Re-render the given workspace only if it is still the one on screen (used after mutations).
function refresh(tab, ...args) {
  if (!S.project || S.global || S.tab !== tab) return Promise.resolve();
  return runRender(tab, () => RENDER[tab](...args));
}
let navWired = false;
function wireNav() {
  if (navWired) return; navWired = true;
  $("newProjectBtn").onclick = newProject;
  const menu = $("moreMenu"), more = $("moreBtn");
  const closeMenu = (focus) => { menu.hidden = true; more.setAttribute("aria-expanded", "false"); if (focus) more.focus(); };
  more.onclick = () => { const open = menu.hidden; menu.hidden = !open; more.setAttribute("aria-expanded", open ? "true" : "false"); if (open) $("settingsBtn").focus(); };
  menu.addEventListener("keydown", (e) => { if (e.key === "Escape" || e.key === "Tab") { e.preventDefault(); e.stopPropagation(); closeMenu(true); } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) { e.preventDefault(); $("settingsBtn").focus(); } });
  document.addEventListener("click", (e) => { if (!menu.hidden && !e.target.closest(".menuwrap")) closeMenu(false); });
  $("settingsBtn").onclick = () => { closeMenu(true); projectSettings(); };
  $("providerSel").onchange = (e) => {
    const pid = S.project && S.project.id; const val = e.target.value; if (!pid) return;
    guard(async () => {
      const updated = await api("PATCH", `/api/projects/${pid}`, { provider_default: val });
      if (S.project && S.project.id === pid) { S.project = updated; renderHeader(); }
      loadProjects(); banner(`Project default provider set to ${routeName(val)}.`, "ok");
    });
  };
  document.querySelectorAll("[data-global]").forEach((b) => (b.onclick = () => { closeOverlay(false); openGlobal(b.dataset.global); }));
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => (b.onclick = () => setTab(b.dataset.tab)));
  $("tabs").addEventListener("keydown", (e) => {
    if (!["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft"].includes(e.key)) return;
    e.preventDefault();
    const tabs = [...document.querySelectorAll("#tabs [data-tab]")]; const i = tabs.findIndex((t) => t.dataset.tab === S.tab);
    const fwd = e.key === "ArrowDown" || e.key === "ArrowRight";
    const n = tabs[(i + (fwd ? 1 : tabs.length - 1)) % tabs.length]; setTab(n.dataset.tab); n.focus();
  });
}
async function boot() {
  setupShell(); setupPalette(); setupRoundtable(); wireNav(); crumbs();
  await bootData();
}
async function bootData() {
  takeKey();
  if (!apiKey()) { signInCard(); renderInspector(); return; }
  let recovered = "";
  try {
    const s = await api("GET", "/api/session");
    S.csrf = s.csrf;
    if (s.reconciled && s.reconciled.length) recovered = `Recovered after restart: ${s.reconciled.length} unfinished task(s) marked ${[...new Set(s.reconciled.map((r) => r.to))].join(", ")}. Nothing was replayed automatically.`;
  } catch (e) {
    $("view").replaceChildren(h("div", { class: "empty welcome" }, h("div", { class: "eico" }, icon("shield")), h("div", { class: "et" }, h("strong", {}, "Sign-in needed"),
      h("p", {}, "Open the one-time launch link from launch-link.txt (start.ps1 opens it for you). This keeps other websites and local programs from using your Studio."))));
    renderInspector();
    return;
  }
  try {
    S.routes = await api("GET", "/api/routes");
    await loadProjects();
  } catch (e) {
    $("view").replaceChildren(errorView(`Studio could not load its routes or projects: ${e.message}`, () => bootData()));
    banner(e.message, "bad");
    return;
  }
  const last = localStorageGet("aesop.project");
  if (last && S.projects.some((p) => p.id === last)) await openProject(last);
  else if (!S.projects.length) renderWelcome(); else await openProject(S.projects[0].id);
  if (recovered) banner(recovered);
}

// Show the end of a path: the folders that tell projects apart, not their shared prefix.
function tailPath(p) {
  const s = String(p || ""); const sep = s.includes("\\") ? "\\" : "/";
  const parts = s.split(/[\\/]+/).filter(Boolean);
  return parts.length > 2 ? `…${sep}${parts.slice(-2).join(sep)}` : s;
}
let loadGen = 0;
async function loadProjects() {
  const g = ++loadGen;
  const list = await api("GET", "/api/projects");
  if (g !== loadGen) return;
  S.projects = list;
  $("projectList").replaceChildren(...S.projects.map((p) => h("button", { "aria-current": S.project && S.project.id === p.id && !S.global ? "true" : "false", "data-pid": p.id, title: p.root, "aria-label": `${p.name}, ${p.root}`, onclick: () => { closeOverlay(false); openProject(p.id); } },
    h("span", { class: "avatar av" + hashIdx(p.id, 8), "aria-hidden": "true" }, initials(p.name)), h("span", { class: "pt" }, h("span", { class: "pname" }, p.name), h("small", {}, tailPath(p.root))))));
  if (!S.projects.length) $("projectList").append(h("p", { class: "muted" }, "No projects yet."));
}
function renderWelcome() {
  navBump();
  S.lay = loadJSON(layKey(), { tab: "chat", w: {} }); layout(); crumbs(); renderInspector();
  $("view").replaceChildren(h("div", { class: "empty welcome" }, h("div", { class: "eico" }, icon("folder")), h("div", { class: "et" }, h("strong", {}, "Start with a project"),
    h("p", {}, "A project is one folder you choose. Chats, files, agent tasks, research and memory stay inside it. Studio never reads outside the folder you select."),
    h("div", { class: "row" }, btn("Create project", newProject, "primary", "plus"), btn("Check provider routes", () => openGlobal("providers"), "ghost", "providers")))));
}
async function newProject() {
  closeOverlay(false);
  const usable = usableRoutes();
  const disabled = Object.entries(S.routes).filter(([, r]) => r.state === "READY_METERED_DISABLED").map(([id]) => id);
  const v = await dialog("New project", [
    { name: "name", label: "Name", required: true },
    { name: "root", label: "Project folder (absolute path)", required: true, placeholder: "C:\\Users\\you\\Projects\\my-project", help: "Agent tasks may write only inside this folder." },
    { name: "provider_default", label: "Default provider", type: "select", options: usable.map(([id, r]) => ({ value: id, label: `${routeName(id)} · ${access(r.state)} (${r.state})` })),
      help: disabled.length ? `${disabled.map(routeName).join(", ")} (separately billed API) needs a monthly operating limit in Evidence → Spend controls before it can be chosen.` : null },
  ], "Create");
  if (!v) return;
  await guard(async () => { const p = await api("POST", "/api/projects", v); await loadProjects(); openProject(p.id); });
}
async function projectSettings() {
  const p = S.project; if (!p) return;
  const pol = p.transfer_policy || {};
  const v = await dialog("Project settings", [
    { name: "name", label: "Name", value: p.name },
    { name: "model", label: "Model override (optional)", value: p.model || "", help: "Leave blank to use the provider CLI's default model." },
    { name: "retention_days", label: "Conversation retention (days)", type: "number", value: String(p.retention_days) },
    ...Object.keys(S.routes).filter((k) => USABLE.includes(S.routes[k].state)).map((k) => ({ name: "tp_" + k, label: `Allow sending attached project files to ${routeName(k)}?`, type: "select", value: pol[k] ? "yes" : "no", options: [{ value: "no", label: "No" }, { value: "yes", label: "Yes" }] })),
  ]);
  if (!v) return;
  const tp = {}; for (const [k, val] of Object.entries(v)) if (k.startsWith("tp_")) tp[k.slice(3)] = val === "yes";
  await guard(async () => {
    const updated = await api("PATCH", `/api/projects/${p.id}`, { name: v.name, model: v.model, retention_days: v.retention_days, transfer_policy: tp });
    if (S.project && S.project.id === p.id && !S.global) { S.project = updated; renderHeader(); }
    loadProjects(); banner("Settings saved.", "ok");
  });
}

async function openProject(id) {
  navBump(); const nav = S.navGen;
  S.global = null; S.conv = null; S.taskSel = null; S.preview = null; stopWatch(); markNav();
  await guard(async () => {
    const p = await api("GET", `/api/projects/${id}`);
    if (nav !== S.navGen) return; // a newer selection won
    S.project = p;
    localStorageSet("aesop.project", id);
    S.lay = loadJSON(layKey(), { tab: "chat", w: {} });
    layout(); renderHeader(); await loadProjects();
    if (nav !== S.navGen) return;
    await setTab(WS[S.lay.tab] ? S.lay.tab : "chat");
  });
}
// Route labels outside the header (composer chip, Build line, research draft line) follow the live project default.
function refreshRouteLabels() {
  const p = S.project; if (!p) return;
  const pv = ($("chatProv") && $("chatProv").value) || p.provider_default;
  const rr = S.routes[pv];
  const c = $("composerRoute");
  if (c) c.replaceChildren(pv ? routeDot(pv) : h("span", { class: "dot" }), h("span", { class: "t" },
    `${routeName(pv) || "No provider chosen"}${rr ? " · " + access(rr.state) : ""}${pv !== p.provider_default ? " · not the project default" : ""}`));
  const bt = $("buildRouteTag"); if (bt) bt.replaceChildren(...(rr ? [routeTag(rr)] : []));
  const bd = $("buildRouteDesc"); if (bd) bd.textContent = `Runs the official ${routeName(pv) || "(choose a provider)"} CLI inside ${p.root}. Output is redacted and size-limited. Cancel stops the local process tree only.`;
  const dr = $("draftRoute"); if (dr) dr.textContent = pv ? `Uses ${routeName(pv)}; one request` : "Choose a project provider first";
  const sb = $("sumBtn"); if (sb) sb.title = `Uses ${routeName(pv) || "the project provider"}; one request. Results are proposals for review in Memory.`;
}
function renderHeader() {
  const p = S.project;
  if (S.global) {
    $("projTitle").textContent = GL[S.global]; $("headWs").textContent = "Studio"; $("projMeta").replaceChildren(); $("projControls").hidden = true; $("tabs").hidden = !p;
    routeIndicator(); crumbs(); return;
  }
  $("projTitle").textContent = p ? p.name : "No project open";
  $("headWs").textContent = p && WS[S.tab] ? WS[S.tab] : "";
  const meta = $("projMeta");
  if (p) {
    const r = S.routes[p.provider_default];
    const root = h("span", { class: "rootline", id: "rootLine", title: p.root }, p.root);
    const tog = h("button", { type: "button", class: "linkish pathtog", "aria-controls": "rootLine", "aria-expanded": "false", onclick: () => {
      const full = root.classList.toggle("full"); tog.setAttribute("aria-expanded", full ? "true" : "false"); tog.textContent = full ? "hide full path" : "show full path"; } }, "show full path");
    meta.replaceChildren(root, tog, h("span", { class: "mdot" }, `${routeName(p.provider_default) || "no default provider"}${r ? " · " + access(r.state) : ""}`), h("span", { class: "mdot" }, "saved locally"));
  } else meta.replaceChildren();
  $("projControls").hidden = !p; $("tabs").hidden = !p;
  routeIndicator(); crumbs();
  if (!p) return;
  const sel = $("providerSel");
  sel.replaceChildren(h("option", { value: "" }, "— choose —"), ...Object.entries(S.routes).map(([id, r]) => {
    // Only routes that can actually take a request right now are listed (owner request); others live on Providers.
    if (!USABLE.includes(r.state) || !(r.supported_modes || []).includes("chat")) return null;
    return h("option", { value: id, selected: id === p.provider_default }, `${routeName(id)} · ${access(r.state)}`);
  }).filter(Boolean));
  refreshRouteLabels();
}
function markNav() {
  document.querySelectorAll("[data-global]").forEach((b) => b.setAttribute("aria-current", S.global === b.dataset.global ? "true" : "false"));
}
function setTab(tab) {
  if (!WS[tab]) tab = "chat";
  navBump();
  S.tab = tab; S.global = null; markNav(); S.activity = "";
  S.lay.tab = tab; saveLay();
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => { b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false"); b.tabIndex = b.dataset.tab === tab ? 0 : -1; });
  document.querySelectorAll("#projectList button").forEach((b) => b.setAttribute("aria-current", S.project && b.dataset.pid === S.project.id ? "true" : "false"));
  renderHeader();
  const done = S.project ? runRender(tab, RENDER[tab]) : Promise.resolve();
  renderInspector();
  return done;
}

// ---------- task watcher (one poll shared by Build, Terminal, Changes and Logs) ----------
// W.gen invalidates in-flight polls when the watched task changes, so A -> B -> A never runs two loops.
const W = { tid: null, offset: 0, text: "", task: null, timer: null, hooks: {}, gen: 0, err: null, fails: 0 };
const PERMANENT = [401, 403, 404];
function stopWatch() { W.gen++; clearTimeout(W.timer); W.timer = null; W.tid = null; W.text = ""; W.offset = 0; W.task = null; W.err = null; W.fails = 0; }
function watchTask(tid) {
  if (W.tid === tid) { if (W.err && !W.timer) wRetry(); else notifyTask(""); return; }
  stopWatch(); W.tid = tid; wtick();
}
async function wtick() {
  const tid = W.tid; const g = W.gen; if (!tid) return;
  W.timer = null;
  try {
    const r = await api("GET", `/api/tasks/${tid}?offset=${W.offset}`);
    if (g !== W.gen || tid !== W.tid) return;
    W.err = null; W.fails = 0;
    W.offset = r.offset; if (r.output) W.text += r.output; W.task = r.task;
    notifyTask(r.output || "");
    if (!DONE.includes(r.task.state)) W.timer = setTimeout(wtick, 1500);
  } catch (e) {
    if (g !== W.gen || tid !== W.tid) return;
    W.err = e; W.fails++;
    if (!PERMANENT.includes(e.status)) W.timer = setTimeout(wtick, Math.min(30000, 1500 * 2 ** Math.min(W.fails, 5)));
    notifyTask("");
  }
}
function wRetry() { W.gen++; clearTimeout(W.timer); W.timer = null; W.err = null; W.fails = 0; wtick(); notifyTask(""); }
function wErrNote() {
  const e = W.err; if (!e) return null;
  const msg = e.status === 401 ? "Your Studio session has expired. Open the launch link again (start.ps1 opens it) to sign back in."
    : e.status === 404 ? "This task record is no longer available."
    : e.status === 403 ? `Studio refused this request: ${e.message}`
    : `Could not refresh this task: ${e.message}. Retrying automatically.`;
  return h("div", { class: "note bad", role: "status" }, icon("alert"), h("div", { class: "section" }, h("span", {}, msg), h("div", {}, btn("Retry now", wRetry, "sm", "refresh"))));
}
const wErrKey = () => (W.err ? `${W.err.status || ""}:${W.err.message}` : "");
function notifyTask(chunk) { for (const f of Object.values(W.hooks)) { try { f(chunk); } catch { /* detached view */ } } }

// ---------- inspector ----------
function setItab(t) {
  S.itab = t; localStorageSet("aesop.itab", t);
  document.querySelectorAll("#itabs [data-itab]").forEach((b) => { const on = b.dataset.itab === t; b.setAttribute("aria-selected", on ? "true" : "false"); b.tabIndex = on ? 0 : -1; if (on && b.id) $("inspBody").setAttribute("aria-labelledby", b.id); if (on && b.scrollIntoView) b.scrollIntoView({ block: "nearest", inline: "nearest" }); });
}
let inspGen = 0;
async function renderInspector() {
  const body = $("inspBody"); const gen = ++inspGen; delete W.hooks.insp;
  if (!inspectorVisible()) return;
  if (!S.project) { body.replaceChildren(empty("panel", "No project open", "Open a project to see its saved items, files, task changes, terminal output and task log here.")); return; }
  const pid = S.project.id;
  try {
    if (S.itab === "files") return await inspFiles(body, pid, gen);
    if (S.itab === "preview") return await inspPreview(body, pid, gen);
    const tasks = await api("GET", `/api/projects/${pid}/tasks`);
    if (gen !== inspGen) return;
    if (S.itab === "logs") return inspLogs(body, tasks);
    const tid = S.taskSel && tasks.some((t) => t.id === S.taskSel) ? S.taskSel : tasks[0] && tasks[0].id;
    if (!tid) {
      body.replaceChildren(S.itab === "terminal"
        ? empty("terminal", "No task output yet", "Start a task in Build. Its live, redacted output from the provider CLI appears here.")
        : empty("diff", "No changes recorded", "Changed files are recorded when a Build task runs in the project folder. Start one in Build to see added, modified and removed files here."));
      return;
    }
    watchTask(tid);
    if (S.itab === "terminal") inspTerminal(body, tid, tid !== S.taskSel); else inspChanges(body, tid, tid !== S.taskSel);
  } catch (e) { if (gen === inspGen) body.replaceChildren(h("div", { class: "note bad" }, icon("alert"), h("span", {}, e.message))); }
}
async function inspFiles(body, pid, gen) {
  const atts = await api("GET", `/api/projects/${pid}/attachments`);
  if (gen !== inspGen) return;
  const input = h("input", { type: "file", multiple: true, "aria-label": "Choose files to add", class: "grow" });
  const upload = (files) => guard(async () => {
    for (const f of files) {
      try { const a = await api("POST", `/api/projects/${pid}/attachments`, undefined, { name: f.name, data: f });
        banner(`${a.name}: ${a.extract_status} — ${a.extract_note}`, a.extract_status === "extracted" ? "ok" : ""); }
      catch (e) { banner(`${f.name}: ${e.message}`, "bad"); }
    }
    renderInspector(); refresh("chat");
  });
  input.onchange = () => upload(input.files);
  const drop = h("div", { class: "drop" }, h("div", { class: "dt" }, h("strong", {}, "Add project files"), "Drop files here or choose them. Only the files you pick are copied in (5 MB limit). Text formats are read; others are kept with a hash and an honest status."), input);
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer && e.dataTransfer.files.length) upload(e.dataTransfer.files); });
  body.replaceChildren(drop, h("div", { class: "section-head" }, h("h2", {}, "Project files", h("span", { class: "count" }, String(atts.length)))),
    atts.length ? h("div", { class: "flist" }, ...atts.map((a) => h("div", { class: "fitem" }, h("div", { class: "fn" }, icon("file", "sm"), h("span", { title: a.name }, a.name), statePill(a.extract_status)),
      a.extract_note ? h("div", { class: "fm" }, a.extract_note) : null,
      h("div", { class: "fm" }, `${(a.size / 1024).toFixed(1)} KB · `, h("code", { title: a.sha256 }, a.sha256.slice(0, 12)), ` · ${fmtTime(a.created)}`))))
      : empty("file", "No files yet", "Uploaded text files can be attached to chat messages and used as local research sources."));
}
async function inspPreview(body, pid, gen) {
  const arts = await api("GET", `/api/projects/${pid}/artifacts`);
  if (gen !== inspGen) return;
  const a = arts.find((x) => x.id === S.preview) || arts[0];
  if (!a) { body.replaceChildren(empty("eye", "Nothing to preview", "Save a chat answer or a task result. Saved items are previewed here as plain text.")); return; }
  body.replaceChildren(h("div", { class: "card-head" }, h("div", { class: "ttl" }, statePill(a.kind)), h("span", { class: "faint" }, a.id === S.preview ? fmtTime(a.created) : "Most recent saved item · " + fmtTime(a.created))),
    h("h2", {}, a.title), h("p", { class: "faint" }, "Shown as plain text. HTML in saved items is never rendered or executed."), h("pre", { class: "out" }, a.content));
}
function inspLogs(body, tasks) {
  body.replaceChildren(h("p", { class: "faint" }, "Recent task states from this project's task records (newest first)."),
    tasks.length ? h("div", { class: "ilist" }, ...tasks.map((t) => h("div", { class: "ilog" }, h("span", { class: "lt" }, fmtClock(t.ended || t.started || t.created)),
      h("span", { class: "lm" }, statePill(t.state), h("span", {}, routeName(t.provider)), h("code", {}, t.id), t.exit_code !== null && t.exit_code !== undefined ? h("span", { class: "faint" }, `exit ${t.exit_code}`) : null,
        t.error ? h("span", { class: "faint" }, t.error) : null))))
      : empty("list", "No log entries", "Each Build task adds its state, provider, exit code and any error here."));
}
function inspTerminal(body, tid, auto) {
  const pre = h("pre", { "aria-live": "off", tabindex: "0", "aria-label": "Task output" });
  const bar = h("span", { class: "grow" }, `task ${tid}`); const st = h("span"); const errBox = h("div");
  pre.textContent = W.tid === tid ? W.text : "";
  body.replaceChildren(auto ? h("p", { class: "faint" }, "Most recent task. Select another in Build.") : null, errBox,
    h("div", { class: "term" }, h("div", { class: "term-bar" }, icon("terminal", "sm"), bar, st), pre));
  let errShown = null;
  const upd = (chunk) => {
    if (W.tid !== tid) return;
    const k = wErrKey(); if (k !== errShown) { errShown = k; errBox.replaceChildren(...(W.err ? [wErrNote()] : [])); }
    const t = W.task; if (!t) return;
    bar.textContent = `${t.id} · ${routeName(t.provider)}`; st.replaceChildren(statePill(t.state));
    if (chunk) { const stick = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 60; pre.append(chunk); if (stick) pre.scrollTop = pre.scrollHeight; }
  };
  W.hooks.insp = upd; upd("");
}
function inspChanges(body, tid, auto) {
  const wrap = h("div", { class: "changes" }); const errBox = h("div");
  body.replaceChildren(auto ? h("p", { class: "faint" }, "Most recent task. Select another in Build.") : null, errBox, wrap);
  let errShown = null; let lastSig = null;
  const upd = () => {
    if (W.tid !== tid) return;
    const k = wErrKey(); if (k !== errShown) { errShown = k; errBox.replaceChildren(...(W.err ? [wErrNote()] : [])); }
    const t = W.task;
    if (!t) { if (lastSig !== "loading") { lastSig = "loading"; wrap.replaceChildren(W.err ? h("span") : h("p", { class: "faint" }, "Loading task record…")); } return; }
    const sig = `${t.state}|${t.changed_files || ""}`; if (sig === lastSig) return; lastSig = sig;
    let ch = null; try { ch = t.changed_files ? JSON.parse(t.changed_files) : null; } catch { ch = null; }
    const head = h("div", { class: "card-head" }, h("div", { class: "ttl" }, h("h3", {}, `Task ${t.id}`)), statePill(t.state));
    if (!ch) { wrap.replaceChildren(head, h("p", { class: "muted" }, DONE.includes(t.state) ? "This task did not record changed files." : "Changed files are recorded when the task finishes.")); return; }
    const grp = (cls, title, list) => h("div", { class: "grp " + cls }, h("h3", {}, title, h("span", { class: "count" }, String(list.length))),
      list.length ? h("ul", {}, ...list.map((f) => h("li", {}, f))) : h("p", { class: "faint" }, "none"));
    wrap.replaceChildren(head, grp("add", "Added", ch.added || []), grp("mod", "Modified", ch.modified || []), grp("rem", "Removed", ch.removed || []));
  };
  W.hooks.insp = upd; upd();
}

// ---------- chat ----------
const SUGGESTIONS = [
  ["note", "Summarize the attached file and list its key points."],
  ["sparkle", "Draft a short plan for the next step of this project."],
  ["layers", "What decisions should I record in project memory?"],
  ["check", "Turn my notes into a checklist I can work through."],
];
function autosize(ta) {
  const grow = () => { ta.style.height = "auto"; const max = parseFloat(getComputedStyle(ta).maxHeight) || 240; ta.style.height = Math.min(ta.scrollHeight + 2, max) + "px"; };
  ta.addEventListener("input", grow); requestAnimationFrame(grow); return grow;
}
// Unsent drafts survive re-renders, conversation switches and page reloads (sessionStorage, best-effort).
function ssGet(k) { try { return sessionStorage.getItem(k); } catch { return null; } }
function ssSet(k, v) { try { if (v) sessionStorage.setItem(k, v); else sessionStorage.removeItem(k); } catch { /* optional */ } }
const chatChips = {}; // cid -> Set of attachment ids chosen in the composer
// ---------- photos, files and folders in chat ----------
// Photos are sized for the provider that will read them: the most pixels it can actually use, no more (beyond
// that it shrinks the image itself, so extra pixels only cost upload time). Claude (Claude Code): long edge
// 1568 px and about 1.15 MP. OpenAI (Codex, Codex API, detail "high"): fits 2048 x 2048 with the short side at
// 768 px. Very tall or wide images (long screenshots, receipts) are split into overlapping parts, each sized the
// same way, so their text stays readable instead of shrinking to a sliver.
const PHOTO_ROUTES = ["codex", "claude", "openai-api", "simulated"]; // verified live to see an image
const PHOTO_TARGETS = { claude: { edge: 1568, mp: 1.15e6 }, codex: { edge: 2048, short: 768 }, "openai-api": { edge: 2048, short: 768 } };
const PHOTO_DEFAULT = { edge: 2048 };
const photoTarget = (route) => PHOTO_TARGETS[route] || PHOTO_DEFAULT;
const PHOTO_MAX = 6, PHOTO_PARTS_MAX = 12, PHOTO_FILE_MAX = 5 * 1024 * 1024;
const chatPhotos = {}; // cid -> [{ key, orig, name, size, url, parts: [ids], target, dims, state, err }]
const chatFiles = {};  // cid -> [{ key, name, size, group, id, state: "uploading"|"ready"|"unreadable"|"error", err }]
const photoCache = {}; // attachment id -> blob URL (thumbnails in sent messages)
const isPhotoFile = (f) => f && (/^image\/(png|jpeg|gif|webp|heic|heif)$/.test(f.type) || /\.(png|jpe?g|gif|webp|heic|heif)$/i.test(f.name || ""));
const fmtKB = (n) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
function fitScale(w, h, t) {
  let s = Math.min(1, t.edge / Math.max(w, h));
  if (t.short) s = Math.min(s, t.short / Math.min(w, h));
  if (t.mp) s = Math.min(s, Math.sqrt(t.mp / (w * h)));
  return s;
}
function splitRects(w, h) {
  const long = Math.max(w, h), short = Math.min(w, h);
  if (long / short <= 2.2) return [[0, 0, w, h]];
  const k = Math.min(4, Math.ceil(long / short / 1.6)); const seg = long / k; const ov = Math.round(seg * 0.06);
  return Array.from({ length: k }, (_, i) => {
    const a = Math.max(0, Math.round(i * seg - ov)), b = Math.min(long, Math.round((i + 1) * seg + ov));
    return w >= h ? [a, 0, b - a, h] : [0, a, w, b - a];
  });
}
async function encodeRect(bmp, [sx, sy, sw, sh], t, type, base) {
  const s = fitScale(sw, sh, t);
  const w = Math.max(1, Math.round(sw * s)), hh = Math.max(1, Math.round(sh * s));
  const cv = document.createElement("canvas"); cv.width = w; cv.height = hh;
  const cx = cv.getContext("2d"); cx.imageSmoothingEnabled = true; cx.imageSmoothingQuality = "high";
  cx.drawImage(bmp, sx, sy, sw, sh, 0, 0, w, hh);
  const blobOf = (ty, q) => new Promise((res) => cv.toBlob(res, ty, q));
  if (type === "image/png") { // screenshots stay lossless when they fit: text edges stay sharp
    const png = await blobOf("image/png");
    if (png && png.size <= PHOTO_FILE_MAX) return new File([png], base + ".png", { type: "image/png" });
  }
  cx.globalCompositeOperation = "destination-over"; cx.fillStyle = "#ffffff"; cx.fillRect(0, 0, w, hh); // no black where it was transparent
  for (const q of [0.92, 0.85, 0.75, 0.6]) {
    const jpg = await blobOf("image/jpeg", q);
    if (jpg && jpg.size <= PHOTO_FILE_MAX) return new File([jpg], base + ".jpg", { type: "image/jpeg" });
  }
  throw new Error(`${base} is still over 5 MB after resizing.`);
}
async function preparePhoto(file, route) {
  const type = file.type || "";
  if (/heic|heif/i.test(type) || /\.hei[cf]$/i.test(file.name || "")) throw new Error(`${file.name}: HEIC photos can't be read here. Save it as JPG or PNG first.`);
  if (!/^image\/(png|jpeg|gif|webp)$/.test(type)) throw new Error(`${file.name || "That file"} isn't a PNG, JPG, GIF or WebP photo.`);
  const t = photoTarget(route); const key = JSON.stringify(t);
  if (type === "image/gif" && file.size <= PHOTO_FILE_MAX) return { parts: [file], target: key, dims: "", split: 1 }; // keep animation
  let bmp;
  try { bmp = await createImageBitmap(file); } catch { throw new Error(`${file.name || "That photo"} couldn't be opened.`); }
  try {
    const rects = splitRects(bmp.width, bmp.height);
    const base = (file.name || "photo").replace(/\.[^.]+$/, "") || "photo";
    if (rects.length === 1 && fitScale(bmp.width, bmp.height, t) === 1 && file.size <= PHOTO_FILE_MAX)
      return { parts: [file], target: key, dims: `${bmp.width}×${bmp.height}`, split: 1 }; // already the right size
    const parts = [];
    for (let i = 0; i < rects.length; i++) parts.push(await encodeRect(bmp, rects[i], t, type, rects.length > 1 ? `${base}-part${i + 1}` : base));
    const s = fitScale(rects[0][2], rects[0][3], t);
    return { parts, target: key, dims: `${Math.round(rects[0][2] * s)}×${Math.round(rects[0][3] * s)}`, split: rects.length };
  } finally { bmp.close && bmp.close(); }
}
// Folders: walk dropped directories (or a picked folder), skipping build output and dependency folders.
const SKIP_DIRS = /^(node_modules|\.git|\.hg|\.svn|\.venv|venv|env|__pycache__|\.mypy_cache|\.pytest_cache|dist|build|out|\.next|\.nuxt|target|bin|obj|coverage|\.cache|\.idea|\.gradle)$/i;
const FILE_MAX = 60, FOLDER_SCAN_MAX = 600;
async function walkEntries(entries) {
  const out = []; let scanned = 0, skipped = 0;
  const readAll = (dir) => new Promise((res) => { const r = dir.createReader(); const acc = [];
    const step = () => r.readEntries((b) => { if (!b.length) res(acc); else { acc.push(...b); step(); } }, () => res(acc)); step(); });
  const fileOf = (fe) => new Promise((res) => fe.file(res, () => res(null)));
  async function walk(entry, prefix) {
    if (scanned >= FOLDER_SCAN_MAX) { skipped++; return; }
    if (entry.isFile) { scanned++; const f = await fileOf(entry); if (f) out.push({ file: f, path: prefix + entry.name }); return; }
    if (entry.isDirectory) {
      if (SKIP_DIRS.test(entry.name)) { skipped++; return; }
      for (const c of await readAll(entry)) await walk(c, prefix + entry.name + "/");
    }
  }
  for (const e of entries) await walk(e, "");
  return { files: out, skipped };
}
async function photoURL(id) {
  if (photoCache[id] !== undefined) return photoCache[id];
  try {
    const r = await fetch(`/api/attachments/${id}/image`, { headers: { "X-Aesop-Key": apiKey() }, credentials: "same-origin" });
    photoCache[id] = r.status === 200 ? URL.createObjectURL(await r.blob()) : null;
  } catch { photoCache[id] = null; }
  return photoCache[id];
}
function photoViewer(url, name) {
  const img = h("img", { src: url, alt: name || "Photo", class: "pv-img" });
  const d = h("dialog", { class: "pv", "aria-label": name || "Photo" },
    h("button", { type: "button", class: "iconbtn pv-x", "aria-label": "Close photo" }, icon("x")), img,
    h("div", { class: "pv-cap" }, name || ""));
  d.addEventListener("click", (e) => { if (e.target === d || e.target.closest(".pv-x")) d.close(); });
  d.addEventListener("close", () => d.remove());
  document.body.append(d); d.showModal();
}
window.addEventListener("paste", (e) => { if (S.chatPaste && !e.defaultPrevented) S.chatPaste(e); });
async function renderChat() {
  if (!S.project || S.global || S.tab !== "chat") return;
  const pid = S.project.id;
  const gen = ++S.viewGen;
  const convs = await api("GET", `/api/projects/${pid}/conversations`);
  if (gen !== S.viewGen) return;
  let atts = (await api("GET", `/api/projects/${pid}/attachments`)).filter((a) => a.extract_status === "extracted");
  if (gen !== S.viewGen) return;
  // Only a current render may change shared chat state.
  if (!S.conv || !convs.some((c) => c.id === S.conv)) S.conv = convs.length ? convs[0].id : null;
  const cid = S.conv;
  if (S.streamConv !== cid) { S.streams = {}; S.streamConv = cid; }
  S.streamUpd = {}; S.msgSig = "";
  const cur = convs.find((c) => c.id === cid); setActivity(cur ? cur.title : "");
  const newConv = async () => guard(async () => { const c = await api("POST", `/api/projects/${pid}/conversations`, {}); if (S.project && S.project.id === pid) { S.conv = c.id; refresh("chat"); } });
  const sumBtn = cid ? abtn("Summarize to memory", async () => {
    await startDerivation("summary", `/api/projects/${pid}/conversations/${cid}/summarize`, {}, () => refresh("memory"));
  }, "ghost", "layers") : null;
  if (sumBtn) { sumBtn.id = "sumBtn"; if (dRunning(DERIV[dkey("summary")]) || !S.project.provider_default) sumBtn.disabled = true; }
  const bar = h("div", { class: "convbar" },
    convs.length ? h("div", { class: "convstrip", role: "list", "aria-label": "Conversations" }, ...convs.map((c) => h("span", { role: "listitem", class: "convchip" + (c.id === cid ? " cur" : "") },
      h("button", { type: "button", class: "convpick", "aria-current": c.id === cid ? "true" : "false", title: c.title, onclick: () => { S.conv = c.id; refresh("chat"); } }, icon("chat", "sm"), h("span", {}, c.title)),
      h("button", { type: "button", class: "convdel", "aria-label": `Delete conversation ${c.title}`, title: "Delete conversation", onclick: () => deleteConversation(pid, c.id) }, icon("trash", "sm"))))) : h("span", { class: "grow" }),
    sumBtn, cid ? abtn("Delete conversation", () => deleteConversation(pid, cid), "ghost danger del", "trash") : null, rtMenu(), btn("War Room", (e) => openRoundtable(e.currentTarget, { mode: "war_room" }), "rt-entry", "shield"), btn("New conversation", newConv, "ghost", "plus"));
  const rpanel = h("section", { id: "researchPanel", class: "card rpanel", "aria-label": "Research notebook", hidden: !researchOpen(pid) });
  const researchBtn = h("button", { type: "button", id: "researchBtn", class: "btn ghost", "aria-expanded": researchOpen(pid) ? "true" : "false", "aria-controls": "researchPanel",
    title: "Sources, findings, project search and notebook export (Ctrl+3)", onclick: async () => {
      const on = rpanel.hidden; setResearchOpen(pid, on); rpanel.hidden = !on; researchBtn.setAttribute("aria-expanded", on ? "true" : "false");
      if (on) await researchPanel(rpanel, pid);
    } }, icon("search"), "Research");
  bar.insertBefore(researchBtn, bar.firstChild && bar.firstChild.nextSibling ? bar.firstChild.nextSibling : null);
  const root = h("div", { class: "chatv" }, bar, rpanel, h("div", { "data-deriv": "summary", class: "section" }, ...dView("summary")));
  if (!rpanel.hidden) researchPanel(rpanel, pid);
  if (!cid) {
    root.append(empty("chat", "No conversations yet", "Start a conversation to talk with this project's provider. Messages are saved locally before anything is sent.", btn("Start a conversation", newConv, "primary", "plus")));
    $("view").replaceChildren(root); refreshRouteLabels(); return;
  }
  const draftKey = "aesop.draft.chat." + cid;
  const provKey = "aesop.chat.prov." + cid;
  const chips = chatChips[cid] || (chatChips[cid] = new Set());
  const usable = usableRoutes();
  let provPick = ssGet(provKey) || S.project.provider_default || "";
  if (!usable.some(([id]) => id === provPick)) provPick = S.project.provider_default || (usable[0] && usable[0][0]) || "";
  const msgsEl = h("div", { class: "msgs", "aria-live": "polite", "aria-relevant": "additions" });
  const ta = h("textarea", { "aria-label": "Message", placeholder: "Ask something about this project…" });
  ta.value = ssGet(draftKey) || "";
  ta.addEventListener("input", () => ssSet(draftKey, ta.value));
  const chosen = () => [...chips].filter((id) => atts.some((a) => a.id === id));
  const photos = chatPhotos[cid] || (chatPhotos[cid] = []);
  const files = chatFiles[cid] || (chatFiles[cid] = []);
  const tray = h("div", { class: "ptray", role: "group", "aria-label": "Photos and files for this message" });
  const trayNote = h("div", { class: "pnote", role: "status", "aria-live": "polite" });
  const readyPhotos = () => photos.filter((x) => x.state === "ready").flatMap((x) => x.parts);
  const readyFiles = () => files.filter((x) => x.state === "ready").map((x) => x.id);
  const busy = () => photos.some((x) => x.state === "uploading") || files.some((x) => x.state === "uploading");
  const discard = (ids) => { for (const id of ids || []) if (id) api("POST", `/api/attachments/${id}/discard`).catch(() => {}); };
  const removeFiles = (pred) => { for (let i = files.length - 1; i >= 0; i--) if (pred(files[i])) { discard([files[i].id]); files.splice(i, 1); } drawTray(); ta.focus(); };
  const drawTray = () => {
    const prov = messageProvider(); const t = photoTarget(prov);
    const groups = {}; const singles = [];
    for (const f of files) { if (f.group) (groups[f.group] = groups[f.group] || []).push(f); else singles.push(f); }
    const fileChip = (label, title, state, onRemove, ico) => h("span", { class: "fchip " + state, title },
      icon(ico, "sm"), h("span", { class: "t" }, label), state === "uploading" ? h("span", { class: "pbusy sm", "aria-label": "Uploading" }) : null,
      h("button", { type: "button", class: "fdel", "aria-label": `Remove ${label}`, onclick: onRemove }, icon("x", "sm")));
    tray.hidden = !photos.length && !files.length;
    tray.replaceChildren(
      ...photos.map((x) => h("figure", { class: "pthumb " + x.state, title: x.err || `${x.name} · ${x.dims || ""} · ${fmtKB(x.size)}${x.parts.length > 1 ? ` · split into ${x.parts.length} parts so the text stays readable` : ""}` },
        x.url ? h("img", { src: x.url, alt: x.name }) : null,
        x.state === "uploading" ? h("span", { class: "pbusy", "aria-label": "Preparing" }) : null,
        x.state === "error" ? h("span", { class: "perr" }, icon("alert", "sm")) : null,
        x.parts.length > 1 ? h("span", { class: "pparts" }, `×${x.parts.length}`) : null,
        h("button", { type: "button", class: "pdel", "aria-label": `Remove ${x.name}`, onclick: () => {
          const i = photos.indexOf(x); if (i >= 0) photos.splice(i, 1); discard(x.parts); if (x.url) URL.revokeObjectURL(x.url); drawTray(); ta.focus(); } }, icon("x", "sm")))),
      ...Object.entries(groups).map(([g, list]) => {
        const ok = list.filter((f) => f.state === "ready").length, bad = list.filter((f) => f.state === "unreadable" || f.state === "error").length;
        const up = list.some((f) => f.state === "uploading");
        return fileChip(`${g}/ · ${ok} file${ok === 1 ? "" : "s"}${bad ? ` (${bad} not readable)` : ""}`, list.map((f) => `${f.name}${f.err ? " — " + f.err : ""}`).join("\n"),
          up ? "uploading" : ok ? "ready" : "error", () => removeFiles((f) => f.group === g), "layers");
      }),
      ...singles.map((f) => fileChip(f.name, f.err || `${f.name} · ${fmtKB(f.size)}`, f.state, () => removeFiles((y) => y === f), "file")),
      photos.length || files.length ? h("span", { class: "pcount faint" }, [
        photos.length ? `${photos.length}/${PHOTO_MAX} photos · sized for ${routeName(prov) || "the provider"} (up to ${t.edge}px)` : "",
        files.length ? `${readyFiles().length}/${FILE_MAX} files` : ""].filter(Boolean).join(" · ")) : null);
    checkAttach();
  };
  const checkAttach = () => {
    const prov = messageProvider(); const nP = readyPhotos().length; const nF = readyFiles().length + chosen().length;
    const errs = [...photos, ...files].filter((x) => x.state === "error" && x.err);
    const bits = [];
    if (errs.length) bits.push(h("span", { class: "bad" }, errs[errs.length - 1].err));
    const research = ["firecrawl", "perplexity"].includes(prov);
    if ((nP || nF) && research) {
      bits.push(h("span", {}, `${routeName(prov)} takes questions and links, not files or photos.`), ...usable.filter(([id]) => PHOTO_ROUTES.includes(id)).map(([id]) => h("button", { type: "button", class: "linkish", onclick: () => {
        provSel.value = id; ssSet(provKey, id); refreshRouteLabels(); refit(); } }, `Use ${routeName(id)}`)));
    } else if (nP && prov && !PHOTO_ROUTES.includes(prov)) {
      const alts = usable.filter(([id]) => PHOTO_ROUTES.includes(id));
      bits.push(h("span", {}, `${routeName(prov)} can't see photos.`), ...alts.map(([id]) => h("button", { type: "button", class: "linkish", onclick: () => {
        provSel.value = id; ssSet(provKey, id); refreshRouteLabels(); refit(); } }, `Use ${routeName(id)}`)));
    } else if ((nP || nF) && prov && !(S.project.transfer_policy || {})[prov]) {
      bits.push(h("span", {}, `Sending files to ${routeName(prov)} is off for this project.`), abtn(`Allow for ${routeName(prov)}`, async () => {
        const pol = { ...(S.project.transfer_policy || {}), [prov]: true };
        const up = await api("PATCH", `/api/projects/${pid}`, { transfer_policy: pol });
        S.project = { ...S.project, ...up, transfer_policy: up.transfer_policy || pol }; banner(`Photos and files can now be sent to ${routeName(prov)} in this project.`, "ok"); checkAttach();
      }, "sm"));
    }
    trayNote.replaceChildren(...bits); trayNote.hidden = !bits.length;
  };
  const uploadPhoto = async (x, route) => {
    x.state = "uploading"; drawTray();
    try {
      const prep = await preparePhoto(x.orig, route);
      if (x.url) URL.revokeObjectURL(x.url);
      x.url = URL.createObjectURL(prep.parts[0]); x.dims = prep.dims; x.size = prep.parts.reduce((n, p) => n + p.size, 0);
      drawTray();
      const ids = [];
      for (const part of prep.parts) {
        const nm = x.pasted ? `pasted-${x.key.slice(0, 5)}${part.name.slice(part.name.lastIndexOf("."))}` : part.name;
        const a = await api("POST", `/api/projects/${pid}/attachments`, undefined, { name: nm, data: part });
        if (a.extract_status !== "image") throw new Error(`${x.name}: ${a.extract_note || "not recognised as a photo"}`);
        ids.push(a.id);
        if (ids.length === 1) photoCache[a.id] = x.url;
      }
      discard(x.parts.filter((id) => !ids.includes(id))); // the previous size is no longer needed
      x.parts = ids; x.target = prep.target; x.state = "ready"; x.err = "";
    } catch (e) {
      x.state = "error"; x.err = e.message; x.parts = [];
      if (!x.url) { const i = photos.indexOf(x); if (i >= 0) photos.splice(i, 1); banner(e.message, "bad"); }
    }
    drawTray();
  };
  // switching provider re-sizes photos for the new one (from the original, never from a smaller copy)
  const refit = () => {
    const prov = messageProvider(); const want = JSON.stringify(photoTarget(prov));
    for (const x of photos) if (x.state === "ready" && x.target !== want && x.orig.type !== "image/gif") uploadPhoto(x, prov);
    drawTray();
  };
  const addPhotos = async (list) => {
    list = [...list].filter(isPhotoFile);
    if (!list.length) return 0;
    const room = PHOTO_MAX - photos.length;
    if (room <= 0) { banner(`Up to ${PHOTO_MAX} photos per message. Remove one to add another.`, "bad"); return list.length; }
    if (list.length > room) banner(`Added ${room} of ${list.length}: up to ${PHOTO_MAX} photos per message.`);
    const items = list.slice(0, room).map((f) => ({ key: Math.random().toString(36).slice(2), orig: f, pasted: !f.name || /^image\.(png|jpe?g)$/i.test(f.name),
      name: f.name || "pasted photo", size: f.size, url: "", parts: [], target: "", dims: "", state: "uploading" }));
    photos.push(...items);
    await Promise.all(items.map((x) => uploadPhoto(x, messageProvider())));
    return list.length;
  };
  // Files and folders: entries are { file, path } (path keeps the folder, e.g. "app/src/main.py").
  const addFiles = async (entries, group, skippedDirs) => {
    entries = [...entries];
    const pics = entries.filter((e) => isPhotoFile(e.file)).map((e) => e.file);
    let rest = entries.filter((e) => !isPhotoFile(e.file));
    if (pics.length) await addPhotos(pics);
    if (!rest.length) return pics.length;
    const room = FILE_MAX - files.length;
    let extra = 0;
    if (rest.length > room) { extra = rest.length - Math.max(0, room); rest = rest.slice(0, Math.max(0, room)); }
    const items = rest.map((e) => ({ key: Math.random().toString(36).slice(2), name: e.path || e.file.name || "file", size: e.file.size, group: group || null, file: e.file, state: "uploading" }));
    files.push(...items); drawTray();
    let i = 0;
    const worker = async () => {
      while (i < items.length) {
        const x = items[i++];
        if (x.size > PHOTO_FILE_MAX) { x.state = "error"; x.err = `${x.name} is over the 5 MB file limit.`; continue; }
        try {
          const a = await api("POST", `/api/projects/${pid}/attachments`, undefined, { name: x.name, data: x.file });
          x.id = a.id;
          if (a.extract_status === "extracted") x.state = "ready";
          else { x.state = "unreadable"; x.err = a.extract_note || `${a.extract_status}`; }
        } catch (e) { x.state = "error"; x.err = e.message; }
        delete x.file; drawTray();
      }
    };
    await Promise.all([worker(), worker(), worker()]); // three uploads at a time
    const unread = items.filter((x) => x.state === "unreadable").length;
    const notes = [];
    if (extra) notes.push(`${extra} more file${extra === 1 ? "" : "s"} left out (up to ${FILE_MAX} per message)`);
    if (skippedDirs) notes.push(`skipped ${skippedDirs} build/dependency folder${skippedDirs === 1 ? "" : "s"} (node_modules, .git, dist…)`);
    if (unread) notes.push(`${unread} file${unread === 1 ? "" : "s"} couldn't be read as text and won't be sent`);
    if (notes.length) banner(notes.join("; ") + ".");
    drawTray();
    return entries.length;
  };
  const photoPick = h("input", { type: "file", accept: "image/png,image/jpeg,image/gif,image/webp", multiple: true, class: "sr-only", tabindex: "-1", "aria-hidden": "true",
    onchange: (e) => { addPhotos(e.target.files); e.target.value = ""; } });
  const filePick = h("input", { type: "file", multiple: true, class: "sr-only", tabindex: "-1", "aria-hidden": "true",
    onchange: (e) => { addFiles([...e.target.files].map((f) => ({ file: f, path: f.name }))); e.target.value = ""; } });
  const folderPick = h("input", { type: "file", multiple: true, webkitdirectory: true, class: "sr-only", tabindex: "-1", "aria-hidden": "true",
    onchange: (e) => {
      const all = [...e.target.files]; e.target.value = ""; if (!all.length) return;
      const group = (all[0].webkitRelativePath || "folder").split("/")[0];
      let skipped = 0; const keep = [];
      for (const f of all) { const segs = (f.webkitRelativePath || f.name).split("/"); if (segs.slice(1, -1).some((s) => SKIP_DIRS.test(s))) skipped++; else keep.push({ file: f, path: segs.join("/") }); }
      addFiles(keep, group, skipped ? 1 : 0);
    } });
  const photoBtn = h("button", { type: "button", class: "btn ghost sm", title: "Add photos (or paste with Ctrl+V, or drop them here)", onclick: () => photoPick.click() }, icon("image", "sm"), "Photo");
  const fileBtn = h("button", { type: "button", class: "btn ghost sm", title: "Add files from this PC (or drop them here)", onclick: () => filePick.click() }, icon("file", "sm"), "File");
  const folderBtn = h("button", { type: "button", class: "btn ghost sm", title: "Add a folder from this PC: its readable files are attached (build and dependency folders are skipped)", onclick: () => folderPick.click() }, icon("layers", "sm"), "Folder");
  S.chatPaste = (e) => {
    if (S.tab !== "chat" || !document.body.contains(ta) || document.querySelector("dialog[open]")) return;
    const got = [...(e.clipboardData ? e.clipboardData.items : [])].filter((i) => i.kind === "file").map((i) => i.getAsFile()).filter(Boolean);
    if (!got.length) return; // plain text pastes normally
    e.preventDefault(); addFiles(got.map((f) => ({ file: f, path: f.name })));
  };
  let sending = false;
  const messageProvider = () => ($("chatProv") && $("chatProv").value) || provPick || S.project.provider_default;
  const send = async (confirm) => {
    if (sending) return;
    const raw = ta.value; const provider = messageProvider();
    if (!provider) { banner("Choose a provider for this message.", "bad"); return; }
    if (busy()) { banner("Photos or files are still uploading — one moment.", "bad"); return; }
    let pics = readyPhotos(); const fids = readyFiles();
    if (pics.length && !PHOTO_ROUTES.includes(provider)) { checkAttach(); banner(`${routeName(provider)} can't see photos. Pick Codex or Claude Code, or remove the photos.`, "bad"); return; }
    const want = JSON.stringify(photoTarget(provider));
    const stale = photos.filter((x) => x.state === "ready" && x.target !== want && x.orig.type !== "image/gif");
    if (stale.length) { sendBtn.disabled = true; await Promise.all(stale.map((x) => uploadPhoto(x, provider))); sendBtn.disabled = false; pics = readyPhotos(); }
    if (pics.length > PHOTO_PARTS_MAX) { banner(`Too many photo parts (${pics.length}); remove a long screenshot or two.`, "bad"); return; }
    const text = raw.trim() || (pics.length ? `Please look at the attached photo${pics.length > 1 ? "s" : ""}.` : fids.length ? "Please look at the attached files." : "");
    if (!text) { ta.focus(); return; }
    sending = true; sendBtn.disabled = true; sendBtn.setAttribute("aria-busy", "true");
    try {
      await api("POST", `/api/projects/${pid}/conversations/${cid}/messages`,
        { text, attachment_ids: [...chosen(), ...fids, ...pics], provider, confirm_switch: !!confirm });
      if (ta.value === raw) { ta.value = ""; grow(); ssSet(draftKey, ""); } // keep anything typed while the request was pending
      for (const x of photos.filter((y) => y.parts.some((id) => pics.includes(id)))) photos.splice(photos.indexOf(x), 1);
      for (const x of files.filter((y) => fids.includes(y.id) || y.state === "unreadable" || y.state === "error")) files.splice(files.indexOf(x), 1);
      try { atts = (await api("GET", `/api/projects/${pid}/attachments`)).filter((x) => x.extract_status === "extracted"); } catch { /* list refreshes on next view */ }
      chips.clear(); drawTray(); drawProjectPick();
      banner("Saved locally and submitted to provider.", "ok");
      if (gen === S.viewGen) { S.msgSig = ""; drawMsgs(); }
    } catch (e) {
      if (e.status === 409 && !confirm) {
        const go = await dialog("Use a different provider for this message?", [
          { name: "why", label: "Reason", type: "textarea", value: e.message, readonly: true, tall: true },
        ], "Send with this provider");
        if (go) return send(true);
      } else banner(e.message, "bad");
    } finally { sending = false; sendBtn.disabled = false; sendBtn.removeAttribute("aria-busy"); }
  };
  const sendBtn = btn("Send", () => send(false), "primary", "send");
  const preview = async () => guard(async () => {
    const provider = messageProvider();
    const r = await api("POST", `/api/projects/${pid}/conversations/${cid}/preview`,
      { text: ta.value, attachment_ids: [...chosen(), ...readyFiles(), ...readyPhotos()], provider });
    await dialog(`Context that will be sent to ${routeName(r.provider)} (${r.chars} chars)`, [{ name: "ctx", label: "Exact payload", type: "textarea", value: r.context, tall: true, readonly: true }], "Close");
  });
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(false); } });
  const grow = autosize(ta);
  // Files already in the project: a compact searchable picker instead of one chip per file.
  const projPick = h("details", { class: "projpick" });
  const drawProjectPick = () => {
    const n = chosen().length;
    const q = h("input", { type: "search", placeholder: "Filter project files…", "aria-label": "Filter project files" });
    const list = h("div", { class: "projlist", role: "group", "aria-label": "Project files" });
    const fill = () => list.replaceChildren(...atts.filter((a) => !q.value || a.name.toLowerCase().includes(q.value.toLowerCase())).slice(0, 200).map((a) => {
      const cb = h("input", { type: "checkbox", id: `pf-${a.id}`, onchange: (e) => { if (e.target.checked) chips.add(a.id); else chips.delete(a.id); sum.textContent = label(); checkAttach(); } });
      cb.checked = chips.has(a.id);
      return h("label", { for: `pf-${a.id}`, class: "projrow", title: `${a.name} (${a.chars} chars)` }, cb, h("span", { class: "t" }, a.name));
    }));
    const label = () => `Project files${chosen().length ? ` · ${chosen().length} attached` : ` (${atts.length})`}`;
    const sum = h("summary", { class: "btn ghost sm" }, icon("clip", "sm"), label());
    q.addEventListener("input", fill); fill();
    projPick.replaceChildren(sum, h("div", { class: "projpop" }, q, list, atts.length ? null : h("p", { class: "faint" }, "No readable files in this project yet. Drop files or a folder here to add some.")));
  };
  projPick.addEventListener("toggle", async () => {
    if (!projPick.open) return;
    try { atts = (await api("GET", `/api/projects/${pid}/attachments`)).filter((a) => a.extract_status === "extracted"); } catch { /* keep the list we have */ }
    const keepOpen = projPick.open; drawProjectPick(); projPick.open = keepOpen;
    const f = projPick.querySelector("input[type=search]"); if (f) f.focus();
  });
  drawProjectPick();
  const attachRow = h("div", { class: "attach", role: "group", "aria-label": "Attach" }, projPick, photoBtn, fileBtn, folderBtn, photoPick, filePick, folderPick);
  const provSel = h("select", { id: "chatProv", class: "chat-prov", "aria-label": "Provider for this message",
    onchange: (e) => { ssSet(provKey, e.target.value); refreshRouteLabels(); refit(); } },
    ...usable.map(([id, r]) => h("option", { value: id, selected: id === provPick },
      `${routeName(id)} · ${access(r.state)}`)));
  let lastProv = null;
  const handoff = h("span", { class: "handoff faint", role: "status", "aria-live": "polite" });
  const showHandoff = () => {
    const prov = messageProvider();
    handoff.textContent = lastProv && prov && lastProv !== prov ? `${routeName(prov)} picks up from ${routeName(lastProv)}: it reads this conversation.` : "";
    handoff.hidden = !handoff.textContent;
  };
  function handoffHint(msgs) {
    const last = [...(msgs || [])].reverse().find((m) => m.role === "assistant" && m.provider && m.status === "generated");
    lastProv = last ? last.provider : null; showHandoff();
  }
  provSel.addEventListener("change", showHandoff);
  const composer = h("div", { class: "composer" }, ta, tray, trayNote, attachRow,
    h("div", { class: "cfoot" },
      h("div", { class: "row chat-prow" }, provSel, h("span", { class: "chip", id: "composerRoute" }), handoff, h("span", { class: "hint" }, h("kbd", {}, "Ctrl"), h("kbd", {}, "Enter"), " send")),
      h("div", { class: "row" }, btn("Preview context", preview, "ghost", "eye"), sendBtn)));
  root.append(msgsEl, h("div", { class: "composer-dock" }, composer));
  // drop photos, files or whole folders anywhere on the chat
  let dragDepth = 0;
  const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  root.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth++; composer.classList.add("dropping"); });
  root.addEventListener("dragover", (e) => { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
  root.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; composer.classList.remove("dropping"); } });
  root.addEventListener("drop", async (e) => {
    if (!hasFiles(e)) return; e.preventDefault(); dragDepth = 0; composer.classList.remove("dropping");
    const entries = [...e.dataTransfer.items].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
    const dirs = entries.filter((x) => x.isDirectory);
    if (!dirs.length) { addFiles([...e.dataTransfer.files].map((f) => ({ file: f, path: f.name }))); return; }
    const loose = entries.filter((x) => x.isFile);
    if (loose.length) { const w = await walkEntries(loose); addFiles(w.files); }
    for (const d of dirs) { const w = await walkEntries([d]); addFiles(w.files, d.name, w.skipped); }
  });
  ta.placeholder = "Ask something about this project… (paste or drop photos, files or folders here)";
  $("view").replaceChildren(root);
  drawTray();
  refreshRouteLabels();

  const scroller = $("main");
  const nearBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
  const toBottom = () => { scroller.scrollTop = scroller.scrollHeight; };
  function msgView(m) {
    const meta = m.meta || {}; const user = m.role === "user"; const r = S.routes[m.provider];
    const costBits = [];
    if (typeof meta.cost_usd === "number") costBits.push(fmtCost(meta.cost_usd));
    if (costBits.length && m.provider) costBits.push(routeName(m.provider));
    if (meta.model) costBits.push(meta.model);
    if (meta.usage && (meta.usage.input_tokens != null || meta.usage.output_tokens != null))
      costBits.push(`${Number(meta.usage.input_tokens || 0).toLocaleString()}→${Number(meta.usage.output_tokens || 0).toLocaleString()} tok`);
    let body;
    if (m.status === "submitted") {
      const st = S.streams[m.id] || (S.streams[m.id] = { offset: 0, text: "" });
      const stream = h("div", { class: "stream" });
      const lbl = h("div", { class: "stream-label" }, "Partial output received so far (not the final answer)");
      const waited = h("span", { class: "faint" });
      const wait = h("p", { class: "muted" }, meta.task_id
        ? "Waiting for the provider. API routes show partial text here as it arrives; CLI routes show the answer only when they finish."
        : "Waiting for the provider. The answer appears here when it finishes.");
      const upd = () => {
        const has = !!st.text; stream.textContent = st.text; lbl.hidden = !has; wait.hidden = has;
        if (m.created) waited.textContent = `Submitted ${Math.max(0, Math.round(Date.now() / 1000 - m.created))}s ago`;
      };
      upd(); S.streamUpd[m.id] = upd;
      body = h("div", { class: "pending" }, waited, lbl, stream, wait);
    } else body = h("div", { class: "mbody" + (tone(m.status) === "bad" ? " err" : "") }, m.content);
    if (user && Array.isArray(meta.attachments) && meta.attachments.length) {
      const strip = h("div", { class: "mphotos" });
      body = h("div", {}, strip, body);
      const named = meta.attachments.map((aid) => atts.find((x) => x.id === aid)).filter(Boolean);
      if (named.length) strip.append(...named.slice(0, 12).map((x) => h("span", { class: "fchip ready", title: x.name }, icon("file", "sm"), h("span", { class: "t" }, x.name))),
        named.length > 12 ? h("span", { class: "faint" }, `+${named.length - 12} more files`) : null);
      for (const aid of meta.attachments) if (!atts.some((x) => x.id === aid)) photoURL(aid).then((u) => {
        if (!u) return;
        strip.append(h("button", { type: "button", class: "mphoto", "aria-label": "Open photo", onclick: () => photoViewer(u, "Photo") }, h("img", { src: u, alt: "Attached photo" })));
      });
    }
    let save = null;
    if (m.role === "assistant" && m.status === "generated") {
      save = h("button", { type: "button", class: "linkish msave", "aria-label": "Save this answer to the project" }, icon("bookmark", "sm"), "Save");
      save.onclick = async () => {
        if (save.disabled) return; save.disabled = true;
        try { await guard(async () => { const a = await api("POST", `/api/projects/${pid}/artifacts`, { kind: "chat_answer", title: m.content.slice(0, 60), content: m.content, source_ref: m.id }); S.preview = a && a.id; banner("Saved to project.", "ok"); if (S.itab === "preview") renderInspector(); }); }
        finally { save.disabled = false; }
      };
    }
    return h("article", { class: "msg " + m.role },
      h("div", { class: "mav", "aria-hidden": "true" }, user ? "You" : initials(routeName(m.provider) || "AI")),
      h("div", { class: "bubble" },
        h("div", { class: "mhead" },
          h("div", { class: "who" }, h("strong", {}, user ? "You" : routeName(m.provider) || "Assistant"), !user ? routeTag(r) : null,
            user && m.status === "saved" ? null : statePill(m.status), user ? h("span", { class: "mdot" }, "saved locally") : null),
          h("span", { class: "macts" }, save,
            m.role === "assistant" && m.status === "generated" && URLS_IN(m.content).length ? h("button", { type: "button", class: "linkish msave", title: "Fetch the pages this answer cites into the research notebook", onclick: () => guard(() => addLinksAsSources(pid, m.content)) }, icon("link", "sm"), "Add links as sources") : null,
            m.role === "assistant" && m.status === "generated" ? h("button", { type: "button", class: "linkish msave", title: "Prefill a finding in the research notebook", onclick: () => saveAsFinding(pid, m.content) }, icon("note", "sm"), "Save as finding") : null)),
        body,
        h("div", { class: "mtime" }, fmtClock(m.created), meta.duration_s ? ` · ${meta.duration_s}s provider wait` : ""),
        costBits.length ? h("div", { class: "costline" }, icon("dollar", "sm"), costBits.join(" · ")) : null));
  }
  let fails = 0;
  async function drawMsgs() {
    let msgs;
    try { msgs = await api("GET", `/api/projects/${pid}/conversations/${cid}/messages`); handoffHint(msgs); }
    catch (e) {
      // A refresh failure never ends polling silently: report once, then retry with backoff while this chat is on screen.
      if (gen !== S.viewGen) return;
      fails++; clearInterval(S.poll);
      if (fails === 1) banner(`Could not refresh this conversation (${e.message}). Retrying…`, "bad");
      const t = setTimeout(() => { if (gen === S.viewGen && S.poll === t) drawMsgs(); }, Math.min(30000, 2000 * 2 ** Math.min(fails, 4)));
      S.poll = t;
      return;
    }
    if (gen !== S.viewGen) return;
    if (fails) { fails = 0; banner("Conversation refreshed.", "ok"); }
    const sig = msgs.map((m) => m.id + ":" + m.status).join("|");
    if (sig !== S.msgSig) {
      const stick = !S.msgSig || nearBottom();
      S.msgSig = sig; S.streamUpd = {};
      msgsEl.replaceChildren(...(msgs.length ? msgs.map(msgView) : [h("div", { class: "empty" }, h("div", { class: "eico" }, icon("sparkle")), h("div", { class: "et" }, h("strong", {}, "Ask your first question"),
        h("p", {}, "Your message is saved locally first, then sent with this project's context. Try one of these:"),
        h("div", { class: "suggest" }, ...SUGGESTIONS.map(([ic, s]) => h("button", { type: "button", onclick: () => { ta.value = s; ssSet(draftKey, s); grow(); ta.focus(); } }, icon(ic), h("span", {}, s))))))]));
      if (stick) toBottom();
    }
    clearInterval(S.poll);
    const pending = msgs.filter((m) => m.status === "submitted");
    if (!pending.length) return;
    let ticks = 0, busy = false;
    const timer = setInterval(async () => {
      if (S.tab !== "chat" || S.global || gen !== S.viewGen || S.poll !== timer) { clearInterval(timer); return; }
      if (busy) return; busy = true;
      try {
        let refreshNow = ++ticks % 3 === 0;
        for (const m of pending) {
          const st = S.streams[m.id] || (S.streams[m.id] = { offset: 0, text: "" });
          const tid = m.meta && m.meta.task_id;
          if (tid) {
            try {
              const r = await api("GET", `/api/tasks/${tid}?offset=${st.offset}`);
              if (gen !== S.viewGen) return;
              st.offset = r.offset;
              // Only API routes stream the answer itself; CLI logs (prompt echo, banners) belong in the Terminal tab.
              if (r.output && r.stream_is_answer) { const stick = nearBottom(); st.text += r.output; if (stick) requestAnimationFrame(toBottom); }
              if (r.task && DONE.includes(r.task.state)) refreshNow = true;
            } catch { /* best-effort; message polling still resolves it */ }
          }
          if (S.streamUpd[m.id]) S.streamUpd[m.id]();
        }
        if (refreshNow && S.poll === timer) { clearInterval(timer); await drawMsgs(); }
      } finally { busy = false; }
    }, 1000);
    S.poll = timer;
  }
  drawMsgs();
}

// ---------- build (agent tasks) ----------
async function renderAgent(selected) {
  if (!S.project || S.global || S.tab !== "agent") return;
  const pid = S.project.id;
  const gen = ++S.viewGen;
  const tasks = await api("GET", `/api/projects/${pid}/tasks`);
  if (gen !== S.viewGen) return;
  let ack = { agent_ack: false, statement: "" };
  try { ack = await api("GET", `/api/projects/${pid}/agent-ack`); } catch (e) { ack = { agent_ack: false, statement: `Could not load the agent acknowledgement: ${e.message}` }; }
  if (gen !== S.viewGen) return;
  let ackOk = !!ack.agent_ack;
  let rv = { reviewers: [], builder: S.project.provider_default, max_rounds: 3 };
  try { rv = await api("GET", `/api/projects/${pid}/reviewers`); } catch { /* reviewing stays optional */ }
  if (gen !== S.viewGen) return;
  const rvKey = "aesop.build.reviewer." + pid;
  let rvPick = null; try { rvPick = localStorage.getItem(rvKey); } catch { /* optional */ }
  if (rvPick === null) rvPick = rv.reviewers.find((r) => r === "claude" || r === "codex") || rv.reviewers[0] || "";
  if (rvPick && !rv.reviewers.includes(rvPick)) rvPick = "";
  const rvSel = h("select", { id: "buildReviewer", class: "chat-prov", "aria-describedby": "buildReviewerHelp",
    onchange: (e) => { try { localStorage.setItem(rvKey, e.target.value); } catch { /* optional */ } } },
    h("option", { value: "" }, "No review"),
    ...rv.reviewers.map((r) => h("option", { value: r, selected: r === rvPick }, `${routeName(r)} reviews it`)));
  const rvRow = h("div", { class: "row rv-row" }, h("label", { for: "buildReviewer", class: "faint" }, "Second opinion"), rvSel,
    h("span", { class: "faint", id: "buildReviewerHelp" }, `When the build finishes, Studio runs the project's tests on this PC (3-minute limit, no keys in the environment), then another AI reviews the change and the results (read-only). Fixes go back only when you say so; at most ${rv.max_rounds} rounds.`));
  const blockNote = h("div");
  const draftKey = "aesop.draft.build." + pid;
  const ta = h("textarea", { "aria-label": "Agent task", placeholder: "Describe a bounded coding task to run inside the project folder…" });
  ta.value = ssGet(draftKey) || "";
  ta.addEventListener("input", () => ssSet(draftKey, ta.value));
  let starting = false;
  const start = async () => {
    if (starting) return;
    const raw = ta.value; if (!raw.trim()) { ta.focus(); return; }
    starting = true; startBtn.disabled = true; startBtn.setAttribute("aria-busy", "true");
    try {
      const t = await api("POST", `/api/projects/${pid}/tasks`, { prompt: raw, reviewer: rvSel.value || null });
      if (ta.value === raw) ssSet(draftKey, "");
      banner(`Task ${t.id} ${t.state}.`, t.state === "BLOCKED_OWNER" ? "bad" : "ok");
      if (t.state === "BLOCKED_OWNER" && /awaiting repair review/i.test(t.error || "")) {
        blockNote.replaceChildren(h("div", { class: "note bad", role: "alert" }, icon("alert"), h("div", { class: "section" }, h("span", {}, t.error),
          h("div", {}, h("button", { type: "button", class: "linkish", onclick: () => openGlobal("evidence") }, icon("evidence", "sm"), "Review the open repair in Evidence")))));
        return;
      }
      if (S.project && S.project.id === pid) { S.taskSel = t.id; refresh("agent", t.id); }
    } catch (e) { banner(e.message, "bad"); }
    finally { starting = false; startBtn.disabled = !ackOk; startBtn.removeAttribute("aria-busy"); }
  };
  const startBtn = btn("Start task", start, "primary", "terminal");
  startBtn.disabled = !ackOk;
  let ackBox = null;
  if (!ackOk) {
    const cb = h("input", { type: "checkbox", id: "agentAck", "aria-describedby": "agentAckText" });
    cb.onchange = () => guard(async () => {
      const want = cb.checked; cb.disabled = true;
      try {
        const r = await api("POST", `/api/projects/${pid}/agent-ack`, { ack: want });
        ackOk = r && typeof r.agent_ack === "boolean" ? r.agent_ack : want; cb.checked = ackOk; startBtn.disabled = !ackOk;
        banner(ackOk ? "Acknowledged. Agent tasks can run in this project." : "Acknowledgement withdrawn.", ackOk ? "ok" : "");
      } catch (e) { cb.checked = ackOk; throw e; } finally { cb.disabled = false; }
    });
    ackBox = h("div", { class: "note" }, icon("shield"), h("div", { class: "section" }, h("p", { id: "agentAckText" }, ack.statement || "Agent tasks run a provider CLI that can change files in this project folder."),
      h("label", { class: "rt-ack", for: "agentAck" }, cb, h("span", {}, "I understand")), h("p", { class: "faint" }, "Start task stays disabled until this is ticked.")));
  }
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); start(); } });
  const detail = h("div", { class: "section" });
  const listEl = h("div", { class: "tasklist" });
  const pickTask = (id) => {
    S.taskSel = id; setActivity(`Task ${id}`);
    listEl.querySelectorAll(".task").forEach((b) => b.setAttribute("aria-current", b.dataset.id === id ? "true" : "false"));
    showTask(id, detail, (other) => { if (S.project && S.project.id === pid) { S.taskSel = other; refresh("agent", other); } }, rv);
    if (inspectorVisible() && !["terminal", "changes", "logs"].includes(S.itab)) setItab("terminal");
    if (inspectorVisible()) renderInspector();
  };
  listEl.append(...tasks.map((t) => h("button", { class: "task", type: "button", "data-id": t.id, "aria-current": "false", onclick: () => pickTask(t.id) },
    h("span", { class: "dot " + tone(t.state) }),
    h("span", {}, h("span", { class: "tp" }, t.prompt.slice(0, 160)),
      h("span", { class: "tm" }, statePill(t.state), h("span", {}, routeName(t.provider)), h("span", {}, fmtClock(t.started || t.created)))))));
  $("view").replaceChildren(
    h("div", { class: "composer" }, h("div", { class: "card-head" }, h("div", { class: "ttl" }, icon("terminal"), h("h2", {}, "Run an agent task")), h("span", { id: "buildRouteTag" })),
      h("p", { class: "muted", id: "buildRouteDesc" }), ackBox, ta, rv.reviewers.length ? rvRow : null, blockNote,
      h("div", { class: "cfoot" }, h("span", { class: "hint" }, h("kbd", {}, "Ctrl"), h("kbd", {}, "Enter"), " start"), startBtn)),
    tasks.length ? h("div", { class: "grid2" }, section("Recent tasks", `${tasks.length} shown`, listEl), detail)
      : empty("terminal", "No agent tasks yet", "Describe a bounded task above. Each run records its state, output, exit code and changed files."));
  refreshRouteLabels();
  autosize(ta);
  if (tasks.length) {
    detail.append(empty("terminal", "Select a task", "Its state, facts and actions appear here; live output and changed files open in the inspector."));
    const sel = selected || (S.taskSel && tasks.some((t) => t.id === S.taskSel) ? S.taskSel : null);
    if (sel) pickTask(sel);
  }
}
// Built once and updated in place, so polling never destroys the control that has keyboard focus.
function showTask(tid, el, openTask, rv) {
  const title = h("h3", {}, `Task ${tid}`); const pill = h("span");
  const cancelBtn = abtn("Cancel", () => guard(async () => { const c = await api("POST", `/api/tasks/${tid}/cancel`); banner(c.note, ""); }), "danger sm", "stop");
  const saveBtn = abtn("Save result", () => guard(async () => { const a = await api("POST", `/api/tasks/${tid}/save`); S.preview = a && a.id; banner("Task result saved to project.", "ok"); }), "sm", "bookmark");
  cancelBtn.hidden = true; saveBtn.hidden = true;
  const fProv = h("b"), fCwd = h("b"), fStart = h("b"), fEnd = h("b"), fExit = h("b");
  const exitSpan = h("span", {}, "exit ", fExit);
  const facts = h("div", { class: "facts" }, h("span", {}, "Provider ", fProv), h("span", {}, "cwd ", fCwd), h("span", {}, "started ", fStart), h("span", {}, "ended ", fEnd), exitSpan);
  const loading = h("p", { class: "faint" }, "Loading task record…");
  const errBox = h("div"); const chLine = h("p", { class: "muted" });
  const views = h("div", { class: "row" }, h("button", { type: "button", class: "linkish", onclick: (e) => openInspector("terminal", e.currentTarget) }, icon("terminal", "sm"), "View output"),
    h("button", { type: "button", class: "linkish", onclick: (e) => openInspector("changes", e.currentTarget) }, icon("diff", "sm"), "View changes"));
  facts.hidden = true; chLine.hidden = true;
  const review = h("section", { class: "rvbox", "aria-label": "Review", "aria-live": "polite" });
  el.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", { class: "ttl" }, title, pill), h("div", { class: "row" }, cancelBtn, saveBtn)),
    h("div", { class: "section" }, loading, facts, errBox, chLine, views)), review);
  reviewPanel(tid, review, openTask, rv);
  let wasDone = null; let errSig = null; let pillState = null;
  const upd = () => {
    const mine = W.tid === tid; const t = mine ? W.task : null;
    const sig = `${mine ? wErrKey() : ""}|${t && t.error ? t.error : ""}`;
    if (sig !== errSig) { errSig = sig; errBox.replaceChildren(...(mine && W.err ? [wErrNote()] : []), ...(t && t.error ? [h("div", { class: "note bad" }, icon("alert"), h("span", {}, t.error))] : [])); }
    if (!t) { loading.hidden = !!(mine && W.err); return; }
    loading.hidden = true; facts.hidden = false;
    const done = DONE.includes(t.state);
    title.textContent = `Task ${t.id}`;
    if (pillState !== t.state) { pillState = t.state; pill.replaceChildren(statePill(t.state)); }
    fProv.textContent = routeName(t.provider); fCwd.textContent = t.cwd || "—"; fStart.textContent = fmtTime(t.started); fEnd.textContent = fmtTime(t.ended);
    const hasExit = t.exit_code !== null && t.exit_code !== undefined; exitSpan.hidden = !hasExit; if (hasExit) fExit.textContent = String(t.exit_code);
    let ch = null; try { ch = t.changed_files ? JSON.parse(t.changed_files) : null; } catch { ch = null; }
    chLine.hidden = !ch; if (ch) chLine.textContent = `Changed files — added: ${(ch.added || []).length}, modified: ${(ch.modified || []).length}, removed: ${(ch.removed || []).length}.`;
    if (wasDone !== done) {
      const hadFocus = document.activeElement === cancelBtn;
      cancelBtn.hidden = done; saveBtn.hidden = !done; wasDone = done;
      if (hadFocus && done) saveBtn.focus();
    }
  };
  W.hooks.build = (c) => { if (S.tab === "agent" && !S.global && el.isConnected) upd(c); };
  watchTask(tid); upd();
}

// ---------- build + review (two AIs working together; the owner decides every next step) ----------
const RV_LABEL = { approve: ["Approved", "ok"], changes: ["Changes requested", "warn"], unclear: ["Review not structured", "info"] };
function reviewPanel(tid, box, openTask, rv) {
  let timer = null; let sig = "";
  const stop = () => { clearTimeout(timer); timer = null; };
  const tick = async () => {
    if (!box.isConnected) return stop();
    let r; try { r = await api("GET", `/api/tasks/${tid}/review`); } catch { timer = setTimeout(tick, 5000); return; }
    let t = null; try { t = (await api("GET", `/api/tasks/${tid}`)).task; } catch { /* shown without task state */ }
    const s2 = JSON.stringify([r, t && t.state]);
    if (s2 !== sig) { sig = s2; draw(r, t); }
    if (["WAITING_FOR_BUILD", "REVIEWING"].includes(r.state) || ["WAITING", "RUNNING"].includes((r.tests || {}).state)) timer = setTimeout(tick, 3000);
  };
  const reviewerPick = (cur) => {
    const sel = h("select", { class: "chat-prov", "aria-label": "Reviewer" }, ...((rv && rv.reviewers) || []).map((x) => h("option", { value: x, selected: x === cur }, routeName(x))));
    return sel;
  };
  const again = (sel, label) => abtn(label || "Review", async () => {
    try { await api("POST", `/api/tasks/${tid}/review`, { reviewer: sel.value }); banner(`${routeName(sel.value)} will review this change.`, "ok"); sig = ""; tick(); }
    catch (e) { banner(e.message, "bad"); }
  }, "sm", "eye");
  const put = (...kids) => box.replaceChildren(...kids.filter(Boolean)); // DOM would print a skipped piece as "null"
  const testsView = (r, t) => {
    const x = r.tests; if (!x) return null;
    const ok = x.state === "PASSED", bad = x.state === "FAILED" || x.state === "ERROR";
    const line = x.state === "WAITING" ? (t && t.state === "COMPLETED" ? "Tests: starting…" : "Tests run here when the build finishes.")
      : x.state === "RUNNING" ? "Tests: running on this PC…"
      : x.state === "NO_TESTS" ? "Tests: none found in this project." : x.state === "SKIPPED" ? `Tests: skipped (${x.note}).`
      : x.state === "ERROR" ? `Tests: could not run — ${x.note}` : `Tests ${ok ? "passed" : "failed"}: ${x.summary} (${x.label}, ${x.duration_s}s)`;
    const again = t && t.state === "COMPLETED" && !["WAITING", "RUNNING"].includes(x.state)
      ? abtn("Run tests again", async () => { await api("POST", `/api/tasks/${tid}/tests`); sig = ""; setTimeout(tick, 800); }, "ghost sm", "terminal") : null;
    return h("div", { class: "rvtests " + (ok ? "ok" : bad ? "bad" : "") },
      h("div", { class: "row" }, icon(ok ? "check" : bad ? "alert" : "terminal", "sm"), h("span", {}, line), again),
      x.output ? h("details", {}, h("summary", {}, "Test output"), h("pre", { class: "out" }, x.output)) : null);
  };
  const draw = (r, t) => {
    const who = r.reviewer ? routeName(r.reviewer) : "The reviewer";
    const head = h("div", { class: "rvhead" }, icon("users"), h("h4", {}, "Second opinion"), r.round > 1 ? h("span", { class: "faint" }, `round ${r.round} of ${(rv && rv.max_rounds) || 3}`) : null);
    const done = t && ["COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED", "BLOCKED_OWNER", "EFFECT_UNKNOWN"].includes(t.state);
    const tv = testsView(r, t);
    if (r.state === "NONE" || r.state === "NO_REVIEW") {
      const canAsk = t && t.state === "COMPLETED" && rv && rv.reviewers.length;
      if (!canAsk && !tv) { box.replaceChildren(); box.hidden = true; return; }
      const sel = canAsk ? reviewerPick(rv.reviewers[0]) : null;
      box.hidden = false;
      put(h("div", { class: "rvhead" }, icon("users"), h("h4", {}, "Checks")), tv,
        canAsk ? h("p", { class: "muted" }, "No review yet. Ask another AI to check this change (read-only):") : null, canAsk ? h("div", { class: "row" }, sel, again(sel)) : null);
      return;
    }
    box.hidden = false;
    if (r.state === "WAITING_FOR_BUILD") { put(head, tv, h("p", { class: "muted" }, done ? `${who} is about to review…` : `${who} reviews the change as soon as the build finishes.`)); return; }
    if (r.state === "REVIEWING") { put(head, tv, h("p", { class: "muted" }, `${who} is reviewing the change (${r.change_kind || "changes"}, ${Number(r.change_chars || 0).toLocaleString()} chars)…`)); return; }
    if (r.state !== "DONE") {
      const sel = reviewerPick(r.reviewer);
      const fix = r.state === "BLOCKED" ? abtn(`Allow files to ${who}`, async () => {
        const pol = { ...(S.project.transfer_policy || {}), [r.reviewer]: true };
        const up = await api("PATCH", `/api/projects/${S.project.id}`, { transfer_policy: pol });
        S.project = { ...S.project, ...up, transfer_policy: up.transfer_policy || pol };
        await api("POST", `/api/tasks/${tid}/review`, { reviewer: r.reviewer }); sig = ""; tick();
      }, "sm") : null;
      put(head, tv, h("div", { class: "note " + (r.state === "SKIPPED" ? "" : "bad") }, icon(r.state === "SKIPPED" ? "info" : "alert"), h("span", {}, r.note || r.state.toLowerCase())),
        h("div", { class: "row" }, fix, r.state !== "SKIPPED" ? sel : null, r.state !== "SKIPPED" ? again(sel, "Review again") : null));
      return;
    }
    const [lbl, tone_] = RV_LABEL[r.verdict] || RV_LABEL.unclear;
    const checks = (r.issues || []).map((it, n) => {
      const cb = h("input", { type: "checkbox", id: `rvi-${tid}-${n}` }); cb.checked = it.severity !== "low";
      return { cb, li: h("li", { class: "rvissue sev-" + it.severity }, h("label", { for: `rvi-${tid}-${n}` }, cb,
        h("span", { class: "rvsev" }, it.severity),
        h("span", {}, h("strong", {}, `${it.file || "general"}${it.line ? ":" + it.line : ""} `), it.problem, it.fix ? h("span", { class: "faint" }, ` — fix: ${it.fix}`) : null))) };
    });
    const note = h("textarea", { rows: "2", placeholder: "Anything to add for the builder (optional)", "aria-label": "Note for the builder" });
    const builder = t ? routeName(t.provider) : "the builder";
    const last = r.round >= ((rv && rv.max_rounds) || 3);
    const sendBtn = abtn(`Send fixes to ${builder}`, async () => {
      const picked = checks.map((c, n) => (c.cb.checked ? n : -1)).filter((n) => n >= 0);
      try { const out = await api("POST", `/api/tasks/${tid}/fixes`, { issues: picked, note: note.value });
        banner(`Sent ${picked.length} issue${picked.length === 1 ? "" : "s"} to ${builder} as task ${out.task.id}.`, "ok"); openTask(out.task.id); }
      catch (e) { banner(e.message, "bad"); }
    }, "primary sm", "send");
    const acceptBtn = abtn(r.accepted_at ? "Accepted" : "Accept", async () => { await api("POST", `/api/tasks/${tid}/accept`); sig = ""; tick(); }, "sm", "check");
    acceptBtn.disabled = !!r.accepted_at;
    put(head, tv,
      h("div", { class: "rvverdict" }, h("span", { class: "pill " + tone_ }, lbl), h("span", { class: "faint" }, `by ${who}`)),
      r.summary ? h("p", {}, r.summary) : null,
      checks.length ? h("ul", { class: "rvissues" }, ...checks.map((c) => c.li)) : h("p", { class: "muted" }, "No issues listed."),
      r.fix_task ? h("p", {}, h("button", { type: "button", class: "linkish", onclick: () => openTask(r.fix_task) }, `Fixes sent as task ${r.fix_task} →`)) : null,
      !r.fix_task && !last && r.verdict !== "approve" ? note : null,
      h("div", { class: "row" }, !r.fix_task && !last && (checks.length || r.verdict !== "approve") ? sendBtn : null, acceptBtn,
        last && !r.fix_task ? h("span", { class: "faint" }, "Last automatic round reached: review it yourself before going on.") : null));
  };
  tick();
}

// ---------- model-assisted proposals (derivations) ----------
// One derivation per kind per project. State lives outside the view so a running request keeps honest progress across re-renders.
const DERIV = {}; // `${pid}:${kind}` -> { id, pid, route, started, status, data, err, timer, onDone }
let dTick = null;
const dkey = (kind) => `${S.project ? S.project.id : "_"}:${kind}`;
const dRunning = (st) => st && (st.status === "RUNNING" || st.status === "STARTING");
function dTicker() {
  if (dTick) return;
  dTick = setInterval(() => {
    document.querySelectorAll("[data-started]").forEach((e) => { e.textContent = `${Math.max(0, Math.round((Date.now() - Number(e.dataset.started)) / 1000))}s`; });
    if (!Object.values(DERIV).some(dRunning)) { clearInterval(dTick); dTick = null; }
  }, 1000);
}
function dSummary(st) {
  const d = st.data || {}; const r = d.result || {};
  if (st.status === "DONE") {
    const c = (r.created || []).length; const rj = r.rejected || [];
    return `${c} proposed, ${rj.length} rejected${rj.length ? ` (${rj.map((x) => x.why).filter(Boolean).join("; ")})` : ""}.`;
  }
  return `Failed: ${r.note || st.err || (d.task_state ? `task ended ${d.task_state}` : "no detail returned")}`;
}
function dItemText(item) {
  if (item == null) return "";
  if (typeof item === "string") return item;
  return item.claim || item.content || item.text || JSON.stringify(item);
}
function dView(kind) {
  const key = dkey(kind); const st = DERIV[key]; if (!st) return [];
  const name = routeName(st.route) || "the provider";
  const dismiss = h("button", { type: "button", class: "linkish", onclick: () => { delete DERIV[key]; dRefresh(kind); } }, "Dismiss");
  if (dRunning(st)) {
    dTicker();
    return [h("div", { class: "note info" }, icon("clock"), h("span", {}, `Waiting for ${name}… `, h("span", { "data-started": String(st.started) }, `${Math.round((Date.now() - st.started) / 1000)}s`),
      kind === "findings" ? " · proposals appear below for your review" : " · proposals appear in Memory for your review"))];
  }
  if (st.status === "ERROR") return [h("div", { class: "note bad" }, icon("alert"), h("div", {}, h("span", {}, st.err), h("div", {}, dismiss)))];
  const r = (st.data && st.data.result) || {};
  const done = st.status === "DONE";
  return [h("div", { class: "note " + (done ? "info" : "bad") }, icon(done ? "info" : "alert"), h("div", { class: "section" },
    h("strong", {}, done ? `${(r.created || []).length} proposed, ${(r.rejected || []).length} rejected` : dSummary(st)),
    done && (r.rejected || []).length ? h("ul", {}, ...(r.rejected || []).map((x) => h("li", {}, `${dItemText(x.item).slice(0, 140)}${x.item ? " — " : ""}${x.why || "no reason given"}`))) : null,
    done && r.note ? h("p", {}, r.note) : null,
    h("div", { class: "row" }, done && kind === "summary" ? h("button", { type: "button", class: "linkish", onclick: () => setTab("memory") }, icon("layers", "sm"), "Review in Memory") : null, dismiss)))];
}
function dRefresh(kind) { document.querySelectorAll(`[data-deriv="${kind}"]`).forEach((el) => el.replaceChildren(...dView(kind))); }
function dPoll(key, kind) {
  const st = DERIV[key]; if (!st || st.status !== "RUNNING" || !st.id) return;
  clearTimeout(st.timer);
  st.timer = setTimeout(async () => {
    try { const d = await api("GET", `/api/derivations/${st.id}`); st.data = d; st.status = d.status; st.route = d.route || st.route; } catch { /* transient; retry */ }
    if (st.status === "RUNNING") dPoll(key, kind);
    else {
      banner(`${routeName(st.route)}: ${dSummary(st)}`, st.status === "DONE" ? "" : "bad");
      if (S.project && S.project.id === st.pid && st.onDone) st.onDone();
    }
    dRefresh(kind);
  }, 1500);
}
async function startDerivation(kind, path, body, onDone) {
  const key = dkey(kind);
  if (dRunning(DERIV[key])) return;
  const st = DERIV[key] = { id: null, pid: S.project.id, route: S.project.provider_default, started: Date.now(), status: "STARTING", data: null, err: "", timer: null, onDone };
  dRefresh(kind);
  try {
    const d = await api("POST", path, body);
    st.id = d.id; st.data = d; st.route = d.route || st.route; st.status = d.status || "RUNNING";
    banner(`Sent one request to ${routeName(st.route)}. Results arrive as proposals for your review.`);
    if (st.status === "RUNNING") dPoll(key, kind); else if (onDone) onDone();
  } catch (e) { st.status = "ERROR"; st.err = e.message; banner(e.message, "bad"); }
  dRefresh(kind);
  if (onDone && st.status === "ERROR") onDone();
}
async function decide(path, label, after) {
  await guard(async () => { const r = await api("POST", path); banner(`${label}${r && r.status ? ` (status: ${r.status})` : ""}.`, "ok"); after(); });
}

// ---------- research ----------
// A labelled form control: the label stays visible while the user types (placeholders are only hints).
function field(id, label, ctrl, help) {
  ctrl.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), ctrl, help ? h("p", { class: "faint" }, help) : null);
}
// Bind a control to a sessionStorage draft so refreshes after other actions never wipe what the user typed.
function keepDraft(ctrl, key) {
  const v = ssGet(key); if (v !== null && v !== undefined) ctrl.value = v;
  ctrl.addEventListener(ctrl.tagName === "SELECT" ? "change" : "input", () => ssSet(key, ctrl.value));
  return ctrl;
}
// ---------- research notebook (a panel inside Chat; the separate Research tab was retired) ----------
const researchKey = (pid) => "aesop.chat.research." + pid;
const researchOpen = (pid) => { try { return localStorage.getItem(researchKey(pid)) === "1"; } catch { return false; } };
function setResearchOpen(pid, on) { try { localStorage.setItem(researchKey(pid), on ? "1" : "0"); } catch { /* optional */ } }
async function openResearch(focus) {
  if (!S.project) return;
  setResearchOpen(S.project.id, true);
  if (S.tab !== "chat" || S.global) await setTab("chat"); else { const el = $("researchPanel"); if (el) { el.hidden = false; await researchPanel(el, S.project.id); } }
  const el = $("researchPanel"); if (el) { el.scrollIntoView({ block: "start" }); const f = focus && el.querySelector(focus); if (f) f.focus(); }
}
async function researchPanel(el, pid) {
  const gen = (el._gen = (el._gen || 0) + 1);
  const live = () => el._gen === gen && el.isConnected && S.project && S.project.id === pid;
  const nb = await api("GET", `/api/projects/${pid}/notebook`);
  if (!live()) return;
  const atts = await api("GET", `/api/projects/${pid}/attachments`);
  if (!live()) return;
  const again = () => researchPanel(el, pid);
  const dk = (k) => `aesop.draft.nb.${pid}.${k}`;
  const url = keepDraft(h("input", { type: "url", placeholder: "https://…", class: "grow" }), dk("url"));
  const attSel = h("select", { class: "grow" }, h("option", { value: "" }, "— choose a project file —"), ...atts.map((a) => h("option", { value: a.id }, a.name)));
  keepDraft(attSel, dk("att"));
  const srcSel = h("select", { class: "grow" }, h("option", { value: "" }, "— no source (unsupported) —"), ...nb.sources.map((s, i) => h("option", { value: s.id }, `[${i + 1}] ${s.title.slice(0, 60)}`)));
  keepDraft(srcSel, dk("src"));
  const claim = keepDraft(h("textarea", { placeholder: "What does the source support?" }), dk("claim"));
  const loc = keepDraft(h("input", { placeholder: "section, page, line or quote" }), dk("loc"));
  const lim = keepDraft(h("input", { placeholder: "e.g. small sample, single vendor" }), dk("lim"));
  const q = h("input", { type: "search", placeholder: "Search this project… (Enter)", "aria-label": "Search project", class: "grow" });
  const results = h("div", { class: "section" });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") guard(async () => { const r = await api("GET", `/api/projects/${pid}/search?q=${encodeURIComponent(q.value)}`); if (!live()) return; results.replaceChildren(...(r.length ? r.map((x) => h("div", { class: "card" }, h("div", { class: "row" }, statePill(x.type), h("strong", {}, x.title)), h("pre", { class: "out" }, x.snippet))) : [empty("search", "No matches", "Nothing in this project matched that search.")])); }); });
  const srcNo = (id) => { const i = nb.sources.findIndex((s) => s.id === id); return i >= 0 ? `[${i + 1}]` : "—"; };
  const srcTitle = (id) => { const s = nb.sources.find((x) => x.id === id); return s ? s.title : ""; };

  // draft findings (model-assisted; results are proposals only)
  const picks = h("div", { class: "picks", role: "group", "aria-label": "Sources to draft findings from (up to 8)" }, ...nb.sources.map((s, i) => {
    const ok = s.status === "read"; const id = "dsrc-" + s.id;
    const cb = h("input", { type: "checkbox", id, value: s.id, disabled: !ok, onchange: (e) => { if (e.target.checked && picks.querySelectorAll("input:checked").length > 8) { e.target.checked = false; banner("Up to 8 sources per request."); } } });
    return h("label", { class: "pickrow" + (ok ? "" : " off"), for: id }, cb, h("span", { class: "pt" }, `[${i + 1}] ${s.title}`), ok ? null : statePill(s.status));
  }));
  const running = dRunning(DERIV[dkey("findings")]);
  const draftBtn = abtn("Draft findings", async () => {
    const ids = [...picks.querySelectorAll("input:checked")].map((x) => x.value);
    if (!ids.length) { banner("Choose at least one read source to draft from.", "bad"); return; }
    await startDerivation("findings", `/api/projects/${pid}/notebook/draft-findings`, { source_ids: ids }, () => { if (S.project && S.project.id === pid) again(); });
  }, "", "sparkle");
  if (running || !S.project.provider_default) draftBtn.disabled = true;
  const draftCard = h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", { class: "ttl" }, icon("sparkle"), h("h2", {}, "Draft findings from sources")),
    h("span", { class: "muted", id: "draftRoute" })),
    h("p", { class: "muted" }, "A model proposes findings with locators from the sources you tick. Nothing is added to Findings until you accept it. Only sources with status “read” can be used."),
    nb.sources.length ? picks : h("p", { class: "muted" }, "Add a source first."),
    h("div", { class: "row end" }, draftBtn),
    h("div", { "data-deriv": "findings", class: "section" }, ...dView("findings")));

  const proposed = nb.findings.filter((f) => f.status === "proposed");
  const rejected = nb.findings.filter((f) => f.status === "rejected");
  const kept = nb.findings.filter((f) => f.status !== "proposed" && f.status !== "rejected");
  const after = () => again();
  const propCard = (f) => h("div", { class: "card prop" }, h("div", { class: "row" }, statePill(f.status), h("span", { class: "tag" }, `source ${srcNo(f.source_id)}`), srcTitle(f.source_id) ? h("span", { class: "faint" }, srcTitle(f.source_id)) : null),
    h("p", { class: "content" }, f.claim),
    h("div", { class: "facts" }, h("span", {}, "Locator ", h("b", {}, f.locator || "—")), h("span", {}, "Limitation ", h("b", {}, f.limitation || "—"))),
    f.status === "proposed" ? h("div", { class: "acts" },
      abtn("Accept", () => decide(`/api/projects/${pid}/notebook/findings/${f.id}/accept`, "Finding accepted", after), "sm", "check"),
      abtn("Reject", () => decide(`/api/projects/${pid}/notebook/findings/${f.id}/reject`, "Proposal rejected", after), "ghost sm", "x")) : null);

  const fetchBtn = abtn("Fetch public page", () => guard(async () => {
    banner("Fetching (public addresses only)…");
    const s = await api("POST", `/api/projects/${pid}/notebook/sources`, { url: url.value });
    ssSet(dk("url"), "");
    banner(`Source ${s.status}: ${s.title}`, s.status === "read" ? "ok" : "bad"); again();
  }), "", "download");
  const addBtn = abtn("Add local document", () => guard(async () => {
    if (!attSel.value) { banner("Choose a project file first.", "bad"); return; }
    await api("POST", `/api/projects/${pid}/notebook/sources`, { attachment_id: attSel.value });
    ssSet(dk("att"), ""); again();
  }), "", "file");
  const saveBtn = abtn("Save finding", () => guard(async () => {
    await api("POST", `/api/projects/${pid}/notebook/findings`, { claim: claim.value, source_id: srcSel.value || null, locator: loc.value, limitation: lim.value });
    for (const k of ["claim", "src", "loc", "lim"]) ssSet(dk(k), "");
    banner("Finding saved.", "ok"); again();
  }), "primary", "check");

  const head = h("div", { class: "rp-head" },
    h("div", { class: "ttl" }, icon("search"), h("h2", {}, "Research notebook"), h("span", { class: "faint" }, `${nb.sources.length} source${nb.sources.length === 1 ? "" : "s"} · ${kept.length} finding${kept.length === 1 ? "" : "s"}${proposed.length ? ` · ${proposed.length} to review` : ""}`)),
    h("div", { class: "row" }, dlBtn("Export (public sources only)", `/api/projects/${pid}/notebook/export?private=0`, `notebook-${pid}.md`), dlBtn("Export incl. private", `/api/projects/${pid}/notebook/export?private=1`, `notebook-${pid}-private.md`),
      h("button", { type: "button", class: "iconbtn", "aria-label": "Close research notebook", onclick: () => { setResearchOpen(pid, false); el.hidden = true; const b = $("researchBtn"); if (b) { b.setAttribute("aria-expanded", "false"); b.focus(); } } }, icon("x"))));
  el.replaceChildren(head,
    h("p", { class: "faint rp-tip" }, "Tip: ask Perplexity or Firecrawl in the chat below, then use “Add links as sources” on the answer; “Save as finding” fills the form here."),
    h("div", { class: "row" }, q),
    results,
    h("div", { class: "grid2" },
      h("div", { class: "card" }, h("div", { class: "ttl" }, icon("link"), h("h2", {}, "Add a source")),
        h("p", { class: "muted" }, "Public pages are fetched from public addresses only. Local documents stay private unless you export them."),
        field("nbUrl", "Public source URL", url), h("div", { class: "row end" }, fetchBtn),
        field("nbAtt", "Local document", attSel), h("div", { class: "row end" }, addBtn)),
      h("div", { class: "card" }, h("div", { class: "ttl" }, icon("note"), h("h2", {}, "Record a finding")),
        field("nbClaim", "Finding", claim), field("nbSrc", "Source", srcSel),
        h("div", { class: "rt-row2" }, field("nbLoc", "Locator", loc), field("nbLim", "Limitation (optional)", lim)),
        h("div", { class: "row end" }, saveBtn))),
    draftCard,
    proposed.length || rejected.length ? section("Proposed — not yet accepted", "Model-drafted findings. Check each against its source, then accept or reject it.",
      ...(proposed.length ? proposed.map(propCard) : [h("p", { class: "muted" }, "No open proposals.")]),
      rejected.length ? h("details", { class: "card disclose" }, h("summary", {}, `Show rejected (${rejected.length})`), h("div", { class: "section" }, ...rejected.map(propCard))) : null) : null,
    section("Findings", "Each claim is tied to a numbered source and locator, or marked unsupported.",
      kept.length ? table(["Claim", "Source", "Locator", "Status", "Limitation"], kept.map((f) => h("tr", {}, h("td", { class: "wrap" }, f.claim), h("td", {}, srcNo(f.source_id)), h("td", {}, f.locator || ""), h("td", {}, statePill(f.status)), h("td", {}, f.limitation || ""))))
        : empty("note", "No findings yet", "Record what a source supports, with a locator, so it can be cited and checked later.")),
    section("Sources", null,
      nb.sources.length ? table(["#", "Title", "Publisher", "Locator", "Retrieved", "Status", "Visibility"], nb.sources.map((s, i) => h("tr", {}, h("td", { class: "num" }, i + 1), h("td", { class: "wrap" }, s.title), h("td", {}, s.publisher || ""), h("td", {}, s.locator), h("td", {}, fmtTime(s.retrieved_at)), h("td", {}, statePill(s.status)), h("td", {}, h("span", { class: "tag" }, s.private ? "private" : "public")))))
        : empty("link", "No sources yet", "Add a public page or a local document to start the research notebook.")));
  refreshRouteLabels();
}
// Chat answers feed the notebook: cited links become sources, an answer can prefill a finding.
const URLS_IN = (t) => [...new Set((String(t || "").match(/https?:\/\/[^\s<>()"'\]]+[^\s<>()"'.,;:!?\]]/g) || []))].slice(0, 8);
async function addLinksAsSources(pid, text) {
  const urls = URLS_IN(text); if (!urls.length) return;
  banner(`Adding ${urls.length} source${urls.length === 1 ? "" : "s"} (public pages only)…`);
  let ok = 0, bad = 0;
  for (const u of urls) { try { const r = await api("POST", `/api/projects/${pid}/notebook/sources`, { url: u }); if (r.status === "read") ok++; else bad++; } catch { bad++; } }
  banner(`Added ${ok} source${ok === 1 ? "" : "s"} to the research notebook${bad ? `; ${bad} could not be read` : ""}.`, ok ? "ok" : "bad");
  await openResearch();
}
function saveAsFinding(pid, text) {
  ssSet(`aesop.draft.nb.${pid}.claim`, String(text || "").replace(/\n+Sources:[\s\S]*$/, "").trim().slice(0, 1500));
  openResearch("textarea");
  banner("Finding prefilled in the research notebook: pick its source and locator, then Save finding.");
}

// ---------- memory ----------
async function renderMemory() {
  if (!S.project || S.global || S.tab !== "memory") return;
  const pid = S.project.id;
  const gen = ++S.viewGen;
  const mem = await api("GET", `/api/projects/${pid}/memory`);
  if (gen !== S.viewGen) return;
  setActivity(`${mem.length} record(s)`);
  const dk = (k) => `aesop.draft.mem.${pid}.${k}`;
  const content = keepDraft(h("textarea", { placeholder: "Constraint, decision or state to remember for this project" }), dk("content"));
  const layer = keepDraft(h("select", {}, h("option", { value: "authoritative" }, "Authoritative record"), h("option", { value: "derived" }, "Derived summary (needs source IDs)")), dk("layer"));
  const srcs = keepDraft(h("input", { placeholder: "comma-separated record IDs" }), dk("srcs"));
  const act = (m, op, body) => guard(async () => { await api("POST", `/api/projects/${pid}/memory/${m.id}/${op}`, body); refresh("memory"); });
  const groups = ["authoritative", "derived", "shared"];
  const titles = { authoritative: "Authoritative records", derived: "Derived working summaries", shared: "Promoted shared knowledge" };
  const desc = { authoritative: "Source of truth for this project.", derived: "Summaries that cite the records they came from.", shared: "Explicitly promoted; visible beyond this project." };
  const proposed = mem.filter((m) => m.status === "proposed");
  const rejected = mem.filter((m) => m.status === "rejected");
  const kept = mem.filter((m) => m.status !== "proposed" && m.status !== "rejected");
  const after = () => refresh("memory");
  const propCard = (m) => h("div", { class: "card mem prop" }, h("div", { class: "row" }, statePill(m.status), h("code", {}, m.id), h("span", { class: "muted" }, fmtTime(m.created))),
    h("p", { class: "content" }, m.content),
    m.source_ids.length ? h("div", { class: "tags", "aria-label": "Cited messages" }, h("span", { class: "faint" }, "Cites"), ...m.source_ids.map((s) => h("span", { class: "tag route" }, s))) : h("p", { class: "faint" }, "No cited messages."),
    m.status === "proposed" ? h("div", { class: "acts" },
      abtn("Accept", () => decide(`/api/projects/${pid}/memory/${m.id}/accept`, "Summary accepted into memory", after), "sm", "check"),
      abtn("Reject", () => decide(`/api/projects/${pid}/memory/${m.id}/reject`, "Proposal rejected", after), "ghost sm", "x")) : null);
  const saveBtn = abtn("Save", () => guard(async () => {
    await api("POST", `/api/projects/${pid}/memory`, { layer: layer.value, kind: "note", content: content.value, source_ids: srcs.value.split(",").map((s) => s.trim()).filter(Boolean) });
    for (const k of ["content", "srcs"]) ssSet(dk(k), "");
    banner("Saved to project memory.", "ok"); refresh("memory");
  }), "primary", "check");
  $("view").replaceChildren(h("div", { class: "card" }, h("div", { class: "ttl" }, icon("layers"), h("h2", {}, "Add to project memory")),
    h("p", { class: "muted" }, "Memory belongs to this project only. Shared knowledge needs an explicit promotion. Corrections supersede old records but keep them for provenance."),
    field("memContent", "Content", content),
    h("div", { class: "rt-row2" }, field("memLayer", "Layer", layer), field("memSrcs", "Source record IDs", srcs)),
    h("div", { class: "row between" }, dlBtn("Download context packet", `/api/projects/${pid}/context-packet`, `context-packet-${pid}.json`), saveBtn)),
    h("div", { "data-deriv": "summary", class: "section" }, ...dView("summary")),
    proposed.length || rejected.length ? section("Proposed summaries", "Drafted by a model from a conversation. Not part of memory until you accept it.",
      ...(proposed.length ? proposed.map(propCard) : [h("p", { class: "muted" }, "No open proposals.")]),
      rejected.length ? h("details", { class: "card disclose" }, h("summary", {}, `Show rejected (${rejected.length})`), h("div", { class: "section" }, ...rejected.map(propCard))) : null) : null,
    ...groups.map((g) => { const rows = kept.filter((m) => m.layer === g); return section(titles[g], desc[g],
      ...(rows.length ? rows.map((m) => h("div", { class: "card mem" + (m.status === "superseded" ? " superseded" : "") }, h("div", { class: "row" }, statePill(m.status), h("code", {}, m.id), m.source_ids.length ? h("span", { class: "muted" }, "sources: " + m.source_ids.join(", ")) : null, h("span", { class: "muted" }, fmtTime(m.created))),
        h("p", { class: "content" }, m.content),
        m.project_id && m.status !== "superseded" ? h("div", { class: "acts" },
          h("button", { class: "linkish", type: "button", onclick: async () => { const v = await dialog("Correct this record", [{ name: "content", label: "Corrected content", type: "textarea", value: m.content }]); if (v) act(m, "correct", v); } }, "Correct"),
          h("button", { class: "linkish", type: "button", onclick: () => act(m, "mark", { status: "stale" }) }, "Mark stale"),
          h("button", { class: "linkish", type: "button", onclick: () => act(m, "mark", { status: "conflict" }) }, "Mark conflicting"),
          h("button", { class: "linkish", type: "button", onclick: () => act(m, "promote", {}) }, "Promote to shared")) : null))
        : [h("p", { class: "muted" }, "Nothing here yet.")])); }));
}

// ---------- saved ----------
async function renderArtifacts() {
  if (!S.project || S.global || S.tab !== "artifacts") return;
  const pid = S.project.id;
  const gen = ++S.viewGen;
  const arts = await api("GET", `/api/projects/${pid}/artifacts`);
  if (gen !== S.viewGen) return;
  setActivity(`${arts.length} item(s)`);
  const hist = h("section", { class: "section", id: "rtHistory" }, h("h2", {}, "Roundtables"), h("p", { class: "muted" }, "Loading sessions…"));
  $("view").replaceChildren(h("div", { class: "row between" }, h("div", { class: "section-head" }, h("h2", {}, "Saved items", h("span", { class: "count" }, String(arts.length)))),
    h("div", { class: "row" }, dlBtn("Export project (JSON)", `/api/projects/${pid}/export`, `aesop-${pid}.json`, "primary"),
      btn("Archive project", () => guard(async () => {
        const name = S.project.name;
        const v = await dialog("Archive project?", [{ name: "confirm", label: `Type the project name (${name}) to hide it. Files in the folder are never deleted.`, required: true }], "Archive");
        if (!v || v.confirm !== name || !S.project || S.project.id !== pid) return;
        await api("POST", `/api/projects/${pid}/archive`);
        if (S.project && S.project.id === pid) { S.project = null; stopWatch(); renderHeader(); await loadProjects(); renderWelcome(); } else loadProjects();
      }), "danger", "archive"))),
    ...(arts.length ? arts.map((a) => h("details", { class: "card" }, h("summary", {}, statePill(a.kind), h("span", { class: "st" }, a.title), h("span", { class: "faint" }, fmtTime(a.created)),
      h("button", { type: "button", class: "linkish", onclick: (e) => { e.preventDefault(); S.preview = a.id; openInspector("preview", e.currentTarget); } }, icon("eye", "sm"), "Preview")), h("pre", { class: "out" }, a.content)))
      : [empty("bookmark", "Nothing saved yet", "Save chat answers or task results to keep them here.")]),
    hist);
  loadRtHistory(hist, gen);
}
// Roundtable history across all projects; View opens the read-only room in the right project.
async function loadRtHistory(el, gen) {
  let rows;
  try { rows = await api("GET", "/api/roundtables"); } catch (e) { if (gen === S.viewGen) el.replaceChildren(h("h2", {}, "Roundtables"), h("div", { class: "note bad" }, icon("alert"), h("span", {}, e.message))); return; }
  if (gen !== S.viewGen) return;
  const sel = new Set(); const trs = {};
  const head = h("h2", { tabindex: "-1" }, "Roundtables", h("span", { class: "count" }, String(rows.length)));
  const delSel = abtn("Delete selected (0)", async () => {
    const ids = rows.filter((r) => sel.has(r.id)).map((r) => r.id); if (!ids.length) return;
    if (!(await confirmDelete("rt"))) return;
    let n = 0, m = 0, fail = "";
    for (const id of ids) {
      try { const res = await rtDeleteOne(id); if (res.ok) { n++; dropRow(id); } else m++; }
      catch (e) { m++; fail = e.message; }
    }
    banner(`${n} deleted, ${m} skipped (still running)${fail ? `. Last error: ${fail}` : ""}.`, m ? "" : "ok");
    setTimeout(() => (rows.length ? all : head).focus(), 0);
  }, "ghost danger sm del", "trash");
  delSel.id = "rtDelSel";
  const all = h("input", { type: "checkbox", class: "rtchk", id: "rtSelAll", onchange: (e) => {
    sel.clear(); if (e.target.checked) rows.forEach((r) => sel.add(r.id));
    el.querySelectorAll("tbody .rtchk").forEach((c) => { c.checked = e.target.checked; }); sync(); } });
  const sync = () => {
    delSel.lastChild.textContent = `Delete selected (${sel.size})`; delSel.disabled = !sel.size;
    all.checked = rows.length > 0 && sel.size === rows.length; all.indeterminate = sel.size > 0 && sel.size < rows.length;
  };
  const toolbar = h("div", { class: "row rt-bulk" }, h("label", { class: "chkl", for: "rtSelAll" }, all, "Select all"), delSel);
  const dropRow = (id) => {
    const i = rows.findIndex((r) => r.id === id); if (i >= 0) rows.splice(i, 1); sel.delete(id);
    if (trs[id]) trs[id].remove(); delete trs[id];
    head.querySelector(".count").textContent = String(rows.length);
    if (!rows.length) { const t = el.querySelector(".tablewrap"); if (t) t.replaceWith(h("p", { class: "muted" }, "No roundtable sessions yet.")); toolbar.hidden = true; }
    sync();
  };
  el.replaceChildren(h("div", { class: "section-head" }, head, h("p", {}, "Every session across projects.")),
    rows.length ? toolbar : null,
    rows.length ? table(["Select", "Project", "Mode", "Objective", "Status", "Messages", "Coverage", "Date", ""], rows.map((r) => trs[r.id] = h("tr", {},
      h("td", {}, h("input", { type: "checkbox", class: "rtchk", "aria-label": `Select roundtable ${r.id}`, onchange: (e) => { if (e.target.checked) sel.add(r.id); else sel.delete(r.id); sync(); } })),
      h("td", {}, r.project || r.project_id), h("td", {}, RT_MODES[r.mode] || r.mode), h("td", { class: "wrap" }, (r.objective || "").slice(0, 90)),
      h("td", {}, statePill(r.live_status || "DRAFT")), h("td", { class: "num" }, String(r.messages ?? "—")),
      h("td", {}, r.coverage ? h("span", { class: "pill " + (r.coverage.valid ? "ok" : "bad"), title: r.coverage.summary || "" }, r.coverage.valid ? "valid" : "not valid") : h("span", { class: "faint" }, "—")),
      h("td", {}, fmtTime(r.ended || r.started || r.updated)),
      h("td", {}, h("div", { class: "row" }, abtn("View", () => viewRoundtable(r), "sm", "eye"),
        abtn("Export record", () => guard(() => download(`/api/roundtables/${r.id}/record`, `roundtable-record-${r.id}.json`)), "ghost sm", "download"),
        delBtn("Delete", `Delete roundtable ${r.id}`, async () => {
          if (!(await confirmDelete("rt"))) return;
          try {
            const res = await rtDeleteOne(r.id);
            if (!res.ok) { banner(res.msg, "bad"); return; }
            const tr = trs[r.id]; const nx = tr && (tr.nextElementSibling || tr.previousElementSibling);
            dropRow(r.id); banner((res.r && res.r.note) || `Deleted ${r.id}.`, "ok");
            const f = (nx && nx.querySelector(".del")) || head; f.focus();
          } catch (e) { banner(e.message, "bad"); }
        }))))))
      : h("p", { class: "muted" }, "No roundtable sessions yet."));
  if (rows.length) sync();
}
async function viewRoundtable(r) {
  const opener = document.activeElement;
  if (!S.project || S.project.id !== r.project_id) await openProject(r.project_id);
  if (!S.project || S.project.id !== r.project_id) return;
  await openRoundtable(opener, { mode: r.mode });
  if (RT && RT.pid === r.project_id) rtRoom(r.id, true);
}

// ---------- global views ----------
function openGlobal(which) {
  navBump();
  S.global = which; markNav(); renderHeader();
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => b.setAttribute("aria-selected", "false"));
  document.querySelectorAll("#projectList button").forEach((b) => b.setAttribute("aria-current", "false"));
  banner("");
  const p = which === "providers" ? renderProviders() : renderEvidence(); const g = S.viewGen;
  return Promise.resolve(p).catch((e) => {
    if (g === S.viewGen && S.global === which) $("view").replaceChildren(errorView(`Could not load ${GL[which]}: ${e.message}`, () => openGlobal(which)));
    banner(e.message, "bad");
  });
}
function goSpend() { openGlobal("evidence").then(() => { const el = $("spend"); if (el) { el.scrollIntoView({ block: "start" }); const i = el.querySelector("input"); if (i) i.focus({ preventScroll: true }); } }); }
// Per-route verification state for this session: { confirm, busy, started, result: {ok, detail, at, latency_s} }.
const VERIFY = {};
const VERIFIABLE = ["cursor", "antigravity", "copilot"];
const canVerify = (id, r) => VERIFIABLE.includes(id) && ["UNVERIFIED", "UNAVAILABLE"].includes(r.state);
function verifyBlock(id, r) {
  const v = VERIFY[id] || (VERIFY[id] = {}); const name = routeName(id);
  const result = v.result ? h("div", { class: "note " + (v.result.ok ? "ok" : "bad"), tabindex: "-1", id: "vres-" + id }, icon(v.result.ok ? "check" : "alert"),
    h("span", {}, v.result.ok ? `Verified${v.result.latency_s != null ? ` in ${v.result.latency_s}s` : ""}. ${v.result.detail || ""}` : `Verification failed: ${v.result.detail || "no detail returned"}`,
      v.result.at ? ` (${fmtTime(v.result.at)})` : "")) : null;
  if (v.busy) {
    const secs = h("span", { class: "faint" }, `${Math.max(0, Math.round((Date.now() - v.started) / 1000))}s`);
    const timer = setInterval(() => { if (!secs.isConnected || !v.busy) { clearInterval(timer); return; } secs.textContent = `${Math.round((Date.now() - v.started) / 1000)}s`; }, 1000);
    return h("div", { class: "row" }, h("button", { type: "button", class: "btn sm", disabled: true }, icon("refresh"), "Verifying…"), secs);
  }
  if (!canVerify(id, r)) return result;
  if (v.confirm) {
    return h("div", { class: "verify-confirm", role: "group", "aria-label": `Confirm verifying ${name}` },
      h("p", { class: "muted", id: "vmsg-" + id }, "Sends one tiny test message using this provider's own plan quota (~10–40s)."),
      h("div", { class: "row" }, h("button", { type: "button", class: "btn sm", id: "vgo-" + id, "aria-describedby": "vmsg-" + id, onclick: () => runVerify(id) }, icon("send"), "Send test message"),
        h("button", { type: "button", class: "btn ghost sm", onclick: () => { v.confirm = false; renderProviders(); const b = $("vbtn-" + id); if (b) b.focus(); } }, "Cancel")));
  }
  return h("div", { class: "section" }, result,
    h("div", { class: "row" }, h("button", { type: "button", class: "btn sm", id: "vbtn-" + id, onclick: () => { v.confirm = true; renderProviders(); const b = $("vgo-" + id); if (b) b.focus(); } }, icon("shield"), "Verify")));
}
async function runVerify(id) {
  const v = VERIFY[id]; const name = routeName(id);
  v.confirm = false; v.busy = true; v.started = Date.now();
  if (S.global === "providers") renderProviders();
  banner(`Verifying ${name} with one test message…`);
  try {
    const r = await api("POST", `/api/routes/${id}/verify`);
    if (r && r.routes) S.routes = r.routes;
    v.result = (r && r.verification) || { ok: false, detail: "No verification result returned." };
    banner(v.result.ok ? `${routeName(id)} verified.` : `${routeName(id)} verification failed: ${v.result.detail || "no detail"}`, v.result.ok ? "ok" : "bad");
  } catch (e) {
    v.result = { ok: false, detail: e.message };
    banner(`${name} verification failed: ${e.message}`, "bad");
  }
  v.busy = false;
  if (S.project) renderHeader();
  if (S.global === "providers") { renderProviders(); const n = $("vres-" + id); if (n) n.focus(); }
}
// Long URLs in cost text become short links instead of breaking mid-word.
function linkText(text) {
  const t = String(text || "—"); const re = /((?:https?:\/\/)?[a-z0-9-]+(?:\.[a-z0-9-]+)+\/[^\s),;]*)/gi;
  const out = []; let last = 0; let m;
  while ((m = re.exec(t))) {
    if (m.index > last) out.push(t.slice(last, m.index));
    const href = /^https?:/i.test(m[1]) ? m[1] : "https://" + m[1];
    let host = m[1]; try { host = new URL(href).host; } catch { /* keep raw */ }
    out.push(h("a", { href, target: "_blank", rel: "noopener noreferrer", class: "nowrap", title: m[1] }, host));
    last = m.index + m[1].length;
  }
  if (last < t.length) out.push(t.slice(last));
  return out;
}
async function renderProviders() {
  if (S.global !== "providers") return;
  ++S.viewGen;
  const entries = Object.entries(S.routes);
  $("view").replaceChildren(h("div", { class: "row between" }, h("div", { class: "section-head" }, h("h2", {}, "Provider routes", h("span", { class: "count" }, String(entries.length)))),
    btn("Re-verify", () => guard(async () => { banner("Re-verifying via each official CLI…"); S.routes = await api("POST", "/api/routes/refresh"); renderProviders(); if (S.project) renderHeader(); banner("Routes re-verified.", "ok"); }), "primary", "refresh")),
    h("div", { class: "note info" }, icon("shield"), h("span", {}, "States come from each official CLI's own status command. Studio never reads credential files. Handoff routes are not counted as in-app integrations.")),
    entries.length ? h("div", { class: "grid3" }, ...entries.map(([id, r]) => {
      const metered = isMetered(r) || id === "openai-api"; const name = routeName(id);
      return h("article", { class: "card route", "aria-label": name },
        h("div", { class: "rhead" }, h("span", { class: "rico av" + hashIdx(id, 8), "aria-hidden": "true" }, initials(name)),
          h("div", { class: "rname" }, h("h3", {}, name), r.family && r.family !== name ? h("p", {}, r.family) : null), statePill(r.state)),
        h("div", { class: "tags" }, routeTag(r), ...(r.supported_modes || []).map((m) => h("span", { class: "tag" }, m))),
        h("dl", {}, h("dt", {}, "Version"), h("dd", {}, r.version || "—"), h("dt", {}, "Billing"), h("dd", {}, r.billing_basis || "—"),
          h("dt", {}, "Incremental cost"), h("dd", {}, ...linkText(r.incremental_cost_status)), h("dt", {}, "Verified"), h("dd", {}, fmtTime(r.last_verified_at))),
        h("div", { class: "ev" }, h("span", {}, h("b", {}, "Evidence: "), r.evidence || "—"), r.limitations ? h("span", {}, h("b", {}, "Limitations: "), r.limitations) : null),
        r.state === "READY_METERED_DISABLED" ? h("div", { class: "note" }, icon("info"), h("span", {}, "Not selectable until a monthly operating limit is set.")) : null,
        verifyBlock(id, r),
        metered ? h("div", { class: "row" }, btn("Spend controls", goSpend, "sm", "dollar")) : null);
    })) : empty("providers", "No routes detected", "Re-verify to check each official CLI's status."));
}
async function postBudget(body, okMsg) {
  await guard(async () => {
    const r = await api("POST", "/api/budget", body);
    if (r && r.routes) S.routes = r.routes;
    if (S.project) renderHeader();
    await renderEvidence(r && r.budget);
    banner(okMsg, "ok");
  });
}
function tile(k, v, sub, cls = "") { return h("div", { class: "tile " + cls }, h("div", { class: "k" }, k), h("div", { class: "v" }, v), sub ? h("div", { class: "s" }, sub) : null); }
async function renderEvidence(budgetOverride) {
  if (S.global !== "evidence") return;
  const gen = ++S.viewGen;
  const e = await api("GET", "/api/evidence");
  if (gen !== S.viewGen || S.global !== "evidence") return;
  const b = budgetOverride || e.budget; const totalCap = e.allocation.reduce((s, a) => s + a.cap, 0); const maxCap = Math.max(1, ...e.allocation.map((a) => a.cap));
  const m = { label: h("input", { "aria-label": "Workflow label", placeholder: "Label" }), workflow: h("select", { "aria-label": "Workflow" }, h("option", { value: "native" }, "Previous native workflow"), h("option", { value: "studio" }, "Aesop Studio")),
    elapsed_s: h("input", { type: "number", "aria-label": "Elapsed seconds", placeholder: "seconds" }), manual_steps: h("input", { type: "number", "aria-label": "Manual steps", placeholder: "steps" }), app_switches: h("input", { type: "number", "aria-label": "App switches", placeholder: "switches" }) };

  const limitIn = h("input", { type: "number", min: "0", step: "0.01", id: "limitIn", value: typeof b.runtime_limit === "number" ? String(b.runtime_limit) : "", placeholder: "0.00", class: "grow" });
  const saveLimit = () => { const n = Number(limitIn.value); if (limitIn.value === "" || !isFinite(n) || n < 0) { banner("Enter a monthly operating limit of 0 or more (USD).", "bad"); return; } postBudget({ runtime_limit_usd: n }, `Monthly operating limit set to ${usd(n)}.`); };
  limitIn.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); saveLimit(); } });
  const permitOn = !!b.permit;
  let liveOn = false; try { liveOn = !!(await api("GET", "/api/roundtable/lanes")).live_authorized; } catch { /* shown as off */ }
  if (gen !== S.viewGen || S.global !== "evidence") return;
  const liveSw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": liveOn ? "true" : "false", "aria-labelledby": "liveLbl", "aria-describedby": "liveDesc",
    onclick: () => guard(async () => { const r = await api("POST", "/api/roundtable/live-authorization", { enabled: !liveOn }); banner(`Live roundtables turned ${r && r.live_authorized ? "on" : "off"}.`, "ok"); await renderEvidence(); }) }, h("span", { class: "knob" }));
  const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": permitOn ? "true" : "false", "aria-labelledby": "permitLbl", "aria-describedby": "permitDesc",
    onclick: () => postBudget({ mission_permit: !permitOn }, `Mission development permit turned ${!permitOn ? "on" : "off"}.`) }, h("span", { class: "knob" }));
  const spend = h("div", { class: "card", id: "spend" },
    h("div", { class: "ttl" }, icon("dollar"), h("h2", {}, "Spend controls")),
    h("div", { class: "grid2" },
      h("div", { class: "section" }, h("label", { for: "limitIn" }, "Monthly operating limit (USD)"),
        h("div", { class: "row" }, limitIn, btn("Save", saveLimit, "primary", "check")),
        h("p", { class: "muted" }, "Caps separately billed API spend for normal use this calendar month. Metered routes stay disabled until a limit is set.")),
      h("div", { class: "section" }, h("div", { class: "row between" }, h("span", { id: "permitLbl" }, h("label", {}, "Mission development permit")), h("div", { class: "row" }, h("span", { class: "muted" }, permitOn ? "On" : "Off"), sw)),
        h("p", { class: "muted", id: "permitDesc" }, "Lets Studio bill the $165 mission envelope for Codex API development tests. Turned off automatically every time Studio restarts.")),
      h("div", { class: "section" }, h("div", { class: "row between" }, h("span", { id: "liveLbl" }, h("label", {}, "Live roundtables")), h("div", { class: "row" }, h("span", { class: "muted" }, liveOn ? "On" : "Off"), liveSw)),
        h("p", { class: "muted", id: "liveDesc" }, "Lets approved providers talk to each other in brokered, time-boxed sessions. Off by default. Each session still needs your roster, sharing acknowledgement and caps."))),
    // Cancelled or cut-off API calls keep their reservation as unresolved exposure until the owner enters the real charge.
    ...(() => {
      const amb = (e.ledger || []).filter((r) => r.status === "ambiguous");
      if (!amb.length) return [];
      return [h("div", { class: "section" }, h("h3", {}, `Unresolved exposure (${amb.length})`),
        h("p", { class: "muted" }, "These calls stopped before the Codex API reported usage, so their full reservation is still held. Check the Codex API usage dashboard (platform.openai.com) and enter the real charge."),
        ...amb.map((r) => h("div", { class: "row between" },
          h("span", {}, `${routeLabel(r.route)} · ${r.purpose} · reserved ${fmtCost(r.reservation_usd)} · ${fmtTime(r.created)}`),
          btn("Resolve", async () => {
            const v = await dialog("Resolve unresolved exposure", [{ name: "actual_usd", label: "Actual charge from the Codex API usage dashboard (platform.openai.com), USD", required: true, value: "", placeholder: "e.g. 0.00004" },
              { name: "note", label: "Note (optional)", value: "" }], "Resolve");
            if (!v) return;
            const amt = Number(String(v.actual_usd).trim()); if (!isFinite(amt) || amt < 0) { banner("Enter the actual charge in USD, 0 or more.", "bad"); return; }
            await guard(async () => { await api("POST", `/api/ledger/${r.id}/resolve`, { actual_usd: amt, note: v.note }); banner("Exposure resolved from the usage dashboard.", "ok"); await renderEvidence(); });
          }, "sm", "check"))))];
    })());

  const accCounts = { ok: 0, warn: 0, bad: 0, n: 0 };
  e.acceptance.forEach((a) => { accCounts[tone(a.status) || "n"]++; });
  const accBar = h("div", { class: "stackbar", role: "img", "aria-label": `Acceptance: ${accCounts.ok} passing, ${accCounts.warn} pending, ${accCounts.bad} failing, ${accCounts.n} other` },
    ...Object.entries(accCounts).filter(([, n]) => n).map(([k, n]) => { const i = h("i", { class: k }); i.style.flexGrow = String(n); return i; }));

  $("view").replaceChildren(
    section("Mission budget", "Mission spending (USD). Allocation is not expenditure.",
      h("div", { class: "tiles" }, tile("Ceiling", usd(b.ceiling), null, "lead"), tile("Settled (billed)", usd(b.settled), "actually charged"),
        tile("Outstanding reservations", usd(b.outstanding), "held, not spent"), tile("Remaining", usd(b.remaining))),
      h("div", { class: "tiles" }, tile("Unresolved exposure", usd(b.ambiguous), null, "small"), tile("Subscription-included runs ($0)", String(b.included_uses ?? "—"), null, "small"),
        tile("Billable permit", b.permit ? "ON" : "off", null, "small"), tile("Phase", String(b.phase ?? "—"), null, "small"))),
    section("Runtime (this month)", "Separately billed API spend for normal use. A separate envelope from the mission budget; the two are never added together.",
      h("div", { class: "tiles" }, tile("Monthly operating limit", usd(b.runtime_limit), b.runtime_limit ? "set by you" : "not set: metered routes disabled", "lead"),
        tile("Settled this month", usd(b.runtime_month_settled)), tile("Outstanding this month", usd(b.runtime_month_outstanding)),
        tile("Remaining this month", usd(b.runtime_month_remaining)), tile("Metered calls", String(b.metered_calls ?? "—")))),
    spend,
    section("Planning envelopes", `Caps, total $${totalCap}. Allocation is not expenditure.`,
      e.allocation.length ? h("div", { class: "card envs" }, ...e.allocation.map((a) => { const i = h("i"); i.style.width = `${(a.cap / maxCap) * 100}%`;
        return h("div", { class: "env" }, h("span", { class: "en" }, a.envelope), h("span", { class: "ev" }, `$${a.cap}`), h("div", { class: "bar", role: "img", "aria-label": `$${a.cap} of $${totalCap}` }, i)); }))
        : h("p", { class: "muted" }, "No envelopes defined.")),
    section("Acceptance matrix", e.acceptance.length ? `${e.acceptance.length} requirement(s)` : null,
      e.acceptance.length ? h("div", { class: "card" }, accBar, h("div", { class: "legend" },
        h("span", {}, h("span", { class: "dot ok" }), `${accCounts.ok} passing`), h("span", {}, h("span", { class: "dot warn" }), `${accCounts.warn} pending`),
        h("span", {}, h("span", { class: "dot bad" }), `${accCounts.bad} failing`), accCounts.n ? h("span", {}, h("span", { class: "dot" }), `${accCounts.n} other`) : null)) : null,
      e.acceptance.length ? table(["ID", "Requirement", "Implementation", "Test", "Status", "Evidence / limitation"], e.acceptance.map((a) => h("tr", {}, h("td", {}, h("code", {}, a.id)), h("td", { class: "wrap" }, a.requirement), h("td", { class: "wrap" }, a.implementation), h("td", {}, a.test), h("td", {}, statePill(a.status)), h("td", { class: "wrap" }, a.evidence))))
        : empty("check", "No acceptance file", "The acceptance matrix appears once docs/acceptance.json is present.")),
    section("Task success and recovery", `${e.tasks.total} run(s) recorded.`,
      h("div", { class: "tiles" }, tile("Runs recorded", String(e.tasks.total), null, "small"), tile("Restart reconciliations", String(e.tasks.reconciliations), null, "small"),
        tile("Open repair packets", String(e.tasks.repairs.filter((r) => /^(OPEN|EXPORTED)/.test(r.status)).length), null, "small")),
      Object.keys(e.tasks.by_state).length ? h("div", { class: "row" }, ...Object.entries(e.tasks.by_state).map(([s, n]) => statePill(`${s}: ${n}`))) : null,
      e.tasks.total ? null : h("p", { class: "muted" }, "No runs yet. Counts appear after real use."),
      e.tasks.repairs.length ? table(["Repair", "Task", "Signature", "Contract", "Status", ""], e.tasks.repairs.map((r) => h("tr", {}, h("td", {}, h("code", {}, r.id)), h("td", {}, r.task_id), h("td", { class: "wrap" }, r.signature), h("td", {}, r.contract), h("td", {}, statePill(r.status)),
        h("td", {}, h("button", { class: "linkish", type: "button", onclick: () => guard(async () => { const x = await api("POST", `/api/repairs/${r.id}/export`); banner(`${x.note} ${x.packet}`, "ok"); await renderEvidence(); }) }, "Export packet"),
          /^(OPEN|EXPORTED)/.test(r.status) ? h("button", { class: "linkish", type: "button", onclick: async () => {
            const v = await dialog("Mark repair resolved", [{ name: "note", label: "What did you check?", type: "textarea", required: true, value: "", help: "This confirms you reviewed the uncertain effects of this task (for example, files it may have changed). It unblocks new agent tasks in this project." }], "Mark resolved");
            if (!v) return;
            await guard(async () => { await api("POST", `/api/repairs/${r.id}/resolve`, { note: v.note }); banner("Repair marked resolved by owner.", "ok"); await renderEvidence(); });
          } }, "Mark resolved") : null))), "Repair packets (Foreman). Studio never replays or repairs automatically.") : null),
    section("Provider latency (completed runs)", "Provider wait measured from process start to exit. Small samples are shown individually; no confidence claims.",
      e.latency.length ? table(["Route/mode", "n", "Median s", "Min", "Max", "Last samples"], e.latency.map((l) => h("tr", {}, h("td", {}, routeLabel(l.route)), h("td", { class: "num" }, l.n), h("td", { class: "num" }, l.median_s), h("td", { class: "num" }, l.min_s), h("td", { class: "num" }, l.max_s), h("td", {}, l.samples.join(", ")))))
        : h("p", { class: "muted" }, "No completed runs yet.")),
    section("Workflow measurements", "Record the same task done the old way and in Studio. Without owner trials, any time saving stays unverified; no time-saving claim is made here.",
      h("div", { class: "card" }, h("div", { class: "measure" }, m.label, m.workflow, m.elapsed_s, m.manual_steps, m.app_switches, btn("Record", () => guard(async () => { await api("POST", "/api/workflow-measure", Object.fromEntries(Object.entries(m).map(([k, el]) => [k, el.value]))); await renderEvidence(); }), "", "plus"))),
      e.workflow.length ? table(["Label", "Workflow", "Seconds", "Steps", "App switches", "When"], e.workflow.map((w) => h("tr", {}, h("td", {}, w.label || ""), h("td", {}, w.workflow || ""), h("td", { class: "num" }, w.elapsed_s || ""), h("td", { class: "num" }, w.manual_steps || ""), h("td", { class: "num" }, w.app_switches || ""), h("td", {}, fmtTime(w.at)))))
        : h("p", { class: "muted" }, "No measurements recorded.")),
    e.research.length ? section("Research background", "External studies are background, not Aesop Studio results.",
      table(["Source", "Context", "Method", "Result", "Limitations", "Decision"], e.research.map((r) => h("tr", {}, h("td", {}, h("a", { href: r.url, rel: "noopener noreferrer", target: "_blank" }, r.source)), h("td", { class: "wrap" }, r.context), h("td", { class: "wrap" }, r.method), h("td", { class: "wrap" }, r.result), h("td", { class: "wrap" }, r.limitations), h("td", { class: "wrap" }, r.decision))))) : null,
    section("Backup", "Archives Studio data locally; the restore test unpacks the latest backup into a separate folder.",
      h("div", { class: "row" }, btn("Create backup", () => guard(async () => { const r = await api("POST", "/api/backup"); banner(`Backup written: ${r.archive}`, "ok"); }), "", "db"),
        btn("Test restore of latest backup", () => guard(async () => { const r = await api("POST", "/api/backup/verify"); banner(r.ok ? `Restore test passed in ${r.target}. ${r.reauth}` : `Restore test FAILED: ${JSON.stringify(r)}`, r.ok ? "ok" : "bad"); }), "", "refresh"))));
}

boot();

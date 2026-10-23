"use strict";
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
const WS = { chat: "Chat", agent: "Build", research: "Research", memory: "Memory", artifacts: "Saved" };
const GL = { providers: "Providers", evidence: "Evidence" };

// ---------- icons (inline SVG via createElementNS; no markup strings) ----------
const SVGNS = "http://www.w3.org/2000/svg";
const ICONS = {
  plus: "M12 5v14M5 12h14", chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12z",
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
  panel: "M3 4h18v16H3zM15 4v16", diff: "M12 3v12M6 9h12M6 21h12", list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
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
  return h("div", { class: "empty" }, h("div", { class: "eico" }, icon(ico)),
    h("div", { class: "et" }, title ? h("strong", {}, title) : null, text ? h("p", {}, text) : null, actions.length ? h("div", { class: "row" }, ...actions) : null));
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
function routeTag(r) { return r ? h("span", { class: "tag " + (isMetered(r) ? "billed" : "route") }, access(r.state)) : null; }

async function api(method, path, body, raw) {
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (method !== "GET") opts.headers["X-CSRF-Token"] = S.csrf;
  if (raw) { opts.body = raw.data; opts.headers["X-Filename"] = encodeURIComponent(raw.name); }
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, opts);
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) { const e = new Error((data && data.error) || data.extract_note || r.statusText); e.status = r.status; e.data = data; throw e; }
  return data;
}
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
  return new Promise((resolve) => {
    const d = $("dlg"), f = $("dlgForm"); const opener = document.activeElement;
    f.replaceChildren(h("h2", {}, title), ...fields.map((fd) => h("div", { class: "field" }, h("label", {}, fd.label,
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
    [["Ctrl", "3"], "Research"], [["Esc"], "Close a dialog, drawer or sheet"], [["?"], "Show this list"], [["←", "→"], "Resize a focused panel divider"]];
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
  if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K")) { e.preventDefault(); if (!$("palette").open) openPalette(); return; }
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
  if (e.ctrlKey && !e.altKey && !e.shiftKey && ["1", "2", "3"].includes(e.key) && S.project) { e.preventDefault(); setTab(["chat", "agent", "research"][Number(e.key) - 1]); return; }
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
  el.setAttribute("title", p.provider_default ? `${p.provider_default}: ${r ? r.state : "unknown"}` : "No default provider chosen");
  el.replaceChildren(p.provider_default ? routeDot(p.provider_default) : h("span", { class: "dot" }), h("b", {}, p.provider_default || "No provider"),
    h("span", { class: "rt" }, r ? access(r.state) : p.provider_default ? "unavailable" : "choose one in the workspace header"));
}

// ---------- command palette ----------
let PAL = { items: [], sel: 0, opener: null };
function paletteItems() {
  const it = [];
  if (S.project) for (const [k, v] of Object.entries(WS)) it.push({ g: "Workspace", ico: { chat: "chat", agent: "terminal", research: "search", memory: "layers", artifacts: "bookmark" }[k], label: `Go to ${v}`, key: { chat: "Ctrl 1", agent: "Ctrl 2", research: "Ctrl 3" }[k], run: () => setTab(k) });
  for (const p of S.projects) it.push({ g: "Project", ico: "folder", label: `Switch to ${p.name}`, hint: p.root, run: () => openProject(p.id) });
  it.push({ g: "Action", ico: "plus", label: "New project", run: newProject });
  if (S.project) it.push({ g: "Action", ico: "chat", label: "New conversation", run: () => guard(async () => { const c = await api("POST", `/api/projects/${S.project.id}/conversations`, {}); S.conv = c.id; setTab("chat"); }) });
  it.push({ g: "Studio", ico: "providers", label: "Open Providers", run: () => openGlobal("providers") });
  it.push({ g: "Studio", ico: "evidence", label: "Open Evidence", run: () => openGlobal("evidence") });
  it.push({ g: "View", ico: "panel", label: "Toggle inspector", run: () => toggleInspector($("inspectorBtn")) });
  for (const t of ["preview", "files", "changes", "terminal", "logs"]) it.push({ g: "View", ico: "panel", label: `Inspector: ${t[0].toUpperCase() + t.slice(1)}`, run: () => openInspector(t, $("inspectorBtn")) });
  it.push({ g: "Help", ico: "help", label: "Keyboard shortcuts", key: "?", run: showShortcuts });
  return it;
}
function openPalette() {
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

// ---------- boot ----------
async function boot() {
  setupShell(); setupPalette(); crumbs();
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
  S.routes = await api("GET", "/api/routes");
  await loadProjects();
  $("newProjectBtn").onclick = newProject;
  $("settingsBtn").onclick = projectSettings;
  $("providerSel").onchange = (e) => guard(async () => { S.project = await api("PATCH", `/api/projects/${S.project.id}`, { provider_default: e.target.value }); renderHeader(); loadProjects(); banner(`Project default provider set to ${e.target.value}.`, "ok"); });
  document.querySelectorAll("[data-global]").forEach((b) => (b.onclick = () => { closeOverlay(false); openGlobal(b.dataset.global); }));
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => (b.onclick = () => setTab(b.dataset.tab)));
  $("tabs").addEventListener("keydown", (e) => {
    if (!["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft"].includes(e.key)) return;
    e.preventDefault();
    const tabs = [...document.querySelectorAll("#tabs [data-tab]")]; const i = tabs.findIndex((t) => t.dataset.tab === S.tab);
    const fwd = e.key === "ArrowDown" || e.key === "ArrowRight";
    const n = tabs[(i + (fwd ? 1 : tabs.length - 1)) % tabs.length]; setTab(n.dataset.tab); n.focus();
  });
  const last = localStorageGet("aesop.project");
  if (last && S.projects.some((p) => p.id === last)) await openProject(last);
  else if (!S.projects.length) renderWelcome(); else await openProject(S.projects[0].id);
  if (recovered) banner(recovered);
}

async function loadProjects() {
  S.projects = await api("GET", "/api/projects");
  $("projectList").replaceChildren(...S.projects.map((p) => h("button", { "aria-current": S.project && S.project.id === p.id && !S.global ? "true" : "false", "data-pid": p.id, title: p.root, onclick: () => { closeOverlay(false); openProject(p.id); } },
    h("span", { class: "avatar av" + hashIdx(p.id, 8), "aria-hidden": "true" }, initials(p.name)), h("span", { class: "pt" }, h("span", { class: "pname" }, p.name), h("small", {}, p.root)))));
  if (!S.projects.length) $("projectList").append(h("p", { class: "muted" }, "No projects yet."));
}
function renderWelcome() {
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
    { name: "provider_default", label: "Default provider", type: "select", options: usable.map(([id, r]) => ({ value: id, label: `${id} — ${r.provider} · ${access(r.state)} (${r.state})` })),
      help: disabled.length ? `${disabled.join(", ")} (separately billed API) needs a monthly operating limit in Evidence → Spend controls before it can be chosen.` : null },
  ], "Create");
  if (!v) return;
  await guard(async () => { const p = await api("POST", "/api/projects", v); await loadProjects(); openProject(p.id); });
}
async function projectSettings() {
  const p = S.project;
  const pol = p.transfer_policy || {};
  const v = await dialog("Project settings", [
    { name: "name", label: "Name", value: p.name },
    { name: "model", label: "Model override (optional)", value: p.model || "", help: "Leave blank to use the provider CLI's default model." },
    { name: "retention_days", label: "Conversation retention (days)", type: "number", value: String(p.retention_days) },
    ...Object.keys(S.routes).filter((k) => USABLE.includes(S.routes[k].state)).map((k) => ({ name: "tp_" + k, label: `Allow sending attached project files to ${k}?`, type: "select", value: pol[k] ? "yes" : "no", options: [{ value: "no", label: "No" }, { value: "yes", label: "Yes" }] })),
  ]);
  if (!v) return;
  const tp = {}; for (const [k, val] of Object.entries(v)) if (k.startsWith("tp_")) tp[k.slice(3)] = val === "yes";
  await guard(async () => { S.project = await api("PATCH", `/api/projects/${p.id}`, { name: v.name, model: v.model, retention_days: v.retention_days, transfer_policy: tp }); renderHeader(); loadProjects(); banner("Settings saved.", "ok"); });
}

async function openProject(id) {
  S.global = null; S.conv = null; S.taskSel = null; S.preview = null; stopWatch(); markNav();
  await guard(async () => {
    S.project = await api("GET", `/api/projects/${id}`);
    localStorageSet("aesop.project", id);
    S.lay = loadJSON(layKey(), { tab: "chat", w: {} });
    layout(); renderHeader(); await loadProjects();
    setTab(WS[S.lay.tab] ? S.lay.tab : "chat");
  });
}
function renderHeader() {
  const p = S.project;
  if (S.global) {
    $("projTitle").textContent = GL[S.global]; $("projMeta").replaceChildren(); $("projControls").hidden = true; $("tabs").hidden = !p;
    routeIndicator(); crumbs(); return;
  }
  $("projTitle").textContent = p ? p.name : "No project open";
  const meta = $("projMeta");
  if (p) {
    const r = S.routes[p.provider_default];
    meta.replaceChildren(h("span", { class: "chip mono", title: p.root }, icon("folder"), h("span", { class: "t" }, p.root)),
      h("span", { class: "chip" }, p.provider_default ? routeDot(p.provider_default) : null, h("span", { class: "t" }, `default provider: ${p.provider_default || "not set"}${r ? " · " + access(r.state) : ""}`)),
      h("span", { class: "chip saved" }, icon("check"), h("span", { class: "t" }, "Saved locally")));
  } else meta.replaceChildren();
  $("projControls").hidden = !p; $("tabs").hidden = !p;
  routeIndicator(); crumbs();
  if (!p) return;
  const sel = $("providerSel");
  sel.replaceChildren(h("option", { value: "" }, "— choose —"), ...Object.entries(S.routes).map(([id, r]) => {
    const ok = USABLE.includes(r.state);
    if (!ok && r.state !== "READY_METERED_DISABLED") return null;
    return h("option", { value: id, selected: id === p.provider_default, disabled: !ok }, `${id} (${r.provider}) · ${access(r.state)}${ok ? "" : " — set a monthly limit in Evidence"}`);
  }).filter(Boolean));
}
function markNav() {
  document.querySelectorAll("[data-global]").forEach((b) => b.setAttribute("aria-current", S.global === b.dataset.global ? "true" : "false"));
}
function setTab(tab) {
  if (!WS[tab]) tab = "chat";
  S.tab = tab; S.global = null; clearInterval(S.poll); markNav(); S.activity = "";
  S.lay.tab = tab; saveLay();
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => { b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false"); b.tabIndex = b.dataset.tab === tab ? 0 : -1; });
  document.querySelectorAll("#projectList button").forEach((b) => b.setAttribute("aria-current", S.project && b.dataset.pid === S.project.id ? "true" : "false"));
  renderHeader();
  ({ chat: renderChat, agent: renderAgent, research: renderResearch, memory: renderMemory, artifacts: renderArtifacts })[tab]();
  renderInspector();
}

// ---------- task watcher (one poll shared by Build, Terminal, Changes and Logs) ----------
const W = { tid: null, offset: 0, text: "", task: null, timer: null, hooks: {} };
function stopWatch() { clearTimeout(W.timer); W.timer = null; W.tid = null; W.text = ""; W.offset = 0; W.task = null; }
function watchTask(tid) {
  if (W.tid === tid) { notifyTask(""); return; }
  stopWatch(); W.tid = tid; wtick();
}
async function wtick() {
  const tid = W.tid; if (!tid) return;
  try {
    const r = await api("GET", `/api/tasks/${tid}?offset=${W.offset}`);
    if (tid !== W.tid) return;
    W.offset = r.offset; if (r.output) W.text += r.output; W.task = r.task;
    notifyTask(r.output || "");
    if (!DONE.includes(r.task.state)) W.timer = setTimeout(wtick, 1500);
  } catch (e) { if (tid === W.tid) W.timer = setTimeout(wtick, 4000); }
}
function notifyTask(chunk) { for (const f of Object.values(W.hooks)) { try { f(chunk); } catch { /* detached view */ } } }

// ---------- inspector ----------
function setItab(t) {
  S.itab = t; localStorageSet("aesop.itab", t);
  document.querySelectorAll("#itabs [data-itab]").forEach((b) => { const on = b.dataset.itab === t; b.setAttribute("aria-selected", on ? "true" : "false"); b.tabIndex = on ? 0 : -1; if (on && b.id) $("inspBody").setAttribute("aria-labelledby", b.id); });
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
    renderInspector(); if (S.tab === "chat" && !S.global) renderChat();
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
      h("span", { class: "lm" }, statePill(t.state), h("span", {}, t.provider), h("code", {}, t.id), t.exit_code !== null && t.exit_code !== undefined ? h("span", { class: "faint" }, `exit ${t.exit_code}`) : null,
        t.error ? h("span", { class: "faint" }, t.error) : null))))
      : empty("list", "No log entries", "Each Build task adds its state, provider, exit code and any error here."));
}
function inspTerminal(body, tid, auto) {
  const pre = h("pre", { "aria-live": "off", tabindex: "0", "aria-label": "Task output" });
  const bar = h("span", { class: "grow" }, `task ${tid}`); const st = h("span");
  pre.textContent = W.text;
  body.replaceChildren(auto ? h("p", { class: "faint" }, "Most recent task. Select another in Build.") : null,
    h("div", { class: "term" }, h("div", { class: "term-bar" }, icon("terminal", "sm"), bar, st), pre));
  const upd = (chunk) => {
    const t = W.task; if (!t || W.tid !== tid) return;
    bar.textContent = `${t.id} · ${t.provider}`; st.replaceChildren(statePill(t.state));
    if (chunk) { const stick = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 60; pre.append(chunk); if (stick) pre.scrollTop = pre.scrollHeight; }
  };
  W.hooks.insp = upd; upd("");
}
function inspChanges(body, tid, auto) {
  const wrap = h("div", { class: "changes" });
  body.replaceChildren(auto ? h("p", { class: "faint" }, "Most recent task. Select another in Build.") : null, wrap);
  const upd = () => {
    const t = W.task; if (!t || W.tid !== tid) { wrap.replaceChildren(h("p", { class: "faint" }, "Loading task record…")); return; }
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
async function renderChat() {
  const pid = S.project.id;
  const gen = ++S.chatGen;
  const convs = await api("GET", `/api/projects/${pid}/conversations`);
  if (!S.conv && convs.length) S.conv = convs[0].id;
  if (S.streamConv !== S.conv) { S.streams = {}; S.streamConv = S.conv; }
  S.streamUpd = {}; S.msgSig = "";
  const atts = (await api("GET", `/api/projects/${pid}/attachments`)).filter((a) => a.extract_status === "extracted");
  if (gen !== S.chatGen) return;
  const cur = convs.find((c) => c.id === S.conv); setActivity(cur ? cur.title : "");
  const newConv = async () => guard(async () => { const c = await api("POST", `/api/projects/${pid}/conversations`, {}); S.conv = c.id; renderChat(); });
  const bar = h("div", { class: "convbar" },
    convs.length ? h("div", { class: "convstrip", role: "list", "aria-label": "Conversations" }, ...convs.map((c) => h("button", { role: "listitem", "aria-current": c.id === S.conv ? "true" : "false", title: c.title, onclick: () => { S.conv = c.id; renderChat(); } }, icon("chat", "sm"), h("span", {}, c.title)))) : h("span", { class: "grow" }),
    btn("New conversation", newConv, "ghost", "plus"));
  const root = h("div", { class: "chatv" }, bar);
  if (!S.conv) {
    root.append(empty("chat", "No conversations yet", "Start a conversation to talk with this project's provider. Messages are saved locally before anything is sent.", btn("Start a conversation", newConv, "primary", "plus")));
    $("view").replaceChildren(root); return;
  }
  const msgsEl = h("div", { class: "msgs", "aria-live": "polite", "aria-relevant": "additions" });
  const ta = h("textarea", { "aria-label": "Message", placeholder: "Ask something about this project…" });
  const chosen = () => [...root.querySelectorAll(".achip[aria-pressed='true']")].map((b) => b.dataset.id);
  const prov = S.project.provider_default; const pr = S.routes[prov];
  const send = async (confirm) => {
    const text = ta.value.trim(); if (!text) { ta.focus(); return; }
    try {
      await api("POST", `/api/projects/${pid}/conversations/${S.conv}/messages`, { text, attachment_ids: chosen(), confirm_switch: confirm });
      ta.value = ""; grow(); banner("Saved locally and submitted to provider.", "ok"); S.msgSig = ""; drawMsgs();
    } catch (e) { banner(e.message, "bad"); }
  };
  const preview = async () => guard(async () => {
    const r = await api("POST", `/api/projects/${pid}/conversations/${S.conv}/preview`, { text: ta.value, attachment_ids: chosen() });
    await dialog(`Context that will be sent to ${r.provider} (${r.chars} chars)`, [{ name: "ctx", label: "Exact payload", type: "textarea", value: r.context, tall: true, readonly: true }], "Close");
  });
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(false); } });
  const grow = autosize(ta);
  const attachRow = atts.length
    ? h("div", { class: "attach", role: "group", "aria-label": "Attach project files" }, h("span", { class: "lbl" }, icon("clip", "sm"), "Attach"),
      ...atts.map((a) => h("button", { type: "button", class: "achip", "aria-pressed": "false", "data-id": a.id, title: `${a.name} (${a.chars} chars)`,
        onclick: (e) => { const b = e.currentTarget; b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") === "true" ? "false" : "true"); } },
      h("span", {}, a.name))))
    : h("div", { class: "attach" }, h("span", { class: "lbl" }, icon("clip", "sm"), "No readable files to attach yet."), h("button", { type: "button", class: "linkish", onclick: (e) => openInspector("files", e.currentTarget) }, "Add files"));
  const composer = h("div", { class: "composer" }, ta, attachRow,
    h("div", { class: "cfoot" },
      h("div", { class: "row" }, h("span", { class: "chip" }, prov ? routeDot(prov) : null, h("span", { class: "t" }, `${prov || "No provider chosen"}${pr ? " · " + access(pr.state) : ""}`)),
        h("span", { class: "hint" }, h("kbd", {}, "Ctrl"), h("kbd", {}, "Enter"), " send")),
      h("div", { class: "row" }, btn("Preview context", preview, "ghost", "eye"), btn("Send", () => send(false), "primary", "send"))));
  root.append(msgsEl, h("div", { class: "composer-dock" }, composer));
  $("view").replaceChildren(root);

  const scroller = $("main");
  const nearBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120;
  const toBottom = () => { scroller.scrollTop = scroller.scrollHeight; };
  function msgView(m) {
    const meta = m.meta || {}; const user = m.role === "user"; const r = S.routes[m.provider];
    const costBits = [];
    if (typeof meta.cost_usd === "number") costBits.push(fmtCost(meta.cost_usd));
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
    return h("article", { class: "msg " + m.role },
      h("div", { class: "mav", "aria-hidden": "true" }, user ? "You" : initials(m.provider || "AI")),
      h("div", { class: "bubble" },
        h("div", { class: "mhead" },
          h("div", { class: "who" }, h("strong", {}, user ? "You" : `${m.provider}`), !user ? routeTag(r) : null,
            user && m.status === "saved" ? null : statePill(m.status), user ? h("span", { class: "chip saved" }, icon("check"), h("span", { class: "t" }, "saved locally")) : null,
            h("span", {}, fmtClock(m.created)), meta.duration_s ? h("span", {}, `· ${meta.duration_s}s provider wait`) : null),
          m.role === "assistant" && m.status === "generated" ? h("button", { class: "linkish", type: "button", onclick: () => guard(async () => { const a = await api("POST", `/api/projects/${pid}/artifacts`, { kind: "chat_answer", title: m.content.slice(0, 60), content: m.content, source_ref: m.id }); S.preview = a && a.id; banner("Saved to project.", "ok"); if (S.itab === "preview") renderInspector(); }) }, icon("bookmark", "sm"), "Save") : null),
        body,
        costBits.length ? h("div", { class: "costline" }, icon("dollar", "sm"), costBits.join(" · ")) : null));
  }
  async function drawMsgs() {
    const msgs = await api("GET", `/api/projects/${pid}/conversations/${S.conv}/messages`);
    if (gen !== S.chatGen) return;
    const sig = msgs.map((m) => m.id + ":" + m.status).join("|");
    if (sig !== S.msgSig) {
      const stick = !S.msgSig || nearBottom();
      S.msgSig = sig; S.streamUpd = {};
      msgsEl.replaceChildren(...(msgs.length ? msgs.map(msgView) : [h("div", { class: "empty" }, h("div", { class: "eico" }, icon("sparkle")), h("div", { class: "et" }, h("strong", {}, "Ask your first question"),
        h("p", {}, "Your message is saved locally first, then sent with this project's context. Try one of these:"),
        h("div", { class: "suggest" }, ...SUGGESTIONS.map(([ic, s]) => h("button", { type: "button", onclick: () => { ta.value = s; grow(); ta.focus(); } }, icon(ic), h("span", {}, s))))))]));
      if (stick) toBottom();
    }
    clearInterval(S.poll);
    const pending = msgs.filter((m) => m.status === "submitted");
    if (!pending.length) return;
    let ticks = 0, busy = false;
    const timer = setInterval(async () => {
      if (S.tab !== "chat" || S.global || gen !== S.chatGen || S.poll !== timer) { clearInterval(timer); return; }
      if (busy) return; busy = true;
      try {
        let refresh = ++ticks % 3 === 0;
        for (const m of pending) {
          const st = S.streams[m.id] || (S.streams[m.id] = { offset: 0, text: "" });
          const tid = m.meta && m.meta.task_id;
          if (tid) {
            try {
              const r = await api("GET", `/api/tasks/${tid}?offset=${st.offset}`);
              if (gen !== S.chatGen) return;
              st.offset = r.offset;
              // Only API routes stream the answer itself; CLI logs (prompt echo, banners) belong in the Terminal tab.
              if (r.output && r.stream_is_answer) { const stick = nearBottom(); st.text += r.output; if (stick) requestAnimationFrame(toBottom); }
              if (r.task && DONE.includes(r.task.state)) refresh = true;
            } catch { /* best-effort; message polling still resolves it */ }
          }
          if (S.streamUpd[m.id]) S.streamUpd[m.id]();
        }
        if (refresh && S.poll === timer) { clearInterval(timer); await drawMsgs(); }
      } finally { busy = false; }
    }, 1000);
    S.poll = timer;
  }
  drawMsgs();
}

// ---------- build (agent tasks) ----------
async function renderAgent(selected) {
  const pid = S.project.id;
  const tasks = await api("GET", `/api/projects/${pid}/tasks`);
  const ta = h("textarea", { "aria-label": "Agent task", placeholder: "Describe a bounded coding task to run inside the project folder…" });
  const start = () => guard(async () => {
    if (!ta.value.trim()) { ta.focus(); return; }
    const t = await api("POST", `/api/projects/${pid}/tasks`, { prompt: ta.value });
    banner(`Task ${t.id} ${t.state}.`, t.state === "BLOCKED_OWNER" ? "bad" : "ok"); S.taskSel = t.id; renderAgent(t.id);
  });
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); start(); } });
  const r = S.routes[S.project.provider_default];
  const detail = h("div", { class: "section" });
  const listEl = h("div", { class: "tasklist" });
  const pickTask = (id) => {
    S.taskSel = id; setActivity(`Task ${id}`);
    listEl.querySelectorAll(".task").forEach((b) => b.setAttribute("aria-current", b.dataset.id === id ? "true" : "false"));
    showTask(id, detail);
    if (inspectorVisible() && !["terminal", "changes", "logs"].includes(S.itab)) setItab("terminal");
    if (inspectorVisible()) renderInspector();
  };
  listEl.append(...tasks.map((t) => h("button", { class: "task", type: "button", "data-id": t.id, "aria-current": "false", onclick: () => pickTask(t.id) },
    h("span", { class: "dot " + tone(t.state) }),
    h("span", {}, h("span", { class: "tp" }, t.prompt.slice(0, 160)),
      h("span", { class: "tm" }, statePill(t.state), h("span", {}, t.provider), h("span", {}, fmtClock(t.started || t.created)))))));
  $("view").replaceChildren(
    h("div", { class: "composer" }, h("div", { class: "card-head" }, h("div", { class: "ttl" }, icon("terminal"), h("h2", {}, "Run an agent task")), routeTag(r)),
      h("p", { class: "muted" }, `Runs the official ${S.project.provider_default || "(choose a provider)"} CLI inside ${S.project.root}. Output is redacted and size-limited. Cancel stops the local process tree only.`), ta,
      h("div", { class: "cfoot" }, h("span", { class: "hint" }, h("kbd", {}, "Ctrl"), h("kbd", {}, "Enter"), " start"), btn("Start task", start, "primary", "terminal"))),
    tasks.length ? h("div", { class: "grid2" }, section("Recent tasks", `${tasks.length} shown`, listEl), detail)
      : empty("terminal", "No agent tasks yet", "Describe a bounded task above. Each run records its state, output, exit code and changed files."));
  autosize(ta);
  if (tasks.length) {
    detail.append(empty("terminal", "Select a task", "Its state, facts and actions appear here; live output and changed files open in the inspector."));
    const sel = selected || (S.taskSel && tasks.some((t) => t.id === S.taskSel) ? S.taskSel : null);
    if (sel) pickTask(sel);
  }
}
function showTask(tid, el) {
  const head = h("div", { class: "card-head" }); const info = h("div", { class: "section" });
  el.replaceChildren(h("div", { class: "card" }, head, info));
  const upd = () => {
    const t = W.task; if (!t || W.tid !== tid) { head.replaceChildren(h("h3", {}, `Task ${tid}`)); info.replaceChildren(h("p", { class: "faint" }, "Loading task record…")); return; }
    const done = DONE.includes(t.state);
    let ch = null; try { ch = t.changed_files ? JSON.parse(t.changed_files) : null; } catch { ch = null; }
    head.replaceChildren(h("div", { class: "ttl" }, h("h3", {}, `Task ${t.id}`), statePill(t.state)),
      h("div", { class: "row" }, !done ? btn("Cancel", () => guard(async () => { const c = await api("POST", `/api/tasks/${tid}/cancel`); banner(c.note, ""); }), "danger sm", "stop") : null,
        done ? btn("Save result", () => guard(async () => { const a = await api("POST", `/api/tasks/${tid}/save`); S.preview = a && a.id; banner("Task result saved to project.", "ok"); }), "sm", "bookmark") : null));
    info.replaceChildren(
      h("div", { class: "facts" }, h("span", {}, "Provider ", h("b", {}, t.provider)), h("span", {}, "cwd ", h("b", {}, t.cwd || "—")),
        h("span", {}, "started ", h("b", {}, fmtTime(t.started))), h("span", {}, "ended ", h("b", {}, fmtTime(t.ended))), t.exit_code !== null && t.exit_code !== undefined ? h("span", {}, "exit ", h("b", {}, String(t.exit_code))) : null),
      t.error ? h("div", { class: "note bad" }, icon("alert"), h("span", {}, t.error)) : null,
      ch ? h("p", { class: "muted" }, `Changed files — added: ${ch.added.length}, modified: ${ch.modified.length}, removed: ${ch.removed.length}.`) : null,
      h("div", { class: "row" }, h("button", { type: "button", class: "linkish", onclick: (e) => openInspector("terminal", e.currentTarget) }, icon("terminal", "sm"), "View output"),
        h("button", { type: "button", class: "linkish", onclick: (e) => openInspector("changes", e.currentTarget) }, icon("diff", "sm"), "View changes")));
  };
  W.hooks.build = (c) => { if (S.tab === "agent" && !S.global && el.isConnected) upd(c); };
  watchTask(tid); upd();
}

// ---------- research ----------
async function renderResearch() {
  const pid = S.project.id; setActivity("Notebook");
  const nb = await api("GET", `/api/projects/${pid}/notebook`);
  const atts = (await api("GET", `/api/projects/${pid}/attachments`));
  const url = h("input", { type: "url", placeholder: "https://…", "aria-label": "Public source URL", class: "grow" });
  const attSel = h("select", { "aria-label": "Local document", class: "grow" }, h("option", { value: "" }, "— local document —"), ...atts.map((a) => h("option", { value: a.id }, a.name)));
  const srcSel = h("select", { "aria-label": "Source for finding", class: "grow" }, h("option", { value: "" }, "— no source (unsupported) —"), ...nb.sources.map((s, i) => h("option", { value: s.id }, `[${i + 1}] ${s.title.slice(0, 60)}`)));
  const claim = h("textarea", { "aria-label": "Finding", placeholder: "What does the source support?" });
  const loc = h("input", { placeholder: "Locator: section, page, line or quote", "aria-label": "Locator", class: "grow" });
  const lim = h("input", { placeholder: "Limitation (optional)", "aria-label": "Limitation", class: "grow" });
  const q = h("input", { type: "search", placeholder: "Search this project… (Enter)", "aria-label": "Search project", class: "grow" });
  const results = h("div", { class: "section" });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") guard(async () => { const r = await api("GET", `/api/projects/${pid}/search?q=${encodeURIComponent(q.value)}`); results.replaceChildren(...(r.length ? r.map((x) => h("div", { class: "card" }, h("div", { class: "row" }, statePill(x.type), h("strong", {}, x.title)), h("pre", { class: "out" }, x.snippet))) : [empty("search", "No matches", "Nothing in this project matched that search.")])); }); });
  $("view").replaceChildren(
    h("div", { class: "row" }, q, h("a", { class: "btn ghost", href: `/api/projects/${pid}/notebook/export?private=0` }, icon("download"), "Export (public sources only)"), h("a", { class: "btn ghost", href: `/api/projects/${pid}/notebook/export?private=1` }, icon("download"), "Export incl. private")),
    results,
    h("div", { class: "grid2" },
      h("div", { class: "card" }, h("div", { class: "ttl" }, icon("link"), h("h2", {}, "Add a source")),
        h("p", { class: "muted" }, "Public pages are fetched from public addresses only. Local documents stay private unless you export them."),
        h("div", { class: "row" }, url, btn("Fetch public page", () => guard(async () => { banner("Fetching (public addresses only)…"); const s = await api("POST", `/api/projects/${pid}/notebook/sources`, { url: url.value }); banner(`Source ${s.status}: ${s.title}`, s.status === "read" ? "ok" : "bad"); renderResearch(); }), "", "download")),
        h("div", { class: "row" }, attSel, btn("Add local document", () => guard(async () => { if (!attSel.value) return; await api("POST", `/api/projects/${pid}/notebook/sources`, { attachment_id: attSel.value }); renderResearch(); }), "", "file"))),
      h("div", { class: "card" }, h("div", { class: "ttl" }, icon("note"), h("h2", {}, "Record a finding")), claim, h("div", { class: "row" }, srcSel), h("div", { class: "row" }, loc, lim),
        h("div", { class: "row end" }, btn("Save finding", () => guard(async () => { await api("POST", `/api/projects/${pid}/notebook/findings`, { claim: claim.value, source_id: srcSel.value || null, locator: loc.value, limitation: lim.value }); renderResearch(); }), "primary", "check")))),
    section("Findings", "Each claim is tied to a numbered source and locator, or marked unsupported.",
      nb.findings.length ? table(["Claim", "Source", "Locator", "Status", "Limitation"], nb.findings.map((f) => { const i = nb.sources.findIndex((s) => s.id === f.source_id); return h("tr", {}, h("td", { class: "wrap" }, f.claim), h("td", {}, i >= 0 ? `[${i + 1}]` : "—"), h("td", {}, f.locator || ""), h("td", {}, statePill(f.status)), h("td", {}, f.limitation || "")); }))
        : empty("note", "No findings yet", "Record what a source supports, with a locator, so it can be cited and checked later.")),
    section("Sources", null,
      nb.sources.length ? table(["#", "Title", "Publisher", "Locator", "Retrieved", "Status", "Visibility"], nb.sources.map((s, i) => h("tr", {}, h("td", { class: "num" }, i + 1), h("td", { class: "wrap" }, s.title), h("td", {}, s.publisher || ""), h("td", {}, s.locator), h("td", {}, fmtTime(s.retrieved_at)), h("td", {}, statePill(s.status)), h("td", {}, h("span", { class: "tag" }, s.private ? "private" : "public")))))
        : empty("link", "No sources yet", "Add a public page or a local document to start the research notebook.")));
}

// ---------- memory ----------
async function renderMemory() {
  const pid = S.project.id;
  const mem = await api("GET", `/api/projects/${pid}/memory`);
  setActivity(`${mem.length} record(s)`);
  const content = h("textarea", { "aria-label": "Memory content", placeholder: "Constraint, decision or state to remember for this project" });
  const layer = h("select", { "aria-label": "Layer" }, h("option", { value: "authoritative" }, "Authoritative record"), h("option", { value: "derived" }, "Derived summary (needs source IDs)"));
  const srcs = h("input", { placeholder: "Source record IDs, comma-separated", "aria-label": "Source IDs", class: "grow" });
  const act = (m, op, body) => guard(async () => { await api("POST", `/api/projects/${pid}/memory/${m.id}/${op}`, body); renderMemory(); });
  const groups = ["authoritative", "derived", "shared"];
  const titles = { authoritative: "Authoritative records", derived: "Derived working summaries", shared: "Promoted shared knowledge" };
  const desc = { authoritative: "Source of truth for this project.", derived: "Summaries that cite the records they came from.", shared: "Explicitly promoted; visible beyond this project." };
  $("view").replaceChildren(h("div", { class: "card" }, h("div", { class: "ttl" }, icon("layers"), h("h2", {}, "Add to project memory")),
    h("p", { class: "muted" }, "Memory belongs to this project only. Shared knowledge needs an explicit promotion. Corrections supersede old records but keep them for provenance."),
    content, h("div", { class: "row" }, layer, srcs),
    h("div", { class: "row between" }, h("a", { class: "btn ghost", href: `/api/projects/${pid}/context-packet` }, icon("eye"), "View context packet"),
      btn("Save", () => guard(async () => { await api("POST", `/api/projects/${pid}/memory`, { layer: layer.value, kind: "note", content: content.value, source_ids: srcs.value.split(",").map((s) => s.trim()).filter(Boolean) }); renderMemory(); }), "primary", "check"))),
    ...groups.map((g) => { const rows = mem.filter((m) => m.layer === g); return section(titles[g], desc[g],
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
  const pid = S.project.id;
  const arts = await api("GET", `/api/projects/${pid}/artifacts`);
  setActivity(`${arts.length} item(s)`);
  $("view").replaceChildren(h("div", { class: "row between" }, h("div", { class: "section-head" }, h("h2", {}, "Saved items", h("span", { class: "count" }, String(arts.length)))),
    h("div", { class: "row" }, h("a", { class: "btn primary", href: `/api/projects/${pid}/export` }, icon("download"), "Export project (JSON)"),
      btn("Archive project", () => guard(async () => { const v = await dialog("Archive project?", [{ name: "confirm", label: `Type the project name (${S.project.name}) to hide it. Files in the folder are never deleted.`, required: true }], "Archive"); if (!v || v.confirm !== S.project.name) return; await api("POST", `/api/projects/${pid}/archive`); S.project = null; stopWatch(); renderHeader(); await loadProjects(); renderWelcome(); }), "danger", "archive"))),
    ...(arts.length ? arts.map((a) => h("details", { class: "card" }, h("summary", {}, statePill(a.kind), h("span", { class: "st" }, a.title), h("span", { class: "faint" }, fmtTime(a.created)),
      h("button", { type: "button", class: "linkish", onclick: (e) => { e.preventDefault(); S.preview = a.id; openInspector("preview", e.currentTarget); } }, icon("eye", "sm"), "Preview")), h("pre", { class: "out" }, a.content)))
      : [empty("bookmark", "Nothing saved yet", "Save chat answers or task results to keep them here.")]));
}

// ---------- global views ----------
async function openGlobal(which) {
  S.global = which; clearInterval(S.poll); markNav(); renderHeader();
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => b.setAttribute("aria-selected", "false"));
  document.querySelectorAll("#projectList button").forEach((b) => b.setAttribute("aria-current", "false"));
  if (which === "providers") return guard(renderProviders);
  return guard(() => renderEvidence());
}
function goSpend() { openGlobal("evidence").then(() => { const el = $("spend"); if (el) { el.scrollIntoView({ block: "start" }); const i = el.querySelector("input"); if (i) i.focus({ preventScroll: true }); } }); }
async function renderProviders() {
  const entries = Object.entries(S.routes);
  $("view").replaceChildren(h("div", { class: "row between" }, h("div", { class: "section-head" }, h("h2", {}, "Provider routes", h("span", { class: "count" }, String(entries.length)))),
    btn("Re-verify", () => guard(async () => { banner("Re-verifying via each official CLI…"); S.routes = await api("POST", "/api/routes/refresh"); renderProviders(); if (S.project) renderHeader(); banner("Routes re-verified.", "ok"); }), "primary", "refresh")),
    h("div", { class: "note info" }, icon("shield"), h("span", {}, "States come from each official CLI's own status command. Studio never reads credential files. Handoff routes are not counted as in-app integrations.")),
    entries.length ? h("div", { class: "grid3" }, ...entries.map(([id, r]) => {
      const metered = isMetered(r) || id === "openai-api";
      return h("article", { class: "card route" },
        h("div", { class: "rhead" }, h("span", { class: "rico av" + hashIdx(id, 8), "aria-hidden": "true" }, initials(r.provider || id)),
          h("div", { class: "rname" }, h("h3", {}, id), h("p", {}, r.provider)), statePill(r.state)),
        h("div", { class: "tags" }, routeTag(r), ...(r.supported_modes || []).map((m) => h("span", { class: "tag" }, m))),
        h("dl", {}, h("dt", {}, "Version"), h("dd", {}, r.version || "—"), h("dt", {}, "Billing"), h("dd", {}, r.billing_basis || "—"),
          h("dt", {}, "Incremental cost"), h("dd", {}, r.incremental_cost_status || "—"), h("dt", {}, "Verified"), h("dd", {}, fmtTime(r.last_verified_at))),
        h("div", { class: "ev" }, h("span", {}, h("b", {}, "Evidence: "), r.evidence || "—"), r.limitations ? h("span", {}, h("b", {}, "Limitations: "), r.limitations) : null),
        r.state === "READY_METERED_DISABLED" ? h("div", { class: "note" }, icon("info"), h("span", {}, "Not selectable until a monthly operating limit is set.")) : null,
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
  const e = await api("GET", "/api/evidence");
  const b = budgetOverride || e.budget; const totalCap = e.allocation.reduce((s, a) => s + a.cap, 0); const maxCap = Math.max(1, ...e.allocation.map((a) => a.cap));
  const m = { label: h("input", { "aria-label": "Workflow label", placeholder: "Label" }), workflow: h("select", { "aria-label": "Workflow" }, h("option", { value: "native" }, "Previous native workflow"), h("option", { value: "studio" }, "Aesop Studio")),
    elapsed_s: h("input", { type: "number", "aria-label": "Elapsed seconds", placeholder: "seconds" }), manual_steps: h("input", { type: "number", "aria-label": "Manual steps", placeholder: "steps" }), app_switches: h("input", { type: "number", "aria-label": "App switches", placeholder: "switches" }) };

  const limitIn = h("input", { type: "number", min: "0", step: "0.01", id: "limitIn", value: typeof b.runtime_limit === "number" ? String(b.runtime_limit) : "", placeholder: "0.00", class: "grow" });
  const saveLimit = () => { const n = Number(limitIn.value); if (limitIn.value === "" || !isFinite(n) || n < 0) { banner("Enter a monthly operating limit of 0 or more (USD).", "bad"); return; } postBudget({ runtime_limit_usd: n }, `Monthly operating limit set to ${usd(n)}.`); };
  limitIn.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); saveLimit(); } });
  const permitOn = !!b.permit;
  const sw = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": permitOn ? "true" : "false", "aria-labelledby": "permitLbl", "aria-describedby": "permitDesc",
    onclick: () => postBudget({ mission_permit: !permitOn }, `Mission development permit turned ${!permitOn ? "on" : "off"}.`) }, h("span", { class: "knob" }));
  const spend = h("div", { class: "card", id: "spend" },
    h("div", { class: "ttl" }, icon("dollar"), h("h2", {}, "Spend controls")),
    h("div", { class: "grid2" },
      h("div", { class: "section" }, h("label", { for: "limitIn" }, "Monthly operating limit (USD)"),
        h("div", { class: "row" }, limitIn, btn("Save", saveLimit, "primary", "check")),
        h("p", { class: "muted" }, "Caps separately billed API spend for normal use this calendar month. Metered routes stay disabled until a limit is set.")),
      h("div", { class: "section" }, h("div", { class: "row between" }, h("span", { id: "permitLbl" }, h("label", {}, "Mission development permit")), h("div", { class: "row" }, h("span", { class: "muted" }, permitOn ? "On" : "Off"), sw)),
        h("p", { class: "muted", id: "permitDesc" }, "Lets Studio bill the $165 mission envelope for OpenAI development tests. Turned off automatically every time Studio restarts."))),
    // Cancelled or cut-off API calls keep their reservation as unresolved exposure until the owner enters the real charge.
    ...(() => {
      const amb = (e.ledger || []).filter((r) => r.status === "ambiguous");
      if (!amb.length) return [];
      return [h("div", { class: "section" }, h("h3", {}, `Unresolved exposure (${amb.length})`),
        h("p", { class: "muted" }, "These calls stopped before OpenAI reported usage, so their full reservation is still held. Check the OpenAI usage dashboard and enter the real charge."),
        ...amb.map((r) => h("div", { class: "row between" },
          h("span", {}, `${r.route} · ${r.purpose} · reserved ${fmtCost(r.reservation_usd)} · ${fmtTime(r.created)}`),
          btn("Resolve", async () => {
            const v = await dialog("Resolve unresolved exposure", [{ name: "actual_usd", label: "Actual charge from the OpenAI usage dashboard (USD)", required: true, value: "", placeholder: "e.g. 0.00004" },
              { name: "note", label: "Note (optional)", value: "" }], "Resolve");
            if (!v) return;
            const amt = Number(String(v.actual_usd).trim()); if (!isFinite(amt) || amt < 0) { banner("Enter the actual charge in USD, 0 or more.", "bad"); return; }
            await guard(async () => { await api("POST", `/api/ledger/${r.id}/resolve`, { actual_usd: amt, note: v.note }); banner("Exposure resolved from the usage dashboard.", "ok"); renderEvidence(); });
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
        tile("Open repair packets", String(e.tasks.repairs.filter((r) => r.status.startsWith("OPEN")).length), null, "small")),
      Object.keys(e.tasks.by_state).length ? h("div", { class: "row" }, ...Object.entries(e.tasks.by_state).map(([s, n]) => statePill(`${s}: ${n}`))) : null,
      e.tasks.total ? null : h("p", { class: "muted" }, "No runs yet. Counts appear after real use."),
      e.tasks.repairs.length ? table(["Repair", "Task", "Signature", "Contract", "Status", ""], e.tasks.repairs.map((r) => h("tr", {}, h("td", {}, h("code", {}, r.id)), h("td", {}, r.task_id), h("td", { class: "wrap" }, r.signature), h("td", {}, r.contract), h("td", {}, statePill(r.status)),
        h("td", {}, h("button", { class: "linkish", type: "button", onclick: () => guard(async () => { const x = await api("POST", `/api/repairs/${r.id}/export`); banner(`${x.note} ${x.packet}`, "ok"); renderEvidence(); }) }, "Export packet")))), "Repair packets (Foreman). Studio never replays or repairs automatically.") : null),
    section("Provider latency (completed runs)", "Provider wait measured from process start to exit. Small samples are shown individually; no confidence claims.",
      e.latency.length ? table(["Route/mode", "n", "Median s", "Min", "Max", "Last samples"], e.latency.map((l) => h("tr", {}, h("td", {}, l.route), h("td", { class: "num" }, l.n), h("td", { class: "num" }, l.median_s), h("td", { class: "num" }, l.min_s), h("td", { class: "num" }, l.max_s), h("td", {}, l.samples.join(", ")))))
        : h("p", { class: "muted" }, "No completed runs yet.")),
    section("Workflow measurements", "Record the same task done the old way and in Studio. Without owner trials, any time saving stays unverified; no time-saving claim is made here.",
      h("div", { class: "card" }, h("div", { class: "measure" }, m.label, m.workflow, m.elapsed_s, m.manual_steps, m.app_switches, btn("Record", () => guard(async () => { await api("POST", "/api/workflow-measure", Object.fromEntries(Object.entries(m).map(([k, el]) => [k, el.value]))); renderEvidence(); }), "", "plus"))),
      e.workflow.length ? table(["Label", "Workflow", "Seconds", "Steps", "App switches", "When"], e.workflow.map((w) => h("tr", {}, h("td", {}, w.label || ""), h("td", {}, w.workflow || ""), h("td", { class: "num" }, w.elapsed_s || ""), h("td", { class: "num" }, w.manual_steps || ""), h("td", { class: "num" }, w.app_switches || ""), h("td", {}, fmtTime(w.at)))))
        : h("p", { class: "muted" }, "No measurements recorded.")),
    e.research.length ? section("Research background", "External studies are background, not Aesop Studio results.",
      table(["Source", "Context", "Method", "Result", "Limitations", "Decision"], e.research.map((r) => h("tr", {}, h("td", {}, h("a", { href: r.url, rel: "noopener noreferrer", target: "_blank" }, r.source)), h("td", { class: "wrap" }, r.context), h("td", { class: "wrap" }, r.method), h("td", { class: "wrap" }, r.result), h("td", { class: "wrap" }, r.limitations), h("td", { class: "wrap" }, r.decision))))) : null,
    section("Backup", "Archives Studio data locally; the restore test unpacks the latest backup into a separate folder.",
      h("div", { class: "row" }, btn("Create backup", () => guard(async () => { const r = await api("POST", "/api/backup"); banner(`Backup written: ${r.archive}`, "ok"); }), "", "db"),
        btn("Test restore of latest backup", () => guard(async () => { const r = await api("POST", "/api/backup/verify"); banner(r.ok ? `Restore test passed in ${r.target}. ${r.reauth}` : `Restore test FAILED: ${JSON.stringify(r)}`, r.ok ? "ok" : "bad"); }), "", "refresh"))));
}

boot();

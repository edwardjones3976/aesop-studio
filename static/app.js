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
  panel: "M3 4h18v16H3zM15 4v16", users: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8", diff: "M12 3v12M6 9h12M6 21h12", list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
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
// Owner naming rule: routes are always titled by display_name (e.g. "Codex API"), never by raw route ids.
function routeName(id) { const r = id && S.routes[id]; return r && r.display_name ? r.display_name : id || ""; }
function routeLabel(route) { const [rid, ...rest] = String(route || "").split("/"); return routeName(rid) + (rest.length ? " · " + rest.join("/") : ""); }
function routeTag(r) { return r ? h("span", { class: "tag " + (isMetered(r) ? "billed" : "route") }, access(r.state)) : null; }

// Origin key: delivered once in the launch redirect fragment, kept in sessionStorage, sent on every API call.
function takeKey() {
  const m = /(?:^#|&)k=([^&]+)/.exec(location.hash || "");
  if (m) {
    try { sessionStorage.setItem("aesop.key", decodeURIComponent(m[1])); } catch { /* storage blocked */ }
    try { history.replaceState(null, "", location.pathname + location.search); } catch { /* ignore */ }
  }
}
function apiKey() { try { return sessionStorage.getItem("aesop.key") || ""; } catch { return ""; } }
function signInCard() {
  navBump();
  $("view").replaceChildren(h("div", { class: "empty welcome" }, h("div", { class: "eico" }, icon("shield")), h("div", { class: "et" }, h("strong", {}, "Sign-in needed"),
    h("p", {}, "Reopen Studio from its launch link (start.ps1 opens one for you). This keeps other websites and local programs from using your Studio."))));
}
function authFail() { signInCard(); banner("Studio session not recognised. Reopen Studio from its launch link.", "bad"); }
async function api(method, path, body, raw) {
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
    [["Ctrl", "3"], "Research"], [["Esc"], "Close a dialog, drawer or sheet"], [["?"], "Show this list"], [["←", "→"], "Resize a focused panel divider"]];
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
  el.setAttribute("title", p.provider_default ? `${routeName(p.provider_default)}: ${r ? r.state : "unknown"}` : "No default provider chosen");
  el.replaceChildren(p.provider_default ? routeDot(p.provider_default) : h("span", { class: "dot" }), h("b", {}, routeName(p.provider_default) || "No provider"),
    h("span", { class: "rt" }, r ? access(r.state) : p.provider_default ? "unavailable" : "choose one in the workspace header"));
}

// ---------- command palette ----------
let PAL = { items: [], sel: 0, opener: null };
function paletteItems() {
  const it = [];
  if (S.project) for (const [k, v] of Object.entries(WS)) it.push({ g: "Workspace", ico: { chat: "chat", agent: "terminal", research: "search", memory: "layers", artifacts: "bookmark" }[k], label: `Go to ${v}`, key: { chat: "Ctrl 1", agent: "Ctrl 2", research: "Ctrl 3" }[k], run: () => setTab(k) });
  for (const p of S.projects) it.push({ g: "Project", ico: "folder", label: `Switch to ${p.name}`, hint: p.root, run: () => openProject(p.id) });
  it.push({ g: "Action", ico: "plus", label: "New project", run: newProject });
  if (S.project) it.push({ g: "Action", ico: "users", label: "Configure roundtable", run: () => openRoundtable(PAL.opener) });
  if (S.project) it.push({ g: "Action", ico: "chat", label: "New conversation", run: () => { const pid = S.project.id; guard(async () => { const c = await api("POST", `/api/projects/${pid}/conversations`, {}); if (S.project && S.project.id === pid) { S.conv = c.id; setTab("chat"); } }); } });
  it.push({ g: "Studio", ico: "providers", label: "Open Providers", run: () => openGlobal("providers") });
  it.push({ g: "Studio", ico: "evidence", label: "Open Evidence", run: () => openGlobal("evidence") });
  it.push({ g: "View", ico: "panel", label: "Toggle inspector", run: () => toggleInspector($("inspectorBtn")) });
  for (const t of ["preview", "files", "changes", "terminal", "logs"]) it.push({ g: "View", ico: "panel", label: `Inspector: ${t[0].toUpperCase() + t.slice(1)}`, run: () => openInspector(t, $("inspectorBtn")) });
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
const RT_NOT_LIVE = "Live roundtables are switched off (Evidence → Spend controls).";
const LIVE_END = ["COMPLETED", "STOPPED", "FAILED", "INTERRUPTED"];
let RT = null;

function rtBlank() {
  return { mode: "general", objective: "", deliverable: "", outcome_type: RT_OUTCOMES[0], time_limit_min: 15, response_window_s: 30,
    max_turns: "", max_msgs: "", cost_cap: "", ack: false, roster: new Set() };
}
function rtFromRecord(r) {
  const mode = RT_TIME[r.mode] ? r.mode : "general"; const c = r.caps || {};
  const s = (v) => (v === null || v === undefined ? "" : String(v));
  return { mode, objective: r.objective || "", deliverable: r.deliverable || "", outcome_type: r.outcome_type || RT_OUTCOMES[0],
    time_limit_min: r.time_limit_min || RT_TIME[mode][1], response_window_s: r.response_window_s || 30,
    max_turns: s(c.max_turns), max_msgs: s(c.max_messages_per_speaker), cost_cap: s(c.cost_cap_usd), ack: !!r.sharing_ack,
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
    clearTimeout(RT.timer); const o = RT.opener; RT = null;
    if (o && o.isConnected && o.focus) o.focus();
  });
}
async function openRoundtable(opener) {
  if (!S.project) { banner("Open a project first to configure a roundtable."); return; }
  if ($("dlg").open || $("rtDlg").open) return;
  closeOverlay(false);
  const s = RT = { opener: opener || document.activeElement, pid: S.project.id, lanes: [], gates: [], example: [], discovered: null, drafts: [], rec: null, pre: null, preStale: false,
    f: rtBlank(), filter: "all", q: "", timer: null, loading: true, err: "", el: {}, gen: 0 };
  rtBuild(); $("rtDlg").showModal(); $("rtObjective").focus();
  try {
    const [lanes, drafts] = await Promise.all([api("GET", "/api/roundtable/lanes"), api("GET", `/api/projects/${s.pid}/roundtables`)]);
    if (RT !== s) return;
    s.lanes = lanes.lanes || []; s.gates = lanes.mission_gates || []; s.example = lanes.documented_example || [];
    s.discovered = lanes.discovered_at || null; s.live = !!lanes.live_authorized; s.drafts = Array.isArray(drafts) ? drafts : [];
  } catch (e) { if (RT === s) s.err = e.message; }
  if (RT !== s) return;
  s.loading = false; rtLanesRender(); rtRefresh(); rtGatesRender(); rtSideRender(); rtDraftsRender(); rtStartRender();
}
// Any edit after a preflight makes its pass/fail list out of date until the next check.
function rtStale() { if (RT && RT.pre && !RT.preStale) { RT.preStale = true; rtSideRender(); rtStartRender(); } }
// Buttons that start a request are disabled until it settles, so double clicks never send twice.
function abtn(label, fn, cls = "", ico) {
  const b = btn(label, async (e) => {
    if (b.disabled) return;
    b.disabled = true; b.setAttribute("aria-busy", "true");
    try { await fn(e); } finally { b.disabled = false; b.removeAttribute("aria-busy"); }
  }, cls, ico);
  return b;
}
function rtBuild(focusId) {
  const f = RT.f; const el = RT.el = {};
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
  const part = h("section", { class: "rt-col rt-part", "aria-labelledby": "rtPartH" }, h("h3", { id: "rtPartH" }, "Participants"),
    h("div", { class: "field" }, h("label", { for: "rtSearch", class: "sr-only" }, "Search lanes"), search), filters, el.counter, el.lanes, el.example);
  // centre
  el.gates = h("div");
  const modeTabs = h("div", { class: "seg rt-mode", role: "tablist", "aria-label": "Roundtable mode" }, ...Object.entries(RT_MODES).map(([k, label]) => h("button", { type: "button", role: "tab", id: "rtMode-" + k,
    "aria-selected": f.mode === k ? "true" : "false", tabindex: f.mode === k ? "0" : "-1", onclick: () => rtSetMode(k),
    onkeydown: (e) => { if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); rtSetMode(k === "general" ? "war_room" : "general"); } } }, label)));
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
  const main = h("section", { class: "rt-col rt-main", "aria-label": "Roundtable setup" }, el.gates, modeTabs,
    fld("rtObjective", "Objective (required)", objective),
    h("div", { class: "rt-row2" }, fld("rtOutcome", "Outcome type", outcome), fld("rtDeliverable", "Desired deliverable", deliverable)),
    h("div", { class: "rt-row3" }, fld("rtTime", f.mode === "war_room" ? "Time limit (War Room)" : "Time limit", time), win ? fld("rtWindow", "Response window", win) : null),
    h("fieldset", { class: "rt-caps" }, h("legend", {}, "Caps"), h("div", { class: "rt-row3" }, fld("rtTurns", "Max turns", num("rtTurns", "max_turns", "e.g. 12")),
      fld("rtMsgs", "Max messages per speaker", num("rtMsgs", "max_msgs", "e.g. 3")), fld("rtCost", "Cost cap (USD)", num("rtCost", "cost_cap", "0.00", "0.01")))),
    h("section", { class: "card rt-share", "aria-labelledby": "rtShareH" }, h("h3", { id: "rtShareH" }, "External-sharing preview"),
      h("p", { class: "muted" }, "This is exactly what would leave this machine, and who would receive it. Changing the objective or the roster clears your confirmation."),
      el.sharePrev, h("label", { class: "rt-ack", for: "rtAck" }, el.ack, h("span", {}, "I've reviewed what would be shared"))),
    h("p", { class: "note info" }, icon("info"), h("span", {}, "Manual side-by-side comparison isn't available in this build.")),
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
    h("div", { class: "row" }, abtn("Save draft", () => rtSave(false), "primary", "check"), abtn("Check preflight", rtPreflight, "", "shield"), el.exportBtn),
    h("div", { class: "rt-startgrp" }, start, el.startWhy));
  $("rtIn").replaceChildren(
    h("header", { class: "rt-head" }, h("div", { class: "ttl" }, icon("users"), h("div", {}, h("h2", { id: "rtTitle" }, "Configure Roundtable"),
      (el.liveNote = h("p", { class: "faint" })))),
      h("button", { type: "button", class: "iconbtn", "aria-label": "Close roundtable", onclick: () => $("rtDlg").close() }, icon("x"))),
    h("div", { id: "rtStatus", class: "rt-status", role: "status", "aria-live": "polite" }),
    (el.body = h("div", { class: "rt-body" }, (el.part = part), main, el.side)), (el.foot = foot));
  rtLanesRender(); rtRefresh(); rtGatesRender(); rtSideRender(); rtStartRender(); rtDraftsRender();
  if (focusId && $(focusId)) $(focusId).focus();
}
function rtSetMode(m) {
  const f = RT.f; if (f.mode === m) return;
  f.mode = m;
  const [opts, def] = RT_TIME[m]; if (!opts.includes(Number(f.time_limit_min))) f.time_limit_min = def;
  if (m === "war_room") { const before = f.roster.size; for (const id of [...f.roster]) { const l = rtLane(id); if (!l || l.lane_class !== "admin") f.roster.delete(id); } if (f.roster.size !== before) f.ack = false; }
  if (RT.pre) RT.preStale = true;
  rtBuild("rtMode-" + m);
  rtSay(`${RT_MODES[m]} selected. Default time ${def} min${m === "war_room" ? "; only admin lanes can take part" : ""}.`);
}
function rtResetAck() { if (RT.f.ack) { RT.f.ack = false; if (RT.el.ack) RT.el.ack.checked = false; } }
function rtLanesRender() {
  const el = RT.el;
  el.example.textContent = RT.example.length ? `Documented example roster: ${RT.example.join(", ")}` : "";
  if (RT.loading) { el.lanes.replaceChildren(h("p", { class: "muted" }, "Checking lanes…")); return; }
  if (RT.err) { el.lanes.replaceChildren(h("div", { class: "note bad" }, icon("alert"), h("span", {}, `Lanes could not be loaded: ${RT.err}`))); return; }
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
    sel.length ? h("ul", { class: "rt-recips" }, ...sel.map((l) => h("li", {}, h("strong", {}, l.name), ` · ${l.route_type || "no route"} · ${RT_CLASS[l.lane_class] || l.lane_class}`))) : h("p", { class: "muted" }, "No lanes selected; nothing would be shared."));
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
  RT.el.liveNote.textContent = RT.live ? "Live roundtables are switched on. Start runs a brokered, time-boxed session once preflight passes." : "Live roundtables are switched off (Evidence → Spend controls). You can still plan and save drafts.";
  const ok = rtCanStart();
  RT.el.start.setAttribute("aria-disabled", ok ? "false" : "true");
  RT.el.start.classList.toggle("primary", ok);
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
      r.live_status && r.live_status !== "DRAFT" ? abtn(LIVE_END.includes(r.live_status) ? "View record" : "Open room", () => rtRoom(r.id, LIVE_END.includes(r.live_status)), "ghost sm", "chat") : null)))
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
    sharing_ack: !!f.ack, caps: { max_turns: num(f.max_turns), max_messages_per_speaker: num(f.max_msgs), cost_cap_usd: num(f.cost_cap) } };
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
// @mentions and [E#] references become highlighted spans; everything stays textContent.
function rtText(t) {
  const out = []; const re = /(@[\w.-]+|\[E\d+\])/g; let last = 0; let m;
  while ((m = re.exec(t))) {
    if (m.index > last) out.push(t.slice(last, m.index));
    out.push(h("span", { class: m[1][0] === "@" ? "mention" : "eref" }, m[1]));
    last = m.index + m[1].length;
  }
  if (last < t.length) out.push(t.slice(last));
  return out;
}
function rtEvent(ev, sps) {
  const sp = sps[ev.speaker]; const name = sp ? sp.name : ev.speaker || (ev.kind === "system" ? "Studio" : ev.kind);
  return h("li", { class: "ev ev-" + ev.kind },
    h("div", { class: "evh" }, h("code", {}, ev.label || `E${ev.seq}`), h("strong", {}, name), ev.kind === "gap" ? h("span", { class: "pill warn" }, "gap") : null,
      ev.phase ? h("span", { class: "tag" }, ev.phase) : null, ev.latency_s != null ? h("span", {}, `${ev.latency_s}s`) : null,
      ev.seen_label ? h("span", {}, `saw up to ${ev.seen_label}`) : null),
    h("div", { class: "evb" }, ...rtText(String(ev.content || ""))));
}
function rtCoverage(c) {
  if (!c) return h("p", { class: "muted" }, "No coverage summary was returned.");
  if (typeof c === "string") return h("div", { class: "note" }, icon("info"), h("span", {}, c));
  const valid = c.valid; const text = c.summary || "";
  return h("div", { class: "note " + (valid === true ? "ok" : "bad"), role: "status" }, icon(valid === true ? "check" : "alert"), h("div", { class: "section" },
    h("strong", {}, valid === true ? "Coverage: valid roundtable" : valid === false ? "Coverage: NOT a valid four-provider roundtable" : "Coverage summary"),
    text ? h("p", {}, text) : null));
}
// The room replaces the modal's centre and right columns; the feed is append-only and polled every second.
function rtRoom(id, readOnly) {
  const s = RT; if (!s) return;
  clearTimeout(s.timer); const gen = ++s.gen;
  const room = { after: 0 };
  const clock = h("span", { class: "rt-clock" }, "—"); const stPill = h("span");
  const chips = h("div", { class: "rt-chips", "aria-label": "Speakers" });
  const feed = h("ol", { class: "rt-feed", "aria-label": "Roundtable feed", tabindex: "0" });
  const announce = h("div", { class: "sr-only", "aria-live": "polite" });
  const memo = h("div", { class: "section" }); const cov = h("div");
  const ctl = (label, op, ico) => abtn(label, async () => {
    try { const r = await api("POST", `/api/roundtables/${id}/${op}`); if (RT === s) rtSay(`${label}: ${(r.status && r.status.live_status) || r.live_status || r.status || "requested"}.`); }
    catch (e) { if (RT === s) rtSay(e.message, "bad"); }
  }, "sm", ico);
  const pauseBtn = ctl("Pause", "pause", "clock"), resumeBtn = ctl("Resume", "resume", "send"), stopBtn = ctl("Stop", "stop", "stop");
  stopBtn.classList.add("danger");
  const exportBtn = abtn("Export record", async () => { try { await download(`/api/roundtables/${id}/record`, `roundtable-record-${id}.json`); } catch (e) { rtSay(e.message, "bad"); } }, "sm", "download");
  const back = btn("Back to setup", () => { clearTimeout(s.timer); s.gen++; rtBuild(); }, "ghost sm");
  pauseBtn.hidden = resumeBtn.hidden = stopBtn.hidden = true;
  const main = h("section", { class: "rt-col rt-main rt-room", "aria-label": "Live room" },
    h("div", { class: "card-head" }, h("div", { class: "ttl" }, h("h3", {}, readOnly ? "Roundtable record" : "Live room"), stPill), clock),
    chips, h("div", { class: "row" }, pauseBtn, resumeBtn, stopBtn, exportBtn, back), cov, feed, announce);
  const side = h("section", { class: "rt-col rt-side", "aria-label": "Memo" }, memo);
  s.el.body.replaceChildren(s.el.part, main, side); s.el.foot.hidden = true;
  memo.replaceChildren(h("h3", {}, "Memo"), h("p", { class: "muted" }, "The memo appears here when the session writes one."));
  let pending = 0, lastSay = 0, memoSig = "";
  const tick = async () => {
    if (RT !== s || s.gen !== gen) return;
    let d;
    try { d = await api("GET", `/api/roundtables/${id}/live?after=${room.after}`); }
    catch (e) { if (RT === s && s.gen === gen) { rtSay(e.message, "bad"); s.timer = setTimeout(tick, 3000); } return; }
    if (RT !== s || s.gen !== gen) return;
    const st = d.status || {}; const sps = st.speakers || {};
    const stick = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
    for (const ev of d.events || []) { if (ev.seq <= room.after) continue; room.after = ev.seq; feed.append(rtEvent(ev, sps)); pending++; }
    if (stick) feed.scrollTop = feed.scrollHeight;
    if (pending && Date.now() - lastSay > 4000) { announce.textContent = `${pending} new item${pending > 1 ? "s" : ""} in the roundtable feed.`; pending = 0; lastSay = Date.now(); }
    clock.textContent = `${fmtS(st.elapsed_s)} elapsed · ${fmtS(st.remaining_s)} left of ${fmtS(st.limit_s)}`;
    stPill.replaceChildren(statePill(st.live_status || "—"));
    chips.replaceChildren(...Object.entries(sps).map(([k, v]) => h("span", { class: "rt-chip" }, h("span", { class: "dot " + (SP_TONE[v.state] || ""), "aria-hidden": "true" }), h("strong", {}, v.name || k),
      h("span", {}, SP_LABEL[v.state] || v.state || "unknown"),
      h("span", { class: "faint" }, `${v.turns || 0} turns${v.last_latency_s != null ? ` · ${v.last_latency_s}s` : ""}${typeof v.cost_usd === "number" ? ` · ${fmtCost(v.cost_usd)}` : ""}`))));
    const ms = st.memo ? (typeof st.memo === "string" ? st.memo : JSON.stringify(st.memo, null, 1)) : "";
    if (ms && ms !== memoSig) { memoSig = ms; memo.replaceChildren(h("h3", {}, "Memo"), h("pre", { class: "out" }, ms)); }
    const ended = LIVE_END.includes(st.live_status);
    const focused = document.activeElement;
    pauseBtn.hidden = readOnly || ended || st.live_status === "PAUSED";
    resumeBtn.hidden = readOnly || ended || st.live_status !== "PAUSED";
    stopBtn.hidden = readOnly || ended;
    if (focused && focused.hidden) [resumeBtn, pauseBtn, exportBtn].find((b) => !b.hidden).focus();
    if (ended) { cov.replaceChildren(rtCoverage(st.coverage)); rtSay(`Session ${st.live_status.toLowerCase()}.`); return; }
    s.timer = setTimeout(tick, 1000);
  };
  tick();
}
async function rtOpenDraft(id) {
  const s = RT; if (!s) return;
  const gen = ++s.gen; // invalidates any save or preflight still in flight for the previous draft
  try {
    const rec = await api("GET", `/api/roundtables/${id}`);
    if (RT !== s || s.gen !== gen) return;
    clearTimeout(s.timer);
    s.rec = rec; s.f = rtFromRecord(rec); s.pre = rec.preflight || null; s.preStale = false;
    rtBuild("rtObjective");
    rtSay(`Opened draft ${rec.id}.`);
  } catch (e) { if (RT === s) rtSay(e.message, "bad"); }
}

// ---------- boot ----------
// Navigation token: every project/view switch bumps navGen and viewGen. Async work checks its token before touching state or the DOM.
S.navGen = 0; S.viewGen = 0;
function navBump() { S.navGen++; S.viewGen++; clearInterval(S.poll); }
const RENDER = { chat: () => renderChat(), agent: (sel) => renderAgent(sel), research: () => renderResearch(), memory: () => renderMemory(), artifacts: () => renderArtifacts() };
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
  $("settingsBtn").onclick = projectSettings;
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
  const pv = p.provider_default; const rr = S.routes[pv];
  const c = $("composerRoute");
  if (c) c.replaceChildren(pv ? routeDot(pv) : h("span", { class: "dot" }), h("span", { class: "t" }, `${routeName(pv) || "No provider chosen"}${rr ? " · " + access(rr.state) : ""}`));
  const bt = $("buildRouteTag"); if (bt) bt.replaceChildren(...(rr ? [routeTag(rr)] : []));
  const bd = $("buildRouteDesc"); if (bd) bd.textContent = `Runs the official ${routeName(pv) || "(choose a provider)"} CLI inside ${p.root}. Output is redacted and size-limited. Cancel stops the local process tree only.`;
  const dr = $("draftRoute"); if (dr) dr.textContent = pv ? `Uses ${routeName(pv)}; one request` : "Choose a project provider first";
  const sb = $("sumBtn"); if (sb) sb.title = `Uses ${routeName(pv) || "the project provider"}; one request. Results are proposals for review in Memory.`;
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
      h("span", { class: "chip" }, p.provider_default ? routeDot(p.provider_default) : null, h("span", { class: "t" }, `default provider: ${routeName(p.provider_default) || "not set"}${r ? " · " + access(r.state) : ""}`)),
      h("span", { class: "chip saved" }, icon("check"), h("span", { class: "t" }, "Saved locally")));
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
async function renderChat() {
  if (!S.project || S.global || S.tab !== "chat") return;
  const pid = S.project.id;
  const gen = ++S.viewGen;
  const convs = await api("GET", `/api/projects/${pid}/conversations`);
  if (gen !== S.viewGen) return;
  const atts = (await api("GET", `/api/projects/${pid}/attachments`)).filter((a) => a.extract_status === "extracted");
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
    convs.length ? h("div", { class: "convstrip", role: "list", "aria-label": "Conversations" }, ...convs.map((c) => h("button", { role: "listitem", "aria-current": c.id === cid ? "true" : "false", title: c.title, onclick: () => { S.conv = c.id; refresh("chat"); } }, icon("chat", "sm"), h("span", {}, c.title)))) : h("span", { class: "grow" }),
    sumBtn, btn("Roundtable", (e) => openRoundtable(e.currentTarget), "rt-entry", "users"), btn("New conversation", newConv, "ghost", "plus"));
  const root = h("div", { class: "chatv" }, bar, h("div", { "data-deriv": "summary", class: "section" }, ...dView("summary")));
  if (!cid) {
    root.append(empty("chat", "No conversations yet", "Start a conversation to talk with this project's provider. Messages are saved locally before anything is sent.", btn("Start a conversation", newConv, "primary", "plus")));
    $("view").replaceChildren(root); refreshRouteLabels(); return;
  }
  const draftKey = "aesop.draft.chat." + cid;
  const chips = chatChips[cid] || (chatChips[cid] = new Set());
  const msgsEl = h("div", { class: "msgs", "aria-live": "polite", "aria-relevant": "additions" });
  const ta = h("textarea", { "aria-label": "Message", placeholder: "Ask something about this project…" });
  ta.value = ssGet(draftKey) || "";
  ta.addEventListener("input", () => ssSet(draftKey, ta.value));
  const chosen = () => [...chips].filter((id) => atts.some((a) => a.id === id));
  let sending = false;
  const send = async (confirm) => {
    if (sending) return;
    const raw = ta.value; const text = raw.trim(); if (!text) { ta.focus(); return; }
    sending = true; sendBtn.disabled = true; sendBtn.setAttribute("aria-busy", "true");
    try {
      await api("POST", `/api/projects/${pid}/conversations/${cid}/messages`, { text, attachment_ids: chosen(), confirm_switch: confirm });
      if (ta.value === raw) { ta.value = ""; grow(); ssSet(draftKey, ""); } // keep anything typed while the request was pending
      banner("Saved locally and submitted to provider.", "ok");
      if (gen === S.viewGen) { S.msgSig = ""; drawMsgs(); }
    } catch (e) { banner(e.message, "bad"); }
    finally { sending = false; sendBtn.disabled = false; sendBtn.removeAttribute("aria-busy"); }
  };
  const sendBtn = btn("Send", () => send(false), "primary", "send");
  const preview = async () => guard(async () => {
    const r = await api("POST", `/api/projects/${pid}/conversations/${cid}/preview`, { text: ta.value, attachment_ids: chosen() });
    await dialog(`Context that will be sent to ${routeName(r.provider)} (${r.chars} chars)`, [{ name: "ctx", label: "Exact payload", type: "textarea", value: r.context, tall: true, readonly: true }], "Close");
  });
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(false); } });
  const grow = autosize(ta);
  const attachRow = atts.length
    ? h("div", { class: "attach", role: "group", "aria-label": "Attach project files" }, h("span", { class: "lbl" }, icon("clip", "sm"), "Attach"),
      ...atts.map((a) => h("button", { type: "button", class: "achip", "aria-pressed": chips.has(a.id) ? "true" : "false", "data-id": a.id, title: `${a.name} (${a.chars} chars)`,
        onclick: (e) => { const b = e.currentTarget; const on = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", on ? "true" : "false"); if (on) chips.add(a.id); else chips.delete(a.id); } },
      h("span", {}, a.name))))
    : h("div", { class: "attach" }, h("span", { class: "lbl" }, icon("clip", "sm"), "No readable files to attach yet."), h("button", { type: "button", class: "linkish", onclick: (e) => openInspector("files", e.currentTarget) }, "Add files"));
  const composer = h("div", { class: "composer" }, ta, attachRow,
    h("div", { class: "cfoot" },
      h("div", { class: "row" }, h("span", { class: "chip", id: "composerRoute" }), h("span", { class: "hint" }, h("kbd", {}, "Ctrl"), h("kbd", {}, "Enter"), " send")),
      h("div", { class: "row" }, btn("Preview context", preview, "ghost", "eye"), sendBtn)));
  root.append(msgsEl, h("div", { class: "composer-dock" }, composer));
  $("view").replaceChildren(root);
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
            user && m.status === "saved" ? null : statePill(m.status), user ? h("span", { class: "chip saved" }, icon("check"), h("span", { class: "t" }, "saved locally")) : null),
          save),
        body,
        h("div", { class: "mtime" }, fmtClock(m.created), meta.duration_s ? ` · ${meta.duration_s}s provider wait` : ""),
        costBits.length ? h("div", { class: "costline" }, icon("dollar", "sm"), costBits.join(" · ")) : null));
  }
  let fails = 0;
  async function drawMsgs() {
    let msgs;
    try { msgs = await api("GET", `/api/projects/${pid}/conversations/${cid}/messages`); }
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
      const t = await api("POST", `/api/projects/${pid}/tasks`, { prompt: raw });
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
    showTask(id, detail);
    if (inspectorVisible() && !["terminal", "changes", "logs"].includes(S.itab)) setItab("terminal");
    if (inspectorVisible()) renderInspector();
  };
  listEl.append(...tasks.map((t) => h("button", { class: "task", type: "button", "data-id": t.id, "aria-current": "false", onclick: () => pickTask(t.id) },
    h("span", { class: "dot " + tone(t.state) }),
    h("span", {}, h("span", { class: "tp" }, t.prompt.slice(0, 160)),
      h("span", { class: "tm" }, statePill(t.state), h("span", {}, routeName(t.provider)), h("span", {}, fmtClock(t.started || t.created)))))));
  $("view").replaceChildren(
    h("div", { class: "composer" }, h("div", { class: "card-head" }, h("div", { class: "ttl" }, icon("terminal"), h("h2", {}, "Run an agent task")), h("span", { id: "buildRouteTag" })),
      h("p", { class: "muted", id: "buildRouteDesc" }), ackBox, ta, blockNote,
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
function showTask(tid, el) {
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
  el.replaceChildren(h("div", { class: "card" }, h("div", { class: "card-head" }, h("div", { class: "ttl" }, title, pill), h("div", { class: "row" }, cancelBtn, saveBtn)),
    h("div", { class: "section" }, loading, facts, errBox, chLine, views)));
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
async function renderResearch() {
  if (!S.project || S.global || S.tab !== "research") return;
  const pid = S.project.id;
  const gen = ++S.viewGen;
  const nb = await api("GET", `/api/projects/${pid}/notebook`);
  if (gen !== S.viewGen) return;
  const atts = await api("GET", `/api/projects/${pid}/attachments`);
  if (gen !== S.viewGen) return;
  setActivity("Notebook");
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
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") guard(async () => { const r = await api("GET", `/api/projects/${pid}/search?q=${encodeURIComponent(q.value)}`); if (gen !== S.viewGen) return; results.replaceChildren(...(r.length ? r.map((x) => h("div", { class: "card" }, h("div", { class: "row" }, statePill(x.type), h("strong", {}, x.title)), h("pre", { class: "out" }, x.snippet))) : [empty("search", "No matches", "Nothing in this project matched that search.")])); }); });
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
    await startDerivation("findings", `/api/projects/${pid}/notebook/draft-findings`, { source_ids: ids }, () => { if (S.project && S.project.id === pid) refresh("research"); });
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
  const after = () => refresh("research");
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
    banner(`Source ${s.status}: ${s.title}`, s.status === "read" ? "ok" : "bad"); refresh("research");
  }), "", "download");
  const addBtn = abtn("Add local document", () => guard(async () => {
    if (!attSel.value) { banner("Choose a project file first.", "bad"); return; }
    await api("POST", `/api/projects/${pid}/notebook/sources`, { attachment_id: attSel.value });
    ssSet(dk("att"), ""); refresh("research");
  }), "", "file");
  const saveBtn = abtn("Save finding", () => guard(async () => {
    await api("POST", `/api/projects/${pid}/notebook/findings`, { claim: claim.value, source_id: srcSel.value || null, locator: loc.value, limitation: lim.value });
    for (const k of ["claim", "src", "loc", "lim"]) ssSet(dk(k), "");
    banner("Finding saved.", "ok"); refresh("research");
  }), "primary", "check");

  $("view").replaceChildren(
    h("div", { class: "row" }, q, dlBtn("Export (public sources only)", `/api/projects/${pid}/notebook/export?private=0`, `notebook-${pid}.md`), dlBtn("Export incl. private", `/api/projects/${pid}/notebook/export?private=1`, `notebook-${pid}-private.md`)),
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
      : [empty("bookmark", "Nothing saved yet", "Save chat answers or task results to keep them here.")]));
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

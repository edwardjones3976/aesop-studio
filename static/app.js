"use strict";
// All untrusted text is rendered with textContent via h(); never assign raw HTML.
const S = { csrf: "", routes: {}, projects: [], project: null, tab: "chat", conv: null, global: null, poll: null };

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
const statePill = (s) => {
  const cls = /COMPLETED|READY_INCLUDED|generated|cited|read|saved|current|ok/i.test(s) ? "ok"
    : /FAILED|BLOCKED|UNAVAILABLE|failed|unavailable|unsupported|malformed|too_large|encrypted|conflict|bad/i.test(s) ? "bad"
    : /RUNNING|STARTING|RESERVED|submitted|AUTH|HANDOFF|DISABLED|UNKNOWN|INTERRUPTED|stale|unread|SIMULATED/i.test(s) ? "warn" : "";
  return h("span", { class: "pill " + cls }, s);
};

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
function banner(msg, kind = "") {
  const b = $("banner");
  if (!msg) { b.hidden = true; return; }
  b.className = "banner " + kind; b.textContent = msg; b.hidden = false;
}
async function guard(fn) { try { banner(""); return await fn(); } catch (e) { banner(e.message, "bad"); } }

// ---------- dialogs ----------
function dialog(title, fields, submitLabel = "Save") {
  return new Promise((resolve) => {
    const d = $("dlg"), f = $("dlgForm");
    f.replaceChildren(h("h2", {}, title), ...fields.map((fd) => h("div", { class: "row" }, h("label", {}, fd.label,
      fd.type === "select" ? h("select", { name: fd.name }, ...fd.options.map((o) => h("option", { value: o.value, selected: o.value === fd.value }, o.label)))
      : fd.type === "textarea" ? h("textarea", { name: fd.name }, fd.value || "")
      : h("input", { name: fd.name, value: fd.value || "", type: fd.type || "text", required: fd.required, placeholder: fd.placeholder || "" })),
      fd.help ? h("p", { class: "muted" }, fd.help) : null)),
      h("div", { class: "row" }, h("button", { class: "btn primary", value: "ok" }, submitLabel), h("button", { class: "btn", value: "cancel", formnovalidate: true }, "Cancel")));
    d.onclose = () => {
      if (d.returnValue !== "ok") return resolve(null);
      resolve(Object.fromEntries(new FormData(f).entries()));
    };
    d.returnValue = ""; d.showModal();
  });
}

// ---------- boot ----------
async function boot() {
  try {
    const s = await api("GET", "/api/session");
    S.csrf = s.csrf;
    if (s.reconciled && s.reconciled.length) banner(`Recovered after restart: ${s.reconciled.length} unfinished task(s) marked ${[...new Set(s.reconciled.map((r) => r.to))].join(", ")}. Nothing was replayed automatically.`);
  } catch (e) {
    $("view").replaceChildren(h("div", { class: "card" }, h("h2", {}, "Sign-in needed"),
      h("p", {}, "Open the one-time launch link from launch-link.txt (start.ps1 opens it for you). This keeps other websites and local programs from using your Studio.")));
    return;
  }
  S.routes = await api("GET", "/api/routes");
  await loadProjects();
  $("newProjectBtn").onclick = newProject;
  $("settingsBtn").onclick = projectSettings;
  $("providerSel").onchange = (e) => guard(async () => { S.project = await api("PATCH", `/api/projects/${S.project.id}`, { provider_default: e.target.value }); renderHeader(); banner(`Project default provider set to ${e.target.value}.`, "ok"); });
  document.querySelectorAll("[data-global]").forEach((b) => (b.onclick = () => openGlobal(b.dataset.global)));
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => (b.onclick = () => setTab(b.dataset.tab)));
  $("tabs").addEventListener("keydown", (e) => {
    if (!["ArrowRight", "ArrowLeft"].includes(e.key)) return;
    const tabs = [...document.querySelectorAll("#tabs [data-tab]")]; const i = tabs.findIndex((t) => t.dataset.tab === S.tab);
    const n = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length]; setTab(n.dataset.tab); n.focus();
  });
  const last = localStorageGet("aesop.project");
  if (last && S.projects.some((p) => p.id === last)) openProject(last);
  else if (!S.projects.length) renderWelcome(); else openProject(S.projects[0].id);
}
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch { /* optional */ } }

async function loadProjects() {
  S.projects = await api("GET", "/api/projects");
  $("projectList").replaceChildren(...S.projects.map((p) => h("button", { "aria-current": S.project && S.project.id === p.id ? "true" : "false", onclick: () => openProject(p.id) },
    p.name, h("small", {}, p.root))));
  if (!S.projects.length) $("projectList").append(h("p", { class: "empty" }, "No projects yet."));
}
function renderWelcome() {
  $("view").replaceChildren(h("div", { class: "card" }, h("h2", {}, "Start with a project"),
    h("p", {}, "A project is one folder you choose. Chats, files, agent tasks, research and memory stay inside it. Studio never reads outside the folder you select."),
    h("button", { class: "btn primary", onclick: newProject }, "Create project")));
}
async function newProject() {
  const usable = Object.entries(S.routes).filter(([, r]) => ["READY_INCLUDED", "SIMULATED"].includes(r.state));
  const v = await dialog("New project", [
    { name: "name", label: "Name", required: true },
    { name: "root", label: "Project folder (absolute path)", required: true, placeholder: "C:\\Users\\you\\Projects\\my-project", help: "Agent tasks may write only inside this folder." },
    { name: "provider_default", label: "Default provider", type: "select", options: usable.map(([id, r]) => ({ value: id, label: `${id} — ${r.provider} (${r.state})` })) },
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
    ...Object.keys(S.routes).filter((k) => ["READY_INCLUDED", "SIMULATED"].includes(S.routes[k].state)).map((k) => ({ name: "tp_" + k, label: `Allow sending attached project files to ${k}?`, type: "select", value: pol[k] ? "yes" : "no", options: [{ value: "no", label: "No" }, { value: "yes", label: "Yes" }] })),
  ]);
  if (!v) return;
  const tp = {}; for (const [k, val] of Object.entries(v)) if (k.startsWith("tp_")) tp[k.slice(3)] = val === "yes";
  await guard(async () => { S.project = await api("PATCH", `/api/projects/${p.id}`, { name: v.name, model: v.model, retention_days: v.retention_days, transfer_policy: tp }); renderHeader(); loadProjects(); banner("Settings saved.", "ok"); });
}

async function openProject(id) {
  S.global = null; S.conv = null;
  await guard(async () => {
    S.project = await api("GET", `/api/projects/${id}`);
    localStorageSet("aesop.project", id);
    renderHeader(); await loadProjects(); setTab(S.tab || "chat");
  });
}
function renderHeader() {
  const p = S.project;
  $("projTitle").textContent = p ? p.name : "No project open";
  $("projMeta").textContent = p ? `${p.root} · default provider: ${p.provider_default || "not set"}` : "";
  $("projControls").hidden = !p; $("tabs").hidden = !p;
  if (p) $("providerSel").replaceChildren(h("option", { value: "" }, "— choose —"), ...Object.entries(S.routes).filter(([, r]) => ["READY_INCLUDED", "SIMULATED"].includes(r.state)).map(([id, r]) => h("option", { value: id, selected: id === p.provider_default }, `${id} (${r.provider})`)));
}
function setTab(tab) {
  S.tab = tab; S.global = null; clearInterval(S.poll);
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => { b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false"); b.tabIndex = b.dataset.tab === tab ? 0 : -1; });
  ({ chat: renderChat, files: renderFiles, agent: renderAgent, research: renderResearch, memory: renderMemory, artifacts: renderArtifacts })[tab]();
}

// ---------- chat ----------
async function renderChat() {
  const pid = S.project.id;
  const convs = await api("GET", `/api/projects/${pid}/conversations`);
  if (!S.conv && convs.length) S.conv = convs[0].id;
  const atts = (await api("GET", `/api/projects/${pid}/attachments`)).filter((a) => a.extract_status === "extracted");
  const list = h("div", { class: "convlist" }, h("button", { class: "btn wide", onclick: async () => { const c = await api("POST", `/api/projects/${pid}/conversations`, {}); S.conv = c.id; renderChat(); } }, "+ New conversation"),
    ...convs.map((c) => h("button", { "aria-current": c.id === S.conv ? "true" : "false", onclick: () => { S.conv = c.id; renderChat(); } }, c.title)));
  const right = h("div");
  if (!S.conv) { right.append(h("p", { class: "empty" }, "Start a conversation to talk with this project's provider.")); }
  else {
    const msgsEl = h("div", { class: "msgs", "aria-live": "polite" });
    const ta = h("textarea", { "aria-label": "Message", placeholder: "Ask something… (Ctrl+Enter to send)" });
    const attSel = h("select", { multiple: true, "aria-label": "Attach project files", size: Math.min(4, Math.max(2, atts.length)) }, ...atts.map((a) => h("option", { value: a.id }, `${a.name} (${a.chars} chars)`)));
    const chosen = () => [...attSel.selectedOptions].map((o) => o.value);
    const send = async (confirm) => {
      const text = ta.value.trim(); if (!text) return;
      try {
        await api("POST", `/api/projects/${pid}/conversations/${S.conv}/messages`, { text, attachment_ids: chosen(), confirm_switch: confirm });
        ta.value = ""; banner("Saved locally and submitted to provider.", "ok"); drawMsgs();
      } catch (e) { banner(e.message, "bad"); }
    };
    const preview = async () => guard(async () => {
      const r = await api("POST", `/api/projects/${pid}/conversations/${S.conv}/preview`, { text: ta.value, attachment_ids: chosen() });
      await dialog(`Context that will be sent to ${r.provider} (${r.chars} chars)`, [{ name: "ctx", label: "Exact payload", type: "textarea", value: r.context }], "Close");
    });
    ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.ctrlKey) send(false); });
    right.append(msgsEl, h("div", { class: "card" }, ta,
      atts.length ? h("div", { class: "row" }, h("label", {}, "Attach (Ctrl-click for several):", attSel)) : h("p", { class: "muted" }, "Upload text files in Files to attach them."),
      h("div", { class: "row" }, h("button", { class: "btn primary", onclick: () => send(false) }, "Send"), h("button", { class: "btn", onclick: preview }, "Preview context"),
        h("span", { class: "muted" }, `Provider: ${S.project.provider_default || "none chosen"}`))));
    async function drawMsgs() {
      const msgs = await api("GET", `/api/projects/${pid}/conversations/${S.conv}/messages`);
      msgsEl.replaceChildren(...(msgs.length ? msgs.map((m) => h("div", { class: "msg " + m.role },
        h("div", { class: "head" }, h("span", {}, m.role === "user" ? "You" : `${m.provider}`, " ", statePill(m.status), m.meta.duration_s ? ` · ${m.meta.duration_s}s provider wait` : ""),
          h("span", {}, m.role === "assistant" && m.status === "generated" ? h("button", { class: "linkish", onclick: () => guard(async () => { await api("POST", `/api/projects/${pid}/artifacts`, { kind: "chat_answer", title: m.content.slice(0, 60), content: m.content, source_ref: m.id }); banner("Saved to project.", "ok"); }) }, "Save") : "")),
        h("pre", {}, m.status === "submitted" ? "Waiting for the provider. Its CLI does not stream partial text here; the answer appears when it finishes." : m.content))) : [h("p", { class: "empty" }, "No messages yet.")]));
      msgsEl.scrollTop = msgsEl.scrollHeight;
      clearInterval(S.poll);
      if (msgs.some((m) => m.status === "submitted")) S.poll = setInterval(async () => { if (S.tab === "chat" && !S.global) { clearInterval(S.poll); drawMsgs(); } }, 2500);
    }
    drawMsgs();
  }
  $("view").replaceChildren(h("div", { class: "chat" }, list, right));
}

// ---------- files ----------
async function renderFiles() {
  const pid = S.project.id;
  const atts = await api("GET", `/api/projects/${pid}/attachments`);
  const input = h("input", { type: "file", multiple: true, "aria-label": "Choose files" });
  input.onchange = () => guard(async () => {
    for (const f of input.files) {
      try { const a = await api("POST", `/api/projects/${pid}/attachments`, undefined, { name: f.name, data: f });
        banner(`${a.name}: ${a.extract_status} — ${a.extract_note}`, a.extract_status === "extracted" ? "ok" : ""); }
      catch (e) { banner(`${f.name}: ${e.message}`, "bad"); }
    }
    renderFiles();
  });
  $("view").replaceChildren(h("div", { class: "card" }, h("h2", {}, "Project files"), h("p", { class: "muted" }, "Only the single files you choose are copied in (5 MB limit). Text formats are read; others are kept with a hash and an honest status."), input),
    h("div", { class: "tablewrap" }, h("table", {}, h("caption", {}, `${atts.length} file(s)`), h("thead", {}, h("tr", {}, ...["Name", "Status", "Note", "Size", "SHA-256", "Added"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...atts.map((a) => h("tr", {}, h("td", {}, a.name), h("td", {}, statePill(a.extract_status)), h("td", {}, a.extract_note || ""), h("td", {}, `${(a.size / 1024).toFixed(1)} KB`), h("td", {}, h("code", {}, a.sha256.slice(0, 12))), h("td", {}, fmtTime(a.created))))))));
}

// ---------- agent ----------
async function renderAgent(selected) {
  const pid = S.project.id;
  const tasks = await api("GET", `/api/projects/${pid}/tasks`);
  const ta = h("textarea", { "aria-label": "Agent task", placeholder: "Describe a bounded coding task to run inside the project folder…" });
  const start = () => guard(async () => {
    if (!ta.value.trim()) return;
    const t = await api("POST", `/api/projects/${pid}/tasks`, { prompt: ta.value });
    banner(`Task ${t.id} ${t.state}.`, t.state === "BLOCKED_OWNER" ? "bad" : "ok"); renderAgent(t.id);
  });
  const detail = h("div");
  $("view").replaceChildren(h("div", { class: "card" }, h("h2", {}, "Run an agent task"),
    h("p", { class: "muted" }, `Runs the official ${S.project.provider_default || "(choose a provider)"} CLI inside ${S.project.root}. Output is redacted and size-limited. Cancel stops the local process tree only.`), ta,
    h("div", { class: "row" }, h("button", { class: "btn primary", onclick: start }, "Start task"))),
    h("div", { class: "tablewrap" }, h("table", {}, h("caption", {}, "Recent tasks"), h("thead", {}, h("tr", {}, ...["Task", "Provider", "State", "Started", "Detail"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...tasks.map((t) => h("tr", {}, h("td", {}, t.prompt.slice(0, 70)), h("td", {}, t.provider), h("td", {}, statePill(t.state)), h("td", {}, fmtTime(t.started || t.created)), h("td", {}, h("button", { class: "linkish", onclick: () => showTask(t.id, detail) }, "Open"))))))),
    detail);
  if (selected) showTask(selected, detail);
}
async function showTask(tid, el) {
  clearInterval(S.poll);
  let offset = 0; const out = h("pre", { class: "out", "aria-live": "polite" }); const head = h("div");
  el.replaceChildren(h("div", { class: "card" }, head, out));
  const tick = async () => {
    const r = await api("GET", `/api/tasks/${tid}?offset=${offset}`);
    offset = r.offset; if (r.output) out.append(r.output);
    const t = r.task; const done = ["COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED", "BLOCKED_OWNER", "EFFECT_UNKNOWN"].includes(t.state);
    const ch = t.changed_files ? JSON.parse(t.changed_files) : null;
    head.replaceChildren(h("h3", {}, `Task ${t.id} `, statePill(t.state)),
      h("p", { class: "muted" }, `Provider ${t.provider} · cwd ${t.cwd} · started ${fmtTime(t.started)} · ended ${fmtTime(t.ended)}${t.exit_code !== null ? " · exit " + t.exit_code : ""}`),
      t.error ? h("p", { class: "banner bad" }, t.error) : null,
      ch ? h("p", {}, `Changed files — added: ${ch.added.join(", ") || "none"}; modified: ${ch.modified.join(", ") || "none"}; removed: ${ch.removed.join(", ") || "none"}`) : null,
      h("div", { class: "row" }, !done ? h("button", { class: "btn danger", onclick: () => guard(async () => { const c = await api("POST", `/api/tasks/${tid}/cancel`); banner(c.note, ""); }) }, "Cancel") : null,
        done ? h("button", { class: "btn", onclick: () => guard(async () => { await api("POST", `/api/tasks/${tid}/save`); banner("Task result saved to project.", "ok"); }) }, "Save result") : null));
    if (done) clearInterval(S.poll);
  };
  await tick(); S.poll = setInterval(() => (S.tab === "agent" && !S.global ? tick() : clearInterval(S.poll)), 1500);
}

// ---------- research ----------
async function renderResearch() {
  const pid = S.project.id;
  const nb = await api("GET", `/api/projects/${pid}/notebook`);
  const atts = (await api("GET", `/api/projects/${pid}/attachments`));
  const url = h("input", { type: "url", placeholder: "https://…", "aria-label": "Public source URL", size: 40 });
  const attSel = h("select", { "aria-label": "Local document" }, h("option", { value: "" }, "— local document —"), ...atts.map((a) => h("option", { value: a.id }, a.name)));
  const srcSel = h("select", { "aria-label": "Source for finding" }, h("option", { value: "" }, "— no source (unsupported) —"), ...nb.sources.map((s, i) => h("option", { value: s.id }, `[${i + 1}] ${s.title.slice(0, 60)}`)));
  const claim = h("textarea", { "aria-label": "Finding", placeholder: "What does the source support?" });
  const loc = h("input", { placeholder: "Locator: section, page, line or quote", "aria-label": "Locator", size: 40 });
  const lim = h("input", { placeholder: "Limitation (optional)", "aria-label": "Limitation", size: 30 });
  const q = h("input", { type: "search", placeholder: "Search this project…", "aria-label": "Search project" });
  const results = h("div");
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") guard(async () => { const r = await api("GET", `/api/projects/${pid}/search?q=${encodeURIComponent(q.value)}`); results.replaceChildren(...(r.length ? r.map((x) => h("div", { class: "card" }, statePill(x.type), " ", h("strong", {}, x.title), h("pre", {}, x.snippet))) : [h("p", { class: "empty" }, "No matches in this project.")])); }); });
  $("view").replaceChildren(
    h("div", { class: "grid2" },
      h("div", { class: "card" }, h("h2", {}, "Add a source"), h("div", { class: "row" }, url, h("button", { class: "btn", onclick: () => guard(async () => { banner("Fetching (public addresses only)…"); const s = await api("POST", `/api/projects/${pid}/notebook/sources`, { url: url.value }); banner(`Source ${s.status}: ${s.title}`, s.status === "read" ? "ok" : "bad"); renderResearch(); }) }, "Fetch public page")),
        h("div", { class: "row" }, attSel, h("button", { class: "btn", onclick: () => guard(async () => { if (!attSel.value) return; await api("POST", `/api/projects/${pid}/notebook/sources`, { attachment_id: attSel.value }); renderResearch(); }) }, "Add local document"))),
      h("div", { class: "card" }, h("h2", {}, "Record a finding"), claim, h("div", { class: "row" }, srcSel), h("div", { class: "row" }, loc, lim),
        h("button", { class: "btn primary", onclick: () => guard(async () => { await api("POST", `/api/projects/${pid}/notebook/findings`, { claim: claim.value, source_id: srcSel.value || null, locator: loc.value, limitation: lim.value }); renderResearch(); }) }, "Save finding"))),
    h("div", { class: "row" }, q, h("a", { class: "btn", href: `/api/projects/${pid}/notebook/export?private=0` }, "Export (public sources only)"), h("a", { class: "btn", href: `/api/projects/${pid}/notebook/export?private=1` }, "Export incl. private")),
    results,
    h("h2", {}, "Findings"), nb.findings.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ...["Claim", "Source", "Locator", "Status", "Limitation"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...nb.findings.map((f) => { const i = nb.sources.findIndex((s) => s.id === f.source_id); return h("tr", {}, h("td", {}, f.claim), h("td", {}, i >= 0 ? `[${i + 1}]` : "—"), h("td", {}, f.locator || ""), h("td", {}, statePill(f.status)), h("td", {}, f.limitation || "")); })))) : h("p", { class: "empty" }, "No findings yet."),
    h("h2", {}, "Sources"), nb.sources.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ...["#", "Title", "Publisher", "Locator", "Retrieved", "Status", "Visibility"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...nb.sources.map((s, i) => h("tr", {}, h("td", {}, i + 1), h("td", {}, s.title), h("td", {}, s.publisher || ""), h("td", {}, s.locator), h("td", {}, fmtTime(s.retrieved_at)), h("td", {}, statePill(s.status)), h("td", {}, s.private ? "private" : "public")))))) : h("p", { class: "empty" }, "No sources yet."));
}

// ---------- memory ----------
async function renderMemory() {
  const pid = S.project.id;
  const mem = await api("GET", `/api/projects/${pid}/memory`);
  const content = h("textarea", { "aria-label": "Memory content", placeholder: "Constraint, decision or state to remember for this project" });
  const layer = h("select", { "aria-label": "Layer" }, h("option", { value: "authoritative" }, "Authoritative record"), h("option", { value: "derived" }, "Derived summary (needs source IDs)"));
  const srcs = h("input", { placeholder: "Source record IDs, comma-separated", "aria-label": "Source IDs", size: 40 });
  const act = (m, op, body) => guard(async () => { await api("POST", `/api/projects/${pid}/memory/${m.id}/${op}`, body); renderMemory(); });
  const groups = ["authoritative", "derived", "shared"];
  $("view").replaceChildren(h("div", { class: "card" }, h("h2", {}, "Add to project memory"), h("p", { class: "muted" }, "Memory belongs to this project only. Shared knowledge needs an explicit promotion. Corrections supersede old records but keep them for provenance."),
    content, h("div", { class: "row" }, layer, srcs, h("button", { class: "btn primary", onclick: () => guard(async () => { await api("POST", `/api/projects/${pid}/memory`, { layer: layer.value, kind: "note", content: content.value, source_ids: srcs.value.split(",").map((s) => s.trim()).filter(Boolean) }); renderMemory(); }) }, "Save"),
      h("a", { class: "btn", href: `/api/projects/${pid}/context-packet` }, "View context packet"))),
    ...groups.map((g) => { const rows = mem.filter((m) => m.layer === g); return h("div", {}, h("h2", {}, { authoritative: "Authoritative records", derived: "Derived working summaries", shared: "Promoted shared knowledge" }[g]),
      rows.length ? rows.map((m) => h("div", { class: "card" }, h("div", { class: "row" }, statePill(m.status), h("code", {}, m.id), m.source_ids.length ? h("span", { class: "muted" }, "sources: " + m.source_ids.join(", ")) : null, h("span", { class: "muted" }, fmtTime(m.created))),
        h("p", {}, m.content),
        m.project_id && m.status !== "superseded" ? h("div", { class: "row" },
          h("button", { class: "linkish", onclick: async () => { const v = await dialog("Correct this record", [{ name: "content", label: "Corrected content", type: "textarea", value: m.content }]); if (v) act(m, "correct", v); } }, "Correct"),
          h("button", { class: "linkish", onclick: () => act(m, "mark", { status: "stale" }) }, "Mark stale"),
          h("button", { class: "linkish", onclick: () => act(m, "mark", { status: "conflict" }) }, "Mark conflicting"),
          h("button", { class: "linkish", onclick: () => act(m, "promote", {}) }, "Promote to shared")) : null)) : h("p", { class: "empty" }, "Nothing here yet.")); }));
}

// ---------- artifacts ----------
async function renderArtifacts() {
  const pid = S.project.id;
  const arts = await api("GET", `/api/projects/${pid}/artifacts`);
  $("view").replaceChildren(h("div", { class: "row" }, h("a", { class: "btn", href: `/api/projects/${pid}/export` }, "Export project (JSON)"),
    h("button", { class: "btn danger", onclick: () => guard(async () => { const v = await dialog("Archive project?", [{ name: "confirm", label: `Type the project name (${S.project.name}) to hide it. Files in the folder are never deleted.`, required: true }], "Archive"); if (!v || v.confirm !== S.project.name) return; await api("POST", `/api/projects/${pid}/archive`); S.project = null; renderHeader(); await loadProjects(); renderWelcome(); }) }, "Archive project")),
    arts.length ? arts.map((a) => h("details", { class: "card" }, h("summary", {}, statePill(a.kind), " ", a.title, h("span", { class: "muted" }, " · " + fmtTime(a.created))), h("pre", { class: "out" }, a.content))) : h("p", { class: "empty" }, "Nothing saved yet. Save chat answers or task results to keep them here."));
}

// ---------- global views ----------
async function openGlobal(which) {
  S.global = which; clearInterval(S.poll);
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => b.setAttribute("aria-selected", "false"));
  if (which === "providers") return renderProviders();
  renderEvidence();
}
async function renderProviders() {
  const routes = S.routes;
  $("view").replaceChildren(h("div", { class: "row" }, h("h2", {}, "Provider routes"), h("button", { class: "btn", onclick: () => guard(async () => { banner("Re-verifying via each official CLI…"); S.routes = await api("POST", "/api/routes/refresh"); renderProviders(); banner("Routes re-verified.", "ok"); }) }, "Re-verify")),
    h("p", { class: "muted" }, "States come from each official CLI's own status command. Studio never reads credential files. Handoff routes are not counted as in-app integrations."),
    h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ...["Route", "Provider", "State", "Version", "Modes", "Billing", "Incremental cost", "Evidence", "Limitations", "Verified"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...Object.entries(routes).map(([id, r]) => h("tr", {}, h("td", {}, id), h("td", {}, r.provider), h("td", {}, statePill(r.state)), h("td", {}, r.version || "—"), h("td", {}, r.supported_modes.join(", ")), h("td", {}, r.billing_basis), h("td", {}, r.incremental_cost_status), h("td", {}, r.evidence), h("td", {}, r.limitations), h("td", {}, fmtTime(r.last_verified_at))))))));
}
async function renderEvidence() {
  const e = await api("GET", "/api/evidence");
  const b = e.budget; const totalCap = e.allocation.reduce((s, a) => s + a.cap, 0);
  const m = { label: h("input", { "aria-label": "Workflow label", placeholder: "Label" }), workflow: h("select", { "aria-label": "Workflow" }, h("option", { value: "native" }, "Previous native workflow"), h("option", { value: "studio" }, "Aesop Studio")),
    elapsed_s: h("input", { type: "number", "aria-label": "Elapsed seconds", placeholder: "seconds" }), manual_steps: h("input", { type: "number", "aria-label": "Manual steps", placeholder: "steps" }), app_switches: h("input", { type: "number", "aria-label": "App switches", placeholder: "switches" }) };
  $("view").replaceChildren(
    h("h2", {}, "Budget ledger"),
    h("div", { class: "grid2" },
      h("div", { class: "card" }, h("table", {}, h("caption", {}, "Mission spending (USD). Allocation is not expenditure."), h("tbody", {},
        ...[["Ceiling", b.ceiling], ["Settled (billed)", b.settled], ["Outstanding reservations", b.outstanding], ["Unresolved exposure", b.ambiguous], ["Remaining", b.remaining], ["Subscription-included runs ($0)", b.included_uses], ["Billable permit", b.permit ? "ON" : "off"], ["Phase", b.phase]].map(([k, v]) => h("tr", {}, h("th", {}, k), h("td", {}, typeof v === "number" && k !== "Subscription-included runs ($0)" ? `$${v.toFixed(2)}` : String(v))))))),
      h("div", { class: "card" }, h("table", {}, h("caption", {}, `Planning envelopes (caps, total $${totalCap})`), h("tbody", {}, ...e.allocation.map((a) => h("tr", {}, h("td", {}, a.envelope), h("td", {}, `$${a.cap}`), h("td", {}, h("meter", { min: 0, max: totalCap, value: a.cap, "aria-label": `$${a.cap} of $${totalCap}` }, `$${a.cap}`)))))))),
    h("h2", {}, "Acceptance matrix"), e.acceptance.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ...["ID", "Requirement", "Implementation", "Test", "Status", "Evidence / limitation"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...e.acceptance.map((a) => h("tr", {}, h("td", {}, a.id), h("td", {}, a.requirement), h("td", {}, a.implementation), h("td", {}, a.test), h("td", {}, statePill(a.status)), h("td", {}, a.evidence)))))) : h("p", { class: "empty" }, "No acceptance file."),
    h("h2", {}, "Task success and recovery"), h("p", {}, `${e.tasks.total} run(s) recorded. `, ...Object.entries(e.tasks.by_state).map(([s, n]) => h("span", {}, statePill(`${s}: ${n}`), " ")), `Restart reconciliations: ${e.tasks.reconciliations}. Open repair packets: ${e.tasks.repairs.filter((r) => r.status.startsWith("OPEN")).length}.`),
    e.tasks.total ? null : h("p", { class: "empty" }, "No runs yet. Counts appear after real use."),
    h("h2", {}, "Provider latency (completed runs)"), e.latency.length ? h("div", { class: "tablewrap" }, h("table", {}, h("caption", {}, "Provider wait measured from process start to exit. Small samples are shown individually; no confidence claims."), h("thead", {}, h("tr", {}, ...["Route/mode", "n", "Median s", "Min", "Max", "Last samples"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...e.latency.map((l) => h("tr", {}, h("td", {}, l.route), h("td", {}, l.n), h("td", {}, l.median_s), h("td", {}, l.min_s), h("td", {}, l.max_s), h("td", {}, l.samples.join(", "))))))) : h("p", { class: "empty" }, "No completed runs yet."),
    h("h2", {}, "Workflow measurements"), h("div", { class: "card" }, h("p", { class: "muted" }, "Record the same task done the old way and in Studio. Without owner trials, any time saving stays unverified."),
      h("div", { class: "row" }, m.label, m.workflow, m.elapsed_s, m.manual_steps, m.app_switches, h("button", { class: "btn", onclick: () => guard(async () => { await api("POST", "/api/workflow-measure", Object.fromEntries(Object.entries(m).map(([k, el]) => [k, el.value]))); renderEvidence(); }) }, "Record"))),
    e.workflow.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ...["Label", "Workflow", "Seconds", "Steps", "App switches", "When"].map((x) => h("th", {}, x)))), h("tbody", {}, ...e.workflow.map((w) => h("tr", {}, h("td", {}, w.label || ""), h("td", {}, w.workflow || ""), h("td", {}, w.elapsed_s || ""), h("td", {}, w.manual_steps || ""), h("td", {}, w.app_switches || ""), h("td", {}, fmtTime(w.at))))))) : h("p", { class: "empty" }, "No measurements recorded."),
    h("h2", {}, "Research background"), e.research.length ? h("div", { class: "tablewrap" }, h("table", {}, h("caption", {}, "External studies are background, not Aesop Studio results."), h("thead", {}, h("tr", {}, ...["Source", "Context", "Method", "Result", "Limitations", "Decision"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...e.research.map((r) => h("tr", {}, h("td", {}, h("a", { href: r.url, rel: "noopener noreferrer", target: "_blank" }, r.source)), h("td", {}, r.context), h("td", {}, r.method), h("td", {}, r.result), h("td", {}, r.limitations), h("td", {}, r.decision)))))) : null,
    h("h2", {}, "Backup"), h("div", { class: "row" }, h("button", { class: "btn", onclick: () => guard(async () => { const r = await api("POST", "/api/backup"); banner(`Backup written: ${r.archive}`, "ok"); }) }, "Create backup"),
      h("button", { class: "btn", onclick: () => guard(async () => { const r = await api("POST", "/api/backup/verify"); banner(r.ok ? `Restore test passed in ${r.target}. ${r.reauth}` : `Restore test FAILED: ${JSON.stringify(r)}`, r.ok ? "ok" : "bad"); }) }, "Test restore of latest backup")));
}

boot();

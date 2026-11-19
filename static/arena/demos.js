"use strict";
/* Arena interactive demo fixtures (plain canvas/CSS; no CDN, CSP script-src 'self').
   Each mount(root, { variant }) returns { destroy() }. Variant "a"|"b" nudges lane styling. */
(function (global) {
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else if (k === "class") n.className = v;
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat()) if (k != null && k !== false) n.append(k instanceof Node ? k : String(k));
    return n;
  }

  function sizeCanvas(cv, host) {
    const r = host.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(280, Math.floor(r.width));
    const h = Math.max(220, Math.floor(r.height || 320));
    cv.width = Math.floor(w * dpr);
    cv.height = Math.floor(h * dpr);
    cv.style.width = w + "px";
    cv.style.height = h + "px";
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h };
  }

  function alpine(root, opts) {
    const variant = (opts && opts.variant) || "a";
    const state = { season: "autumn", time: 0.68, camera: "Marienbrücke", mood: "Golden autumn", raf: 0 };
    const shell = el("div", { class: "ademo alpine v-" + variant });
    const stage = el("div", { class: "ademo-stage" });
    const cv = el("canvas", { class: "ademo-cv", "aria-label": "Alpine Atlas scene" });
    const brand = el("div", { class: "ademo-brand" },
      el("strong", {}, "Alpine Atlas"), el("span", {}, "Interactive field series"));
    const plate = el("div", { class: "ademo-plate" },
      el("span", {}, "Plate 41 — Bavarian Alps"),
      el("strong", {}, "Neuschwanstein Castle"),
      el("span", {}, "Schwangau · 1,008 m"));
    const panel = el("div", { class: "ademo-panel" });
    const seasons = el("div", { class: "ademo-row" }, el("span", { class: "ademo-k" }, "Atmosphere"));
    ["Summer", "Autumn", "Misty"].forEach((s) => {
      const id = s.toLowerCase();
      seasons.append(el("button", { type: "button", class: "ademo-chip" + (state.season === id ? " on" : ""),
        onclick: () => { state.season = id; paint(); sync(); } }, s));
    });
    const timeLab = el("span", { class: "ademo-val" }, "16:20");
    const time = el("input", { type: "range", min: "0", max: "1", step: "0.01", value: String(state.time),
      "aria-label": "Time of day", oninput: (e) => { state.time = +e.target.value; paint(); sync(); } });
    const cam = el("select", { "aria-label": "Viewpoint", onchange: (e) => { state.camera = e.target.value; paint(); } },
      ...["Marienbrücke", "Valley approach", "Aerial orbit", "Castle terrace"].map((c) =>
        el("option", { value: c, selected: c === state.camera }, c)));
    const moods = el("div", { class: "ademo-moods" });
    ["Clear Alpine day", "Golden autumn", "Valley mist", "Dramatic clouds", "Fairy-tale dusk", "Moonlit night"]
      .forEach((m) => moods.append(el("button", { type: "button", class: "ademo-chip sm" + (state.mood === m ? " on" : ""),
        onclick: () => { state.mood = m; if (/mist/i.test(m)) state.season = "misty";
          if (/autumn|golden/i.test(m)) state.season = "autumn";
          if (/moon|dusk/i.test(m)) state.time = 0.88; paint(); sync(); } }, m)));
    function sync() {
      const hh = Math.floor(5 + state.time * 16); const mm = Math.floor((state.time * 16 * 60) % 60);
      timeLab.textContent = `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
      seasons.querySelectorAll(".ademo-chip").forEach((b) => b.classList.toggle("on", b.textContent.toLowerCase() === state.season));
      moods.querySelectorAll(".ademo-chip").forEach((b) => b.classList.toggle("on", b.textContent === state.mood));
    }
    panel.append(
      seasons,
      el("div", { class: "ademo-row" }, el("span", { class: "ademo-k" }, "Time"), time, timeLab),
      el("div", { class: "ademo-row" }, el("span", { class: "ademo-k" }, "Camera"), cam),
      variant === "b" ? el("div", { class: "ademo-row col" }, el("span", { class: "ademo-k" }, "Moods"), moods) : null);
    stage.append(cv, brand, plate, panel);
    shell.append(stage);
    root.append(shell);

    function paint() {
      const { ctx, w, h } = sizeCanvas(cv, stage);
      const t = state.time;
      const skyTop = state.season === "misty" ? "#8fa8b8" : t > 0.8 ? "#1a2038" : t > 0.65 ? "#c96b45" : "#6eb0e0";
      const skyBot = state.season === "autumn" ? "#d4a06a" : state.season === "misty" ? "#c8d4dc" : t > 0.8 ? "#2a3358" : "#cfe8ff";
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, skyTop); g.addColorStop(1, skyBot);
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
      // mountains
      ctx.fillStyle = state.season === "autumn" ? "#5a4a3a" : "#3d5248";
      ctx.beginPath(); ctx.moveTo(0, h * 0.72);
      ctx.lineTo(w * 0.2, h * 0.42); ctx.lineTo(w * 0.38, h * 0.58);
      ctx.lineTo(w * 0.55, h * 0.28); ctx.lineTo(w * 0.72, h * 0.55);
      ctx.lineTo(w, h * 0.4); ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.fill();
      // castle
      const cx = state.camera === "Aerial orbit" ? w * 0.5 : state.camera === "Valley approach" ? w * 0.62 : w * 0.48;
      const cy = h * (state.camera === "Castle terrace" ? 0.48 : 0.42);
      ctx.fillStyle = "#e8e0d4";
      ctx.fillRect(cx - 18, cy, 36, 55);
      ctx.fillRect(cx - 28, cy + 20, 12, 35);
      ctx.fillRect(cx + 16, cy + 10, 14, 45);
      ctx.beginPath(); ctx.moveTo(cx - 18, cy); ctx.lineTo(cx, cy - 22); ctx.lineTo(cx + 18, cy); ctx.fill();
      ctx.fillStyle = "#c45c4a"; ctx.fillRect(cx - 6, cy + 28, 10, 18);
      // mist / trees
      if (state.season === "misty" || /mist/i.test(state.mood)) {
        ctx.fillStyle = "rgba(220,230,236,.45)"; ctx.fillRect(0, h * 0.55, w, h * 0.3);
      }
      ctx.fillStyle = state.season === "autumn" ? "#8b4518" : "#2f5a3c";
      for (let i = 0; i < 14; i++) {
        const x = (i / 14) * w + (i % 3) * 8; const th = 18 + (i % 5) * 6;
        ctx.fillRect(x, h * 0.78 - th, 6, th);
      }
      ctx.fillStyle = "rgba(255,255,255,.55)";
      ctx.font = "12px Segoe UI, sans-serif";
      ctx.fillText(state.camera + " · " + state.mood, 12, h - 14);
    }
    const onResize = () => paint();
    window.addEventListener("resize", onResize);
    paint(); sync();
    return { destroy() { cancelAnimationFrame(state.raf); window.removeEventListener("resize", onResize); shell.remove(); } };
  }

  function lostValley(root, opts) {
    const variant = (opts && opts.variant) || "a";
    const state = { habitat: true, fog: variant === "b", herd: variant === "b" ? 5 : 3, raf: 0, t: 0 };
    const shell = el("div", { class: "ademo lost v-" + variant });
    const stage = el("div", { class: "ademo-stage" });
    const cv = el("canvas", { class: "ademo-cv", "aria-label": "Lost Valley habitat" });
    const brand = el("div", { class: "ademo-brand" },
      el("strong", {}, "Lost Valley"), el("span", {}, "Primeval sanctuary"));
    const live = el("div", { class: "ademo-live" }, el("span", { class: "pulse" }), "Live habitat");
    const panel = el("div", { class: "ademo-panel" });
    const tog = el("button", { type: "button", class: "ademo-chip on", onclick: () => {
      state.habitat = !state.habitat; tog.classList.toggle("on", state.habitat); tog.textContent = state.habitat ? "Field controls · on" : "Field controls · paused";
    } }, "Field controls · on");
    const fog = el("button", { type: "button", class: "ademo-chip" + (state.fog ? " on" : ""), onclick: () => {
      state.fog = !state.fog; fog.classList.toggle("on", state.fog);
    } }, "Valley fog");
    const herd = el("input", { type: "range", min: "1", max: "7", value: String(state.herd), "aria-label": "Herd size",
      oninput: (e) => { state.herd = +e.target.value; } });
    panel.append(el("div", { class: "ademo-row" }, tog, fog),
      el("div", { class: "ademo-row" }, el("span", { class: "ademo-k" }, "Herd"), herd));
    stage.append(cv, brand, live, panel);
    shell.append(stage);
    root.append(shell);

    function paint() {
      const { ctx, w, h } = sizeCanvas(cv, stage);
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, "#1c3a2e"); g.addColorStop(0.45, "#2f6b4a"); g.addColorStop(1, "#1a4a55");
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
      // waterfall
      ctx.fillStyle = "#7ec8e3";
      ctx.fillRect(w * 0.62, h * 0.15, 18, h * 0.45);
      ctx.fillStyle = "rgba(180,230,255,.35)";
      ctx.fillRect(w * 0.58, h * 0.55, 40, 20);
      // river
      ctx.fillStyle = "#2a8a8a";
      ctx.beginPath(); ctx.moveTo(0, h * 0.72); ctx.quadraticCurveTo(w * 0.4, h * 0.62, w, h * 0.78);
      ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.fill();
      // arch (variant b)
      if (variant === "b") {
        ctx.fillStyle = "#6a6258";
        ctx.beginPath(); ctx.moveTo(w * 0.2, h * 0.55); ctx.lineTo(w * 0.35, h * 0.25);
        ctx.lineTo(w * 0.55, h * 0.25); ctx.lineTo(w * 0.7, h * 0.55); ctx.closePath(); ctx.fill();
        ctx.globalCompositeOperation = "destination-out";
        ctx.beginPath(); ctx.ellipse(w * 0.42, h * 0.5, w * 0.12, h * 0.18, 0, 0, Math.PI * 2); ctx.fill();
        ctx.globalCompositeOperation = "source-over";
      }
      // dinos
      const n = state.habitat ? state.herd : 0;
      for (let i = 0; i < n; i++) {
        const x = w * (0.15 + i * 0.11) + Math.sin(state.t * 0.02 + i) * 6;
        const y = h * (0.62 + (i % 2) * 0.04);
        const scale = 0.7 + (i % 3) * 0.15;
        ctx.fillStyle = i % 2 ? "#6b8f3a" : "#8f7a3a";
        ctx.beginPath();
        ctx.ellipse(x, y, 28 * scale, 14 * scale, 0, 0, Math.PI * 2); ctx.fill(); // body
        ctx.beginPath(); ctx.ellipse(x + 30 * scale, y - 18 * scale, 10 * scale, 8 * scale, 0, 0, Math.PI * 2); ctx.fill(); // head
        ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 3 * scale;
        ctx.beginPath(); ctx.moveTo(x + 28 * scale, y - 12 * scale); ctx.lineTo(x + 22 * scale, y); ctx.stroke(); // neck
        ctx.beginPath(); ctx.moveTo(x - 26 * scale, y); ctx.quadraticCurveTo(x - 50 * scale, y + 10 * scale, x - 40 * scale, y + 18 * scale); ctx.stroke();
      }
      if (state.fog) {
        ctx.fillStyle = "rgba(200,220,210,.28)"; ctx.fillRect(0, h * 0.4, w, h * 0.35);
      }
      ctx.fillStyle = "rgba(255,255,255,.7)"; ctx.font = "12px Segoe UI, sans-serif";
      ctx.fillText(variant === "b" ? "Stone gate overlook" : "River ford · live", 12, h - 14);
    }
    function tick() {
      if (state.habitat) state.t++;
      paint();
      state.raf = requestAnimationFrame(tick);
    }
    const onResize = () => paint();
    window.addEventListener("resize", onResize);
    state.raf = requestAnimationFrame(tick);
    return { destroy() { cancelAnimationFrame(state.raf); window.removeEventListener("resize", onResize); shell.remove(); } };
  }

  function deepTime(root, opts) {
    const variant = (opts && opts.variant) || "a";
    const specimens = [
      { name: "Nile crocodile", when: 0, period: "Present day", diet: "Carnivore", note: "Surviving crown-group crocodylian of African wetlands." },
      { name: "Amphicotylus", when: 0.42, period: "Late Jurassic · ~150 Ma", diet: "Fish and small animals", note: "Early neosuchian from floodplain forests." },
      { name: "Protosuchus", when: 0.72, period: "Early Jurassic · ~190 Ma", diet: "Small vertebrates", note: "Terrestrial cursorial predator, short snout." },
      { name: "Erpetosuchus", when: 0.88, period: "Late Triassic · ~220 Ma", diet: "Insects and small prey", note: "Before true crocodiles — slender archosaur relative." },
    ];
    const state = { idx: variant === "b" ? 1 : 0, playing: false, speed: 1, raf: 0 };
    const shell = el("div", { class: "ademo deep v-" + variant });
    const stage = el("div", { class: "ademo-stage" });
    const cv = el("canvas", { class: "ademo-cv", "aria-label": "Deep Time specimen" });
    const card = el("div", { class: "ademo-card" });
    const title = el("strong", {}, "");
    const meta = el("div", { class: "ademo-meta" });
    const note = el("p", {}, "");
    card.append(el("span", { class: "ademo-k" }, "Deep Time Atlas"), title, meta, note);
    const hint = el("div", { class: "ademo-hint" }, "Drag timeline · orbit specimen");
    const scrub = el("input", { type: "range", min: "0", max: "1", step: "0.001", value: "0", "aria-label": "Geologic timeline",
      oninput: (e) => { pick(+e.target.value); } });
    const axis = el("div", { class: "ademo-axis" },
      el("span", {}, "250 Ma"), el("span", {}, "Jurassic"), el("span", {}, "Today"));
    const transport = el("div", { class: "ademo-row" });
    const play = el("button", { type: "button", class: "ademo-chip", onclick: () => {
      state.playing = !state.playing; play.textContent = state.playing ? "Pause" : "Play";
    } }, "Play");
    [1, 5, 10, 20].forEach((s) => transport.append(el("button", { type: "button", class: "ademo-chip sm" + (state.speed === s ? " on" : ""),
      onclick: (e) => { state.speed = s; transport.querySelectorAll(".ademo-chip.sm").forEach((b) => b.classList.remove("on")); e.currentTarget.classList.add("on"); } }, s + "×")));
    transport.prepend(play);
    const panel = el("div", { class: "ademo-panel wide" },
      el("div", { class: "ademo-row col" }, el("span", { class: "ademo-k" }, "Geologic timeline"), scrub, axis), transport);
    stage.append(cv, card, hint, panel);
    shell.append(stage);
    root.append(shell);

    function pick(pos) {
      let best = 0; let bd = 1;
      specimens.forEach((s, i) => { const d = Math.abs(s.when - (1 - pos)); if (d < bd) { bd = d; best = i; } });
      state.idx = best;
      scrub.value = String(pos);
      const sp = specimens[best];
      title.textContent = sp.name;
      meta.replaceChildren(el("span", {}, sp.period), el("span", {}, sp.diet));
      note.textContent = sp.note;
      paint();
    }
    function paint() {
      const { ctx, w, h } = sizeCanvas(cv, stage);
      const sp = specimens[state.idx];
      const g = ctx.createLinearGradient(0, 0, 0, h);
      g.addColorStop(0, sp.when > 0.5 ? "#3a4a38" : "#2a4a45");
      g.addColorStop(1, "#1a2a28");
      ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
      // water / mist
      ctx.fillStyle = "rgba(100,160,140,.25)"; ctx.fillRect(0, h * 0.55, w, h * 0.45);
      // specimen silhouette
      const cx = w * 0.55; const cy = h * 0.52; const sc = 1.1 - sp.when * 0.2;
      ctx.fillStyle = "#1e3a28";
      ctx.beginPath();
      ctx.ellipse(cx, cy, 70 * sc, 22 * sc, -0.1, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.ellipse(cx + 78 * sc, cy - 6 * sc, 32 * sc, 14 * sc, 0.05, 0, Math.PI * 2); ctx.fill();
      ctx.fillRect(cx - 60 * sc, cy + 8 * sc, 8 * sc, 28 * sc);
      ctx.fillRect(cx - 20 * sc, cy + 10 * sc, 8 * sc, 26 * sc);
      ctx.fillRect(cx + 20 * sc, cy + 10 * sc, 8 * sc, 26 * sc);
      ctx.fillRect(cx + 50 * sc, cy + 8 * sc, 8 * sc, 28 * sc);
      // eye
      ctx.fillStyle = "#c4e88a"; ctx.beginPath(); ctx.arc(cx + 95 * sc, cy - 8 * sc, 3 * sc, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,.65)"; ctx.font = "12px Segoe UI, sans-serif";
      ctx.fillText(sp.name, 12, h - 14);
    }
    function tick() {
      if (state.playing) {
        let v = +scrub.value + 0.0004 * state.speed;
        if (v > 1) v = 0;
        pick(v);
      }
      state.raf = requestAnimationFrame(tick);
    }
    const onResize = () => paint();
    window.addEventListener("resize", onResize);
    pick(1 - specimens[state.idx].when);
    state.raf = requestAnimationFrame(tick);
    return { destroy() { cancelAnimationFrame(state.raf); window.removeEventListener("resize", onResize); shell.remove(); } };
  }

  function optical(root, opts) {
    const variant = (opts && opts.variant) || "a";
    const isField = variant !== "b";
    const works = [
      { t: "Elastic Field", c: ["#1a3a2e", "#7ec8a0"] },
      { t: "Twin Suns", c: ["#2a2030", "#e8a060"] },
      { t: "Blue Passage", c: ["#0e1a28", "#6ec0e8"] },
      { t: "Crochet Wave", c: ["#201818", "#e07070"] },
      { t: "Still Garden", c: ["#1a2818", "#a0d070"] },
      { t: "Hold Pattern", c: ["#101010", "#f0f0f0"] },
      { t: "Orbit Ink", c: ["#181828", "#a090e0"] },
      { t: "Clay Ribbon", c: ["#2a2218", "#d0a070"] },
      { t: "Unstill", c: ["#f4f0e8", "#101010"] },
    ];
    const shell = el("div", { class: "ademo optical v-" + variant + (isField ? " dark" : " light") });
    const nav = el("header", { class: "og-nav" },
      el("strong", {}, isField ? "Fieldwork Gallery" : "UNSTILL"),
      el("nav", {}, ...((isField ? ["Gallery", "Artists", "Exhibition map"] : ["Works", "Artists", "Map", "Visit"])
        .map((x) => el("button", { type: "button", class: "og-link" }, x)))),
      el("div", { class: "og-cta" },
        isField ? el("button", { type: "button", class: "ademo-chip on" }, "Book a visit")
          : [el("button", { type: "button", class: "ademo-chip" }, "Hold still"),
             el("button", { type: "button", class: "ademo-chip on" }, "Book")]));
    const hero = el("div", { class: "og-hero" });
    const cv = el("canvas", { class: "og-hero-cv", "aria-label": "Optical hero pattern" });
    const copy = el("div", { class: "og-copy" },
      el("h3", {}, isField ? "Optical Garden" : "The Optical Art Exhibition"),
      el("p", {}, isField ? "Botanical geometry that will not sit still."
        : "Nine works of optical art that will not hold still."),
      isField ? null : el("span", { class: "ademo-k" }, "Thu–Sun · 11–18"));
    hero.append(cv, copy);
    const grid = el("div", { class: "og-grid" });
    const show = isField ? works.slice(0, 6) : works;
    show.forEach((w, i) => {
      const cell = el("button", { type: "button", class: "og-cell", "aria-label": w.t });
      const c = el("canvas", { class: "og-thumb" });
      cell.append(c, el("span", {}, w.t));
      grid.append(cell);
      requestAnimationFrame(() => drawOp(c, w, i, true));
      cell.addEventListener("click", () => drawOp(cv, w, i, false));
    });
    shell.append(nav, hero, el("section", { class: "og-section" },
      el("h4", {}, isField ? "The gallery" : "Works"), grid));
    root.append(shell);

    function drawOp(canvas, work, seed, small) {
      const host = canvas.parentElement;
      const r = host.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(80, Math.floor(small ? (r.width || 120) : (hero.getBoundingClientRect().width * (isField ? 1 : 0.42))));
      const h = Math.max(60, Math.floor(small ? 90 : 200));
      canvas.width = w * dpr; canvas.height = h * dpr;
      canvas.style.width = w + "px"; canvas.style.height = h + "px";
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = work.c[0]; ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = work.c[1]; ctx.lineWidth = small ? 1.5 : 2.5;
      const n = 10 + (seed % 5);
      for (let i = 0; i < n; i++) {
        const y = (i / n) * h;
        ctx.beginPath();
        for (let x = 0; x <= w; x += 4) {
          const yy = y + Math.sin((x / w) * Math.PI * (2 + seed % 3) + seed + i * 0.4) * (8 + seed);
          if (x === 0) ctx.moveTo(x, yy); else ctx.lineTo(x, yy);
        }
        ctx.stroke();
      }
      if (!small && !isField) {
        ctx.fillStyle = work.c[1];
        for (let i = 0; i < 6; i++) {
          ctx.beginPath();
          ctx.arc(w * 0.5, h * 0.5, 10 + i * 12, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
    }
    drawOp(cv, show[0], 0, false);
    const onResize = () => drawOp(cv, show[0], 0, false);
    window.addEventListener("resize", onResize);
    return { destroy() { window.removeEventListener("resize", onResize); shell.remove(); } };
  }

  const REGISTRY = {
    alpine: alpine,
    "lost-valley": lostValley,
    "deep-time": deepTime,
    optical: optical,
  };

  global.AesopArenaDemos = {
    ids: Object.keys(REGISTRY),
    mount(id, root, opts) {
      const fn = REGISTRY[id];
      if (!fn) throw new Error("unknown arena demo: " + id);
      root.replaceChildren();
      return fn(root, opts || {});
    },
  };
})(typeof window !== "undefined" ? window : globalThis);

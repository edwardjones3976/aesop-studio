"use strict";

function updateUI(st) {
  const dot = document.getElementById("dot");
  const title = document.getElementById("statusTitle");
  const note = document.getElementById("statusNote");
  if (st && st.paired) {
    dot.className = "dot ok";
    title.textContent = `Connected (127.0.0.1:${st.port})`;
    note.textContent = "Your normal Chrome profile and logins are linked to Aesop Studio.";
  } else {
    dot.className = "dot";
    title.textContent = "Not paired yet";
    note.textContent =
      (st && st.lastError) ||
      "Open Aesop Studio in Chrome to pair automatically, or paste the pairing code below.";
  }
}

chrome.runtime.sendMessage({ type: "AESOP_STATUS" }, (st) => updateUI(st));

document.getElementById("useTabBtn").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && tab.id) {
    chrome.runtime.sendMessage({ type: "AESOP_USE_TAB", tabId: tab.id }, () => {
      document.getElementById("statusNote").textContent = `Shared tab: ${tab.title || tab.url}`;
    });
  }
});

document.getElementById("pairBtn").addEventListener("click", () => {
  const raw = document.getElementById("pairIn").value.trim();
  if (!raw) return;
  let port = 8765;
  let token = raw;
  if (raw.includes("#")) {
    const [hostPart, tok] = raw.split("#", 2);
    token = tok.trim();
    const m = hostPart.match(/:(\d+)/);
    if (m) port = Number(m[1]);
  }
  chrome.runtime.sendMessage({ type: "AESOP_PAIR", port, token }, (res) => {
    updateUI({ paired: !!(res && res.ok), port, lastError: res && res.error });
  });
});

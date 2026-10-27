"use strict";

function updateUI(st) {
  const dot = document.getElementById("dot");
  const title = document.getElementById("statusTitle");
  const note = document.getElementById("statusNote");
  const confirmBox = document.getElementById("confirmBox");
  const confirmPrompt = document.getElementById("confirmPrompt");

  if (st && st.pendingPair && st.pendingPair.port) {
    confirmBox.hidden = false;
    confirmPrompt.textContent =
      st.pendingPair.prompt || `Pair with Aesop Studio at 127.0.0.1:${st.pendingPair.port}?`;
  } else {
    confirmBox.hidden = true;
  }

  if (st && st.paired) {
    dot.className = "dot ok";
    title.textContent = `Connected (127.0.0.1:${st.port})`;
    note.textContent = st.captureError
      ? st.captureError
      : st.lastError
        ? `Last error: ${st.lastError}`
        : "Your normal Chrome profile and logins are linked to Aesop Studio.";
  } else if (st && st.pendingPair && st.pendingPair.port) {
    dot.className = "dot";
    title.textContent = "Confirmation required";
    note.textContent = `Approve pairing with 127.0.0.1:${st.pendingPair.port} below.`;
  } else {
    dot.className = "dot";
    title.textContent = "Not paired yet";
    note.textContent =
      (st && (st.captureError || st.lastError)) ||
      "Open Aesop Studio in Chrome and confirm pairing here, or paste the pairing code below.";
  }
}

function refreshStatus() {
  chrome.runtime.sendMessage({ type: "AESOP_STATUS" }, (st) => updateUI(st));
}

refreshStatus();

document.getElementById("confirmApproveBtn").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "AESOP_CONFIRM_PAIR", approve: true }, () => {
    refreshStatus();
  });
});

document.getElementById("confirmRejectBtn").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "AESOP_CONFIRM_PAIR", approve: false }, () => {
    refreshStatus();
  });
});

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
  chrome.runtime.sendMessage({ type: "AESOP_MANUAL_PAIR", port, token }, (res) => {
    updateUI({ paired: !!(res && res.ok), port, lastError: res && res.error });
  });
});

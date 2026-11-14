// Loopback pairing content script for Aesop Studio Browser Bridge.
// Runs only on http://127.0.0.1/* and http://localhost/* pages that identify as Aesop Studio.
// Never trusts a page-supplied port; background.js pairs strictly with sender.origin / sender.tab.url
// and requires explicit owner confirmation in the extension UI before first pairing or any port change.
// Never reads cookies, storage, or page credentials.
(function () {
  "use strict";

  const MIN_RESEND_MS = 1200;
  let lastSentToken = "";
  let lastSentAt = 0;

  function getOriginPort() {
    if (window.location.protocol !== "http:") return null;
    const host = window.location.hostname;
    if (host !== "127.0.0.1" && host !== "localhost") return null;
    const port = Number(window.location.port || 80);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
    return port;
  }

  function isAesopStudioPage() {
    if (!getOriginPort()) return false;
    return (
      document.title === "Aesop Studio" ||
      !!document.querySelector('meta[name="aesop-studio"]') ||
      !!document.getElementById("inspectorBtn")
    );
  }

  function sendPair(token, suppliedPort, cb) {
    const originPort = getOriginPort();
    if (!originPort) return;
    if (
      suppliedPort !== undefined &&
      suppliedPort !== null &&
      suppliedPort !== "" &&
      Number(suppliedPort) !== originPort
    ) {
      if (cb) cb({ ok: false, error: "port does not match page origin" });
      return;
    }
    const cleanToken = String(token || "").trim();
    if (!cleanToken) return;
    const now = Date.now();
    if (cleanToken === lastSentToken && now - lastSentAt < MIN_RESEND_MS) {
      return;
    }
    lastSentToken = cleanToken;
    lastSentAt = now;
    chrome.runtime.sendMessage(
      { type: "AESOP_PAIR", port: originPort, token: cleanToken },
      (resp) => {
        if (cb) cb(resp);
      }
    );
  }

  function tryPairFromDataset() {
    if (!isAesopStudioPage()) return;
    document.documentElement.dataset.aesopExtension = "2.0";
    const raw = document.documentElement.dataset.aesopBridge;
    if (!raw) return;
    try {
      const info = JSON.parse(raw);
      if (info && info.token) {
        sendPair(info.token, info.port);
      }
    } catch (_e) {
      // Ignore malformed attribute
    }
  }

  window.addEventListener("message", (ev) => {
    if (ev.source !== window || ev.origin !== window.location.origin) return;
    if (!ev.data || ev.data.type !== "AESOP_STUDIO_PAIR") return;
    if (!isAesopStudioPage()) return;
    sendPair(ev.data.token, ev.data.port, (resp) => {
      window.postMessage(
        {
          type: "AESOP_EXTENSION_PAIRED",
          ok: !!(resp && resp.ok),
          pendingConfirmation: !!(resp && (resp.pendingConfirmation || resp.pending)),
        },
        window.location.origin
      );
    });
  });

  if (isAesopStudioPage()) {
    document.documentElement.dataset.aesopExtension = "2.0";
    tryPairFromDataset();
    const obs = new MutationObserver(() => tryPairFromDataset());
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-aesop-bridge"],
    });
  }
})();

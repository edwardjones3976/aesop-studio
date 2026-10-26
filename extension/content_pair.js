// Loopback auto-pairing content script for Aesop Studio Browser Bridge.
// Runs only on 127.0.0.1 / localhost pages that identify as Aesop Studio.
// Never reads cookies, storage, or page credentials.
(function () {
  "use strict";

  function isAesopStudioPage() {
    return (
      document.title === "Aesop Studio" ||
      !!document.querySelector('meta[name="aesop-studio"]') ||
      !!document.getElementById("inspectorBtn")
    );
  }

  function tryPairFromDataset() {
    if (!isAesopStudioPage()) return;
    document.documentElement.dataset.aesopExtension = "2.0";
    const raw = document.documentElement.dataset.aesopBridge;
    if (!raw) return;
    try {
      const info = JSON.parse(raw);
      if (info && info.token && info.port) {
        chrome.runtime.sendMessage({
          type: "AESOP_PAIR",
          port: Number(info.port),
          token: String(info.token),
        });
      }
    } catch (_e) {
      // Ignore malformed attribute
    }
  }

  window.addEventListener("message", (ev) => {
    if (ev.source !== window || !ev.data || ev.data.type !== "AESOP_STUDIO_PAIR") return;
    if (!isAesopStudioPage()) return;
    const port = Number(ev.data.port || window.location.port || 8765);
    const token = String(ev.data.token || "");
    if (!token) return;
    chrome.runtime.sendMessage(
      { type: "AESOP_PAIR", port, token },
      (resp) => {
        window.postMessage(
          { type: "AESOP_EXTENSION_PAIRED", ok: !!(resp && resp.ok) },
          window.location.origin
        );
      }
    );
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

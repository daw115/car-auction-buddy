// Świat izolowany: jedyne miejsce, które widzi jednocześnie `window` strony
// i `chrome.runtime`. Przenosi ładunek w obie strony.
(() => {
  "use strict";

  const CHANNEL = "usacar-manheim-collector";

  // strona -> service worker
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.channel !== CHANNEL || !data.payload) return;

    try {
      chrome.runtime.sendMessage({ type: "manheim-capture", payload: data.payload });
    } catch (_) {
      // Service worker bywa uśpiony/przeładowany — gubienie pojedynczej próbki
      // jest tańsze niż wywalenie strony operatora wyjątkiem.
    }
  });

  // service worker -> strona (zlecenie powtórzenia wyszukiwania)
  chrome.runtime.onMessage.addListener((message) => {
    if (!message || message.type !== "manheim-replay") return;
    window.postMessage(
      {
        channel: CHANNEL,
        command: "replay",
        jobId: message.jobId,
        keyword: message.keyword,
      },
      window.location.origin,
    );
  });
})();

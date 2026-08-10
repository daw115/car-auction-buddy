// Service worker: przekazuje próbki do backendu i odbiera od niego zlecenia
// wyszukiwania, które wykonuje strona (page-hook.js).
//
// Kierunek jest odwrócony — backend nie steruje przeglądarką, tylko zostawia
// zadanie, a rozszerzenie po nie sięga. Inaczej się nie da: sesję Manheima
// trzyma BidWise przez chrome.debugger, a Chrome ma jeden slot debuggera na
// kartę, więc podpięcie Playwrighta zamyka kartę w kilka sekund.
"use strict";

const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8000",
  token: "",
  enabled: true,
  pollSeconds: 3,
};

const FLUSH_AFTER_MS = 1500;
const MAX_BUFFER = 40;

let buffer = [];
let flushTimer = null;

async function config() {
  const stored = await chrome.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...stored };
}

async function setStatus(text) {
  await chrome.storage.local.set({ lastStatus: `${new Date().toLocaleTimeString()} — ${text}` });
}

async function backendFetch(path, options) {
  const { backendUrl, token } = await config();
  if (!backendUrl) throw new Error("brak adresu backendu");
  const headers = { "Content-Type": "application/json", ...((options && options.headers) || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  return fetch(`${backendUrl.replace(/\/+$/, "")}${path}`, { ...options, headers });
}

// --------------------------------------------------------------- przekazywanie

async function flush() {
  flushTimer = null;
  if (buffer.length === 0) return;

  const batch = buffer;
  buffer = [];

  const { enabled } = await config();
  if (!enabled) return;

  try {
    const response = await backendFetch("/api/manheim/ingest", {
      method: "POST",
      body: JSON.stringify({ captures: batch }),
    });
    await setStatus(`HTTP ${response.status}, próbek: ${batch.length}`);
  } catch (error) {
    await setStatus(`błąd wysyłki: ${String(error).slice(0, 100)}`);
  }
}

function schedule() {
  if (buffer.length >= MAX_BUFFER) {
    if (flushTimer) clearTimeout(flushTimer);
    flush();
    return;
  }
  if (flushTimer) return;
  flushTimer = setTimeout(flush, FLUSH_AFTER_MS);
}

// -------------------------------------------------------------------- zadania

async function manheimTabId() {
  const tabs = await chrome.tabs.query({ url: "*://*.manheim.com/*" });
  // Karta wyszukiwarki ma pierwszeństwo — tylko w niej SPA wykonuje zapytania,
  // z których pochodzi podpatrzony szablon.
  const preferred =
    tabs.find((tab) => /search\.manheim\.com|landingPage/i.test(tab.url || "")) || tabs[0];
  return preferred ? preferred.id : null;
}

async function pollForJob() {
  const { enabled } = await config();
  if (!enabled) return;

  let job;
  try {
    const response = await backendFetch("/api/manheim/next-job", { method: "GET" });
    if (!response.ok) return;
    job = await response.json();
  } catch (_) {
    // Backend zgaszony albo brak zgody na jego origin — cisza jest lepsza niż
    // spam w statusie; operator i tak zobaczy brak wyników.
    return;
  }
  if (!job || !job.id) return;

  const tabId = await manheimTabId();
  if (tabId === null) {
    await reportJob(job.id, null, "Brak otwartej karty Manheima w tej przeglądarce.");
    return;
  }

  await setStatus(`zlecenie: ${job.keyword}`);
  try {
    // frameId 0 = ramka główna. Bez tego zlecenie idzie do wszystkich ramek,
    // a te z innym originem kończą na CORS i odsyłają błąd szybciej niż
    // ramka główna zdąży odpowiedzieć.
    await chrome.tabs.sendMessage(
      tabId,
      { type: "manheim-replay", jobId: job.id, keyword: job.keyword },
      { frameId: 0 },
    );
  } catch (error) {
    await reportJob(job.id, null, `Karta nie odpowiada: ${String(error).slice(0, 120)}`);
  }
}

async function reportJob(jobId, capture, error) {
  try {
    const response = await backendFetch("/api/manheim/ingest", {
      method: "POST",
      body: JSON.stringify({
        captures: capture ? [capture] : [],
        jobId,
        error: error || null,
      }),
    });
    await setStatus(error ? `zlecenie ${jobId}: ${error}` : `zlecenie ${jobId}: HTTP ${response.status}`);
  } catch (sendError) {
    await setStatus(`nie odesłałem zlecenia: ${String(sendError).slice(0, 100)}`);
  }
}

// Szablony żądań trzymamy poza pamięcią strony: po przeładowaniu karty (a tym
// bardziej po restarcie przeglądarki) hook startuje pusty, a bez szablonu nie
// da się powtórzyć wyszukiwania. Tak zlecenia działają od razu po starcie.
async function storeTemplate(operationName, template) {
  const { templates = {} } = await chrome.storage.local.get({ templates: {} });
  templates[operationName] = template;
  await chrome.storage.local.set({ templates });
}

async function sendTemplates(tabId, frameId) {
  const { templates = {} } = await chrome.storage.local.get({ templates: {} });
  if (!Object.keys(templates).length) return;
  try {
    await chrome.tabs.sendMessage(tabId, { type: "manheim-templates", templates }, { frameId });
  } catch (_) {
    // Karta mogła zniknąć w międzyczasie — nic się nie psuje, hook nadrobi
    // szablon przy pierwszym wyszukiwaniu.
  }
}

chrome.runtime.onMessage.addListener((message, sender) => {
  if (!message || message.type !== "manheim-capture") return;
  const payload = message.payload || {};

  if (payload.kind === "replay-result") {
    reportJob(payload.jobId, payload.capture || null, payload.error || null);
    return;
  }

  if (payload.kind === "template") {
    storeTemplate(payload.operationName, payload.template);
    return;
  }

  if (payload.kind === "templates-request") {
    if (sender.tab) sendTemplates(sender.tab.id, sender.frameId ?? 0);
    return;
  }

  buffer.push(payload);
  schedule();
});

// Alarm zamiast setInterval: service worker MV3 jest usypiany, a alarmy go budzą.
chrome.alarms.create("manheim-poll", { periodInMinutes: 0.083 }); // ~5 s
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "manheim-poll") pollForJob();
});

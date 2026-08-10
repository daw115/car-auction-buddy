// Działa w świecie MAIN, czyli w tym samym kontekście co SPA Manheima.
//
// Robi dwie rzeczy:
//   1. podsłuchuje wywołania strony (fetch/XHR) i przekazuje je do backendu,
//   2. na zlecenie POWTARZA wyszukiwanie z podanym hasłem, używając szablonu
//      podpatrzonego w ruchu aplikacji.
//
// Czemu w świecie MAIN: tylko tutaj widać własne żądania strony razem z ich
// nagłówkami autoryzacji. Świat izolowany content-scriptu ma inny `window`.
//
// Czego tu NIE ma i być nie może: chrome.debugger. Chrome dopuszcza jednego
// klienta debuggera na kartę, ten slot zajmuje BidWise i to ona utrzymuje sesję
// Manheima — podpięcie się tam (Playwright/CDP) kończy się zamknięciem karty.
(() => {
  "use strict";

  const CHANNEL = "usacar-manheim-collector";
  // Payload wyników potrafi mieć ~1,2 MB (wyniki wracają jako gzip w base64
  // w polu `stringifiedJSON`). 400 kB je ucinało i backend nie mógł ich sparsować.
  const MAX_BODY_CHARS = 3_000_000;

  // Szablony żądań podpatrzone w ruchu aplikacji — z nich składamy powtórkę.
  // Klucz to operationName GraphQL.
  const templates = new Map();

  const isInteresting = (url) =>
    typeof url === "string" &&
    /manheim\.com/.test(url) &&
    /graphql|search|listing|vehicle|inventory/i.test(url) &&
    !/\/time$|engine-api|analytics|collect\?/i.test(url);

  function emit(payload) {
    try {
      window.postMessage({ channel: CHANNEL, payload }, window.location.origin);
    } catch (_) {
      /* postMessage nie może wywrócić strony operatora */
    }
  }

  function rememberTemplate(url, method, headers, body) {
    if (!body || typeof body !== "string") return;
    let parsed;
    try {
      parsed = JSON.parse(body);
    } catch (_) {
      return;
    }
    if (!parsed || !parsed.operationName) return;
    templates.set(parsed.operationName, { url, method: method || "POST", headers, body: parsed });
  }

  function report(kind, url, method, requestBody, responseText, requestHeaders) {
    emit({
      kind,
      url,
      method: method || "GET",
      requestHeaders: requestHeaders || null,
      requestBody: (requestBody || "").slice(0, MAX_BODY_CHARS),
      responseBody: (responseText || "").slice(0, MAX_BODY_CHARS),
      capturedAt: new Date().toISOString(),
      pageUrl: window.location.href,
    });
  }

  // ----------------------------------------------------------------- podsłuch

  const originalFetch = window.fetch;
  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : input && input.url;
    const response = await originalFetch.apply(this, arguments);
    if (isInteresting(url)) {
      let headers = null;
      try {
        const raw = (init && init.headers) || (input && input.headers);
        if (raw) headers = Object.fromEntries(new Headers(raw).entries());
      } catch (_) {
        headers = null;
      }
      const body = init && typeof init.body === "string" ? init.body : null;
      rememberTemplate(url, init && init.method, headers, body);
      // Klon, żeby nie skonsumować strumienia, którego potrzebuje aplikacja.
      response
        .clone()
        .text()
        .then((text) => report("fetch", url, (init && init.method) || "GET", body, text, headers))
        .catch(() => {});
    }
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url) {
    this.__usacarMethod = method;
    this.__usacarUrl = url;
    return originalOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function (body) {
    if (isInteresting(this.__usacarUrl)) {
      if (typeof body === "string") rememberTemplate(this.__usacarUrl, this.__usacarMethod, null, body);
      this.addEventListener("load", () => {
        try {
          report("xhr", this.__usacarUrl, this.__usacarMethod, body, this.responseText, null);
        } catch (_) {}
      });
    }
    return originalSend.apply(this, arguments);
  };

  // ------------------------------------------------------------- powtarzanie

  function patchedPayload(template, changes) {
    // Manheim pakuje parametry jako JSON W STRINGU pod variables.payload.
    const body = JSON.parse(JSON.stringify(template.body));
    const variables = body.variables || (body.variables = {});
    let payload = {};
    try {
      payload = JSON.parse(variables.payload || "{}");
    } catch (_) {
      payload = {};
    }
    Object.assign(payload, changes);
    variables.payload = JSON.stringify(payload);
    return body;
  }

  // Nagłówki, których przeglądarka nie pozwala ustawić ręcznie — próba kończy
  // się wyjątkiem albo cichym odrzuceniem żądania.
  const FORBIDDEN_HEADERS = new Set([
    "host", "connection", "content-length", "origin", "referer", "cookie",
    "accept-encoding", "sec-fetch-mode", "sec-fetch-site", "sec-fetch-dest",
  ]);

  function safeHeaders(headers) {
    const out = { "Content-Type": "application/json" };
    for (const [name, value] of Object.entries(headers || {})) {
      if (!FORBIDDEN_HEADERS.has(String(name).toLowerCase())) out[name] = value;
    }
    return out;
  }

  async function callGraphql(template, changes) {
    const body = patchedPayload(template, changes);
    const request = {
      method: "POST",
      headers: safeHeaders(template.headers),
      body: JSON.stringify(body),
    };
    let response;
    try {
      response = await originalFetch.call(window, template.url, {
        ...request,
        credentials: "include",
      });
    } catch (error) {
      // Część konfiguracji CORS odrzuca żądanie z ciasteczkami. Aplikacja i tak
      // autoryzuje się nagłówkiem, więc druga próba bez nich bywa skuteczna.
      response = await originalFetch.call(window, template.url, request);
    }
    const text = await response.text();
    return { text, status: response.status };
  }

  function searchIdFrom(responseText) {
    // getSearches oddaje {"id": "...", "href": "..."} — znowu w stringu.
    const outer = JSON.parse(responseText);
    const node = outer && outer.data && outer.data.getSearches;
    const inner = JSON.parse((node && node.stringifiedJSON) || "{}");
    return inner.id || null;
  }

  async function replay(jobId, keyword) {
    // Zlecenie trafia do WSZYSTKICH ramek karty, a podramki mają inny origin —
    // ich żądanie do onesearch-api ginie na CORS. Odpowiada tylko ramka główna.
    if (window.top !== window) return;

    const searchTemplate = templates.get("getSearches");
    const executeTemplate = templates.get("getExecuteSearchId");
    if (!searchTemplate || !executeTemplate) {
      emit({
        kind: "replay-result",
        jobId,
        error:
          "Brak podpatrzonego szablonu zapytania. Zrób RAZ ręczne wyszukiwanie " +
          "na Manheimie w tej karcie — wtedy wtyczka zapamięta kształt żądania.",
      });
      return;
    }

    try {
      const created = await callGraphql(searchTemplate, { keyword });
      const searchId = searchIdFrom(created.text);
      if (!searchId) throw new Error(`getSearches nie zwróciło id (HTTP ${created.status})`);

      const results = await callGraphql(executeTemplate, { searchId, start: 0 });
      emit({
        kind: "replay-result",
        jobId,
        keyword,
        capture: {
          kind: "replay",
          url: executeTemplate.url,
          method: "POST",
          requestBody: "",
          responseBody: results.text.slice(0, MAX_BODY_CHARS),
          capturedAt: new Date().toISOString(),
          pageUrl: window.location.href,
        },
      });
    } catch (error) {
      emit({
        kind: "replay-result",
        jobId,
        error: `${String(error).slice(0, 200)} [${window.location.host}]`,
      });
    }
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.channel !== CHANNEL || data.command !== "replay") return;
    replay(data.jobId, data.keyword);
  });

  emit({
    kind: "hook-ready",
    pageUrl: window.location.href,
    capturedAt: new Date().toISOString(),
  });
})();

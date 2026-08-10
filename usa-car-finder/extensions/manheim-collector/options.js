"use strict";

const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8000",
  token: "",
  enabled: true,
  lastStatus: "—",
};

const $ = (id) => document.getElementById(id);

async function load() {
  const cfg = await chrome.storage.local.get(DEFAULTS);
  $("backendUrl").value = cfg.backendUrl;
  $("token").value = cfg.token;
  $("enabled").checked = cfg.enabled;
  $("status").textContent = `Ostatnia wysyłka: ${cfg.lastStatus}`;
}

function originOf(url) {
  try {
    return new URL(url).origin + "/*";
  } catch (_) {
    return null;
  }
}

$("save").addEventListener("click", async () => {
  const backendUrl = $("backendUrl").value.trim();
  const origin = originOf(backendUrl);
  if (!origin) {
    $("status").textContent = "Nieprawidłowy adres backendu.";
    return;
  }

  // Backend bywa zdalny (np. na Ubuntu), a adresu nie da się zaszyć w manifeście.
  // Kliknięcie Zapisz jest gestem użytkownika, więc możemy tu poprosić o dostęp.
  const granted = await chrome.permissions.request({ origins: [origin] }).catch(() => false);
  if (!granted) {
    $("status").textContent =
      `Bez zgody na ${origin} rozszerzenie nie wyśle danych do backendu.`;
    return;
  }

  await chrome.storage.local.set({
    backendUrl,
    token: $("token").value,
    enabled: $("enabled").checked,
  });
  $("status").textContent = "Zapisano.";
});

// Status wysyłki aktualizuje service worker — odświeżamy go na żywo.
chrome.storage.onChanged.addListener((changes) => {
  if (changes.lastStatus) {
    $("status").textContent = `Ostatnia wysyłka: ${changes.lastStatus.newValue}`;
  }
});

load();

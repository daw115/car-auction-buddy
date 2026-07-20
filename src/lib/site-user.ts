// Helpers do odczytu aktualnie zalogowanego użytkownika strony (ustawianego w PasswordGate).
// Wykorzystywane m.in. przy zapisie rekordów wyszukiwań aby wiedzieć kto wykonał search.

export const SITE_USERS = ["Dawid", "Pawel"] as const;
export type SiteUser = (typeof SITE_USERS)[number];

export const SITE_CURRENT_USER_KEY = "site_current_user_v1";
export const SITE_LAST_ACTIVE_KEY = "site_last_active_v1";

export function getCurrentSiteUser(): SiteUser | null {
  if (typeof window === "undefined") return null;
  const v = localStorage.getItem(SITE_CURRENT_USER_KEY);
  return (SITE_USERS as readonly string[]).includes(v ?? "") ? (v as SiteUser) : null;
}

export function bumpSiteActivity() {
  if (typeof window === "undefined") return;
  localStorage.setItem(SITE_LAST_ACTIVE_KEY, String(Date.now()));
}

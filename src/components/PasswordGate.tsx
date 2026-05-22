import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { Lock, LogOut, RefreshCw, User } from "lucide-react";
import {
  SITE_USERS,
  SITE_CURRENT_USER_KEY,
  SITE_LAST_ACTIVE_KEY,
  bumpSiteActivity,
  type SiteUser,
} from "@/lib/site-user";
import { supabase } from "@/integrations/supabase/client";

// Hasło ogólne — wymagane raz na nowego użytkownika żeby ustawić własne hasło.
const SITE_PASSWORD = "carbuddy2026";
// Sesja unlocked dla danego użytkownika (tylko nazwa, nie hasło).
const UNLOCKED_KEY = "site_unlocked_user_v1";

const CHUNK_ERROR_RE =
  /Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk \S+ failed|ChunkLoadError/i;

function isChunkError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err ?? "");
  return CHUNK_ERROR_RE.test(msg);
}

async function fetchUserHashWithRetry(
  username: string,
  attempts = 2,
): Promise<string | null> {
  let lastErr: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      const { data, error } = await supabase
        .from("site_user_passwords")
        .select("password_hash")
        .eq("username", username)
        .maybeSingle();
      if (error) throw error;
      return data?.password_hash ?? null;
    } catch (err) {
      lastErr = err;
      // Chunk-load fail — od razu propaguj, ChunkErrorOverlay to pokaże.
      if (isChunkError(err)) throw err;
      // Krótki backoff przed kolejną próbą.
      if (i < attempts - 1) await new Promise((r) => setTimeout(r, 400 * (i + 1)));
    }
  }
  throw lastErr;
}

async function saveUserHash(username: string, hash: string): Promise<void> {
  const { error } = await supabase
    .from("site_user_passwords")
    .upsert({ username, password_hash: hash, updated_at: new Date().toISOString() });
  if (error) throw error;
}
// Auto-logout: 60 minut nieaktywności.
const INACTIVITY_MS = 60 * 60 * 1000;

async function sha256(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

type Step = "pickUser" | "enterPersonal" | "setPersonal" | "unlocked";

export function PasswordGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [step, setStep] = useState<Step>("pickUser");
  const [user, setUser] = useState<SiteUser | null>(null);
  const [masterPw, setMasterPw] = useState("");
  const [personalPw, setPersonalPw] = useState("");
  const [personalPw2, setPersonalPw2] = useState("");
  const [error, setError] = useState("");
  const [diagLog, setDiagLog] = useState<string[]>([]);
  const inactivityTimer = useRef<number | null>(null);

  // Bootstrap: sprawdź czy ktoś już zalogowany i czy sesja nie wygasła.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const unlockedUser = localStorage.getItem(UNLOCKED_KEY);
    const last = Number(localStorage.getItem(SITE_LAST_ACTIVE_KEY) || 0);
    const expired = !last || Date.now() - last > INACTIVITY_MS;

    if (unlockedUser && SITE_USERS.includes(unlockedUser as SiteUser) && !expired) {
      setUser(unlockedUser as SiteUser);
      setStep("unlocked");
      bumpSiteActivity();
    } else if (expired && unlockedUser) {
      localStorage.removeItem(UNLOCKED_KEY);
    }
    setReady(true);
  }, []);

  // Tracking aktywności + auto-logout.
  useEffect(() => {
    if (step !== "unlocked") return;

    const onActivity = () => {
      bumpSiteActivity();
      scheduleLogout();
    };
    const scheduleLogout = () => {
      if (inactivityTimer.current) window.clearTimeout(inactivityTimer.current);
      inactivityTimer.current = window.setTimeout(() => {
        handleLogout();
      }, INACTIVITY_MS);
    };

    const events: Array<keyof WindowEventMap> = ["mousemove", "keydown", "click", "scroll", "touchstart"];
    events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }));
    scheduleLogout();
    bumpSiteActivity();

    return () => {
      events.forEach((e) => window.removeEventListener(e, onActivity));
      if (inactivityTimer.current) window.clearTimeout(inactivityTimer.current);
    };
  }, [step]);

  function handleLogout() {
    localStorage.removeItem(UNLOCKED_KEY);
    setUser(null);
    setStep("pickUser");
    setMasterPw("");
    setPersonalPw("");
    setPersonalPw2("");
    setError("");
  }

  async function hardRefreshApp() {
    try {
      // Czyść SW/cache jeśli istnieją — wymusza ponowny pobór modułów po stale-deploy.
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
      if ("serviceWorker" in navigator) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map((r) => r.unregister()));
      }
    } catch (err) {
      console.warn("hardRefreshApp cleanup failed", err);
    }
    // Bust query string żeby ominąć HTTP cache.
    const url = new URL(window.location.href);
    url.searchParams.set("_r", String(Date.now()));
    window.location.replace(url.toString());
  }


  function diag(msg: string) {
    setDiagLog((prev) => [`${new Date().toLocaleTimeString()}  ${msg}`, ...prev].slice(0, 20));
  }

  async function pickUser(u: SiteUser) {
    diag(`pickUser START — wybrano: ${u}`);
    setUser(u);
    setError("");
    try {
      const stored = await fetchUserHashWithRetry(u);
      diag(`pickUser OK — fetchUserHash zwróciło: ${stored ? "tak" : "nie"}`);
      setStep(stored ? "enterPersonal" : "setPersonal");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      diag(`pickUser BŁĄD — ${msg}`);
      console.error(err);

      if (isChunkError(err)) {
        // Re-dispatch żeby ChunkErrorOverlay (globalny) pokazał overlay z reloadem.
        window.dispatchEvent(new ErrorEvent("error", { message: msg, error: err }));
        setError("Aplikacja wymaga odświeżenia (chunk nie załadował się).");
        return;
      }

      // Sieć/Supabase padło — pozwól przejść dalej, żeby przycisk „Wejdź"
      // mógł ponowić zapytanie. Brak hasha = traktuj jak pierwsze logowanie.
      diag("pickUser FALLBACK — przechodzę do ekranu hasła mimo błędu");
      setError("Połączenie z bazą zawiodło — spróbuj ponownie wpisując hasło.");
      setStep("enterPersonal");
    }
  }

  async function submitPersonal(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    try {
      const stored = await fetchUserHash(user);
      const hash = await sha256(personalPw);
      if (stored && hash === stored) {
        localStorage.setItem(UNLOCKED_KEY, user);
        localStorage.setItem(SITE_CURRENT_USER_KEY, user);
        bumpSiteActivity();
        setPersonalPw("");
        setStep("unlocked");
      } else {
        setError("Nieprawidłowe hasło osobiste");
        setPersonalPw("");
      }
    } catch (err) {
      setError("Błąd połączenia z bazą");
      console.error(err);
    }
  }

  async function submitSetup(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    if (masterPw !== SITE_PASSWORD) {
      setError("Nieprawidłowe hasło ogólne");
      setMasterPw("");
      return;
    }
    if (personalPw.length < 4) {
      setError("Hasło osobiste musi mieć min. 4 znaki");
      return;
    }
    if (personalPw !== personalPw2) {
      setError("Hasła nie są identyczne");
      return;
    }
    try {
      const hash = await sha256(personalPw);
      await saveUserHash(user, hash);
      localStorage.setItem(UNLOCKED_KEY, user);
      localStorage.setItem(SITE_CURRENT_USER_KEY, user);
      bumpSiteActivity();
      setMasterPw("");
      setPersonalPw("");
      setPersonalPw2("");
      setStep("unlocked");
    } catch (err) {
      setError("Nie udało się zapisać hasła");
      console.error(err);
    }
  }

  if (!ready) return null;

  if (step === "unlocked" && user) {
    return (
      <>
        {children}
        <button
          onClick={handleLogout}
          className="fixed bottom-3 right-3 z-50 inline-flex items-center gap-1.5 rounded-full bg-card/90 backdrop-blur border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-card shadow-sm"
          title="Wyloguj"
        >
          <User className="h-3.5 w-3.5" />
          <span className="font-medium text-foreground">{user}</span>
          <LogOut className="h-3.5 w-3.5" />
        </button>
      </>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm p-6">
        <div className="flex flex-col items-center text-center mb-5">
          <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center mb-3">
            <Lock className="h-5 w-5 text-primary" />
          </div>
          <h1 className="text-lg font-semibold">
            {step === "pickUser" && "Kim jesteś?"}
            {step === "enterPersonal" && `Hasło — ${user}`}
            {step === "setPersonal" && `Pierwsze logowanie — ${user}`}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {step === "pickUser" && "Wybierz swoje konto."}
            {step === "enterPersonal" && "Podaj swoje hasło osobiste."}
            {step === "setPersonal" &&
              "Podaj hasło ogólne, a następnie ustaw własne hasło dostępu."}
          </p>
        </div>

        {step === "pickUser" && (
          <>
            <div className="grid grid-cols-2 gap-2">
              {SITE_USERS.map((u) => (
                <Button
                  key={u}
                  variant="outline"
                  className="h-12 justify-start gap-2"
                  onClick={() => pickUser(u)}
                >
                  <User className="h-4 w-4" />
                  {u}
                </Button>
              ))}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="mt-3 w-full text-xs text-muted-foreground"
              onClick={hardRefreshApp}
              title="Wymuś ponowną inicjalizację aplikacji (czyści cache modułów i sesji UI)"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Odśwież UI
            </Button>

            {/* Panel diagnostyczny */}
            <div className="mt-4 rounded-md border bg-muted/40 p-3 text-xs space-y-2">
              <div className="font-semibold text-foreground flex items-center gap-1.5">
                <span className="inline-block h-2 w-2 rounded-full bg-primary" />
                Diagnostyka logowania
              </div>
              <div className="space-y-1 text-muted-foreground">
                <div className="flex justify-between">
                  <span>Lista użytkowników:</span>
                  <span className="font-mono text-foreground">{SITE_USERS.length} użytkowników</span>
                </div>
                <div className="flex justify-between">
                  <span>Wybrany użytkownik:</span>
                  <span className="font-mono text-foreground">{user ?? "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span>Handler pickUser:</span>
                  <span className={diagLog[0]?.includes("BŁĄD") ? "text-destructive" : "text-emerald-500"}>
                    {diagLog[1]?.includes("START") && !diagLog[0]?.includes("BŁĄD") ? "działa" : diagLog[0]?.includes("BŁĄD") ? "błąd" : "nie testowano"}
                  </span>
                </div>
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="w-full text-xs"
                onClick={() => pickUser("Dawid")}
                disabled={user === "Dawid"}
              >
                Testuj pickUser (Dawid)
              </Button>
              {diagLog.length > 1 && (
                <pre className="max-h-28 overflow-auto rounded bg-background p-2 text-[10px] font-mono whitespace-pre-wrap">
                  {diagLog.join("\n")}
                </pre>
              )}
            </div>
          </>
        )}

        {step === "enterPersonal" && (
          <form onSubmit={submitPersonal} className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="personal-pw">Hasło osobiste</Label>
              <Input
                id="personal-pw"
                type="password"
                autoFocus
                value={personalPw}
                onChange={(e) => {
                  setPersonalPw(e.target.value);
                  setError("");
                }}
              />
              {error && <p className="text-xs text-destructive">{error}</p>}
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setStep("pickUser");
                  setUser(null);
                  setError("");
                  setPersonalPw("");
                }}
              >
                Wstecz
              </Button>
              <Button type="submit" className="flex-1" disabled={!personalPw}>
                Wejdź
              </Button>
            </div>
          </form>
        )}

        {step === "setPersonal" && (
          <form onSubmit={submitSetup} className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="master-pw">Hasło ogólne</Label>
              <Input
                id="master-pw"
                type="password"
                autoFocus
                value={masterPw}
                onChange={(e) => {
                  setMasterPw(e.target.value);
                  setError("");
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-pw">Twoje nowe hasło</Label>
              <Input
                id="new-pw"
                type="password"
                value={personalPw}
                onChange={(e) => {
                  setPersonalPw(e.target.value);
                  setError("");
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-pw2">Powtórz nowe hasło</Label>
              <Input
                id="new-pw2"
                type="password"
                value={personalPw2}
                onChange={(e) => {
                  setPersonalPw2(e.target.value);
                  setError("");
                }}
              />
              {error && <p className="text-xs text-destructive">{error}</p>}
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setStep("pickUser");
                  setUser(null);
                  setError("");
                  setMasterPw("");
                  setPersonalPw("");
                  setPersonalPw2("");
                }}
              >
                Wstecz
              </Button>
              <Button
                type="submit"
                className="flex-1"
                disabled={!masterPw || !personalPw || !personalPw2}
              >
                Ustaw hasło i wejdź
              </Button>
            </div>
          </form>
        )}
      </Card>
    </div>
  );
}

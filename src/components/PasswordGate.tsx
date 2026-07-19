import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Lock, LogOut, RefreshCw, Trash2, User } from "lucide-react";
import {
  SITE_USERS,
  SITE_CURRENT_USER_KEY,
  SITE_LAST_ACTIVE_KEY,
  bumpSiteActivity,
  type SiteUser,
} from "@/lib/site-user";
import {
  siteUserDeletePassword,
  siteUserHasPassword,
  siteUserLogin,
  siteUserSetPassword,
} from "@/functions/site-auth.functions";

// Hasło ogólne walidowane wyłącznie po stronie serwera.
const UNLOCKED_KEY = "site_unlocked_user_v1";

const CHUNK_ERROR_RE =
  /Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk \S+ failed|ChunkLoadError/i;

function isChunkError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err ?? "");
  return CHUNK_ERROR_RE.test(msg);
}

async function userHasPasswordWithRetry(
  username: SiteUser,
  attempts = 2,
): Promise<boolean> {
  let lastErr: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await siteUserHasPassword({ data: { username } });
      return res.exists;
    } catch (err) {
      lastErr = err;
      if (isChunkError(err)) throw err;
      if (i < attempts - 1) await new Promise((r) => setTimeout(r, 400 * (i + 1)));
    }
  }
  throw lastErr;
}

// Auto-logout: 60 minut nieaktywności.
const INACTIVITY_MS = 60 * 60 * 1000;

type Step = "pickUser" | "enterPersonal" | "setPersonal" | "unlocked";

export function PasswordGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [step, setStep] = useState<Step>("pickUser");
  const [user, setUser] = useState<SiteUser | null>(null);
  const [masterPw, setMasterPw] = useState("");
  const [personalPw, setPersonalPw] = useState("");
  const [personalPw2, setPersonalPw2] = useState("");
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<SiteUser | null>(null);
  const [deleteMasterPw, setDeleteMasterPw] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
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

  async function pickUser(u: SiteUser) {
    setUser(u);
    setError("");
    try {
      const exists = await userHasPasswordWithRetry(u);
      setStep(exists ? "enterPersonal" : "setPersonal");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(err);

      if (isChunkError(err)) {
        window.dispatchEvent(new ErrorEvent("error", { message: msg, error: err }));
        setError("Aplikacja wymaga odświeżenia (chunk nie załadował się).");
        return;
      }

      setError("Połączenie z serwerem zawiodło — spróbuj ponownie wpisując hasło.");
      setStep("enterPersonal");
    }
  }

  async function submitPersonal(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    try {
      const res = await siteUserLogin({ data: { username: user, password: personalPw } });
      if (res.ok) {
        localStorage.setItem(UNLOCKED_KEY, user);
        localStorage.setItem(SITE_CURRENT_USER_KEY, user);
        bumpSiteActivity();
        setPersonalPw("");
        setStep("unlocked");
      } else if (res.error === "rate_limited") {
        const mins = Math.ceil((res.retryAfterSeconds ?? 60) / 60);
        setError(`Zbyt wiele nieudanych prób. Spróbuj ponownie za ~${mins} min.`);
        setPersonalPw("");
      } else {
        const remaining =
          typeof res.attemptsRemaining === "number"
            ? ` (pozostało prób: ${res.attemptsRemaining})`
            : "";
        setError(`Nieprawidłowe hasło osobiste${remaining}`);
        setPersonalPw("");
      }
    } catch (err) {
      setError("Błąd połączenia z serwerem");
      console.error(err);
    }
  }

  async function submitSetup(e: FormEvent) {
    e.preventDefault();
    if (!user) return;
    if (personalPw.length < 4) {
      setError("Hasło osobiste musi mieć min. 4 znaki");
      return;
    }
    if (personalPw !== personalPw2) {
      setError("Hasła nie są identyczne");
      return;
    }
    try {
      const res = await siteUserSetPassword({
        data: { username: user, masterPassword: masterPw, newPassword: personalPw },
      });
      if (!res.ok) {
        if (res.error === "not_configured") {
          setError(
            "Serwer nie ma skonfigurowanego hasła ogólnego (SITE_MASTER_PASSWORD). Skontaktuj się z administratorem.",
          );
        } else {
          setError("Nieprawidłowe hasło ogólne");
        }
        setMasterPw("");
        return;
      }
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
            <div key={refreshTick} className="grid grid-cols-2 gap-2">
              {SITE_USERS.map((u) => (
                <div key={u} className="relative group">
                  <Button
                    variant="outline"
                    className="h-12 w-full justify-start gap-2 pr-9"
                    onClick={() => pickUser(u)}
                  >
                    <User className="h-4 w-4" />
                    {u}
                  </Button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteTarget(u);
                      setDeleteMasterPw("");
                      setDeleteError("");
                    }}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1.5 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 opacity-60 hover:opacity-100"
                    title={`Usuń profil ${u}`}
                    aria-label={`Usuń profil ${u}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
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

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
            setDeleteMasterPw("");
            setDeleteError("");
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Usunąć profil „{deleteTarget}"?</AlertDialogTitle>
            <AlertDialogDescription>
              Ta operacja usuwa hasło osobiste użytkownika. Przy następnym logowaniu
              trzeba będzie ustawić je od nowa (wymagane hasło ogólne). Aby potwierdzić,
              podaj hasło ogólne.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="delete-master-pw">Hasło ogólne</Label>
            <Input
              id="delete-master-pw"
              type="password"
              autoFocus
              value={deleteMasterPw}
              onChange={(e) => {
                setDeleteMasterPw(e.target.value);
                setDeleteError("");
              }}
            />
            {deleteError && <p className="text-xs text-destructive">{deleteError}</p>}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Anuluj</AlertDialogCancel>
            <AlertDialogAction
              disabled={!deleteMasterPw || deleteBusy}
              onClick={async (e) => {
                e.preventDefault();
                if (!deleteTarget) return;
                setDeleteBusy(true);
                try {
                  const res = await siteUserDeletePassword({
                    data: {
                      username: deleteTarget,
                      masterPassword: deleteMasterPw,
                    },
                  });
                  if (res.ok) {
                    setDeleteTarget(null);
                    setDeleteMasterPw("");
                    setDeleteError("");
                    setRefreshTick((t) => t + 1);
                  } else if (res.error === "not_configured") {
                    setDeleteError(
                      "Serwer nie ma skonfigurowanego hasła ogólnego (SITE_MASTER_PASSWORD).",
                    );
                  } else {
                    setDeleteError("Nieprawidłowe hasło ogólne");
                  }
                } catch (err) {
                  console.error(err);
                  setDeleteError("Nie udało się usunąć profilu");
                } finally {
                  setDeleteBusy(false);
                }
              }}
            >
              Usuń
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AlertTriangle, RefreshCw, Loader2 } from "lucide-react";

// Wzorce charakterystyczne dla nieudanego dynamicznego importu chunku Vite
// (typowe po nowym deployu — stary index.html odwołuje się do nieistniejących
// hashowanych plików w /assets).
const CHUNK_ERROR_PATTERNS = [
  /Failed to fetch dynamically imported module/i,
  /Importing a module script failed/i,
  /error loading dynamically imported module/i,
  /Loading chunk \S+ failed/i,
  /ChunkLoadError/i,
];

function isChunkError(msg: unknown): boolean {
  if (!msg) return false;
  const text = typeof msg === "string" ? msg : msg instanceof Error ? msg.message : String(msg);
  return CHUNK_ERROR_PATTERNS.some((re) => re.test(text));
}

async function hardRefresh() {
  try {
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
    }
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
  } catch (err) {
    console.warn("ChunkErrorOverlay cleanup failed", err);
  }
  const url = new URL(window.location.href);
  url.searchParams.set("_r", String(Date.now()));
  window.location.replace(url.toString());
}

export function ChunkErrorOverlay() {
  const [visible, setVisible] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const trigger = (text: string) => {
      setDetail(text);
      setVisible(true);
    };

    const onError = (e: ErrorEvent) => {
      if (isChunkError(e.message) || isChunkError(e.error)) {
        trigger(e.message || String(e.error));
      }
    };
    const onRejection = (e: PromiseRejectionEvent) => {
      if (isChunkError(e.reason)) {
        const r = e.reason;
        trigger(typeof r === "string" ? r : r?.message ?? String(r));
      }
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  if (!visible) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 backdrop-blur-sm p-4"
    >
      <Card className="w-full max-w-md p-6 space-y-4 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 shrink-0 rounded-full bg-destructive/10 flex items-center justify-center">
            <AlertTriangle className="h-5 w-5 text-destructive" />
          </div>
          <div className="space-y-1">
            <h2 className="text-base font-semibold">Aktualizacja aplikacji wymaga odświeżenia</h2>
            <p className="text-sm text-muted-foreground">
              Przeglądarka próbowała załadować moduł, który nie jest już dostępny — najczęściej oznacza to,
              że pojawiła się nowa wersja aplikacji.
            </p>
          </div>
        </div>

        <div className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground space-y-1">
          <p className="font-medium text-foreground">Co zrobić:</p>
          <ol className="list-decimal list-inside space-y-0.5">
            <li>Kliknij „Odśwież teraz" poniżej.</li>
            <li>Jeśli to nie pomoże — wciśnij Ctrl/Cmd + Shift + R (twardy reload).</li>
            <li>W ostateczności wyloguj się i zaloguj ponownie.</li>
          </ol>
          {detail && (
            <p className="pt-2 text-[10px] opacity-70 break-all font-mono">{detail}</p>
          )}
        </div>

        <div className="flex gap-2 justify-end">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setVisible(false)}
            disabled={refreshing}
          >
            Zignoruj
          </Button>
          <Button
            size="sm"
            onClick={async () => {
              setRefreshing(true);
              await hardRefresh();
            }}
            disabled={refreshing}
          >
            {refreshing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Odśwież teraz
          </Button>
        </div>
      </Card>
    </div>
  );
}

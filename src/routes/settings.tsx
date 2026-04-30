import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import { getConfig, testAnthropic } from "@/server/api.functions";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ArrowLeft, CheckCircle2, XCircle, Loader2, KeyRound, ShieldCheck } from "lucide-react";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

type EnvFlags = {
  ANTHROPIC_API_KEY: boolean;
  ANTHROPIC_MODEL: string;
  ANTHROPIC_BASE_URL: string;
  SCRAPER_BASE_URL: boolean;
  SCRAPER_API_TOKEN: boolean;
};

type TestResult =
  | {
      ok: true;
      configured: true;
      model: string;
      baseUrl?: string;
      sample?: string;
      usage?: { input_tokens: number; output_tokens: number };
    }
  | { ok: false; configured: boolean; model?: string; status?: number; error: string };

const ANTHROPIC_MODEL_OPTIONS = [
  "claude-opus-4-7",
  "claude-sonnet-4-6",
  "claude-haiku-4-5",
] as const;

function SettingsPage() {
  const getConfigFn = useServerFn(getConfig);
  const testFn = useServerFn(testAnthropic);

  const [env, setEnv] = useState<EnvFlags | null>(null);
  const [model, setModel] = useState("");
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);

  useEffect(() => {
    let mounted = true;
    getConfigFn()
      .then((res) => {
        if (!mounted) return;
        setEnv(res.env as EnvFlags);
      })
      .catch((e) => toast.error(`Nie udało się pobrać konfiguracji: ${e.message}`))
      .finally(() => mounted && setLoading(false));
    return () => {
      mounted = false;
    };
  }, [getConfigFn]);

  const handleTest = async () => {
    setTesting(true);
    setResult(null);
    try {
      const r = (await testFn({ data: { model: model || undefined } })) as TestResult;
      setResult(r);
      if (r.ok) toast.success("Połączenie z Anthropic OK");
      else toast.error("Test nie powiódł się");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setResult({ ok: false, configured: true, error: msg });
      toast.error(msg);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-3xl px-6 py-10">
        <div className="mb-6 flex items-center justify-between">
          <Link
            to="/"
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> Wróć do panelu
          </Link>
          <Badge variant="outline" className="gap-1">
            <ShieldCheck className="h-3 w-3" /> Sekrety przechowywane w Lovable Cloud
          </Badge>
        </div>

        <h1 className="mb-2 text-3xl font-bold tracking-tight">Ustawienia — Anthropic API</h1>
        <p className="mb-8 text-sm text-muted-foreground">
          Klucz <code className="rounded bg-muted px-1">ANTHROPIC_API_KEY</code> nigdy nie jest
          wyświetlany w interfejsie. Możesz tylko sprawdzić, czy jest skonfigurowany i działa.
        </p>

        <Card className="p-6">
          <div className="mb-4 flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Status klucza</h2>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Ładowanie...
            </div>
          ) : env ? (
            <div className="space-y-3 text-sm">
              <Row
                label="ANTHROPIC_API_KEY"
                value={
                  env.ANTHROPIC_API_KEY ? (
                    <Badge className="gap-1 bg-emerald-500/15 text-emerald-700 hover:bg-emerald-500/20 dark:text-emerald-400">
                      <CheckCircle2 className="h-3 w-3" /> Skonfigurowany
                    </Badge>
                  ) : (
                    <Badge variant="destructive" className="gap-1">
                      <XCircle className="h-3 w-3" /> Brak
                    </Badge>
                  )
                }
              />
              <Row label="ANTHROPIC_MODEL (domyślny)" value={<code>{env.ANTHROPIC_MODEL}</code>} />
              <Row label="ANTHROPIC_BASE_URL" value={<code>{env.ANTHROPIC_BASE_URL}</code>} />
            </div>
          ) : null}

          {env && !env.ANTHROPIC_API_KEY && (
            <div className="mt-5 rounded-md border border-amber-500/30 bg-amber-500/10 p-4 text-sm">
              <p className="font-medium text-amber-700 dark:text-amber-400">
                Klucz nie jest jeszcze ustawiony.
              </p>
              <p className="mt-1 text-muted-foreground">
                Aby dodać <code>ANTHROPIC_API_KEY</code> bezpiecznie (poza kodem i UI), poproś
                Lovable o jego dodanie — pojawi się chroniony formularz, w którym wpiszesz wartość.
                Wartość trafi prosto do sekretów Lovable Cloud i nie będzie widoczna w aplikacji.
              </p>
            </div>
          )}
        </Card>

        <Card className="mt-6 p-6">
          <h2 className="mb-1 text-lg font-semibold">Test połączenia</h2>
          <p className="mb-4 text-sm text-muted-foreground">
            Wykonuje minimalne zapytanie <code>messages</code> (max 16 tokenów) i raportuje wynik.
          </p>

          <div className="mb-4">
            <Label htmlFor="model">Model AI</Label>
            <select
              id="model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="mt-1.5 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="">
                Domyślny ({env?.ANTHROPIC_MODEL || "claude-sonnet-4-6"})
              </option>
              {ANTHROPIC_MODEL_OPTIONS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-muted-foreground">
              Wybierz konkretny model lub zostaw domyślny ze zmiennej <code>ANTHROPIC_MODEL</code>.
            </p>
          </div>

          <Button onClick={handleTest} disabled={testing || !env?.ANTHROPIC_API_KEY}>
            {testing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Testuję...
              </>
            ) : (
              "Wykonaj test"
            )}
          </Button>

          {result && (
            <>
              <Separator className="my-5" />
              {result.ok ? (
                <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm">
                  <div className="mb-2 flex items-center gap-2 font-medium text-emerald-700 dark:text-emerald-400">
                    <CheckCircle2 className="h-4 w-4" /> Połączenie OK
                  </div>
                  <div className="space-y-1 text-muted-foreground">
                    <div>Model: <code>{result.model}</code></div>
                    {result.baseUrl && <div>Endpoint: <code>{result.baseUrl}</code></div>}
                    {result.sample && (
                      <div>
                        Odpowiedź (próbka): <code>{result.sample}</code>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm">
                  <div className="mb-2 flex items-center gap-2 font-medium text-destructive">
                    <XCircle className="h-4 w-4" /> Test nieudany
                  </div>
                  <div className="space-y-1 text-muted-foreground">
                    {result.status && <div>Status HTTP: {result.status}</div>}
                    {result.model && <div>Model: <code>{result.model}</code></div>}
                    <div className="break-words">Błąd: {result.error}</div>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border/50 pb-2 last:border-0 last:pb-0">
      <span className="text-muted-foreground">{label}</span>
      <span>{value}</span>
    </div>
  );
}

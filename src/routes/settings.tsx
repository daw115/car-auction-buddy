import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import { getConfig, testAnthropic, testGemini } from "@/server/api.functions";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ArrowLeft, CheckCircle2, XCircle, Loader2, KeyRound, ShieldCheck, Zap } from "lucide-react";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

type EnvFlags = {
  ANTHROPIC_API_KEY: boolean;
  ANTHROPIC_MODEL: string;
  ANTHROPIC_BASE_URL: string;
  GEMINI_API_KEY: boolean;
  GEMINI_MODEL: string;
  AI_PROVIDER: "anthropic" | "gemini";
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

const GEMINI_MODEL_OPTIONS = [
  "gemini-2.5-flash",
  "gemini-2.5-pro",
  "gemini-2.0-flash",
] as const;

function SettingsPage() {
  const getConfigFn = useServerFn(getConfig);
  const testAnthropicFn = useServerFn(testAnthropic);
  const testGeminiFn = useServerFn(testGemini);

  const [env, setEnv] = useState<EnvFlags | null>(null);
  const [anthropicModel, setAnthropicModel] = useState("");
  const [geminiModel, setGeminiModel] = useState("");
  const [loading, setLoading] = useState(true);
  const [testingAnthropic, setTestingAnthropic] = useState(false);
  const [testingGemini, setTestingGemini] = useState(false);
  const [anthropicResult, setAnthropicResult] = useState<TestResult | null>(null);
  const [geminiResult, setGeminiResult] = useState<TestResult | null>(null);

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

  const handleTestAnthropic = async () => {
    setTestingAnthropic(true);
    setAnthropicResult(null);
    try {
      const r = (await testAnthropicFn({ data: { model: anthropicModel || undefined } })) as TestResult;
      setAnthropicResult(r);
      if (r.ok) toast.success("Połączenie z Anthropic OK");
      else toast.error("Test Anthropic nie powiódł się");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setAnthropicResult({ ok: false, configured: true, error: msg });
      toast.error(msg);
    } finally {
      setTestingAnthropic(false);
    }
  };

  const handleTestGemini = async () => {
    setTestingGemini(true);
    setGeminiResult(null);
    try {
      const r = (await testGeminiFn({ data: { model: geminiModel || undefined } })) as TestResult;
      setGeminiResult(r);
      if (r.ok) toast.success("Połączenie z Gemini OK");
      else toast.error("Test Gemini nie powiódł się");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setGeminiResult({ ok: false, configured: true, error: msg });
      toast.error(msg);
    } finally {
      setTestingGemini(false);
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

        <h1 className="mb-2 text-3xl font-bold tracking-tight">Ustawienia — AI</h1>
        <p className="mb-8 text-sm text-muted-foreground">
          Konfiguracja dostawców AI. Aplikacja automatycznie wykrywa dostępne klucze i wybiera
          dostawcę. Jeśli oba są skonfigurowane, Anthropic jest domyślny, a Gemini działa jako fallback.
        </p>

        {/* Active provider indicator */}
        {env && (
          <div className="mb-6 flex items-center gap-3 rounded-lg border border-primary/20 bg-primary/5 p-4">
            <Zap className="h-5 w-5 text-primary" />
            <div className="text-sm">
              <span className="font-medium">Aktywny dostawca AI:</span>{" "}
              <Badge variant="secondary" className="ml-1">
                {env.AI_PROVIDER === "gemini" ? "Google Gemini" : "Anthropic Claude"}
              </Badge>
              {env.ANTHROPIC_API_KEY && env.GEMINI_API_KEY && (
                <span className="ml-2 text-muted-foreground">
                  (fallback: {env.AI_PROVIDER === "gemini" ? "Anthropic" : "Gemini"})
                </span>
              )}
            </div>
          </div>
        )}

        {/* Anthropic Card */}
        <Card className="p-6">
          <div className="mb-4 flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-semibold">Anthropic Claude</h2>
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
              <Row label="ANTHROPIC_MODEL" value={<code>{env.ANTHROPIC_MODEL}</code>} />
              <Row label="ANTHROPIC_BASE_URL" value={<code>{env.ANTHROPIC_BASE_URL}</code>} />
            </div>
          ) : null}

          <Separator className="my-4" />

          <div className="mb-4">
            <Label htmlFor="anthropic-model">Model do testu</Label>
            <select
              id="anthropic-model"
              value={anthropicModel}
              onChange={(e) => setAnthropicModel(e.target.value)}
              className="mt-1.5 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="">Domyślny ({env?.ANTHROPIC_MODEL || "claude-sonnet-4-6"})</option>
              {ANTHROPIC_MODEL_OPTIONS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          <Button onClick={handleTestAnthropic} disabled={testingAnthropic || !env?.ANTHROPIC_API_KEY}>
            {testingAnthropic ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Testuję...</>
            ) : (
              "Testuj Anthropic"
            )}
          </Button>

          {anthropicResult && (
            <>
              <Separator className="my-5" />
              <TestResultDisplay result={anthropicResult} />
            </>
          )}
        </Card>

        {/* Gemini Card */}
        <Card className="mt-6 p-6">
          <div className="mb-4 flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-blue-500" />
            <h2 className="text-lg font-semibold">Google Gemini (AI Studio)</h2>
            <Badge variant="outline" className="text-xs">Fallback</Badge>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Ładowanie...
            </div>
          ) : env ? (
            <div className="space-y-3 text-sm">
              <Row
                label="GEMINI_API_KEY"
                value={
                  env.GEMINI_API_KEY ? (
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
              <Row label="GEMINI_MODEL" value={<code>{env.GEMINI_MODEL}</code>} />
            </div>
          ) : null}

          {env && !env.GEMINI_API_KEY && (
            <div className="mt-4 rounded-md border border-blue-500/30 bg-blue-500/10 p-4 text-sm">
              <p className="font-medium text-blue-700 dark:text-blue-400">
                Klucz Gemini nie jest ustawiony.
              </p>
              <p className="mt-1 text-muted-foreground">
                Aby dodać <code>GEMINI_API_KEY</code>, wygeneruj klucz w{" "}
                <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="underline text-blue-600 dark:text-blue-400">
                  Google AI Studio
                </a>{" "}
                i poproś Lovable o dodanie sekretu <code>GEMINI_API_KEY</code>.
              </p>
              <p className="mt-1 text-muted-foreground">
                Opcjonalnie ustaw <code>GEMINI_MODEL</code> (domyślnie: gemini-2.5-flash)
                i <code>AI_PROVIDER=gemini</code> aby używać Gemini jako głównego dostawcy.
              </p>
            </div>
          )}

          <Separator className="my-4" />

          <div className="mb-4">
            <Label htmlFor="gemini-model">Model do testu</Label>
            <select
              id="gemini-model"
              value={geminiModel}
              onChange={(e) => setGeminiModel(e.target.value)}
              className="mt-1.5 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="">Domyślny ({env?.GEMINI_MODEL || "gemini-2.5-flash"})</option>
              {GEMINI_MODEL_OPTIONS.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          <Button onClick={handleTestGemini} disabled={testingGemini || !env?.GEMINI_API_KEY} variant="outline">
            {testingGemini ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Testuję...</>
            ) : (
              "Testuj Gemini"
            )}
          </Button>

          {geminiResult && (
            <>
              <Separator className="my-5" />
              <TestResultDisplay result={geminiResult} />
            </>
          )}
        </Card>

        {/* Info about fallback */}
        <Card className="mt-6 p-6 border-dashed">
          <h3 className="mb-2 text-sm font-semibold">Jak działa fallback?</h3>
          <ul className="space-y-1.5 text-sm text-muted-foreground list-disc pl-5">
            <li>Aplikacja najpierw próbuje użyć <strong>głównego dostawcy</strong> (domyślnie Anthropic).</li>
            <li>Jeśli wywołanie się nie powiedzie, automatycznie przełącza się na <strong>zapasowego dostawcę</strong> (Gemini).</li>
            <li>Aby zmienić głównego dostawcę, ustaw sekret <code>AI_PROVIDER=gemini</code>.</li>
            <li>Jeśli tylko jeden klucz jest skonfigurowany, aplikacja użyje tego dostawcy bez fallbacku.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}

function TestResultDisplay({ result }: { result: TestResult }) {
  if (result.ok) {
    return (
      <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm">
        <div className="mb-2 flex items-center gap-2 font-medium text-emerald-700 dark:text-emerald-400">
          <CheckCircle2 className="h-4 w-4" /> Połączenie OK
        </div>
        <div className="space-y-1 text-muted-foreground">
          <div>Model: <code>{result.model}</code></div>
          {result.baseUrl && <div>Endpoint: <code>{result.baseUrl}</code></div>}
          {result.usage && (
            <div>
              Tokeny: <code>{result.usage.input_tokens} in + {result.usage.output_tokens} out</code>
            </div>
          )}
          {result.sample && <div>Odpowiedź: <code>{result.sample}</code></div>}
        </div>
      </div>
    );
  }
  return (
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

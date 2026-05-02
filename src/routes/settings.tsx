import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import { getConfig, testAnthropic, testGemini, updateConfig } from "@/server/api.functions";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import {
  ArrowLeft, CheckCircle2, XCircle, Loader2, KeyRound,
  ShieldCheck, Zap, Shield, Gauge, AlertTriangle,
} from "lucide-react";

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

type ConfigRow = {
  ai_analysis_mode: string;
  ai_fallback_mode: string;
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
  const updateConfigFn = useServerFn(updateConfig);

  const [env, setEnv] = useState<EnvFlags | null>(null);
  const [config, setConfig] = useState<ConfigRow | null>(null);
  const [anthropicModel, setAnthropicModel] = useState("");
  const [geminiModel, setGeminiModel] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
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
        const cfg = res.config as Record<string, unknown>;
        setConfig({
          ai_analysis_mode: (cfg?.ai_analysis_mode as string) ?? "auto",
          ai_fallback_mode: (cfg?.ai_fallback_mode as string) ?? "error_only",
        });
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

  const handleSaveConfig = async (patch: Partial<ConfigRow>) => {
    if (!config) return;
    setSaving(true);
    try {
      await updateConfigFn({ data: patch as never });
      setConfig({ ...config, ...patch });
      toast.success("Zapisano ustawienia AI");
    } catch (e) {
      toast.error(`Błąd zapisu: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const bothKeysConfigured = env?.ANTHROPIC_API_KEY && env?.GEMINI_API_KEY;
  const isRaceBoth = config?.ai_fallback_mode === "race_both";

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
          dostawcę. Jeśli oba są skonfigurowane, możesz kontrolować strategię fallbacku.
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
              {bothKeysConfigured && (
                <span className="ml-2 text-muted-foreground">
                  (fallback: {env.AI_PROVIDER === "gemini" ? "Anthropic" : "Gemini"})
                </span>
              )}
            </div>
          </div>
        )}

        {/* Validation Warnings */}
        {env && config && <ConfigValidationWarnings env={env} config={config} />}

        {/* Fallback Strategy Card */}
        {bothKeysConfigured && config && (
          <Card className="mb-6 p-6">
            <div className="mb-4 flex items-center gap-2">
              <Shield className="h-5 w-5 text-amber-500" />
              <h2 className="text-lg font-semibold">Strategia fallbacku</h2>
            </div>

            <div className="space-y-5">
              {/* Mode selector */}
              <div
                className={`rounded-lg border p-4 cursor-pointer transition-colors ${
                  !isRaceBoth
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/30"
                }`}
                onClick={() => handleSaveConfig({ ai_fallback_mode: "error_only" })}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Shield className="h-5 w-5 text-muted-foreground" />
                    <div>
                      <div className="font-medium text-sm">Fallback tylko przy błędach</div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        Najpierw główny dostawca. Zapasowy tylko gdy główny zwróci błąd.
                      </div>
                    </div>
                  </div>
                  <div className={`h-4 w-4 rounded-full border-2 ${
                    !isRaceBoth ? "border-primary bg-primary" : "border-muted-foreground/40"
                  }`}>
                    {!isRaceBoth && (
                      <div className="h-full w-full rounded-full bg-primary flex items-center justify-center">
                        <div className="h-1.5 w-1.5 rounded-full bg-primary-foreground" />
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div
                className={`rounded-lg border p-4 cursor-pointer transition-colors ${
                  isRaceBoth
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/30"
                }`}
                onClick={() => handleSaveConfig({ ai_fallback_mode: "race_both" })}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Gauge className="h-5 w-5 text-muted-foreground" />
                    <div>
                      <div className="font-medium text-sm">Zawsze próbuj obu</div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        Oba dostawcy uruchamiani równolegle. Używa odpowiedzi tego, który odpowie pierwszy.
                      </div>
                    </div>
                  </div>
                  <div className={`h-4 w-4 rounded-full border-2 ${
                    isRaceBoth ? "border-primary bg-primary" : "border-muted-foreground/40"
                  }`}>
                    {isRaceBoth && (
                      <div className="h-full w-full rounded-full bg-primary flex items-center justify-center">
                        <div className="h-1.5 w-1.5 rounded-full bg-primary-foreground" />
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {saving && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" /> Zapisuję...
                </div>
              )}

              {isRaceBoth && (
                <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
                  <strong>Uwaga:</strong> Tryb „zawsze próbuj obu" zużywa tokeny u obu dostawców
                  przy każdym zapytaniu. Szybsze odpowiedzi, ale wyższe koszty.
                </div>
              )}
            </div>
          </Card>
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
            <li>
              <strong>Fallback tylko przy błędach</strong> — próbuje głównego dostawcę.
              Jeśli zwróci błąd (timeout, HTTP 5xx, brak klucza), automatycznie próbuje zapasowego.
              Oszczędza tokeny.
            </li>
            <li>
              <strong>Zawsze próbuj obu</strong> — oba dostawcy uruchamiani równolegle (race).
              Używa odpowiedzi tego, kto odpowie szybciej. Szybsze czasy odpowiedzi, ale
              podwójne zużycie tokenów.
            </li>
            <li>Jeśli tylko jeden klucz jest skonfigurowany, fallback jest niedostępny.</li>
            <li>Głównego dostawcę zmieniasz w panelu konfiguracji (pole „Tryb analizy AI").</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}

function ConfigValidationWarnings({ env, config }: { env: EnvFlags; config: ConfigRow }) {
  const warnings: { message: string; hint: string }[] = [];

  const mode = config.ai_analysis_mode;
  const hasAnthropic = env.ANTHROPIC_API_KEY;
  const hasGemini = env.GEMINI_API_KEY;

  if (!hasAnthropic && !hasGemini) {
    warnings.push({
      message: "Brak kluczy API — analiza AI nie będzie działać.",
      hint: "Dodaj co najmniej jeden sekret: ANTHROPIC_API_KEY lub GEMINI_API_KEY.",
    });
  } else if (mode === "anthropic" && !hasAnthropic) {
    warnings.push({
      message: 'Wybrany dostawca "Anthropic", ale brak klucza ANTHROPIC_API_KEY.',
      hint: 'Dodaj sekret ANTHROPIC_API_KEY lub zmień tryb na "Gemini" albo "Auto".',
    });
  } else if (mode === "gemini" && !hasGemini) {
    warnings.push({
      message: 'Wybrany dostawca "Gemini", ale brak klucza GEMINI_API_KEY.',
      hint: 'Dodaj sekret GEMINI_API_KEY lub zmień tryb na "Anthropic" albo "Auto".',
    });
  }

  if (config.ai_fallback_mode === "race_both" && (!hasAnthropic || !hasGemini)) {
    warnings.push({
      message: 'Strategia "Zawsze próbuj obu" wymaga obu kluczy API.',
      hint: 'Dodaj brakujący klucz lub zmień strategię na "Fallback tylko przy błędach".',
    });
  }

  if (mode === "auto" && !hasAnthropic && !hasGemini) {
    // already covered above
  } else if (mode === "auto" && hasAnthropic && !hasGemini) {
    // fine, auto will pick anthropic
  } else if (mode === "auto" && !hasAnthropic && hasGemini) {
    // fine, auto will pick gemini
  }

  if (warnings.length === 0) return null;

  return (
    <div className="mb-6 space-y-3">
      {warnings.map((w, i) => (
        <div
          key={i}
          className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4"
        >
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
          <div className="text-sm">
            <p className="font-medium text-amber-700 dark:text-amber-400">{w.message}</p>
            <p className="mt-1 text-muted-foreground">{w.hint}</p>
          </div>
        </div>
      ))}
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

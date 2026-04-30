import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState, useCallback } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import {
  listClients,
  createClient,
  deleteClient,
  listRecords,
  loadRecord,
  saveRecord,
  deleteRecord,
  getConfig,
  updateConfig,
  runAnalysis,
  renderReport,
  runScraperSearch,
} from "@/server/api.functions";
import type { CarLot, ClientCriteria, AnalyzedLot } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Card } from "@/components/ui/card";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Loader2,
  Plus,
  Trash2,
  RefreshCw,
  Settings,
  Search,
  Brain,
  FileText,
  Download,
  Save,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";

export const Route = createFileRoute("/")({
  component: Panel,
});

type ClientRow = { id: string; name: string; contact: string | null; notes: string | null; created_at: string };
type RecordSummary = {
  id: string;
  client_id: string | null;
  title: string | null;
  status: string;
  created_at: string;
  updated_at: string;
};
type ConfigEnv = {
  ANTHROPIC_API_KEY: boolean;
  ANTHROPIC_MODEL: string;
  ANTHROPIC_BASE_URL: string;
  SCRAPER_BASE_URL: boolean;
  SCRAPER_API_TOKEN: boolean;
};
type ConfigRow = {
  use_mock_data: boolean;
  ai_analysis_mode: string;
  filter_seller_insurance_only: boolean;
  min_auction_window_hours: number;
  max_auction_window_hours: number;
  collect_all_prefiltered_results: boolean;
  open_all_prefiltered_details: boolean;
};

const DEFAULT_CRITERIA: ClientCriteria = {
  make: "",
  model: "",
  year_from: 2015,
  year_to: 2024,
  budget_usd: 20000,
  max_odometer_mi: 120000,
  excluded_damage_types: ["Flood", "Fire"],
  max_results: 30,
  sources: ["copart", "iaai"],
};

function downloadFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function recommendationBadge(r: string) {
  if (r === "POLECAM") return "bg-[oklch(0.92_0.08_145)] text-[oklch(0.30_0.10_145)]";
  if (r === "RYZYKO") return "bg-[oklch(0.92_0.10_85)] text-[oklch(0.35_0.12_85)]";
  return "bg-[oklch(0.92_0.10_25)] text-[oklch(0.35_0.15_25)]";
}

function Panel() {
  // ---- server fn handles
  const fnListClients = useServerFn(listClients);
  const fnCreateClient = useServerFn(createClient);
  const fnDeleteClient = useServerFn(deleteClient);
  const fnListRecords = useServerFn(listRecords);
  const fnLoadRecord = useServerFn(loadRecord);
  const fnSaveRecord = useServerFn(saveRecord);
  const fnDeleteRecord = useServerFn(deleteRecord);
  const fnGetConfig = useServerFn(getConfig);
  const fnUpdateConfig = useServerFn(updateConfig);
  const fnRunAnalysis = useServerFn(runAnalysis);
  const fnRenderReport = useServerFn(renderReport);
  const fnRunScraper = useServerFn(runScraperSearch);

  // ---- state
  const [clients, setClients] = useState<ClientRow[]>([]);
  const [records, setRecords] = useState<RecordSummary[]>([]);
  const [config, setConfig] = useState<ConfigRow | null>(null);
  const [env, setEnv] = useState<ConfigEnv | null>(null);

  const [activeClientId, setActiveClientId] = useState<string | null>(null);
  const [activeRecordId, setActiveRecordId] = useState<string | null>(null);

  const [criteria, setCriteria] = useState<ClientCriteria>(DEFAULT_CRITERIA);
  const [listings, setListings] = useState<CarLot[]>([]);
  const [listingsRaw, setListingsRaw] = useState<string>("");
  const [analysis, setAnalysis] = useState<AnalyzedLot[] | null>(null);
  const [aiInput, setAiInput] = useState<unknown>(null);
  const [aiPrompt, setAiPrompt] = useState<string>("");
  const [reportHtml, setReportHtml] = useState<string>("");
  const [mailHtml, setMailHtml] = useState<string>("");

  const [busy, setBusy] = useState<string | null>(null);

  // new-client form
  const [newName, setNewName] = useState("");
  const [newContact, setNewContact] = useState("");
  const [newNotes, setNewNotes] = useState("");

  // ---- loaders
  const refreshClients = useCallback(async () => {
    try {
      const c = (await fnListClients()) as ClientRow[];
      setClients(c);
    } catch (e) {
      toast.error(`Klienci: ${(e as Error).message}`);
    }
  }, [fnListClients]);

  const refreshRecords = useCallback(
    async (clientId?: string | null) => {
      try {
        const r = (await fnListRecords({ data: { clientId: clientId ?? undefined } })) as RecordSummary[];
        setRecords(r);
      } catch (e) {
        toast.error(`Rekordy: ${(e as Error).message}`);
      }
    },
    [fnListRecords],
  );

  const refreshConfig = useCallback(async () => {
    try {
      const r = (await fnGetConfig()) as { config: ConfigRow; env: ConfigEnv };
      setConfig(r.config);
      setEnv(r.env);
    } catch (e) {
      toast.error(`Konfiguracja: ${(e as Error).message}`);
    }
  }, [fnGetConfig]);

  useEffect(() => {
    void refreshClients();
    void refreshRecords(null);
    void refreshConfig();
  }, [refreshClients, refreshRecords, refreshConfig]);

  useEffect(() => {
    void refreshRecords(activeClientId);
  }, [activeClientId, refreshRecords]);

  const activeClient = useMemo(
    () => clients.find((c) => c.id === activeClientId) ?? null,
    [clients, activeClientId],
  );

  // ---- actions
  async function addClient() {
    if (!newName.trim()) {
      toast.error("Nazwa klienta jest wymagana");
      return;
    }
    setBusy("client");
    try {
      const row = (await fnCreateClient({
        data: { name: newName.trim(), contact: newContact.trim() || null, notes: newNotes.trim() || null },
      })) as ClientRow;
      setClients((cs) => [row, ...cs]);
      setActiveClientId(row.id);
      setNewName("");
      setNewContact("");
      setNewNotes("");
      toast.success("Klient dodany");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function removeClient(id: string) {
    if (!confirm("Usunąć klienta i wszystkie jego rekordy?")) return;
    try {
      await fnDeleteClient({ data: { id } });
      setClients((cs) => cs.filter((c) => c.id !== id));
      if (activeClientId === id) setActiveClientId(null);
      toast.success("Usunięto");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  function parseListingsFromText() {
    const text = listingsRaw.trim();
    if (!text) {
      setListings([]);
      return;
    }
    try {
      const parsed = JSON.parse(text);
      if (!Array.isArray(parsed)) throw new Error("JSON musi być tablicą obiektów lotów.");
      setListings(parsed as CarLot[]);
      toast.success(`Wczytano ${parsed.length} lotów z JSON`);
    } catch (e) {
      toast.error(`Błąd JSON: ${(e as Error).message}`);
    }
  }

  async function callScraper() {
    if (!env?.SCRAPER_BASE_URL) {
      toast.error("SCRAPER_BASE_URL nie jest ustawiony.");
      return;
    }
    if (!criteria.make.trim()) {
      toast.error("Marka jest wymagana.");
      return;
    }
    setBusy("scraper");
    try {
      const r = (await fnRunScraper({ data: { criteria } })) as { listings: CarLot[] };
      setListings(r.listings);
      setListingsRaw(JSON.stringify(r.listings, null, 2));
      toast.success(`Scraper zwrócił ${r.listings.length} lotów`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function runAi() {
    if (listings.length === 0) {
      toast.error("Brak lotów do analizy. Wczytaj wyniki scrapera lub wklej JSON.");
      return;
    }
    if (!criteria.make.trim()) {
      toast.error("Marka jest wymagana w kryteriach.");
      return;
    }
    setBusy("ai");
    try {
      const r = (await fnRunAnalysis({ data: { criteria, listings } })) as {
        ai_input: unknown;
        ai_prompt: string;
        analysis: AnalyzedLot[];
      };
      setAiInput(r.ai_input);
      setAiPrompt(r.ai_prompt);
      setAnalysis(r.analysis);
      toast.success(`Analiza gotowa (${r.analysis.length} lotów)`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function makeReport() {
    if (!analysis || analysis.length === 0) {
      toast.error("Najpierw uruchom analizę AI.");
      return;
    }
    setBusy("report");
    try {
      const r = (await fnRenderReport({
        data: {
          clientName: activeClient?.name ?? "Klient",
          analyzed: analysis,
        },
      })) as { report_html: string; mail_html: string };
      setReportHtml(r.report_html);
      setMailHtml(r.mail_html);
      toast.success("Raport wygenerowany");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function persistRecord() {
    if (!activeClient) {
      toast.error("Wybierz klienta przed zapisem.");
      return;
    }
    setBusy("save");
    try {
      const title = `${criteria.make} ${criteria.model || ""} ${criteria.year_from || ""}-${criteria.year_to || ""}`.trim();
      const row = (await fnSaveRecord({
        data: {
          id: activeRecordId ?? undefined,
          client_id: activeClient.id,
          title,
          status: analysis ? "analyzed" : "draft",
          criteria,
          listings,
          ai_input: aiInput,
          ai_prompt: aiPrompt || null,
          analysis,
          report_html: reportHtml || null,
          mail_html: mailHtml || null,
        },
      })) as { id: string };
      setActiveRecordId(row.id);
      await refreshRecords(activeClient.id);
      toast.success("Rekord zapisany");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function openRecord(id: string) {
    setBusy("load");
    try {
      const row = (await fnLoadRecord({ data: { id } })) as {
        id: string;
        client_id: string | null;
        criteria: ClientCriteria;
        listings: CarLot[];
        ai_input: unknown;
        ai_prompt: string | null;
        analysis: AnalyzedLot[] | null;
        report_html: string | null;
        mail_html: string | null;
      };
      setActiveRecordId(row.id);
      if (row.client_id) setActiveClientId(row.client_id);
      setCriteria({ ...DEFAULT_CRITERIA, ...row.criteria });
      setListings(row.listings ?? []);
      setListingsRaw(JSON.stringify(row.listings ?? [], null, 2));
      setAiInput(row.ai_input);
      setAiPrompt(row.ai_prompt ?? "");
      setAnalysis(row.analysis);
      setReportHtml(row.report_html ?? "");
      setMailHtml(row.mail_html ?? "");
      toast.success("Rekord wczytany");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function removeRecord(id: string) {
    if (!confirm("Usunąć ten rekord?")) return;
    try {
      await fnDeleteRecord({ data: { id } });
      setRecords((rs) => rs.filter((r) => r.id !== id));
      if (activeRecordId === id) setActiveRecordId(null);
      toast.success("Usunięto");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  function newSession() {
    setActiveRecordId(null);
    setCriteria(DEFAULT_CRITERIA);
    setListings([]);
    setListingsRaw("");
    setAnalysis(null);
    setAiInput(null);
    setAiPrompt("");
    setReportHtml("");
    setMailHtml("");
  }

  // ---- render
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Top bar */}
      <header className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground font-bold">
              UC
            </div>
            <div>
              <h1 className="text-base font-semibold leading-tight">USA Car Finder</h1>
              <p className="text-xs text-muted-foreground leading-tight">
                Panel operatora · Copart + IAAI · analiza AI
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <EnvStatus env={env} />
            <SettingsSheet
              config={config}
              env={env}
              onSave={async (patch) => {
                try {
                  const r = (await fnUpdateConfig({ data: patch })) as ConfigRow;
                  setConfig(r);
                  toast.success("Konfiguracja zapisana");
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            />
          </div>
        </div>
      </header>

      <main className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[280px_minmax(0,1fr)_320px]">
        {/* ---- Clients column ---- */}
        <aside className="space-y-3">
          <Card className="p-3">
            <h2 className="mb-2 text-sm font-semibold">Nowy klient</h2>
            <div className="space-y-2">
              <Input
                placeholder="Imię i nazwisko / firma"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
              <Input
                placeholder="Kontakt (e-mail / telefon)"
                value={newContact}
                onChange={(e) => setNewContact(e.target.value)}
              />
              <Textarea
                placeholder="Notatki (opcjonalnie)"
                value={newNotes}
                onChange={(e) => setNewNotes(e.target.value)}
                rows={2}
              />
              <Button onClick={addClient} disabled={busy === "client"} className="w-full" size="sm">
                {busy === "client" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Dodaj
              </Button>
            </div>
          </Card>

          <Card className="p-3">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Klienci ({clients.length})</h2>
              <Button variant="ghost" size="sm" onClick={() => void refreshClients()}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </div>
            <div className="max-h-[60vh] space-y-1 overflow-y-auto">
              {clients.length === 0 && (
                <p className="px-1 py-2 text-xs text-muted-foreground">Brak klientów. Dodaj pierwszego powyżej.</p>
              )}
              {clients.map((c) => (
                <div
                  key={c.id}
                  className={`group flex items-start justify-between rounded-md border px-2 py-1.5 text-sm cursor-pointer ${
                    activeClientId === c.id
                      ? "border-primary bg-accent"
                      : "border-transparent hover:bg-muted"
                  }`}
                  onClick={() => setActiveClientId(c.id)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{c.name}</div>
                    {c.contact && <div className="truncate text-xs text-muted-foreground">{c.contact}</div>}
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void removeClient(c.id);
                    }}
                    className="ml-2 opacity-0 group-hover:opacity-100"
                    title="Usuń"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                  </button>
                </div>
              ))}
            </div>
          </Card>
        </aside>

        {/* ---- Workspace ---- */}
        <section className="min-w-0 space-y-4">
          <Card className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold">
                  {activeClient ? `Sesja: ${activeClient.name}` : "Nowa sesja"}
                </h2>
                <p className="text-xs text-muted-foreground">
                  {activeRecordId ? `Rekord ${activeRecordId.slice(0, 8)}…` : "(nie zapisano)"}
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={newSession}>
                  Nowa sesja
                </Button>
                <Button size="sm" onClick={persistRecord} disabled={busy === "save" || !activeClient}>
                  {busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Zapisz rekord
                </Button>
              </div>
            </div>

            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Kryteria
            </h3>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="Marka *">
                <Input
                  value={criteria.make}
                  onChange={(e) => setCriteria({ ...criteria, make: e.target.value })}
                  placeholder="Audi"
                />
              </Field>
              <Field label="Model">
                <Input
                  value={criteria.model ?? ""}
                  onChange={(e) => setCriteria({ ...criteria, model: e.target.value })}
                  placeholder="A5"
                />
              </Field>
              <Field label="Rocznik od">
                <Input
                  type="number"
                  value={criteria.year_from ?? ""}
                  onChange={(e) =>
                    setCriteria({ ...criteria, year_from: e.target.value ? +e.target.value : null })
                  }
                />
              </Field>
              <Field label="Rocznik do">
                <Input
                  type="number"
                  value={criteria.year_to ?? ""}
                  onChange={(e) =>
                    setCriteria({ ...criteria, year_to: e.target.value ? +e.target.value : null })
                  }
                />
              </Field>
              <Field label="Budżet USD *">
                <Input
                  type="number"
                  value={criteria.budget_usd}
                  onChange={(e) => setCriteria({ ...criteria, budget_usd: +e.target.value || 0 })}
                />
              </Field>
              <Field label="Max przebieg (mil)">
                <Input
                  type="number"
                  value={criteria.max_odometer_mi ?? ""}
                  onChange={(e) =>
                    setCriteria({ ...criteria, max_odometer_mi: e.target.value ? +e.target.value : null })
                  }
                />
              </Field>
              <Field label="Max wyników">
                <Input
                  type="number"
                  value={criteria.max_results ?? 30}
                  onChange={(e) => setCriteria({ ...criteria, max_results: +e.target.value || 30 })}
                />
              </Field>
              <Field label="Wykluczone uszkodzenia">
                <Input
                  value={(criteria.excluded_damage_types ?? []).join(", ")}
                  onChange={(e) =>
                    setCriteria({
                      ...criteria,
                      excluded_damage_types: e.target.value
                        .split(",")
                        .map((s) => s.trim())
                        .filter(Boolean),
                    })
                  }
                  placeholder="Flood, Fire"
                />
              </Field>
            </div>

            <Separator className="my-4" />

            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Loty z aukcji ({listings.length})
              </h3>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={parseListingsFromText}
                  disabled={!listingsRaw.trim()}
                >
                  Wczytaj z JSON
                </Button>
                <Button
                  size="sm"
                  onClick={callScraper}
                  disabled={busy === "scraper" || !env?.SCRAPER_BASE_URL}
                  title={!env?.SCRAPER_BASE_URL ? "Ustaw SCRAPER_BASE_URL w sekretach" : ""}
                >
                  {busy === "scraper" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Search className="h-4 w-4" />
                  )}
                  Wyszukaj online
                </Button>
              </div>
            </div>
            <Textarea
              className="font-mono text-xs"
              rows={6}
              placeholder='Wklej tutaj JSON z lotami: [{"source":"copart","lot_id":"123","year":2020,...}]'
              value={listingsRaw}
              onChange={(e) => setListingsRaw(e.target.value)}
            />
            {listings.length > 0 && <ListingsTable listings={listings} />}

            <Separator className="my-4" />

            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={runAi} disabled={busy === "ai" || listings.length === 0}>
                {busy === "ai" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Brain className="h-4 w-4" />}
                Uruchom analizę AI
              </Button>
              <Button
                variant="outline"
                onClick={makeReport}
                disabled={busy === "report" || !analysis}
              >
                {busy === "report" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FileText className="h-4 w-4" />
                )}
                Wygeneruj raport
              </Button>
              {!env?.ANTHROPIC_API_KEY && (
                <span className="inline-flex items-center gap-1 text-xs text-destructive">
                  <AlertCircle className="h-3.5 w-3.5" />
                  Brak ANTHROPIC_API_KEY
                </span>
              )}
            </div>
          </Card>

          {analysis && analysis.length > 0 && (
            <Card className="p-4">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Wyniki analizy AI ({analysis.length})
              </h3>
              <div className="space-y-3">
                {analysis.map((a) => (
                  <div key={a.lot.lot_id} className="rounded-md border p-3">
                    <div className="mb-2 flex items-start justify-between">
                      <div>
                        <div className="font-semibold">
                          {a.lot.year} {a.lot.make} {a.lot.model}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {a.lot.source?.toUpperCase()} · Lot {a.lot.lot_id} · {a.lot.location_state ?? "—"}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-bold">{a.analysis.score.toFixed(1)}</span>
                        <span
                          className={`rounded px-2 py-0.5 text-xs font-semibold ${recommendationBadge(
                            a.analysis.recommendation,
                          )}`}
                        >
                          {a.analysis.recommendation}
                        </span>
                      </div>
                    </div>
                    <p className="text-sm">{a.analysis.client_description_pl}</p>
                    {a.analysis.red_flags.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {a.analysis.red_flags.map((f, i) => (
                          <Badge key={i} variant="outline" className="text-xs">
                            ⚠ {f}
                          </Badge>
                        ))}
                      </div>
                    )}
                    <div className="mt-2 text-xs text-muted-foreground">
                      Naprawa: ${a.analysis.estimated_repair_usd ?? "—"} · Łącznie: ${a.analysis.estimated_total_cost_usd ?? "—"}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {reportHtml && (
            <Card className="p-4">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Podgląd raportu HTML
              </h3>
              <iframe
                title="Raport"
                srcDoc={reportHtml}
                className="h-[600px] w-full rounded border"
              />
            </Card>
          )}

          {/* Downloads */}
          <Card className="p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Pliki do pobrania
            </h3>
            <div className="flex flex-wrap gap-2">
              <DownloadBtn
                label="ai_input.json"
                disabled={!aiInput}
                onClick={() => downloadFile("ai_input.json", JSON.stringify(aiInput, null, 2), "application/json")}
              />
              <DownloadBtn
                label="prompt.txt"
                disabled={!aiPrompt}
                onClick={() => downloadFile("prompt.txt", aiPrompt, "text/plain")}
              />
              <DownloadBtn
                label="analysis.json"
                disabled={!analysis}
                onClick={() => downloadFile("analysis.json", JSON.stringify(analysis, null, 2), "application/json")}
              />
              <DownloadBtn
                label="report.html"
                disabled={!reportHtml}
                onClick={() => downloadFile("report.html", reportHtml, "text/html")}
              />
              <DownloadBtn
                label="mail.html"
                disabled={!mailHtml}
                onClick={() => downloadFile("mail.html", mailHtml, "text/html")}
              />
              <DownloadBtn
                label="report.md"
                disabled={!analysis}
                onClick={() => {
                  const md = (analysis ?? [])
                    .map(
                      (a) =>
                        `## ${a.lot.year} ${a.lot.make} ${a.lot.model} — ${a.analysis.score.toFixed(1)}/10 ${a.analysis.recommendation}\n\n` +
                        `- Lot: ${a.lot.source}/${a.lot.lot_id}\n- Lokalizacja: ${a.lot.location_state ?? "—"}\n- Bid: $${a.lot.current_bid_usd ?? "—"}\n\n${a.analysis.client_description_pl}\n\n${a.analysis.ai_notes ?? ""}\n`,
                    )
                    .join("\n---\n\n");
                  downloadFile("report.md", md, "text/markdown");
                }}
              />
            </div>
          </Card>
        </section>

        {/* ---- Records column ---- */}
        <aside>
          <Card className="p-3">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold">
                {activeClient ? `Rekordy: ${activeClient.name}` : "Wszystkie rekordy"}
              </h2>
              <Button variant="ghost" size="sm" onClick={() => void refreshRecords(activeClientId)}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            </div>
            <div className="max-h-[80vh] space-y-1 overflow-y-auto">
              {records.length === 0 && (
                <p className="px-1 py-2 text-xs text-muted-foreground">Brak rekordów.</p>
              )}
              {records.map((r) => (
                <div
                  key={r.id}
                  className={`group flex items-start justify-between rounded-md border px-2 py-1.5 text-sm cursor-pointer ${
                    activeRecordId === r.id ? "border-primary bg-accent" : "border-transparent hover:bg-muted"
                  }`}
                  onClick={() => void openRecord(r.id)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{r.title || "(bez tytułu)"}</div>
                    <div className="text-xs text-muted-foreground">
                      {new Date(r.created_at).toLocaleString("pl-PL")} · {r.status}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void removeRecord(r.id);
                    }}
                    className="ml-2 opacity-0 group-hover:opacity-100"
                    title="Usuń"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                  </button>
                </div>
              ))}
            </div>
          </Card>
        </aside>
      </main>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      {children}
    </div>
  );
}

function DownloadBtn({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <Button variant="outline" size="sm" onClick={onClick} disabled={disabled}>
      <Download className="h-3.5 w-3.5" /> {label}
    </Button>
  );
}

function ListingsTable({ listings }: { listings: CarLot[] }) {
  return (
    <div className="mt-3 max-h-[260px] overflow-auto rounded border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted">
          <tr className="text-left">
            <th className="px-2 py-1.5">Pojazd</th>
            <th className="px-2 py-1.5">Lot</th>
            <th className="px-2 py-1.5">Stan</th>
            <th className="px-2 py-1.5">Bid</th>
            <th className="px-2 py-1.5">Uszkodzenie</th>
            <th className="px-2 py-1.5">Tytuł</th>
            <th className="px-2 py-1.5">Sprzedawca</th>
          </tr>
        </thead>
        <tbody>
          {listings.map((l) => (
            <tr key={`${l.source}-${l.lot_id}`} className="border-t">
              <td className="px-2 py-1">
                {l.year ?? "?"} {l.make ?? ""} {l.model ?? ""}
              </td>
              <td className="px-2 py-1 text-muted-foreground">
                {l.source}/{l.lot_id}
              </td>
              <td className="px-2 py-1">{l.location_state ?? "—"}</td>
              <td className="px-2 py-1">${l.current_bid_usd ?? "—"}</td>
              <td className="px-2 py-1">{l.damage_primary ?? "—"}</td>
              <td className="px-2 py-1">{l.title_type ?? "—"}</td>
              <td className="px-2 py-1">{l.seller_type ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EnvStatus({ env }: { env: ConfigEnv | null }) {
  if (!env) return null;
  const Item = ({ ok, label }: { ok: boolean; label: string }) => (
    <span className="inline-flex items-center gap-1 text-xs">
      {ok ? (
        <CheckCircle2 className="h-3.5 w-3.5 text-[oklch(0.55_0.16_145)]" />
      ) : (
        <AlertCircle className="h-3.5 w-3.5 text-destructive" />
      )}
      {label}
    </span>
  );
  return (
    <div className="hidden items-center gap-3 rounded-md border bg-card px-3 py-1.5 md:flex">
      <Item ok={env.ANTHROPIC_API_KEY} label="AI" />
      <Item ok={env.SCRAPER_BASE_URL && env.SCRAPER_API_TOKEN} label="Scraper" />
    </div>
  );
}

function SettingsSheet({
  config,
  env,
  onSave,
}: {
  config: ConfigRow | null;
  env: ConfigEnv | null;
  onSave: (patch: Partial<ConfigRow>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ConfigRow | null>(config);
  useEffect(() => setDraft(config), [config]);
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm">
          <Settings className="h-4 w-4" /> Ustawienia
        </Button>
      </SheetTrigger>
      <SheetContent className="w-[400px] overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Ustawienia operacyjne</SheetTitle>
        </SheetHeader>
        {draft && (
          <div className="mt-4 space-y-4">
            <ToggleRow
              label="Tryb demo (mock data)"
              value={draft.use_mock_data}
              onChange={(v) => setDraft({ ...draft, use_mock_data: v })}
            />
            <ToggleRow
              label="Filtruj tylko Seller-Type Insurance"
              value={draft.filter_seller_insurance_only}
              onChange={(v) => setDraft({ ...draft, filter_seller_insurance_only: v })}
            />
            <ToggleRow
              label="Zbieraj wszystkie wstępnie odfiltrowane wyniki"
              value={draft.collect_all_prefiltered_results}
              onChange={(v) => setDraft({ ...draft, collect_all_prefiltered_results: v })}
            />
            <ToggleRow
              label="Otwieraj wszystkie szczegóły wstępnie odfiltrowanych"
              value={draft.open_all_prefiltered_details}
              onChange={(v) => setDraft({ ...draft, open_all_prefiltered_details: v })}
            />
            <Field label="Tryb analizy AI">
              <select
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={draft.ai_analysis_mode}
                onChange={(e) => setDraft({ ...draft, ai_analysis_mode: e.target.value })}
              >
                <option value="anthropic">anthropic</option>
                <option value="auto">auto</option>
                <option value="openai">openai</option>
                <option value="local">local</option>
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Min okno aukcji (h)">
                <Input
                  type="number"
                  value={draft.min_auction_window_hours}
                  onChange={(e) =>
                    setDraft({ ...draft, min_auction_window_hours: +e.target.value || 0 })
                  }
                />
              </Field>
              <Field label="Max okno aukcji (h)">
                <Input
                  type="number"
                  value={draft.max_auction_window_hours}
                  onChange={(e) =>
                    setDraft({ ...draft, max_auction_window_hours: +e.target.value || 0 })
                  }
                />
              </Field>
            </div>
            <Button
              className="w-full"
              onClick={() => void onSave(draft)}
            >
              Zapisz ustawienia
            </Button>
            <Separator />
            <div>
              <h4 className="mb-2 text-sm font-semibold">Sekrety środowiska</h4>
              <ul className="space-y-1 text-xs">
                <li>ANTHROPIC_API_KEY: {env?.ANTHROPIC_API_KEY ? "✓ ustawiony" : "✗ brak"}</li>
                <li>ANTHROPIC_MODEL: {env?.ANTHROPIC_MODEL}</li>
                <li>ANTHROPIC_BASE_URL: {env?.ANTHROPIC_BASE_URL}</li>
                <li>SCRAPER_BASE_URL: {env?.SCRAPER_BASE_URL ? "✓ ustawiony" : "✗ brak"}</li>
                <li>SCRAPER_API_TOKEN: {env?.SCRAPER_API_TOKEN ? "✓ ustawiony" : "✗ brak"}</li>
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">
                Sekrety dodajesz w Lovable Cloud (Connectors → secrets). Aplikacja czyta je w server functions.
              </p>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function ToggleRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <Label className="text-sm">{label}</Label>
      <Switch checked={value} onCheckedChange={onChange} />
    </div>
  );
}

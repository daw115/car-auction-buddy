import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";

import {
  backendSearch,
  backendGenerateReport,
  backendListRecords,
  backendJobStatus,
  type BackendSearchResponse,
  type BackendRecordSummary,
} from "@/functions/backend.functions";
import type { AnalyzedLot, CarLot, ClientCriteria } from "@/lib/types";


import { CriteriaForm } from "@/components/panels/criteria-form";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Loader2, ExternalLink, FileText, Mail, RefreshCcw } from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "USA Car Finder — panel operatora" },
      { name: "description", content: "Wyszukiwanie i analiza AI ofert z aukcji Copart/IAAI." },
    ],
  }),
  component: HomePage,
});

// ---------------- helpers ----------------

const REPORT_MODES = [
  { id: "client-html", label: "Raport klienta (HTML)", icon: FileText },
  { id: "broker-html", label: "Raport brokera (HTML)", icon: FileText },
  { id: "client-llm", label: "Raport klienta (LLM)", icon: FileText },
  { id: "broker-llm", label: "Raport brokera (LLM)", icon: FileText },
  { id: "offer-email-html", label: "E-mail ofertowy", icon: Mail },
] as const;
type ReportMode = (typeof REPORT_MODES)[number]["id"];

function recommendationTone(r?: string) {
  const v = (r ?? "").toUpperCase();
  if (v === "POLECAM") return "bg-emerald-500/15 text-emerald-500 border-emerald-500/30";
  if (v === "RYZYKO") return "bg-amber-500/15 text-amber-500 border-amber-500/30";
  if (v === "ODRZUĆ" || v === "ODRZUC") return "bg-rose-500/15 text-rose-500 border-rose-500/30";
  return "bg-muted text-muted-foreground border-border";
}

function fmtUsd(v?: number | null) {
  if (v == null) return "—";
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

function openHtmlInNewTab(html: string) {
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const w = window.open(url, "_blank", "noopener,noreferrer");
  if (!w) {
    toast.error("Przeglądarka zablokowała nowe okno.");
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// Backend zwraca lekki `CarLot[]` (listings) — analiza dogrywana asynchronicznie,
// dlatego traktujemy każdą pozycję jako AnalyzedLot (analiza opcjonalna).
type SearchResult =
  | { kind: "listings"; lots: CarLot[]; source: BackendSearchResponse["source"]; jobId: string }
  | { kind: "analyzed"; lots: AnalyzedLot[]; jobId: string };

function normalizeResponse(res: BackendSearchResponse): SearchResult {
  return { kind: "listings", lots: res.listings ?? [], source: res.source, jobId: res.job_id };
}

// ---------------- page ----------------

function HomePage() {
  const runSearch = useServerFn(backendSearch);
  const genReport = useServerFn(backendGenerateReport);
  const loadRecords = useServerFn(backendListRecords);

  const [criteria, setCriteria] = useState<ClientCriteria>({
    make: "",
    model: "",
    year_from: null,
    year_to: null,
    budget_usd: null,
    max_odometer_mi: null,
    fuel_type: null,
    excluded_damage_types: [],
    max_results: 15,
  });

  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [clientName, setClientName] = useState("");
  const [reporting, setReporting] = useState<ReportMode | null>(null);

  const [records, setRecords] = useState<BackendRecordSummary[] | null>(null);
  const [recordsLoading, setRecordsLoading] = useState(false);

  const listings: CarLot[] = useMemo(() => {
    if (!result) return [];
    return result.kind === "analyzed" ? result.lots.map((a) => a.lot) : result.lots;
  }, [result]);

  const analyzedByLotId: Record<string, AnalyzedLot | undefined> = useMemo(() => {
    if (!result || result.kind !== "analyzed") return {};
    return Object.fromEntries(result.lots.map((a) => [a.lot.lot_id, a]));
  }, [result]);

  async function onSearch() {
    if (!criteria.make.trim()) {
      toast.error("Podaj markę pojazdu.");
      return;
    }
    setLoading(true);
    setLoadingMsg("Trwa wyszukiwanie i analiza AI… to może potrwać kilka minut.");
    setResult(null);
    setSelected({});
    try {
      const res = await runSearch({ data: { criteria } });
      if (!res.listings || res.listings.length === 0) {
        toast.info("Nie znaleziono aukcji spełniających kryteria.");
      } else {
        toast.success(`Znaleziono ${res.listings.length} ofert.`);
      }
      setResult(normalizeResponse(res));
      if (res.analysis_notice) {
        toast.message(res.analysis_notice);
      }
    } catch (e) {
      const err = e as { message?: string; status?: number };
      toast.error(err.message || "Błąd wyszukiwania.");
    } finally {
      setLoading(false);
      setLoadingMsg("");
    }
  }

  function toggleSelected(id: string) {
    setSelected((s) => ({ ...s, [id]: !s[id] }));
  }

  function selectAll(v: boolean) {
    setSelected(v ? Object.fromEntries(listings.map((l) => [l.lot_id, true])) : {});
  }

  async function onGenerateReport(mode: ReportMode) {
    const chosen = listings.filter((l) => selected[l.lot_id]);
    if (chosen.length === 0) {
      toast.error("Zaznacz przynajmniej jedno auto.");
      return;
    }
    setReporting(mode);
    try {
      const approved_lots = chosen.map((lot) => {
        const a = analyzedByLotId[lot.lot_id];
        return a ? { ...a, included_in_report: true } : { lot, included_in_report: true };
      });
      const { html } = await genReport({
        data: {
          mode,
          approved_lots,
          criteria,
          client_name: clientName || undefined,
        },
      });
      openHtmlInNewTab(html);
      toast.success("Raport wygenerowany.");
    } catch (e) {
      const err = e as { message?: string };
      toast.error(err.message || "Błąd generowania raportu.");
    } finally {
      setReporting(null);
    }
  }

  async function onLoadRecords() {
    setRecordsLoading(true);
    try {
      const res = await loadRecords();
      const list = Array.isArray(res) ? res : (res as { records?: BackendRecordSummary[] }).records ?? [];
      setRecords(list);
    } catch (e) {
      const err = e as { message?: string };
      toast.error(err.message || "Nie udało się pobrać historii.");
    } finally {
      setRecordsLoading(false);
    }
  }

  const selectedCount = Object.values(selected).filter(Boolean).length;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 md:p-6">
      {/* Formularz kryteriów */}
      <Card className="p-4">
        <CriteriaForm criteria={criteria} setCriteria={setCriteria} />
        <Separator className="my-4" />
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[220px] flex-1">
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              Klient (opcjonalnie — trafi na raport)
            </label>
            <Input
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              placeholder="Jan Kowalski"
            />
          </div>
          <Button size="lg" onClick={onSearch} disabled={loading} className="min-w-[180px]">
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Szukam…
              </>
            ) : (
              "🔎 Wyszukaj"
            )}
          </Button>
        </div>
      </Card>

      {/* Loader */}
      {loading && (
        <Card className="p-6">
          <div className="flex items-center gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            <div>
              <div className="font-medium">{loadingMsg}</div>
              <div className="text-xs text-muted-foreground">
                Nie zamykaj karty — request idzie do zewnętrznego scrapera + analizy AI.
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* Wyniki */}
      {result && !loading && (
        <Card className="p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-lg font-semibold">
                Wyniki ({listings.length})
                {result.kind === "listings" && (
                  <Badge variant="outline" className="ml-2 text-xs">
                    źródło: {result.source}
                  </Badge>
                )}
              </h2>
              <p className="text-xs text-muted-foreground">Job ID: {result.jobId}</p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => selectAll(true)}>
                Zaznacz wszystkie
              </Button>
              <Button variant="outline" size="sm" onClick={() => selectAll(false)}>
                Wyczyść
              </Button>
            </div>
          </div>

          {listings.length === 0 ? (
            <p className="text-sm text-muted-foreground">Brak wyników.</p>
          ) : (
            <div className="space-y-3">
              {listings.map((lot) => {
                const a = analyzedByLotId[lot.lot_id];
                const isSel = !!selected[lot.lot_id];
                return (
                  <div
                    key={`${lot.source}-${lot.lot_id}`}
                    className={`rounded-lg border p-3 transition ${
                      isSel ? "border-primary bg-primary/5" : "border-border"
                    }`}
                  >
                    <div className="flex gap-3">
                      <Checkbox
                        checked={isSel}
                        onCheckedChange={() => toggleSelected(lot.lot_id)}
                        className="mt-1"
                      />
                      {lot.images?.[0] && (
                        <img
                          src={lot.images[0]}
                          alt={`${lot.year ?? ""} ${lot.make ?? ""} ${lot.model ?? ""}`}
                          className="h-20 w-28 rounded-md object-cover"
                          loading="lazy"
                        />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">
                            {lot.year ?? "—"} {lot.make} {lot.model}
                          </span>
                          <Badge variant="outline" className="text-[10px] uppercase">
                            {lot.source}
                          </Badge>
                          {a?.analysis.recommendation && (
                            <Badge
                              variant="outline"
                              className={`text-xs ${recommendationTone(a.analysis.recommendation)}`}
                            >
                              {a.analysis.recommendation}
                              {typeof a.analysis.score === "number" && ` · ${a.analysis.score}/10`}
                            </Badge>
                          )}
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          VIN: {lot.vin || lot.full_vin || "—"} · Lot: {lot.lot_id} · Przebieg:{" "}
                          {lot.odometer_mi != null ? `${lot.odometer_mi.toLocaleString()} mi` : "—"} ·{" "}
                          Uszk.: {lot.damage_primary ?? "—"}
                        </div>
                        <div className="mt-1 text-xs">
                          Bid: <b>{fmtUsd(lot.current_bid_usd)}</b> · Buy now:{" "}
                          <b>{fmtUsd(lot.buy_now_price_usd)}</b>
                          {a?.analysis.estimated_total_cost_usd != null && (
                            <>
                              {" "}
                              · Est. total:{" "}
                              <b>{fmtUsd(a.analysis.estimated_total_cost_usd)}</b>
                            </>
                          )}
                        </div>
                        {a?.analysis.client_description_pl && (
                          <p className="mt-2 line-clamp-2 text-sm">
                            {a.analysis.client_description_pl}
                          </p>
                        )}
                        {lot.url && (
                          <a
                            className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                            href={lot.url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            <ExternalLink className="h-3 w-3" /> Zobacz aukcję
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Sekcja raportów */}
          {listings.length > 0 && (
            <>
              <Separator className="my-4" />
              <div className="flex flex-wrap items-center gap-2">
                <div className="mr-2 text-sm">
                  Zaznaczone: <b>{selectedCount}</b> / {listings.length}
                </div>
                {REPORT_MODES.map(({ id, label, icon: Icon }) => (
                  <Button
                    key={id}
                    variant="secondary"
                    size="sm"
                    disabled={selectedCount === 0 || reporting !== null}
                    onClick={() => onGenerateReport(id)}
                  >
                    {reporting === id ? (
                      <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                    ) : (
                      <Icon className="mr-2 h-3 w-3" />
                    )}
                    {label}
                  </Button>
                ))}
              </div>
            </>
          )}
        </Card>
      )}

      {/* Historia */}
      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Historia wyszukiwań (backend)</h2>
          <Button variant="outline" size="sm" onClick={onLoadRecords} disabled={recordsLoading}>
            {recordsLoading ? (
              <Loader2 className="mr-2 h-3 w-3 animate-spin" />
            ) : (
              <RefreshCcw className="mr-2 h-3 w-3" />
            )}
            Odśwież
          </Button>
        </div>
        {records == null ? (
          <p className="text-sm text-muted-foreground">
            Kliknij „Odśwież", żeby pobrać listę z <code>/api/records</code>.
          </p>
        ) : records.length === 0 ? (
          <p className="text-sm text-muted-foreground">Brak zapisanych rekordów.</p>
        ) : (
          <ul className="divide-y">
            {records.slice(0, 50).map((r) => (
              <li key={r.id} className="flex items-center justify-between py-2 text-sm">
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">
                    {r.make ?? "—"} {r.model ?? ""}{" "}
                    {r.client_name && (
                      <span className="text-muted-foreground">· {r.client_name}</span>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {r.id} · {r.created_at ?? "—"} · status: {r.status ?? "—"} · ofert:{" "}
                    {r.listings_count ?? "—"}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

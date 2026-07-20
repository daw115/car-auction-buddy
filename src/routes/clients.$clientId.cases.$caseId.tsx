import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { ArrowLeft, Play, Trash2 } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  getCase,
  updateCase,
  deleteCase,
  toggleCaseAutoRefresh,
  listCaseSearches,
  getCaseOperators,
  attachSearchToCase,
  detachSearchFromCase,
  runCaseNow,
} from "@/functions/clients.functions";

export const Route = createFileRoute("/clients/$clientId/cases/$caseId")({
  component: CaseDetailPage,
});

function CaseDetailPage() {
  const { clientId, caseId } = Route.useParams();
  const qc = useQueryClient();

  const fnGet = useServerFn(getCase);
  const fnUpdate = useServerFn(updateCase);
  const fnDelete = useServerFn(deleteCase);
  const fnToggle = useServerFn(toggleCaseAutoRefresh);
  const fnListSearches = useServerFn(listCaseSearches);
  const fnOps = useServerFn(getCaseOperators);
  const fnAttach = useServerFn(attachSearchToCase);
  const fnDetach = useServerFn(detachSearchFromCase);
  const fnRun = useServerFn(runCaseNow);

  const { data: kase } = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => fnGet({ data: { id: caseId } }),
  });
  const { data: searches = [] } = useQuery({
    queryKey: ["case-searches", caseId],
    queryFn: () => fnListSearches({ data: { caseId } }),
  });
  const { data: operators = [] } = useQuery({
    queryKey: ["case-operators", caseId],
    queryFn: () => fnOps({ data: { caseId } }),
  });

  const [criteriaText, setCriteriaText] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [interval, setInterval] = useState(24);
  const [attachId, setAttachId] = useState("");
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (kase) {
      setTitle(kase.title);
      setDescription(kase.description ?? "");
      setCriteriaText(
        kase.default_criteria ? JSON.stringify(kase.default_criteria, null, 2) : "",
      );
      setInterval(kase.auto_refresh_interval_hours);
    }
  }, [kase]);

  const saveMeta = async () => {
    let parsed: Record<string, unknown> | null = null;
    if (criteriaText.trim()) {
      try {
        parsed = JSON.parse(criteriaText);
      } catch {
        toast.error("Nieprawidłowy JSON w kryteriach");
        return;
      }
    }
    try {
      await fnUpdate({
        data: {
          id: caseId,
          title: title.trim(),
          description: description.trim() || null,
          default_criteria: parsed,
        },
      });
      toast.success("Zapisano");
      qc.invalidateQueries({ queryKey: ["case", caseId] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const toggleAuto = async (enabled: boolean) => {
    try {
      await fnToggle({ data: { id: caseId, enabled, intervalHours: interval } });
      toast.success(enabled ? "Auto-refresh włączony" : "Auto-refresh wyłączony");
      qc.invalidateQueries({ queryKey: ["case", caseId] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const doAttach = async () => {
    if (!attachId.trim()) return;
    try {
      await fnAttach({ data: { caseId, recordId: attachId.trim() } });
      toast.success("Przypięto");
      setAttachId("");
      qc.invalidateQueries({ queryKey: ["case-searches", caseId] });
      qc.invalidateQueries({ queryKey: ["case-operators", caseId] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const doDetach = async (id: string) => {
    try {
      await fnDetach({ data: { id } });
      qc.invalidateQueries({ queryKey: ["case-searches", caseId] });
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  const doRun = async () => {
    setRunning(true);
    try {
      const res = await fnRun({ data: { caseId } });
      toast.success(
        `Uruchomiono: ${res.total_lots} lotów, ${res.new_lots} nowych`,
      );
      qc.invalidateQueries({ queryKey: ["case-searches", caseId] });
      qc.invalidateQueries({ queryKey: ["case", caseId] });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const doDeleteCase = async () => {
    if (!confirm("Usunąć sprawę i wszystkie powiązania?")) return;
    try {
      await fnDelete({ data: { id: caseId } });
      toast.success("Sprawa usunięta");
      window.location.assign(`/clients/${clientId}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  if (!kase) return <div className="text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <div className="space-y-4">
      <Link
        to="/clients/$clientId"
        params={{ clientId }}
        className="text-sm text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
      >
        <ArrowLeft className="h-3 w-3" /> Wróć do klienta
      </Link>
      <PageHeader
        title={kase.title}
        description={kase.description ?? "Sprawa klienta"}
        actions={
          <div className="flex gap-2">
            <Button onClick={doRun} disabled={running}>
              <Play className="h-4 w-4 mr-2" />
              {running ? "Uruchamiam…" : "Uruchom teraz"}
            </Button>
            <Button variant="destructive" onClick={doDeleteCase}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4 space-y-3">
          <h3 className="font-semibold">Dane sprawy</h3>
          <div>
            <Label>Tytuł</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <Label>Opis</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
          </div>
          <div>
            <Label>Domyślne kryteria (JSON)</Label>
            <Textarea
              value={criteriaText}
              onChange={(e) => setCriteriaText(e.target.value)}
              rows={8}
              className="font-mono text-xs"
              placeholder='{"make":"Tesla","model":"Model 3","budget_usd":20000}'
            />
            <p className="text-xs text-muted-foreground mt-1">
              Używane przy „Uruchom teraz" oraz w cyklicznym auto-refresh.
            </p>
          </div>
          <Button onClick={saveMeta} variant="outline">
            Zapisz
          </Button>
        </Card>

        <Card className="p-4 space-y-3">
          <h3 className="font-semibold">Cykliczne odświeżanie</h3>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm">Włączone</div>
              <div className="text-xs text-muted-foreground">
                {kase.auto_refresh_enabled
                  ? `Co ${kase.auto_refresh_interval_hours}h. Następne: ${
                      kase.next_auto_run_at
                        ? new Date(kase.next_auto_run_at).toLocaleString("pl-PL")
                        : "—"
                    }`
                  : "Wyłączone — użyj przełącznika, żeby uruchamiać automatycznie."}
              </div>
            </div>
            <Switch checked={kase.auto_refresh_enabled} onCheckedChange={toggleAuto} />
          </div>
          <div>
            <Label>Interwał (godziny, 1–168)</Label>
            <Input
              type="number"
              min={1}
              max={168}
              value={interval}
              onChange={(e) => setInterval(Math.max(1, Math.min(168, Number(e.target.value) || 24)))}
              onBlur={() => {
                if (kase.auto_refresh_enabled) toggleAuto(true);
              }}
            />
          </div>
          {kase.last_auto_run_at && (
            <div className="text-xs text-muted-foreground">
              Ostatnie uruchomienie: {new Date(kase.last_auto_run_at).toLocaleString("pl-PL")}
            </div>
          )}

          <div className="pt-3 border-t">
            <h4 className="font-semibold text-sm mb-2">Operatorzy ({operators.length})</h4>
            {operators.length === 0 ? (
              <div className="text-xs text-muted-foreground">Nikt jeszcze nie uruchamiał tej sprawy.</div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {operators.map((o) => (
                  <Badge key={o.user} variant="outline" className="text-xs">
                    {o.user} · {o.count}× · {new Date(o.last_at).toLocaleDateString("pl-PL")}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </Card>
      </div>

      <Card className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold">Przypięte wyszukiwania ({searches.length})</h3>
        </div>
        <div className="flex gap-2">
          <Input
            placeholder="Wklej record_id / job_id z /records aby przypiąć"
            value={attachId}
            onChange={(e) => setAttachId(e.target.value)}
            className="max-w-md"
          />
          <Button onClick={doAttach} variant="outline">
            Przypnij
          </Button>
        </div>
        {searches.length === 0 ? (
          <div className="text-xs text-muted-foreground">Brak powiązań.</div>
        ) : (
          <div className="space-y-1">
            {searches.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between gap-2 py-2 border-b last:border-b-0"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-mono truncate">{s.record_id}</div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(s.created_at).toLocaleString("pl-PL")} · {s.searched_by ?? "?"} ·{" "}
                    <Badge variant="outline" className="text-[10px]">
                      {s.triggered_by}
                    </Badge>
                    {s.new_lot_ids.length > 0 && (
                      <span className="ml-2 text-green-600">🆕 {s.new_lot_ids.length} nowych</span>
                    )}
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => doDetach(s.id)}>
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

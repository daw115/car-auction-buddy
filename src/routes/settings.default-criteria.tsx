import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  updateDefaultCriteria,
  type DefaultCriteria,
} from "@/functions/default-criteria.functions";
import { defaultCriteriaQuery, settingsQueryKeys } from "@/queries/settings.queries";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ArrowLeft,
  Loader2,
  AlertCircle,
  Save,
  Eraser,
  SlidersHorizontal,
} from "lucide-react";

export const Route = createFileRoute("/settings/default-criteria")({
  head: () => ({
    meta: [
      { title: "Domyślne kryteria wyszukiwania" },
      { name: "robots", content: "noindex, nofollow" },
      {
        name: "description",
        content:
          "Domyślne wartości formularza wyszukiwania (marka, budżet, sources, wykluczenia).",
      },
    ],
  }),
  component: DefaultCriteriaPage;
});

const BLANK: DefaultCriteria = {
  make: null,
  model: null,
  year_from: null,
  year_to: null,
  budget_usd: null,
  max_odometer_mi: null,
  fuel_type: null,
  allowed_damage_types: [],
  excluded_damage_types: ["Flood", "Fire"],
  max_results: 15,
  sources: ["copart", "iaai"],
};

const FUEL_OPTIONS = ["Gas", "Hybrid", "Diesel", "Electric"] as const;
const FUEL_ANY = "__any__";

function parseCsv(s: string): string[] {
  return s
    .split(",")
    .map((x) => x.trim())
    .filter((x) => x.length > 0);
}

function nOrNull(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function DefaultCriteriaPage() {
  const qc = useQueryClient();
  const q = useQuery(defaultCriteriaQuery());
  const [form, setForm] = useState<DefaultCriteria>(BLANK);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (q.data) {
      setForm({
        ...BLANK,
        ...q.data,
        allowed_damage_types: q.data.allowed_damage_types ?? [],
        excluded_damage_types: q.data.excluded_damage_types ?? [],
        sources: q.data.sources && q.data.sources.length > 0 ? q.data.sources : ["copart", "iaai"],
        max_results: q.data.max_results ?? 15,
      });
    }
  }, [q.data]);

  const mut = useMutation({
    mutationFn: (payload: DefaultCriteria) => updateDefaultCriteria({ data: payload }),
    onMutate: () => setError(null),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: settingsQueryKeys.defaultCriteria });
      toast.success("Zapisano domyślne kryteria.");
    },
    onError: (e: unknown) => {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      toast.error("Nie zapisano.");
    },
  });

  const yearErr =
    form.year_from != null && form.year_to != null && form.year_from > form.year_to
      ? "Rok od musi być ≤ rok do."
      : null;
  const sourcesErr = (form.sources ?? []).length === 0 ? "Wybierz co najmniej jedno źródło." : null;
  const maxErr =
    form.max_results < 1 || form.max_results > 15 ? "max_results musi być 1–15." : null;
  const canSave = !yearErr && !sourcesErr && !maxErr && !mut.isPending;

  const handleSave = () => {
    if (!canSave) return;
    mut.mutate(form);
  };

  const handleClear = () => {
    setForm(BLANK);
    mut.mutate(BLANK);
  };

  const toggleSource = (src: "copart" | "iaai", checked: boolean) => {
    setForm((f) => {
      const cur = new Set(f.sources ?? []);
      if (checked) cur.add(src);
      else cur.delete(src);
      return { ...f, sources: Array.from(cur) };
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <SlidersHorizontal className="h-6 w-6" /> Domyślne kryteria
          </h1>
          <p className="text-sm text-muted-foreground">
            Wypełniają formularz wyszukiwania na starcie. User może je nadpisać przed „Szukaj”.
          </p>
        </div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/settings">
            <ArrowLeft className="mr-1 h-4 w-4" /> Ustawienia
          </Link>
        </Button>
      </div>

      {q.isLoading && (
        <Card className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Ładuję…
        </Card>
      )}

      {q.isError && (
        <Card className="flex items-start gap-2 border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex-1">
            <div className="font-medium">Błąd wczytywania</div>
            <div className="text-xs opacity-90">
              {q.error instanceof Error ? q.error.message : String(q.error)}
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => void q.refetch()}>Ponów</Button>
        </Card>
      )}

      {!q.isLoading && !q.isError && (
        <Card className="p-6 space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="make">Marka</Label>
              <Input
                id="make"
                value={form.make ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, make: e.target.value || null }))}
                placeholder="np. BMW"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="model">Model</Label>
              <Input
                id="model"
                value={form.model ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, model: e.target.value || null }))}
                placeholder="np. X5"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="yf">Rok od</Label>
              <Input
                id="yf"
                type="number"
                value={form.year_from ?? ""}
                onChange={(e) =>
                  setForm((f) => ({ ...f, year_from: nOrNull(e.target.value) }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="yt">Rok do</Label>
              <Input
                id="yt"
                type="number"
                value={form.year_to ?? ""}
                onChange={(e) => setForm((f) => ({ ...f, year_to: nOrNull(e.target.value) }))}
              />
              {yearErr && (
                <p className="text-xs text-destructive flex items-center gap-1">
                  <AlertCircle className="h-3 w-3" /> {yearErr}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="bud">Budżet (USD)</Label>
              <Input
                id="bud"
                type="number"
                value={form.budget_usd ?? ""}
                onChange={(e) =>
                  setForm((f) => ({ ...f, budget_usd: nOrNull(e.target.value) }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="odo">Max przebieg (mi)</Label>
              <Input
                id="odo"
                type="number"
                value={form.max_odometer_mi ?? ""}
                onChange={(e) =>
                  setForm((f) => ({ ...f, max_odometer_mi: nOrNull(e.target.value) }))
                }
              />
            </div>

            <div className="space-y-1.5">
              <Label>Rodzaj paliwa</Label>
              <Select
                value={form.fuel_type ?? FUEL_ANY}
                onValueChange={(v) =>
                  setForm((f) => ({ ...f, fuel_type: v === FUEL_ANY ? null : v }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={FUEL_ANY}>— dowolny —</SelectItem>
                  {FUEL_OPTIONS.map((x) => (
                    <SelectItem key={x} value={x}>
                      {x}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="mr">Max wyników (1–15)</Label>
              <Input
                id="mr"
                type="number"
                min={1}
                max={15}
                value={form.max_results}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    max_results: Math.max(1, Math.min(15, Number(e.target.value) || 15)),
                  }))
                }
              />
              {maxErr && (
                <p className="text-xs text-destructive flex items-center gap-1">
                  <AlertCircle className="h-3 w-3" /> {maxErr}
                </p>
              )}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="allow">Dozwolone uszkodzenia (comma-separated)</Label>
            <Input
              id="allow"
              value={(form.allowed_damage_types ?? []).join(", ")}
              onChange={(e) =>
                setForm((f) => ({ ...f, allowed_damage_types: parseCsv(e.target.value) }))
              }
              placeholder="np. Front End, Rear End"
            />
            <p className="text-[11px] text-muted-foreground">
              Pusta lista = brak whitelisty (dowolne uszkodzenia dopuszczone).
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="excl">Wykluczone uszkodzenia (comma-separated)</Label>
            <Input
              id="excl"
              value={(form.excluded_damage_types ?? []).join(", ")}
              onChange={(e) =>
                setForm((f) => ({ ...f, excluded_damage_types: parseCsv(e.target.value) }))
              }
              placeholder="Flood, Fire"
            />
          </div>

          <div className="space-y-2">
            <Label>Źródła</Label>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={(form.sources ?? []).includes("copart")}
                  onCheckedChange={(v) => toggleSource("copart", !!v)}
                />
                Copart
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={(form.sources ?? []).includes("iaai")}
                  onCheckedChange={(v) => toggleSource("iaai", !!v)}
                />
                IAAI
              </label>
            </div>
            {sourcesErr && (
              <p className="text-xs text-destructive flex items-center gap-1">
                <AlertCircle className="h-3 w-3" /> {sourcesErr}
              </p>
            )}
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-medium">Nie zapisano</div>
                <div className="text-xs opacity-90">{error}</div>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-2 pt-2">
            <Button onClick={handleSave} disabled={!canSave}>
              {mut.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              Zapisz domyślne
            </Button>
            <Button variant="outline" onClick={handleClear} disabled={mut.isPending}>
              <Eraser className="mr-2 h-4 w-4" /> Wyczyść wszystkie
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

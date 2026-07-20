import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import {
  listWatchlist,
  removeFromWatchlist,
  updateWatchlist,
} from "@/functions/watchlist.functions";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import type { Tables, TablesUpdate } from "@/integrations/supabase/types";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Loader2, Trash2, ExternalLink, GitCompare, Eye, EyeOff, Bookmark } from "lucide-react";

export const Route = createFileRoute("/watchlist")({
  head: () => ({
    meta: [
      { title: "Watchlist obserwowanych lotów — USA Car Finder" },
      {
        name: "description",
        content:
          "Zarządzaj listą obserwowanych lotów aukcyjnych, porównuj do trzech ofert obok siebie i śledź zmiany cen w czasie.",
      },
      { property: "og:title", content: "Watchlist obserwowanych lotów — USA Car Finder" },
      {
        property: "og:description",
        content: "Lista obserwowanych aukcji z porównywarką i historią zmian cen.",
      },
      { property: "og:url", content: "https://car-auction-buddy.lovable.app/watchlist" },
    ],
    links: [{ rel: "canonical", href: "https://car-auction-buddy.lovable.app/watchlist" }],
  }),
  component: WatchlistPage,
});

function WatchlistPage() {
  const fetchList = useServerFn(listWatchlist);
  const remove = useServerFn(removeFromWatchlist);
  const update = useServerFn(updateWatchlist);
  const [items, setItems] = useState<Tables<"watchlist">[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setItems(await fetchList());
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Nie udało się pobrać watchlisty.");
    } finally {
      setLoading(false);
    }
  }, [fetchList]);
  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (id: string) => {
    setSelected((s) =>
      s.includes(id) ? s.filter((x) => x !== id) : s.length >= 3 ? s : [...s, id],
    );
  };

  const compared = useMemo(() => items.filter((i) => selected.includes(i.id)), [items, selected]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Watchlist"
        description="Obserwuj loty, porównuj oferty i zarządzaj zapisanymi pojazdami."
        icon={<Bookmark className="h-5 w-5" />}
        actions={
          <div className="flex items-center gap-2">
            <Badge variant="secondary">{items.length}</Badge>
            <Button
              variant="outline"
              size="sm"
              disabled={selected.length < 2}
              onClick={() => setCompareOpen((value) => !value)}
            >
              <GitCompare className="h-4 w-4" />
              {compareOpen ? "Ukryj porównanie" : `Porównaj (${selected.length})`}
            </Button>
          </div>
        }
      />

      {compareOpen && compared.length >= 2 && (
        <Card className="p-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-2 pr-4">Pole</th>
                {compared.map((c) => (
                  <th key={c.id} className="py-2 pr-4 max-w-[220px] truncate">
                    {c.title || `${c.year ?? ""} ${c.make ?? ""} ${c.model ?? ""}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              <Row label="Źródło" values={compared.map((c) => c.source ?? "—")} />
              <Row label="VIN" values={compared.map((c) => c.vin ?? "—")} />
              <Row label="Rok" values={compared.map((c) => c.year ?? "—")} />
              <Row
                label="Marka / model"
                values={compared.map((c) => `${c.make ?? "—"} ${c.model ?? ""}`)}
              />
              <Row label="Bid USD" values={compared.map((c) => c.current_bid_usd ?? "—")} />
              <Row label="Buy now USD" values={compared.map((c) => c.buy_now_usd ?? "—")} />
              <Row label="Score" values={compared.map((c) => c.score ?? "—")} />
              <Row label="Kategoria" values={compared.map((c) => c.category ?? "—")} />
              <Row label="Notatki" values={compared.map((c) => c.notes ?? "—")} />
            </tbody>
          </table>
        </Card>
      )}

      {loadError ? (
        <ErrorState description={loadError} onRetry={() => void load()} retrying={loading} />
      ) : loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="Brak obserwowanych lotów"
          description="Dodaj loty z panelu analizy przyciskiem „Obserwuj”."
          icon={<Bookmark className="h-6 w-6" />}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {items.map((it) => (
            <Card key={it.id} className="p-4 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium text-sm truncate">
                    {it.title || `${it.year ?? ""} ${it.make ?? ""} ${it.model ?? ""}`}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {it.source ?? "—"} · lot {it.lot_id ?? "—"}
                  </div>
                </div>
                <Checkbox
                  checked={selected.includes(it.id)}
                  onCheckedChange={() => toggle(it.id)}
                  aria-label={`Wybierz ${it.title || it.lot_id || "lot"} do porównania`}
                />
              </div>
              <div className="flex flex-wrap gap-2 text-xs">
                {it.score != null && <Badge>Score {Number(it.score).toFixed(1)}</Badge>}
                {it.current_bid_usd != null && (
                  <Badge variant="secondary">Bid ${it.current_bid_usd}</Badge>
                )}
                {it.category && <Badge variant="outline">{it.category}</Badge>}
              </div>
              {it.notes && <p className="text-xs text-muted-foreground line-clamp-2">{it.notes}</p>}
              <div className="flex items-center gap-2 pt-1">
                {it.url && (
                  <a
                    href={it.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" /> Otwórz
                  </a>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto h-7 px-2"
                  aria-label="Ukryj lot na watchliście"
                  onClick={async () => {
                    await update({
                      data: {
                        id: it.id,
                        patch: { active: false } satisfies TablesUpdate<"watchlist">,
                      },
                    });
                    toast.success("Ukryto z watchlist");
                    void load();
                  }}
                >
                  <EyeOff className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-destructive"
                  aria-label="Usuń lot z watchlisty"
                  onClick={async () => {
                    if (!confirm("Usunąć z watchlist?")) return;
                    await remove({ data: { id: it.id } });
                    toast.success("Usunięto");
                    void load();
                  }}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Row({ label, values }: { label: string; values: unknown[] }) {
  return (
    <tr>
      <td className="py-2 pr-4 text-xs text-muted-foreground whitespace-nowrap">{label}</td>
      {values.map((v, i) => (
        <td key={i} className="py-2 pr-4 align-top">
          {String(v ?? "—")}
        </td>
      ))}
    </tr>
  );
}

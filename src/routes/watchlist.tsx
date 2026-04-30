import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import {
  listWatchlist, removeFromWatchlist, updateWatchlist,
} from "@/server/watchlist.functions";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Loader2, ArrowLeft, Trash2, ExternalLink, GitCompare, Eye, EyeOff } from "lucide-react";

export const Route = createFileRoute("/watchlist")({ component: WatchlistPage });

function WatchlistPage() {
  const fetchList = useServerFn(listWatchlist);
  const remove = useServerFn(removeFromWatchlist);
  const update = useServerFn(updateWatchlist);
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);

  const load = async () => {
    setLoading(true);
    try { setItems(await fetchList()); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const toggle = (id: string) => {
    setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : s.length >= 3 ? s : [...s, id]);
  };

  const compared = useMemo(() => items.filter((i) => selected.includes(i.id)), [items, selected]);

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="max-w-7xl mx-auto space-y-4">
        <header className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link to="/" className="text-sm text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
              <ArrowLeft className="h-4 w-4" /> Panel
            </Link>
            <h1 className="text-2xl font-semibold">Watchlist</h1>
            <Badge variant="secondary">{items.length}</Badge>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline" size="sm"
              disabled={selected.length < 2}
              onClick={() => setCompareOpen((v) => !v)}
            >
              <GitCompare className="h-4 w-4 mr-1" />
              {compareOpen ? "Ukryj porównanie" : `Porównaj (${selected.length})`}
            </Button>
          </div>
        </header>

        {compareOpen && compared.length >= 2 && (
          <Card className="p-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-4">Pole</th>
                  {compared.map((c) => (
                    <th key={c.id} className="py-2 pr-4 max-w-[220px] truncate">{c.title || `${c.year ?? ""} ${c.make ?? ""} ${c.model ?? ""}`}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                <Row label="Źródło" values={compared.map((c) => c.source ?? "—")} />
                <Row label="VIN" values={compared.map((c) => c.vin ?? "—")} />
                <Row label="Rok" values={compared.map((c) => c.year ?? "—")} />
                <Row label="Marka / model" values={compared.map((c) => `${c.make ?? "—"} ${c.model ?? ""}`)} />
                <Row label="Bid USD" values={compared.map((c) => c.current_bid_usd ?? "—")} />
                <Row label="Buy now USD" values={compared.map((c) => c.buy_now_usd ?? "—")} />
                <Row label="Score" values={compared.map((c) => c.score ?? "—")} />
                <Row label="Kategoria" values={compared.map((c) => c.category ?? "—")} />
                <Row label="Notatki" values={compared.map((c) => c.notes ?? "—")} />
              </tbody>
            </table>
          </Card>
        )}

        {loading ? (
          <div className="flex justify-center py-20"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
        ) : items.length === 0 ? (
          <Card className="p-10 text-center text-sm text-muted-foreground">
            Brak obserwowanych lotów. Dodaj loty z panelu analizy przyciskiem „Obserwuj".
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {items.map((it) => (
              <Card key={it.id} className="p-4 space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-medium text-sm truncate">{it.title || `${it.year ?? ""} ${it.make ?? ""} ${it.model ?? ""}`}</div>
                    <div className="text-xs text-muted-foreground">{it.source ?? "—"} · lot {it.lot_id ?? "—"}</div>
                  </div>
                  <Checkbox checked={selected.includes(it.id)} onCheckedChange={() => toggle(it.id)} />
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  {it.score != null && <Badge>Score {Number(it.score).toFixed(1)}</Badge>}
                  {it.current_bid_usd != null && <Badge variant="secondary">Bid ${it.current_bid_usd}</Badge>}
                  {it.category && <Badge variant="outline">{it.category}</Badge>}
                </div>
                {it.notes && <p className="text-xs text-muted-foreground line-clamp-2">{it.notes}</p>}
                <div className="flex items-center gap-2 pt-1">
                  {it.url && (
                    <a href={it.url} target="_blank" rel="noreferrer" className="text-xs inline-flex items-center gap-1 text-primary hover:underline">
                      <ExternalLink className="h-3 w-3" /> Otwórz
                    </a>
                  )}
                  <Button
                    variant="ghost" size="sm" className="ml-auto h-7 px-2"
                    onClick={async () => {
                      await update({ data: { id: it.id, patch: { active: false } as any } });
                      toast.success("Ukryto z watchlist");
                      load();
                    }}
                  >
                    <EyeOff className="h-3 w-3" />
                  </Button>
                  <Button
                    variant="ghost" size="sm" className="h-7 px-2 text-destructive"
                    onClick={async () => {
                      if (!confirm("Usunąć z watchlist?")) return;
                      await remove({ data: { id: it.id } });
                      toast.success("Usunięto");
                      load();
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
    </div>
  );
}

function Row({ label, values }: { label: string; values: any[] }) {
  return (
    <tr>
      <td className="py-2 pr-4 text-xs text-muted-foreground whitespace-nowrap">{label}</td>
      {values.map((v, i) => (
        <td key={i} className="py-2 pr-4 align-top">{String(v ?? "—")}</td>
      ))}
    </tr>
  );
}

import { useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bell, BellOff, Loader2, Trash2, Plus } from "lucide-react";

import {
  createWatch,
  deleteWatch,
  listWatchHits,
  listWatches,
  setWatchActive,
} from "@/functions/watches.functions";
import type { ClientCriteria } from "@/lib/types";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

type Props = {
  /** Kryteria do założenia nowego nasłuchu — zwykle te z ostatniego wyszukiwania. */
  criteria?: ClientCriteria | null;
  clientName?: string | null;
  clientPhone?: string | null;
};

function kiedy(stamp: number | null): string {
  if (!stamp) return "jeszcze nie";
  const minut = Math.round((Date.now() - stamp * 1000) / 60000);
  if (minut < 60) return `${minut} min temu`;
  const godzin = Math.round(minut / 60);
  return godzin < 48 ? `${godzin} h temu` : `${Math.round(godzin / 24)} dni temu`;
}

/** Cykliczne sprawdzanie aukcji pod klienta.
 *
 *  Powiadomienie idzie do brokera, nie do klienta — panel mówi to wprost, bo to
 *  jedyna rzecz, którą łatwo tu źle założyć.
 */
export function WatchesPanel({ criteria, clientName, clientPhone }: Props) {
  const fnList = useServerFn(listWatches);
  const fnCreate = useServerFn(createWatch);
  const fnDelete = useServerFn(deleteWatch);
  const fnToggle = useServerFn(setWatchActive);
  const fnHits = useServerFn(listWatchHits);
  const queryClient = useQueryClient();
  const [interval, setInterval] = useState(12);

  const { data, isLoading } = useQuery({
    queryKey: ["watches"],
    queryFn: () => fnList({}),
    refetchInterval: 60_000,
  });

  const odswiez = () => queryClient.invalidateQueries({ queryKey: ["watches"] });

  const zaloz = useMutation({
    mutationFn: () => {
      if (!criteria?.make) throw new Error("Nasłuch potrzebuje przynajmniej marki.");
      return fnCreate({
        data: {
          criteria,
          clientName: clientName ?? null,
          clientPhone: clientPhone ?? null,
          intervalHours: interval,
        },
      });
    },
    onSuccess: () => {
      toast.success("Nasłuch założony. Odezwę się do Ciebie, gdy wjedzie coś nowego.");
      odswiez();
    },
    onError: (e: { message?: string }) =>
      toast.error(e.message || "Nie udało się założyć nasłuchu."),
  });

  // Powiadomienie z Telegrama znika w historii czatu — tu broker do niego wraca.
  const { data: znaleziska } = useQuery({
    queryKey: ["watch-hits"],
    queryFn: () => fnHits({ data: { limit: 10 } }),
    refetchInterval: 120_000,
  });

  // Na karcie klienta pokazujemy JEGO nasłuchy. Bez tego broker widziałby tam
  // nasłuchy założone dla innych osób — i mógłby je stąd wyłączyć w przekonaniu,
  // że dotyczą klienta, którego ma przed sobą.
  const wszystkie = data?.watches ?? [];
  const dlaKlienta = clientName || clientPhone;
  const watches = dlaKlienta
    ? wszystkie.filter((w) => w.clientName === clientName || w.clientPhone === clientPhone)
    : wszystkie;
  const moje = new Set(watches.map((w) => w.id));
  const hits = (znaleziska?.hits ?? []).filter((h) => !dlaKlienta || moje.has(h.watchId));

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold">🔔 Nasłuch aukcji</h3>
          <p className="text-xs text-muted-foreground">
            Backend sprawdza giełdy sam i pisze <b>do Ciebie</b>, gdy wjedzie nowe auto. Do klienta
            nic nie wychodzi bez Twojego kliknięcia.
          </p>
        </div>
        {criteria?.make && (
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={1}
              max={168}
              value={interval}
              onChange={(e) => setInterval(Math.max(1, Math.min(168, +e.target.value || 12)))}
              className="w-20"
              aria-label="Co ile godzin sprawdzać"
            />
            <span className="text-xs text-muted-foreground">h</span>
            <Button size="sm" onClick={() => zaloz.mutate()} disabled={zaloz.isPending}>
              {zaloz.isPending ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="mr-1.5 h-3.5 w-3.5" />
              )}
              Załóż na te kryteria
            </Button>
          </div>
        )}
      </div>

      {isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      ) : watches.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {dlaKlienta
            ? "Ten klient nie ma jeszcze nasłuchu. Przy wąskich kryteriach auta wjeżdżają pojedynczo, więc warto go założyć."
            : "Żaden nasłuch nie działa. Przy wąskich kryteriach — rocznik, wersja, stan — auta wjeżdżają pojedynczo i ręczne sprawdzanie co rano jest stratą czasu."}
        </p>
      ) : (
        <div className="space-y-2">
          {watches.map((w) => (
            <div
              key={w.id}
              className={`flex items-center justify-between rounded border p-2 text-sm ${
                w.active ? "border-border" : "border-dashed opacity-60"
              }`}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {[w.criteria?.make, w.criteria?.model].filter(Boolean).join(" ") || "auto"}
                  </span>
                  {w.clientName && (
                    <Badge variant="outline" className="text-[10px]">
                      {w.clientName}
                    </Badge>
                  )}
                  {!w.active && <Badge variant="secondary">wstrzymany</Badge>}
                  {w.lastError && (
                    <Badge variant="destructive" className="text-[10px]">
                      błąd
                    </Badge>
                  )}
                </div>
                <div className="text-xs text-muted-foreground">
                  co {w.intervalHours} h · sprawdzeń {w.runs} · znalezionych {w.foundTotal} ·
                  ostatnio {kiedy(w.lastRunAt)}
                </div>
                {w.lastError && <div className="text-xs text-destructive">{w.lastError}</div>}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  title={w.active ? "Wstrzymaj" : "Wznów"}
                  onClick={() => fnToggle({ data: { id: w.id, active: !w.active } }).then(odswiez)}
                >
                  {w.active ? (
                    <BellOff className="h-3.5 w-3.5" />
                  ) : (
                    <Bell className="h-3.5 w-3.5" />
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  title="Usuń nasłuch"
                  onClick={() => fnDelete({ data: { id: w.id } }).then(odswiez)}
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {hits.length > 0 && (
        <div className="mt-4 border-t pt-3">
          <div className="mb-2 text-xs font-medium text-muted-foreground">Ostatnio wyłowione</div>
          <div className="space-y-1">
            {hits.map((h, i) => (
              <div key={`${h.watchId}-${h.lot.lot_id}-${i}`} className="text-sm">
                <span className="font-medium">
                  {[h.lot.year, h.lot.make, h.lot.model].filter(Boolean).join(" ")}
                </span>
                <span className="text-muted-foreground">
                  {h.lot.odometer_mi ? ` · ${h.lot.odometer_mi.toLocaleString("pl-PL")} mi` : ""}
                  {h.lot.damage_primary ? ` · ${h.lot.damage_primary}` : ""}
                </span>
                {h.lot.url && (
                  <a
                    href={h.lot.url}
                    target="_blank"
                    rel="noreferrer"
                    className="ml-2 text-xs text-primary hover:underline"
                  >
                    aukcja
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

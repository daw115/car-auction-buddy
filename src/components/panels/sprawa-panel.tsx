/** Cztery kroki sprawy klienta, na jego karcie.
 *
 *  Etap leada mówi „gdzie jesteśmy", ale nie „co pokazaliśmy". Po tygodniu
 *  milczenia broker musi wiedzieć, czy klient nie odpisuje na trzy auta czy na
 *  jedno i który raport dostał — z rozmowy na WhatsAppie tego nie widać, bo idzie
 *  tam obrazek oferty i załączniki, których treści wątek nie pokazuje.
 *
 *  Krok 1 i 3 zapisują się SAME, przy wysyłce oferty i raportu. Ręcznie zaznacza
 *  się tylko to, czego system nie może wiedzieć: co klient wybrał i czy kupuje —
 *  a i to podpowiadamy, czytając numer z jego ostatniej odpowiedzi.
 */

import { useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, FileText, Loader2, X } from "lucide-react";

import {
  getStanSprawy,
  odczytajWybor,
  wyslijRaportSzczegolowy,
  zapiszDecyzje,
  zapiszWybor,
} from "@/functions/sales.functions";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";

const KROKI = ["Oferta wstępna", "Wybrane auta", "Raport szczegółowy", "Decyzja"] as const;

type Props = {
  leadId: number;
  /** Ostatnia wiadomość od klienta — z niej czytamy numer wybranego auta. */
  ostatniaOdKlienta?: string | null;
};

export function SprawaPanel({ leadId, ostatniaOdKlienta = null }: Props) {
  const fnStan = useServerFn(getStanSprawy);
  const fnOdczyt = useServerFn(odczytajWybor);
  const fnWybor = useServerFn(zapiszWybor);
  const fnDecyzja = useServerFn(zapiszDecyzje);
  const fnRaport = useServerFn(wyslijRaportSzczegolowy);
  const qc = useQueryClient();
  const [zaznaczone, setZaznaczone] = useState<Set<string>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ["sprawa", leadId],
    queryFn: () => fnStan({ data: { leadId } }),
  });

  const odswiez = () => {
    qc.invalidateQueries({ queryKey: ["sprawa", leadId] });
    qc.invalidateQueries({ queryKey: ["lead", leadId] });
  };

  const wybor = useMutation({
    mutationFn: () => fnWybor({ data: { leadId, lotIds: [...zaznaczone] } }),
    onSuccess: () => {
      toast.success("Zapisane. Teraz raport szczegółowy o tych autach.");
      setZaznaczone(new Set());
      odswiez();
    },
    onError: (e: { message?: string }) => toast.error(e.message || "Nie udało się zapisać."),
  });

  /** Zapisuje wybór i od razu wysyła oba raporty na Telegram — jedno kliknięcie
   *  zamiast trzech. Klient odpisał numerem, więc dalsza droga jest tylko jedna. */
  const raport = useMutation({
    mutationFn: (lotIds: string[]) => fnRaport({ data: { leadId, lotIds } }),
    onSuccess: (w) => {
      toast.success(
        `Raporty na Telegramie (${w.pliki.length} pliki, ${w.rozmiar_kb} KB). Raport klienta przekaż w rozmowie.`,
      );
      setZaznaczone(new Set());
      odswiez();
    },
    onError: (e: { message?: string }) =>
      toast.error(e.message || "Nie udało się wysłać raportów."),
  });

  // Podpowiedź, nie automat. Oferta jest ponumerowana i klient odpisuje „2",
  // ale „mam 2 dzieci" też zawiera dwójkę — dlatego numer tylko podświetlamy,
  // a zaznacza go broker.
  const { data: podpowiedz } = useQuery({
    queryKey: ["wybor-z-odpowiedzi", leadId, ostatniaOdKlienta],
    queryFn: () => fnOdczyt({ data: { leadId, tekst: ostatniaOdKlienta! } }),
    enabled: Boolean(ostatniaOdKlienta) && (data?.wyslane?.length ?? 0) > 0,
  });

  const decyzja = useMutation({
    mutationFn: (co: "kupuje" | "rezygnuje") =>
      fnDecyzja({ data: { leadId, decyzja: co, notatka: "" } }),
    onSuccess: (wynik) => {
      toast.success(
        wynik.decyzja === "kupuje"
          ? "Klient kupuje. Lead przechodzi na etap decyzji — dalej licytacja."
          : "Klient rezygnuje. Lead oznaczony jako stracony.",
      );
      odswiez();
    },
    onError: (e: { message?: string }) => toast.error(e.message || "Nie udało się zapisać."),
  });

  if (isLoading) {
    return (
      <Card className="p-4">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </Card>
    );
  }

  const krok = data?.krok ?? 1;

  return (
    <Card className="p-4">
      <h3 className="mb-3 text-sm font-semibold">📍 Sprawa</h3>

      <div className="mb-4 grid grid-cols-4 gap-1">
        {KROKI.map((nazwa, i) => {
          const numer = i + 1;
          const zrobiony = numer < krok;
          const biezacy = numer === krok;
          return (
            <div key={nazwa} className="min-w-0">
              <div
                className={`h-1 rounded ${
                  zrobiony ? "bg-success" : biezacy ? "bg-primary" : "bg-muted"
                }`}
              />
              <div
                className={`mt-1 truncate text-[11px] ${
                  biezacy ? "font-semibold text-foreground" : "text-muted-foreground"
                }`}
                title={nazwa}
              >
                {numer}. {nazwa}
              </div>
            </div>
          );
        })}
      </div>

      {(data?.wyslane?.length ?? 0) > 0 && (
        <div className="mb-3">
          <div className="mb-1 text-xs font-medium">Wysłane w ofercie ({data!.wyslane.length})</div>

          {(podpowiedz?.numery.length ?? 0) > 0 && (
            <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-primary/40 bg-primary/5 p-2 text-xs">
              <span>
                Klient odpisał <b>{podpowiedz!.numery.map((n) => `nr ${n}`).join(" i ")}</b>
                {podpowiedz!.auta[0]?.nazwa
                  ? ` — ${podpowiedz!.auta.map((a) => a.nazwa).join(", ")}`
                  : ""}
              </span>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-xs"
                onClick={() => setZaznaczone(new Set(podpowiedz!.lot_ids))}
              >
                Zaznacz
              </Button>
            </div>
          )}

          <div className="space-y-1">
            {data!.wyslane.map((auto, i) => {
              const id = String(auto.lot_id ?? i);
              const wybrany = data!.wybrane.some((w) => String(w.lot_id) === id);
              return (
                <label
                  key={id}
                  className="flex items-center gap-2 rounded border p-1.5 text-sm"
                  title="Zaznacz, jeśli klient wskazał to auto"
                >
                  <Checkbox
                    checked={zaznaczone.has(id) || wybrany}
                    disabled={wybrany}
                    onCheckedChange={() =>
                      setZaznaczone((p) => {
                        const n = new Set(p);
                        if (n.has(id)) n.delete(id);
                        else n.add(id);
                        return n;
                      })
                    }
                  />
                  <span className="min-w-0 flex-1 truncate">{auto.nazwa || id}</span>
                  {wybrany && (
                    <Badge variant="outline" className="text-[10px]">
                      wybrane
                    </Badge>
                  )}
                </label>
              );
            })}
          </div>
          {zaznaczone.size > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {/* Wybór klienta prowadzi zawsze do tego samego: raport o wskazanym
                  aucie. Osobny przycisk „zapisz" zostaje dla sytuacji, gdy klient
                  wskazał, ale raport ma iść później. */}
              <Button
                size="sm"
                disabled={raport.isPending || wybor.isPending}
                onClick={() => raport.mutate([...zaznaczone])}
              >
                {raport.isPending ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <FileText className="mr-1.5 h-3.5 w-3.5" />
                )}
                Wybrał te — wyślij raport ({zaznaczone.size})
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={wybor.isPending || raport.isPending}
                onClick={() => wybor.mutate()}
              >
                {wybor.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
                Tylko zapisz wybór
              </Button>
            </div>
          )}
        </div>
      )}

      {(data?.raporty?.length ?? 0) > 0 && (
        <div className="mb-3 text-xs text-muted-foreground">
          Wysłane raporty: {data!.raporty.join(", ")}
        </div>
      )}

      {data?.decyzja ? (
        <div
          className={`rounded border p-2 text-sm ${
            data.decyzja === "kupuje" ? "border-success text-success" : "text-muted-foreground"
          }`}
        >
          {data.decyzja === "kupuje"
            ? "✅ Klient kupuje — dalej licytacja."
            : "Klient zrezygnował."}
        </div>
      ) : krok >= 3 ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Decyzja klienta:</span>
          <Button size="sm" disabled={decyzja.isPending} onClick={() => decyzja.mutate("kupuje")}>
            <Check className="mr-1.5 h-3.5 w-3.5" /> Kupuje
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={decyzja.isPending}
            onClick={() => decyzja.mutate("rezygnuje")}
          >
            <X className="mr-1.5 h-3.5 w-3.5" /> Rezygnuje
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Decyzję zapiszesz, gdy klient dostanie raport szczegółowy.
        </p>
      )}
    </Card>
  );
}

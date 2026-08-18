/** Auta znalezione pod konkretnego klienta — i jedyne miejsce, z którego agent
 *  dostaje je do napisania oferty.
 *
 *  Do sierpnia 2026 backend liczył kandydatów i ceny pod drzwi do szuflady:
 *  `GET /api/sales/leads/{id}/candidates` nie miał w panelu ani jednego wywołania,
 *  a `POST .../offer` — ani jednego przycisku. Agent pisał więc oferty, nie znając
 *  aut, i wychodziły z tego ogólniki.
 *
 *  Auta ponad budżet są wyszarzone, ale zaznaczalne: czasem warto pokazać klientowi,
 *  co leży tuż nad jego kwotą. Zaznaczenie ich to świadoma decyzja brokera, więc
 *  „Zaznacz w budżecie” ich nie bierze.
 */

import { useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Copy, ImageDown, Loader2, RefreshCw, Sparkles } from "lucide-react";

import {
  getLeadCandidates,
  proposeOffer,
  raportNaTelegram,
  zapiszOferteWstepna,
  type LeadCandidate,
} from "@/functions/sales.functions";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";

type Props = {
  leadId: number;
  /** Budżet pod drzwi w złotówkach — po nim poznajemy, co jest ponad. */
  budzetPln: number | null;
};

/** Klucz lota. `lot_id` bywa pusty przy Manheimie, więc doklejamy źródło i VIN. */
function kluczLota(k: LeadCandidate, i: number): string {
  const l = k.lot as { lot_id?: string; vin?: string; source?: string };
  return [l.source, l.lot_id, l.vin, i].filter(Boolean).join("-");
}

function opisLota(k: LeadCandidate): string {
  const l = k.lot as { year?: number; make?: string; model?: string };
  return [l.year, l.make, l.model].filter(Boolean).join(" ") || "auto bez opisu";
}

export function KandydaciPanel({ leadId, budzetPln }: Props) {
  const fnKandydaci = useServerFn(getLeadCandidates);
  const fnOferta = useServerFn(proposeOffer);
  const fnPdf = useServerFn(raportNaTelegram);
  const fnZapiszOferte = useServerFn(zapiszOferteWstepna);
  const qc = useQueryClient();
  const [zaznaczone, setZaznaczone] = useState<Set<string>>(new Set());
  // Tekst wiadomości do klienta, zwrócony razem z wysłanym obrazkiem. Obrazek
  // pokazuje auta, ten tekst mówi, co z nimi zrobić — broker wysyła oba.
  const [tekstOferty, setTekstOferty] = useState<string | null>(null);

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["kandydaci", leadId],
    queryFn: () => fnKandydaci({ data: { leadId } }),
    // Scrape trwa minuty. Dopóki leci, dopytujemy; gdy skończy — przestajemy,
    // żeby nie łomotać backendu w tle przez cały dzień pracy brokera.
    refetchInterval: (q) => (q.state.data?.status === "running" ? 15_000 : false),
  });

  const kandydaci = data?.candidates ?? [];

  const ponadBudzet = (k: LeadCandidate): boolean => {
    if (!budzetPln) return false;
    const cena = (k.lot as { landed_cost_pln?: number | null }).landed_cost_pln;
    return typeof cena === "number" && cena > budzetPln;
  };

  const przelacz = (klucz: string) =>
    setZaznaczone((poprzednie) => {
      const nowe = new Set(poprzednie);
      if (nowe.has(klucz)) nowe.delete(klucz);
      else nowe.add(klucz);
      return nowe;
    });

  const napiszOferte = useMutation({
    mutationFn: async () => {
      const wybrane = kandydaci.filter((k, i) => zaznaczone.has(kluczLota(k, i)));
      if (!wybrane.length) throw new Error("Zaznacz auta, z których mam napisać ofertę.");
      return fnOferta({
        data: {
          leadId,
          lots: wybrane.slice(0, 10).map((k) => k.lot as unknown as Record<string, unknown>),
        },
      });
    },
    onSuccess: (wynik) => {
      if (wynik.draft) {
        toast.success("Propozycja gotowa — jest na górze karty, do przeczytania przed wysłaniem.");
        qc.invalidateQueries({ queryKey: ["lead", leadId] });
      } else {
        toast.warning(wynik.reason || "Agent nie ma nic do napisania na tym etapie.");
      }
    },
    onError: (e: { message?: string }) => toast.error(e.message || "Nie udało się napisać oferty."),
  });

  /** Krótka lista jako OBRAZEK, prosto na telefon brokera. Stamtąd przekazuje ją
   *  klientowi w rozmowie — panel nie ma jak podać załącznika przez wa.me.
   *
   *  Obrazek, nie PDF: pierwszą ofertę klient ma zobaczyć w wątku, bez pobierania
   *  pliku i otwierania go w innej aplikacji. Auta są ponumerowane, więc odpowiada
   *  samą cyfrą. PDF przychodzi później, razem ze szczegółowym raportem. */
  const obrazekNaTelegram = useMutation({
    mutationFn: async () => {
      const wybrane = kandydaci.filter((k, i) => zaznaczone.has(kluczLota(k, i)));
      if (!wybrane.length) throw new Error("Zaznacz auta do oferty.");
      const trojka = wybrane.slice(0, 3);
      const wynik = await fnPdf({
        data: {
          rodzaj: "oferta-png" as const,
          // Cały kandydat, nie sam `k.lot`: backend potrzebuje oceny, żeby brief
          // brokera nie pokazywał zera zamiast wyniku. Endpoint akceptuje ten
          // kształt wprost (ApproveReportRequest normalizuje go u siebie).
          lots: trojka.map((k) => k as unknown as Record<string, unknown>),
          clientName: null,
        },
      });

      // KROK 1 SPRAWY, tym samym kliknięciem. Wcześniej nie zapisywał go nikt:
      // komentarz obok mówił, że „zapisuje się sam", a `stan.wyslane` zostawało
      // puste i cała reszta sprawy była martwa — nie było listy aut do zaznaczenia,
      // podpowiedź numeru nigdy nie leciała, a raport szczegółowy odpowiadał
      // „ta sprawa nie ma jeszcze oferty wstępnej".
      //
      // Ta sama trójka i ta sama kolejność, co na obrazku: klient odpisuje „2",
      // więc pozycja 2 w sprawie musi być tym autem, które widzi jako drugie.
      // Zapis idzie PO wysyłce, bo dopiero wtedy oferta naprawdę wyszła.
      await fnZapiszOferte({
        data: {
          leadId,
          lots: trojka.map((k) => k as unknown as Record<string, unknown>),
        },
      });
      return wynik;
    },
    onSuccess: (w) => {
      setTekstOferty(w.tekst ?? null);
      toast.success(`Obrazek na Telegramie (${w.rozmiar_kb} KB). Przekaż go klientowi w rozmowie.`);
      // Sprawa przechodzi na krok 2 i karta obok pokazuje wysłane auta.
      qc.invalidateQueries({ queryKey: ["sprawa", leadId] });
    },
    onError: (e: { message?: string }) => toast.error(e.message || "Nie udało się wysłać oferty."),
  });

  const wBudzecie = kandydaci.filter((k) => !ponadBudzet(k));

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">🚗 Znalezione auta</h3>
          <p className="text-xs text-muted-foreground">
            Zaznacz te, które chcesz pokazać klientowi. Agent napisze wiadomość{" "}
            <b>znając te konkretne auta</b> i ich ceny pod drzwi.
          </p>
        </div>
        <Button
          size="sm"
          variant="ghost"
          title="Odśwież listę"
          onClick={() => qc.invalidateQueries({ queryKey: ["kandydaci", leadId] })}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {isLoading ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      ) : data?.status === "running" ? (
        <p className="text-sm text-muted-foreground">
          Szukam na giełdach. To potrwa kilka minut — lista odświeży się sama.
        </p>
      ) : data?.error ? (
        <p className="text-sm text-destructive">{data.error}</p>
      ) : kandydaci.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Jeszcze nic nie znaleziono. Uruchom „Szukaj teraz” w karcie powyżej.
        </p>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            {/* Trzy, nie wszystkie: przy dłuższej liście klient odkłada decyzję,
                a „później" znaczy w tej branży „aukcja się skończyła". Ranking
                jest deterministyczny (scoring/unified.py), więc „najlepsze" to
                nie opinia panelu — bierzemy wierzch listy, pomijając ponad budżet. */}
            <Button
              size="sm"
              disabled={wBudzecie.length === 0}
              onClick={() => {
                const trzy = wBudzecie.slice(0, 3);
                setZaznaczone(new Set(trzy.map((k) => kluczLota(k, kandydaci.indexOf(k)))));
                toast.info(
                  trzy.length < 3
                    ? `W budżecie mieszczą się tylko ${trzy.length}. Zaznaczyłem wszystkie.`
                    : "Zaznaczone trzy najlepsze. Sprawdź je przed napisaniem oferty.",
                );
              }}
            >
              Weź trzy najlepsze
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                setZaznaczone(new Set(wBudzecie.map((k) => kluczLota(k, kandydaci.indexOf(k)))))
              }
            >
              Zaznacz w budżecie ({wBudzecie.length})
            </Button>
            {zaznaczone.size > 0 && (
              <Button size="sm" variant="ghost" onClick={() => setZaznaczone(new Set())}>
                Wyczyść
              </Button>
            )}
            <span className="text-muted-foreground">zaznaczone: {zaznaczone.size}</span>
          </div>

          <div className="space-y-1.5">
            {kandydaci.map((k, i) => {
              const klucz = kluczLota(k, i);
              const drogie = ponadBudzet(k);
              const l = k.lot as {
                landed_cost_pln?: number | null;
                odometer_mi?: number | null;
                damage_primary?: string | null;
                url?: string | null;
                source?: string | null;
              };
              return (
                <label
                  key={klucz}
                  className={`flex cursor-pointer items-start gap-2 rounded border p-2 text-sm ${
                    drogie ? "border-dashed opacity-60" : "border-border"
                  }`}
                >
                  <Checkbox
                    checked={zaznaczone.has(klucz)}
                    onCheckedChange={() => przelacz(klucz)}
                    className="mt-0.5"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <b>{opisLota(k)}</b>
                      {k.is_top && <Badge className="text-[10px]">TOP</Badge>}
                      {typeof k.score === "number" && (
                        <Badge variant="outline" className="text-[10px]">
                          {k.score.toFixed(1)}
                        </Badge>
                      )}
                      {drogie && (
                        <Badge variant="secondary" className="text-[10px]">
                          ponad budżet
                        </Badge>
                      )}
                      {l.source && (
                        <span className="text-[10px] text-muted-foreground">{l.source}</span>
                      )}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {typeof l.landed_cost_pln === "number"
                        ? `${l.landed_cost_pln.toLocaleString("pl-PL")} zł pod drzwi`
                        : "cena pod drzwi nieustalona"}
                      {l.odometer_mi ? ` · ${l.odometer_mi.toLocaleString("pl-PL")} mi` : ""}
                      {l.damage_primary ? ` · ${l.damage_primary}` : ""}
                    </span>
                    {k.reasoning && (
                      <span className="block text-xs text-muted-foreground">{k.reasoning}</span>
                    )}
                  </span>
                  {l.url && (
                    <a
                      href={l.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="shrink-0 text-xs text-primary hover:underline"
                    >
                      aukcja
                    </a>
                  )}
                </label>
              );
            })}
          </div>

          <Button
            variant="outline"
            className="mt-3 w-full"
            disabled={zaznaczone.size === 0 || obrazekNaTelegram.isPending}
            onClick={() => obrazekNaTelegram.mutate()}
          >
            {obrazekNaTelegram.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <ImageDown className="mr-1.5 h-4 w-4" />
            )}
            Wyślij ofertę jako obrazek na mój Telegram ({zaznaczone.size})
          </Button>

          {tekstOferty && (
            <div className="mt-2 rounded border bg-muted/40 p-2">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-xs font-medium">Wiadomość do wysłania razem z obrazkiem</span>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-xs"
                  onClick={() => {
                    navigator.clipboard
                      .writeText(tekstOferty)
                      .then(() => toast.success("Skopiowane."))
                      .catch(() =>
                        toast.error("Przeglądarka nie dała skopiować — zaznacz i skopiuj ręcznie."),
                      );
                  }}
                >
                  <Copy className="mr-1 h-3 w-3" /> Kopiuj
                </Button>
              </div>
              <p className="whitespace-pre-wrap text-xs text-muted-foreground">{tekstOferty}</p>
            </div>
          )}

          <Button
            className="mt-2 w-full"
            disabled={zaznaczone.size === 0 || napiszOferte.isPending}
            onClick={() => napiszOferte.mutate()}
          >
            {napiszOferte.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="mr-1.5 h-4 w-4" />
            )}
            Napisz ofertę z zaznaczonych ({zaznaczone.size})
          </Button>
          <p className="mt-1.5 text-center text-xs text-muted-foreground">
            Powstanie propozycja do przeczytania. Do klienta nic nie wychodzi bez Twojego
            kliknięcia.
          </p>
        </>
      )}
    </Card>
  );
}

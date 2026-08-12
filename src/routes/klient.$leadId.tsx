import { useState } from "react";
import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Check, Loader2, MessageSquare, RefreshCw, Search, X } from "lucide-react";

import {
  approveDraft,
  getLeadDetail,
  recordClientReply,
  regenerateDraft,
  rejectDraft,
  patchLead,
  promoteLead,
  setLeadStage,
} from "@/functions/sales.functions";
import { readWhatsappConversation } from "@/functions/intake.functions";
import { backendSearch } from "@/functions/backend.functions";
import { WatchesPanel } from "@/components/panels/watches-panel";
import type { ClientCriteria } from "@/lib/types";

import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Etapy lejka — te same, co `Stage` w sales/models.py. */
const ETAPY = [
  "nowy",
  "kwalifikacja",
  "szukanie",
  "oferta",
  "rozmowa",
  "decyzja",
  "licytacja",
  "wygrana",
  "przegrana",
  "stracony",
];

const TON_SEGMENTU: Record<string, string> = {
  A: "bg-emerald-500/15 text-emerald-600 border-emerald-500/30",
  B: "bg-sky-500/15 text-sky-600 border-sky-500/30",
  C: "bg-amber-500/15 text-amber-600 border-amber-500/30",
  D: "bg-muted text-muted-foreground border-border",
};

export const Route = createFileRoute("/klient/$leadId")({
  component: KartaKlienta,
  errorComponent: BladKarty,
  notFoundComponent: () => <p className="p-6">Nie ma takiego klienta.</p>,
});

function BladKarty({ error }: { error: Error }) {
  const router = useRouter();
  return (
    <div className="p-6">
      <p className="mb-3 text-sm text-destructive">{error.message}</p>
      <Button onClick={() => router.invalidate()}>Spróbuj ponownie</Button>
    </div>
  );
}

/** Karta klienta — jedno miejsce na całą obsługę: co powiedział, co o nim wiemy,
 *  co mu proponujemy i czego jeszcze szukamy.
 *
 *  Wcześniej te informacje leżały w czterech ekranach (skrzynka, wyszukiwanie,
 *  rekordy, klienci), a broker składał je w głowie.
 */
function KartaKlienta() {
  const { leadId } = Route.useParams();
  const id = Number(leadId);
  const queryClient = useQueryClient();

  const fnDetail = useServerFn(getLeadDetail);
  const fnApprove = useServerFn(approveDraft);
  const fnReject = useServerFn(rejectDraft);
  const fnRegenerate = useServerFn(regenerateDraft);
  const fnReply = useServerFn(recordClientReply);
  const fnStage = useServerFn(setLeadStage);
  const fnPatch = useServerFn(patchLead);
  const fnPromote = useServerFn(promoteLead);
  const fnReadWhatsapp = useServerFn(readWhatsappConversation);
  const fnSearch = useServerFn(backendSearch);

  const [odpowiedz, setOdpowiedz] = useState("");
  const [tresc, setTresc] = useState<string | null>(null);
  const [zajety, setZajety] = useState<string | null>(null);
  const [budzet, setBudzet] = useState<string>("");
  const [przebieg, setPrzebieg] = useState<string>("");

  const { data: lead, isLoading } = useQuery({
    queryKey: ["lead", id],
    queryFn: () => fnDetail({ data: { leadId: id } }),
    refetchInterval: 30_000,
  });

  const odswiez = () => queryClient.invalidateQueries({ queryKey: ["lead", id] });

  async function zrob(nazwa: string, akcja: () => Promise<unknown>, komunikat?: string) {
    setZajety(nazwa);
    try {
      await akcja();
      if (komunikat) toast.success(komunikat);
      await odswiez();
    } catch (e) {
      const err = e as { message?: string };
      toast.error(err.message || "Nie udało się.");
    } finally {
      setZajety(null);
    }
  }

  if (isLoading || !lead) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const draft = lead.pending_drafts?.[0];
  const kryteria: ClientCriteria | null = lead.make
    ? {
        make: lead.make,
        model: lead.model,
        year_from: lead.year_from,
        year_to: lead.year_to,
        budget_pln_to: lead.budget_pln,
        settlement: lead.settlement === "company" ? "company" : "private",
        max_results: 15,
        sources: ["copart", "iaai", "manheim"],
        excluded_damage_types: ["Flood", "Fire"],
      }
    : null;

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center gap-3">
        <Button asChild variant="ghost" size="sm">
          <Link to="/inbox">
            <ArrowLeft className="mr-1.5 h-3.5 w-3.5" /> Skrzynka
          </Link>
        </Button>
        <h1 className="text-lg font-semibold">{lead.display_name}</h1>
        <Badge variant="outline" className={TON_SEGMENTU[lead.score.segment]}>
          {lead.score.segment} · {lead.score.score}/100
        </Badge>
        <Select
          value={lead.stage}
          onValueChange={(v) =>
            zrob("stage", () => fnStage({ data: { leadId: id, stage: v } }), "Etap zmieniony.")
          }
        >
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ETAPY.map((e) => (
              <SelectItem key={e} value={e}>
                {e}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {lead.phone && <span className="text-sm text-muted-foreground">{lead.phone}</span>}
        {/* Awans to jawna decyzja brokera, nie skutek uboczny zmiany etapu. */}
        {lead.client_id ? (
          <Badge variant="secondary">klient #{lead.client_id}</Badge>
        ) : (
          <Button
            size="sm"
            variant="outline"
            disabled={zajety !== null}
            title="Zapisz jako klienta w kartotece"
            onClick={() =>
              zrob("promote", async () => {
                const wynik = await fnPromote({ data: { leadId: id } });
                toast.success(wynik.message);
              })
            }
          >
            {zajety === "promote" ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Check className="mr-1.5 h-3.5 w-3.5" />
            )}
            Awansuj na klienta
          </Button>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {/* PROPOZYCJA AGENTA — jedyne miejsce, gdzie zapada decyzja o wysyłce */}
          <Card className="p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">✉️ Propozycja wiadomości</h3>
              <Button
                size="sm"
                variant="outline"
                disabled={zajety !== null}
                onClick={() =>
                  zrob("regen", () => fnRegenerate({ data: { leadId: id } }), "Nowa propozycja.")
                }
              >
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Napisz od nowa
              </Button>
            </div>

            {!draft ? (
              <p className="text-sm text-muted-foreground">
                Agent nie ma teraz nic do napisania. To bywa świadome — {lead.score.next_action}
              </p>
            ) : (
              <>
                <Textarea
                  rows={5}
                  value={tresc ?? draft.text}
                  onChange={(e) => setTresc(e.target.value)}
                  className="text-sm"
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  <b>Dlaczego tak:</b> {draft.rationale}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    disabled={zajety !== null}
                    onClick={() =>
                      zrob(
                        "approve",
                        async () => {
                          const wynik = await fnApprove({
                            data: {
                              draftId: draft.id,
                              ...(tresc && tresc !== draft.text ? { editedText: tresc } : {}),
                            },
                          });
                          setTresc(null);
                          // Serwer nie wysyła. Otwieramy WhatsAppa, klikasz Ty.
                          if (wynik.wa_me) window.open(wynik.wa_me, "_blank", "noopener");
                        },
                        "Zatwierdzone — otwieram WhatsApp.",
                      )
                    }
                  >
                    <Check className="mr-1.5 h-3.5 w-3.5" /> Zatwierdź i otwórz WhatsApp
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={zajety !== null}
                    onClick={() =>
                      zrob("reject", () => fnReject({ data: { draftId: draft.id } }), "Odrzucone.")
                    }
                  >
                    <X className="mr-1.5 h-3.5 w-3.5" /> Odrzuć
                  </Button>
                </div>
              </>
            )}
          </Card>

          {/* ROZMOWA */}
          <Card className="p-4">
            <h3 className="mb-2 text-sm font-semibold">💬 Rozmowa</h3>
            <div className="mb-3 max-h-72 space-y-2 overflow-y-auto">
              {(lead.messages ?? []).length === 0 && (
                <p className="text-sm text-muted-foreground">Jeszcze nic nie zapisano.</p>
              )}
              {(lead.messages ?? []).map((m) => (
                <div
                  key={m.id}
                  className={`rounded p-2 text-sm ${
                    m.author === "klient" ? "bg-muted" : "bg-primary/5 border border-primary/20"
                  }`}
                >
                  <span className="text-[10px] uppercase text-muted-foreground">{m.author}</span>
                  <div className="whitespace-pre-wrap">{m.text}</div>
                </div>
              ))}
            </div>
            <Textarea
              rows={2}
              placeholder="Wklej, co klient odpisał…"
              value={odpowiedz}
              onChange={(e) => setOdpowiedz(e.target.value)}
              className="text-sm"
            />
            <div className="mt-2 flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={!odpowiedz.trim() || zajety !== null}
                onClick={() =>
                  zrob(
                    "reply",
                    async () => {
                      await fnReply({ data: { leadId: id, text: odpowiedz.trim() } });
                      setOdpowiedz("");
                    },
                    "Zapisane. Agent przygotował odpowiedź.",
                  )
                }
              >
                <MessageSquare className="mr-1.5 h-3.5 w-3.5" /> Zapisz odpowiedź klienta
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={zajety !== null}
                title="Czyta rozmowę otwartą w oknie operatora"
                onClick={() =>
                  zrob(
                    "wa",
                    async () => {
                      const wynik = await fnReadWhatsapp({});
                      const ostatnia = [...(wynik.messages ?? [])]
                        .reverse()
                        .find((m) => m.kierunek === "klient");
                      if (!ostatnia)
                        throw new Error("W tej rozmowie nie ma wiadomości od klienta.");
                      setOdpowiedz(ostatnia.tekst);
                    },
                    "Wczytane z WhatsAppa — sprawdź i zapisz.",
                  )
                }
              >
                Wczytaj z WhatsAppa
              </Button>
            </div>
          </Card>
        </div>

        {/* PRAWA KOLUMNA: co wiemy i czego szukamy */}
        <div className="space-y-4">
          <Card className="p-4">
            <h3 className="mb-2 text-sm font-semibold">🎯 Co teraz</h3>
            <p className="text-sm">{lead.score.next_action}</p>
            {lead.score.missing.length > 0 && (
              <div className="mt-3">
                <div className="text-xs font-medium text-muted-foreground">Do dopytania</div>
                <ul className="mt-1 list-inside list-disc text-sm">
                  {lead.score.missing.map((m) => (
                    <li key={m}>{m}</li>
                  ))}
                </ul>
              </div>
            )}
            {lead.score.red_flags.length > 0 && (
              <div className="mt-3 rounded border border-amber-500/40 bg-amber-500/10 p-2">
                <div className="text-xs font-medium text-amber-600">Uwaga</div>
                <ul className="mt-1 list-inside list-disc text-sm">
                  {lead.score.red_flags.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          {/* Poprawki po telefonie. Wysyłamy tylko zmienione pola — backend
              rozróżnia brak pola od jawnego null, a damage_ok jest trójstanem. */}
          <Card className="p-4">
            <h3 className="mb-2 text-sm font-semibold">✏️ Popraw po rozmowie</h3>
            <div className="space-y-2">
              <div>
                <label className="text-xs text-muted-foreground" htmlFor="pole-budzet">
                  Budżet pod klucz (zł)
                </label>
                <Input
                  id="pole-budzet"
                  type="number"
                  placeholder={lead.budget_pln ? String(lead.budget_pln) : "nie podał"}
                  value={budzet}
                  onChange={(e) => setBudzet(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground" htmlFor="pole-przebieg">
                  Maksymalny przebieg (mile)
                </label>
                <Input
                  id="pole-przebieg"
                  type="number"
                  placeholder={lead.max_odometer_mi ? String(lead.max_odometer_mi) : "bez limitu"}
                  value={przebieg}
                  onChange={(e) => setPrzebieg(e.target.value)}
                />
              </div>
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <span className="text-xs text-muted-foreground">Auto po szkodzie:</span>
                {[
                  { etykieta: "zgadza się", wartosc: true as boolean | null },
                  { etykieta: "odmawia", wartosc: false as boolean | null },
                  { etykieta: "nie pytaliśmy", wartosc: null as boolean | null },
                ].map((opcja) => (
                  <Button
                    key={String(opcja.wartosc)}
                    size="sm"
                    variant={lead.damage_ok === opcja.wartosc ? "default" : "outline"}
                    disabled={zajety !== null}
                    onClick={() =>
                      zrob(
                        "patch",
                        () =>
                          fnPatch({ data: { leadId: id, changes: { damage_ok: opcja.wartosc } } }),
                        "Zapisane.",
                      )
                    }
                  >
                    {opcja.etykieta}
                  </Button>
                ))}
              </div>
              <Button
                size="sm"
                className="mt-1"
                disabled={zajety !== null || (!budzet && !przebieg)}
                onClick={() =>
                  zrob(
                    "patch",
                    async () => {
                      const changes: Record<string, number> = {};
                      if (budzet) changes.budget_pln = Number(budzet);
                      if (przebieg) changes.max_odometer_mi = Number(przebieg);
                      const wynik = await fnPatch({ data: { leadId: id, changes } });
                      setBudzet("");
                      setPrzebieg("");
                      toast.info(
                        `Ocena po zmianie: ${wynik.score.score}/100 (${wynik.score.segment})`,
                      );
                    },
                    "Zapisane.",
                  )
                }
              >
                {zajety === "patch" ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Check className="mr-1.5 h-3.5 w-3.5" />
                )}
                Zapisz
              </Button>
            </div>
          </Card>

          {/* Auto w rozliczeniu bywa CAŁYM budżetem klienta — pieniądze są zamrożone
              w aucie, które dopiero trzeba sprzedać. Bez tego lead z segmentu A
              wygląda jak lead bez pieniędzy. */}
          {lead.trade_in_model && (
            <Card className="p-4">
              <h3 className="mb-2 text-sm font-semibold">🔁 Ma do sprzedania</h3>
              <div className="text-sm">
                {[lead.trade_in_year, lead.trade_in_model].filter(Boolean).join(" ")}
                {lead.trade_in_value_pln
                  ? ` — ok. ${lead.trade_in_value_pln.toLocaleString("pl-PL")} zł`
                  : ""}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Badge variant={lead.trade_in_sold ? "default" : "secondary"}>
                  {lead.trade_in_sold ? "sprzedane" : "jeszcze nie sprzedane"}
                </Badge>
                {!lead.trade_in_sold && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={zajety !== null}
                    title="Klient sprzedał auto — odblokowuje budżet"
                    onClick={() =>
                      zrob(
                        "patch",
                        () =>
                          fnPatch({ data: { leadId: id, changes: { trade_in_sold: true } } }),
                        "Zapisane — budżet klienta jest wolny.",
                      )
                    }
                  >
                    Sprzedał
                  </Button>
                )}
              </div>
              {lead.blocked_by && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Czeka na: {lead.blocked_by}
                </p>
              )}
            </Card>
          )}

          <Card className="p-4">
            <h3 className="mb-2 text-sm font-semibold">🔎 Czego szuka</h3>
            {kryteria ? (
              <>
                <div className="text-sm">
                  {[kryteria.make, kryteria.model].filter(Boolean).join(" ")}
                  {kryteria.year_from ? `, ${kryteria.year_from}–${kryteria.year_to ?? ""}` : ""}
                </div>
                {(lead.engine_hint || lead.trim_hint) && (
                  <div className="text-xs text-muted-foreground">
                    {[lead.engine_hint, lead.trim_hint].filter(Boolean).join(" · ")}
                  </div>
                )}
                <div className="text-xs text-muted-foreground">
                  {lead.budget_pln
                    ? `budżet ${lead.budget_pln.toLocaleString("pl-PL")} zł pod klucz`
                    : "budżet niepodany — bez niego nie policzymy ceny końcowej"}
                </div>
                <Button
                  size="sm"
                  className="mt-3"
                  disabled={zajety !== null}
                  onClick={() =>
                    zrob("search", async () => {
                      const res = await fnSearch({ data: { criteria: kryteria } });
                      const ile = res.listings?.length ?? 0;
                      toast.info(
                        ile > 0 ? `Znaleziono ${ile} aut.` : "Nic nie pasuje do tych kryteriów.",
                      );
                    })
                  }
                >
                  {zajety === "search" ? (
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Search className="mr-1.5 h-3.5 w-3.5" />
                  )}
                  Szukaj teraz
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Klient nie podał marki — bez niej nie ma czego szukać.
              </p>
            )}
          </Card>

          <WatchesPanel
            criteria={kryteria}
            clientName={lead.display_name}
            clientPhone={lead.phone}
          />
        </div>
      </div>
    </div>
  );
}

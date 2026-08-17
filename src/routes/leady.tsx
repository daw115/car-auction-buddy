/** Wszystkie leady — także te, o których Skrzynka milczy.
 *
 *  Skrzynka pokazuje wyłącznie dwie rzeczy: propozycje czekające na zgodę
 *  i leady bez propozycji. Klient, któremu broker odpisał i który jeszcze nie
 *  odpowiedział, nie mieści się w żadnej z nich — znikał więc z panelu na
 *  dobre, mimo że backend zwracał go pod `/api/sales/leads`. To była cicha
 *  utrata najbardziej wartościowych rozmów: tych w toku.
 */

import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Users } from "lucide-react";

import { getSalesLeads, type Lead, type LeadScore } from "@/functions/sales.functions";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/leady")({
  component: LeadyPage,
});

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
] as const;

/** Segment mówi, kto kupi. Kolor ma to powiedzieć bez czytania liczby. */
function SegmentBadge({ score }: { score: LeadScore }) {
  const wariant =
    score.segment === "A" ? "default" : score.segment === "B" ? "secondary" : "outline";
  return (
    <Badge variant={wariant} className="text-[10px]">
      {score.segment} · {score.score}
    </Badge>
  );
}

function kiedy(stamp: string | null): string {
  if (!stamp) return "—";
  const minut = Math.round((Date.now() - new Date(stamp).getTime()) / 60000);
  if (minut < 60) return `${minut} min temu`;
  const godzin = Math.round(minut / 60);
  return godzin < 48 ? `${godzin} h temu` : `${Math.round(godzin / 24)} dni temu`;
}

function LeadyPage() {
  const fnLeady = useServerFn(getSalesLeads);
  const [szukaj, setSzukaj] = useState("");
  const [etap, setEtap] = useState<string>("");

  const { data, isLoading } = useQuery({
    queryKey: ["leady"],
    queryFn: () => fnLeady(),
  });

  const wszystkie = data?.items ?? [];
  const widoczne = wszystkie.filter((lead) => {
    if (etap && lead.stage !== etap) return false;
    if (!szukaj) return true;
    const fraza = szukaj.toLowerCase();
    return [lead.display_name, lead.phone, lead.make, lead.model]
      .filter(Boolean)
      .some((v) => String(v).toLowerCase().includes(fraza));
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Leady"
        description="Wszystkie rozmowy, także te w toku. Skrzynka pokazuje tylko to, co czeka na Twoją zgodę."
      />

      <div className="flex flex-wrap items-center gap-2">
        <Input
          placeholder="Szukaj po nazwisku, telefonie, marce…"
          value={szukaj}
          onChange={(e) => setSzukaj(e.target.value)}
          className="max-w-xs"
        />
        <Button size="sm" variant={etap === "" ? "default" : "outline"} onClick={() => setEtap("")}>
          wszystkie ({wszystkie.length})
        </Button>
        {ETAPY.map((e) => {
          const ile = wszystkie.filter((l) => l.stage === e).length;
          if (!ile) return null;
          return (
            <Button
              key={e}
              size="sm"
              variant={etap === e ? "default" : "outline"}
              onClick={() => setEtap(etap === e ? "" : e)}
            >
              {e} ({ile})
            </Button>
          );
        })}
      </div>

      {isLoading ? (
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      ) : widoczne.length === 0 ? (
        <Card className="p-8 text-center text-muted-foreground">
          <Users className="mx-auto mb-2 h-10 w-10 opacity-40" />
          {wszystkie.length === 0
            ? "Nie ma jeszcze żadnego leada."
            : "Żaden lead nie pasuje do tego filtra."}
        </Card>
      ) : (
        <div className="grid gap-2">
          {widoczne.map((lead: Lead & { score: LeadScore }) => (
            <Link key={lead.id} to="/klient/$leadId" params={{ leadId: String(lead.id) }}>
              <Card className="p-3 transition-shadow hover:shadow-md">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{lead.display_name}</span>
                      <SegmentBadge score={lead.score} />
                      <Badge variant="outline" className="text-[10px]">
                        {lead.stage}
                      </Badge>
                      {lead.blocked_by ? (
                        <Badge variant="secondary" className="text-[10px]">
                          czeka: {lead.blocked_by}
                        </Badge>
                      ) : null}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {[lead.make, lead.model].filter(Boolean).join(" ") || "bez kryteriów"}
                      {lead.budget_pln
                        ? ` · ${lead.budget_pln.toLocaleString("pl-PL")} zł pod drzwi`
                        : ""}
                      {lead.phone ? ` · ${lead.phone}` : ""}
                    </div>
                    <div className="text-xs text-muted-foreground">{lead.score.next_action}</div>
                  </div>
                  <div className="shrink-0 text-right text-xs text-muted-foreground">
                    {kiedy(lead.updated_at ?? lead.created_at)}
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

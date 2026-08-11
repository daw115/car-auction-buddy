// Skrzynka brokera — jedyny ekran, który trzeba otworzyć rano.
//
// Ekran odpowiada na jedno pytanie: co wysłać i do kogo, w tej kolejności. Dlatego
// pozycje są posortowane po segmencie leada, a nie po dacie: najpierw ci, którzy kupią.
//
// PRZYCISK „WYŚLIJ” NIE WYSYŁA. Zapisuje wiadomość jako wysłaną i otwiera WhatsAppa
// z wpisaną treścią — ostatnie kliknięcie należy do brokera, bo wiadomość idzie
// z jego telefonu i pod jego nazwiskiem.

import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import {
  AlertTriangle,
  Check,
  Inbox as InboxIcon,
  Loader2,
  MessageSquare,
  RefreshCw,
  Search,
  Send,
  X,
} from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import {
  approveDraft,
  getSalesInbox,
  recordClientReply,
  regenerateDraft,
  rejectDraft,
  startLeadSearch,
  type Inbox,
  type InboxItem,
  type LeadScore,
  type LeadSegment,
} from "@/functions/sales.functions";

export const Route = createFileRoute("/inbox")({
  head: () => ({
    meta: [
      { title: "Skrzynka sprzedaży — USA Car Finder" },
      {
        name: "description",
        content:
          "Propozycje wiadomości do klientów czekające na zatwierdzenie, z oceną leada i następnym krokiem.",
      },
    ],
  }),
  component: InboxPage,
});

const SEGMENT_STYLE: Record<LeadSegment, string> = {
  A: "bg-emerald-600 text-white",
  B: "bg-sky-600 text-white",
  C: "bg-amber-500 text-white",
  D: "bg-muted text-muted-foreground",
};

function ScoreBadge({ score }: { score: LeadScore }) {
  return (
    <span className="flex items-center gap-2">
      <Badge className={SEGMENT_STYLE[score.segment]}>
        {score.segment} · {score.segment_label}
      </Badge>
      <span className="text-xs text-muted-foreground">{score.score.toFixed(0)}/100</span>
    </span>
  );
}

/** Rozbicie oceny. Broker ma widzieć, skąd wzięła się liczba, zanim na niej polegnie. */
function ScoreBreakdown({ score }: { score: LeadScore }) {
  return (
    <div className="space-y-1">
      {score.components.map((c) => (
        <div key={c.key} className="flex items-center gap-2 text-xs">
          <div className="h-1.5 w-24 shrink-0 overflow-hidden rounded bg-muted">
            <div className="h-full bg-primary" style={{ width: `${Math.round(c.value * 100)}%` }} />
          </div>
          <span className="w-56 shrink-0 truncate text-muted-foreground">{c.label}</span>
          <span className="truncate text-muted-foreground/80">{c.note}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Wyszukiwanie z kryteriów leada — ostatnie brakujące ogniwo agenta.
 *
 * Do tej pory marka, model, rocznik i budżet leżały w bazie, a broker i tak
 * przepisywał je ręcznie do formularza na stronie głównej. Tu jest jeden przycisk,
 * a wynik ląduje przy leadzie.
 */
function SearchRow({ item, onDone }: { item: InboxItem; onDone: () => void }) {
  const start = useServerFn(startLeadSearch);
  const [busy, setBusy] = useState(false);
  const stan = item.search;
  const lead = item.lead;

  // Bez marki nie ma czego szukać — backend i tak odmówi, więc nie pokazujemy
  // przycisku, który na pewno zwróci błąd.
  if (!lead?.make) return null;

  const handleStart = async () => {
    setBusy(true);
    try {
      const wynik = await start({ data: { leadId: item.lead_id } });
      toast.success(
        wynik.warnings.length
          ? `Szukam. Uwaga: brakuje ${wynik.warnings.join(", ")}.`
          : "Szukam — wynik pojawi się za kilka minut.",
      );
      onDone();
    } catch (error) {
      const msg = String(error);
      toast.error(
        msg.includes("409") ? "Dla tego leada wyszukiwanie już trwa." : `Nie udało się: ${msg}`,
      );
    } finally {
      setBusy(false);
    }
  };

  const opis =
    stan?.status === "running"
      ? "Szukam…"
      : stan?.status === "done"
        ? `${stan.candidate_count} ${stan.candidate_count === 1 ? "kandydat" : "kandydatów"}`
        : stan?.status === "error"
          ? `Wyszukiwanie padło: ${stan.error ?? "nieznany błąd"}`
          : "Nie szukaliśmy jeszcze";

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
      <span className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">
          {lead.make} {lead.model ?? ""} {lead.year_from ? `${lead.year_from}+` : ""}
        </span>
        {" · "}
        {opis}
      </span>
      <Button
        size="sm"
        variant={stan?.offer_ready ? "secondary" : "outline"}
        onClick={handleStart}
        disabled={busy || stan?.status === "running"}
      >
        {busy || stan?.status === "running" ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <Search className="mr-2 h-4 w-4" />
        )}
        {stan?.status === "done" ? "Szukaj ponownie" : "Szukaj aut"}
      </Button>
    </div>
  );
}

function DraftCard({ item, onDone }: { item: InboxItem; onDone: () => void }) {
  const approve = useServerFn(approveDraft);
  const reject = useServerFn(rejectDraft);
  const reply = useServerFn(recordClientReply);
  const regenerate = useServerFn(regenerateDraft);

  const [text, setText] = useState(item.text);
  const [clientReply, setClientReply] = useState("");
  const [busy, setBusy] = useState<null | "approve" | "reject" | "reply" | "regen">(null);
  const [showDetails, setShowDetails] = useState(false);

  const edited = text.trim() !== item.text.trim();

  const handleApprove = async () => {
    setBusy("approve");
    try {
      const result = await approve({
        data: { draftId: item.id, editedText: edited ? text.trim() : undefined },
      });
      // Otwieramy WhatsAppa dopiero teraz i w nowej karcie. Wiadomość jest już
      // zapisana w wątku, więc nawet gdy broker zamknie kartę bez wysłania,
      // historia rozmowy się zgadza z tym, co zatwierdził.
      if (result.wa_me) window.open(result.wa_me, "_blank", "noopener,noreferrer");
      else if (result.mailto) window.location.href = result.mailto;
      toast.success("Zatwierdzone — otwieram WhatsAppa z wpisaną treścią");
      onDone();
    } catch (error) {
      toast.error(`Nie udało się zatwierdzić: ${String(error)}`);
    } finally {
      setBusy(null);
    }
  };

  const handleReject = async () => {
    setBusy("reject");
    try {
      await reject({ data: { draftId: item.id, reason: "odrzucone w panelu" } });
      toast.success("Odrzucone. Propozycja zostaje w historii do wglądu.");
      onDone();
    } catch (error) {
      toast.error(`Nie udało się odrzucić: ${String(error)}`);
    } finally {
      setBusy(null);
    }
  };

  const handleReply = async () => {
    if (!clientReply.trim()) return;
    setBusy("reply");
    try {
      await reply({ data: { leadId: item.lead_id, text: clientReply.trim() } });
      toast.success("Zapisane. Agent przygotował odpowiedź.");
      setClientReply("");
      onDone();
    } catch (error) {
      toast.error(`Nie udało się zapisać: ${String(error)}`);
    } finally {
      setBusy(null);
    }
  };

  const handleRegenerate = async () => {
    setBusy("regen");
    try {
      const result = await regenerate({ data: { leadId: item.lead_id } });
      if (result.draft) {
        toast.success("Nowa propozycja gotowa");
        onDone();
      } else {
        toast.info(result.reason ?? "Agent nie ma nic do napisania na tym etapie");
      }
    } catch (error) {
      toast.error(`Nie udało się wygenerować: ${String(error)}`);
    } finally {
      setBusy(null);
    }
  };

  const lead = item.lead;

  return (
    <Card className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <Link
            to="/klient/$leadId"
            params={{ leadId: String(item.lead_id) }}
            className="font-medium hover:underline"
            title="Otwórz kartę klienta"
          >
            {lead?.display_name ?? `lead #${item.lead_id}`}
          </Link>
          <ScoreBadge score={item.score} />
          <Badge variant="outline">{item.channel}</Badge>
          {lead?.stage ? <Badge variant="secondary">{lead.stage}</Badge> : null}
        </div>
        <Button variant="ghost" size="sm" onClick={() => setShowDetails((v) => !v)}>
          {showDetails ? "Zwiń" : "Szczegóły oceny"}
        </Button>
      </div>

      <p className="text-sm text-muted-foreground">
        <span className="font-medium text-foreground">Następny krok: </span>
        {item.score.next_action}
      </p>

      {item.score.red_flags.length > 0 ? (
        <ul className="space-y-1 rounded border border-amber-500/40 bg-amber-500/5 p-2">
          {item.score.red_flags.map((flag) => (
            <li key={flag} className="flex gap-2 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{flag}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {showDetails ? (
        <div className="space-y-3 rounded bg-muted/40 p-3">
          <ScoreBreakdown score={item.score} />
          {lead?.raw_request ? (
            <p className="border-t pt-2 text-xs text-muted-foreground">
              <span className="font-medium">Zgłoszenie: </span>
              {lead.raw_request}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">
          Propozycja agenta {edited ? "(zmieniona)" : ""}
        </label>
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={4}
          className="text-sm"
        />
        {item.rationale ? (
          <p className="whitespace-pre-line text-xs text-muted-foreground">
            <span className="font-medium">Dlaczego to: </span>
            {item.rationale}
          </p>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button onClick={handleApprove} disabled={busy !== null || !text.trim()}>
          {busy === "approve" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Send className="mr-2 h-4 w-4" />
          )}
          Zatwierdź i otwórz WhatsAppa
        </Button>
        <Button variant="outline" onClick={handleRegenerate} disabled={busy !== null}>
          {busy === "regen" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-2 h-4 w-4" />
          )}
          Napisz inaczej
        </Button>
        <Button variant="ghost" onClick={handleReject} disabled={busy !== null}>
          <X className="mr-2 h-4 w-4" />
          Odrzuć
        </Button>
      </div>

      <SearchRow item={item} onDone={onDone} />

      <div className="space-y-2 border-t pt-3">
        <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <MessageSquare className="h-3.5 w-3.5" />
          Klient odpisał — wklej treść, agent przygotuje odpowiedź
        </label>
        <div className="flex gap-2">
          <Textarea
            value={clientReply}
            onChange={(event) => setClientReply(event.target.value)}
            rows={2}
            placeholder="Wklej wiadomość od klienta…"
            className="text-sm"
          />
          <Button
            variant="secondary"
            onClick={handleReply}
            disabled={busy !== null || !clientReply.trim()}
          >
            {busy === "reply" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Check className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    </Card>
  );
}

function InboxPage() {
  const fetchInbox = useServerFn(getSalesInbox);
  const regenerate = useServerFn(regenerateDraft);
  const [data, setData] = useState<Inbox | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchInbox());
    } catch (error) {
      toast.error(`Nie udało się pobrać skrzynki: ${String(error)}`);
    } finally {
      setLoading(false);
    }
  }, [fetchInbox]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleWrite = async (leadId: number) => {
    try {
      const result = await regenerate({ data: { leadId } });
      if (result.draft) {
        toast.success("Propozycja gotowa");
        void load();
      } else {
        toast.info(result.reason ?? "Agent nie ma nic do napisania");
      }
    } catch (error) {
      toast.error(`Nie udało się wygenerować: ${String(error)}`);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Skrzynka sprzedaży"
        description="Propozycje wiadomości czekające na Twoją zgodę. Nic nie idzie do klienta, dopóki nie klikniesz."
        icon={<InboxIcon className="h-5 w-5" />}
      />

      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
          {loading ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-2 h-4 w-4" />
          )}
          Odśwież
        </Button>
      </div>

      {loading && !data ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">Ładuję…</Card>
      ) : null}

      {data && data.items.length === 0 && data.needs_attention.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">
          Pusto — nic nie czeka na zatwierdzenie.
        </Card>
      ) : null}

      {data?.items.map((item) => (
        <DraftCard key={item.id} item={item} onDone={() => void load()} />
      ))}

      {data && data.needs_attention.length > 0 ? (
        <Card className="space-y-3 p-4">
          <div>
            <h2 className="text-sm font-medium">Czekają bez propozycji</h2>
            <p className="text-xs text-muted-foreground">
              Ktoś czeka na odpowiedź, a agent nie miał czego napisać albo nie zdążył. Nie giną — tu
              są, żeby żaden lead nie przepadł przez awarię modelu.
            </p>
          </div>
          {data.needs_attention.map((lead) => (
            <div key={lead.id} className="space-y-2 rounded border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-3">
                  <span className="font-medium">{lead.display_name}</span>
                  <ScoreBadge score={lead.score} />
                  <span className="text-xs text-muted-foreground">{lead.score.next_action}</span>
                </div>
                <Button size="sm" variant="secondary" onClick={() => void handleWrite(lead.id)}>
                  Napisz propozycję
                </Button>
              </div>
              {lead.last_client_message ? (
                <p className="border-l-2 pl-2 text-xs text-muted-foreground">
                  {lead.last_client_message}
                </p>
              ) : null}
            </div>
          ))}
        </Card>
      ) : null}
    </div>
  );
}

import { useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import { Loader2, MessageCircle, Copy, ExternalLink } from "lucide-react";

import { backendWhatsappDraft } from "@/functions/backend.functions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

type Props = {
  /** Loty zaznaczone przez brokera — backend bierze z nich 3-4 pierwsze. */
  lots: Record<string, unknown>[];
  budgetPln?: number | null;
  settlement?: "private" | "company";
  /** Wśród zaznaczonych jest auto droższe niż budżet klienta. */
  hasOverBudget?: boolean;
  disabled?: boolean;
};

/** Broker generuje treść, czyta ją i dopiero wtedy wysyła sam.
 *
 *  Nic tu nie wysyła wiadomości. Link wa.me tylko otwiera WhatsApp z wpisanym
 *  tekstem — przycisk „wyślij” zostaje po stronie człowieka, bo wiadomość idzie
 *  pod jego nazwiskiem i to on odpowiada za to, co klient dostanie. */
export function WhatsappDraftDialog({
  lots,
  budgetPln,
  settlement,
  hasOverBudget = false,
  disabled,
}: Props) {
  const generate = useServerFn(backendWhatsappDraft);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState<string | null>(null);
  // Domyślnie NIE. Auto ponad budżet wchodzi do wiadomości dopiero, gdy broker
  // świadomie to zaznaczy — i wtedy treść mówi o tym klientowi wprost.
  const [allowOverBudget, setAllowOverBudget] = useState(false);
  const [waMeUrl, setWaMeUrl] = useState<string | null>(null);
  const [offers, setOffers] = useState(0);

  async function handleGenerate() {
    setBusy(true);
    try {
      const res = await generate({
        data: {
          lots: lots.slice(0, 10),
          client: { name: name.trim() || null, phone: phone.trim() || null },
          budgetPln: budgetPln ?? null,
          ...(settlement ? { settlement } : {}),
          allowOverBudget,
        },
      });
      setText(res.text);
      setWaMeUrl(res.waMeUrl);
      setOffers(res.offers);
      if (!res.text) {
        toast.warning(
          hasOverBudget && !allowOverBudget
            ? "Zaznaczone auta są ponad budżet. Zaznacz zgodę poniżej, żeby weszły do treści."
            : "Żaden lot nie mieści się w budżecie — nie ma czego wysyłać.",
        );
      } else if (res.skipped) {
        toast.info(`Pominięto ${res.skipped} — ponad budżet klienta.`);
      }
    } catch (e) {
      const err = e as { message?: string };
      toast.error(err.message || "Nie udało się wygenerować wiadomości.");
    } finally {
      setBusy(false);
    }
  }

  async function handleCopy() {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Treść skopiowana.");
    } catch {
      toast.error("Przeglądarka zablokowała schowek — zaznacz tekst i skopiuj ręcznie.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          title="Wygeneruj wiadomość do klienta"
        >
          <MessageCircle className="mr-1.5 h-3.5 w-3.5" /> WhatsApp
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Wiadomość do klienta</DialogTitle>
          <DialogDescription>
            Aplikacja niczego nie wysyła. Przeczytaj treść, popraw jeśli trzeba, wyślij sam.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="wa-name">Imię klienta</Label>
            <Input
              id="wa-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Wojciech"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wa-phone">Telefon (opcjonalnie)</Label>
            <Input
              id="wa-phone"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="605 083 832"
            />
          </div>
        </div>

        {hasOverBudget && (
          <label className="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
            <Checkbox
              checked={allowOverBudget}
              onCheckedChange={(v) => setAllowOverBudget(v === true)}
              className="mt-0.5"
            />
            <span>
              Wśród zaznaczonych jest auto droższe niż budżet klienta. Zaznacz, żeby weszło do
              wiadomości — w treści będzie opisane jako powyżej budżetu.
            </span>
          </label>
        )}

        {text !== null && (
          <div className="space-y-1.5">
            <Label htmlFor="wa-text">
              Treść {offers > 0 && <span className="text-muted-foreground">({offers} ofert)</span>}
            </Label>
            <Textarea
              id="wa-text"
              rows={10}
              value={text ?? ""}
              onChange={(e) => setText(e.target.value)}
              className="font-mono text-xs"
              placeholder="Brak ofert w budżecie — nie ma czego wysyłać."
            />
          </div>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="outline" onClick={handleGenerate} disabled={busy}>
            {busy ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <MessageCircle className="mr-1.5 h-3.5 w-3.5" />
            )}
            {text === null ? "Generuj" : "Generuj ponownie"}
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleCopy} disabled={!text}>
              <Copy className="mr-1.5 h-3.5 w-3.5" /> Kopiuj
            </Button>
            <Button asChild disabled={!waMeUrl}>
              {/* Otwarcie WhatsAppa to nie wysyłka — broker wciąż klika „wyślij”. */}
              <a
                href={waMeUrl ?? "#"}
                target="_blank"
                rel="noreferrer"
                aria-disabled={!waMeUrl}
                className={!waMeUrl ? "pointer-events-none opacity-50" : undefined}
              >
                <ExternalLink className="mr-1.5 h-3.5 w-3.5" /> Otwórz WhatsApp
              </a>
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

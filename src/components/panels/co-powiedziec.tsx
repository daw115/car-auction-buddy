/** Co powiedzieć nowemu klientowi — gotowe zdania, nie nazwy pól.
 *
 *  Karta „Co teraz" pokazywała listę braków w postaci, w jakiej liczy je backend:
 *  „czy godzi się na auto po szkodzie", „budżet pod drzwi w złotówkach". To są
 *  nazwy pól, a broker w rozmowie potrzebuje ZDANIA — i musiał je za każdym razem
 *  układać sam, przy telefonie, na gorąco.
 *
 *  Różnica nie jest kosmetyczna. Pytanie o zgodę na auto po szkodzie to
 *  najtrudniejsze zdanie w tej sprzedaży: źle postawione kończy rozmowę, a odmowa
 *  klienta jest najczęstszą przyczyną utraty leada.
 *
 *  DWIE FORMY, BO TO DWA KANAŁY. Przez telefon zdanie może nieść powód;
 *  w wiadomości ma być krótkie, bo długi tekst na WhatsAppie zostaje bez
 *  odpowiedzi. Broker wybiera raz, a wybór zostaje na czas rozmowy.
 */

import { useState } from "react";
import { toast } from "sonner";
import { Check, Copy, MessageSquare, Phone } from "lucide-react";

import { Button } from "@/components/ui/button";

export type Podpowiedz = {
  klucz: string;
  temat: string;
  przez_telefon: string;
  na_pismie: string;
  dlaczego: string;
};

export function CoPowiedziec({ podpowiedzi }: { podpowiedzi: Podpowiedz[] }) {
  const [kanal, setKanal] = useState<"telefon" | "pismo">("telefon");
  const [skopiowane, setSkopiowane] = useState<string | null>(null);

  if (!podpowiedzi?.length) return null;

  const tresc = (p: Podpowiedz) => (kanal === "telefon" ? p.przez_telefon : p.na_pismie);

  const kopiuj = (p: Podpowiedz) => {
    navigator.clipboard
      .writeText(tresc(p))
      .then(() => {
        setSkopiowane(p.klucz);
        setTimeout(() => setSkopiowane(null), 2000);
      })
      .catch(() => toast.error("Przeglądarka nie dała skopiować — zaznacz i skopiuj ręcznie."));
  };

  return (
    <div className="mt-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-xs font-medium text-muted-foreground">
          Do dopytania ({podpowiedzi.length})
        </div>
        <div className="flex gap-1">
          <Button
            size="sm"
            variant={kanal === "telefon" ? "default" : "outline"}
            className="h-6 px-2 text-xs"
            onClick={() => setKanal("telefon")}
          >
            <Phone className="mr-1 h-3 w-3" /> Rozmowa
          </Button>
          <Button
            size="sm"
            variant={kanal === "pismo" ? "default" : "outline"}
            className="h-6 px-2 text-xs"
            onClick={() => setKanal("pismo")}
          >
            <MessageSquare className="mr-1 h-3 w-3" /> Wiadomość
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        {podpowiedzi.map((p, i) => (
          <div key={p.klucz} className="rounded border bg-muted/30 p-2">
            <div className="mb-1 flex items-start justify-between gap-2">
              {/* Numer, bo kolejność nie jest przypadkowa: najpierw pytania,
                  które mogą zakończyć rozmowę, potem doprecyzowujące. */}
              <span className="text-xs font-medium">
                {i + 1}. {p.temat}
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="h-5 shrink-0 px-1.5 text-xs"
                onClick={() => kopiuj(p)}
                title="Kopiuj do schowka"
              >
                {skopiowane === p.klucz ? (
                  <Check className="h-3 w-3 text-success" />
                ) : (
                  <Copy className="h-3 w-3" />
                )}
              </Button>
            </div>
            <p className="text-sm leading-snug">{tresc(p)}</p>
            <p className="mt-1 text-[11px] italic text-muted-foreground">{p.dlaczego}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// Publiczny checker VIN — landing dla klientów z zewnątrz.
//
// Strona renderuje się poza bramką hasła (patrz `src/lib/public-routes.ts`) i nie
// pokazuje niczego z panelu. Czyta wyłącznie publiczny endpoint backendu.
//
// DLACZEGO WYNIK JEST BEZ BRAMKI KONTAKTOWEJ. Przy prowizji rzędu 3-19 tys. zł nie
// opłaca się kupować masy leadów, opłaca się kilku właściwych. Otwarte narzędzie
// filtruje przez samoselekcję: kto sam wróci po pełną kalkulację, jest wart czasu.
// Numer telefonu wyciągnięty od kogoś, kto sprawdzał VIN z ciekawości, jest szumem.
//
// Ton tekstów jest ten sam, co w ofertach (`agent-oferta-auto-usa.md`): bez
// wykrzykników, bez obietnic, których nie dotrzymamy, i z nazwaniem wprost tego,
// czego nie wiemy.

import { createFileRoute } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { AlertTriangle, Check, Loader2, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { sprawdzVin, zglosLead, type VinCheckResult } from "@/lib/vin-check";

export const Route = createFileRoute("/sprawdz-vin")({
  head: () => ({
    meta: [
      { title: "Sprawdź cło po VIN — auta z USA" },
      {
        name: "description",
        content:
          "Wklej VIN i sprawdź, czy auto z USA ma zerowe cło, jaka jest stawka akcyzy " +
          "i ile wyjdzie pod klucz w Polsce. Bez podawania kontaktu.",
      },
    ],
  }),
  component: VinCheckPage,
});

function pln(value: number): string {
  return `${Math.round(value).toLocaleString("pl-PL")} zł`;
}

function ResultCard({ wynik }: { wynik: VinCheckResult }) {
  const zeroweClo = wynik.duty_free;

  return (
    <Card className="space-y-5 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <Badge className={zeroweClo ? "bg-emerald-600 text-white" : "bg-amber-600 text-white"}>
          {zeroweClo ? "Cło 0%" : `Cło ${wynik.duty_rate_pct}%`}
        </Badge>
        <span className="text-sm text-muted-foreground">
          Montaż: <span className="font-medium text-foreground">{wynik.assembly_country}</span>
        </span>
        <span className="text-sm text-muted-foreground">
          Akcyza: <span className="font-medium text-foreground">{wynik.excise_rate_pct}%</span>
        </span>
      </div>

      {wynik.saving_pln !== undefined && wynik.saving_pln > 0 ? (
        <div className="rounded-lg border border-emerald-600/30 bg-emerald-600/5 p-4">
          <p className="text-sm text-muted-foreground">Na tym aucie zerowe cło oszczędza</p>
          <p className="text-3xl font-semibold text-emerald-700 dark:text-emerald-400">
            {pln(wynik.saving_pln)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Różnica wobec kwoty liczonej po dawnej stawce 10%.
          </p>
        </div>
      ) : null}

      {wynik.landed_pln !== undefined ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded border p-3">
            <p className="text-xs text-muted-foreground">Cena pod klucz w Polsce</p>
            <p className="text-2xl font-semibold">{pln(wynik.landed_pln)}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Zakup, transport, odprawa, akcyza i prowizja. Bez rejestracji i bez naprawy.
            </p>
          </div>
          {wynik.landed_if_duty_10_pln !== undefined ? (
            <div className="rounded border p-3 opacity-70">
              <p className="text-xs text-muted-foreground">Gdyby liczyć po dawnym cle 10%</p>
              <p className="text-2xl font-semibold line-through">
                {pln(wynik.landed_if_duty_10_pln)}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="space-y-1 text-sm">
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Dlaczego taka stawka cła: </span>
          {wynik.duty_reason}
        </p>
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Akcyza: </span>
          {wynik.excise_reason}
        </p>
      </div>

      {wynik.assumptions.length > 0 ? (
        <ul className="space-y-2 rounded border border-amber-500/40 bg-amber-500/5 p-3">
          {wynik.assumptions.map((a) => (
            <li key={a} className="flex gap-2 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{a}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <p className="text-xs text-muted-foreground">
        Wyliczenie po kursie {wynik.usd_rate.toFixed(4)} zł. Cło zależy od kraju montażu, a nie od
        marki — decyduje pierwszy znak numeru VIN. To wyliczenie jest orientacyjne i nie zastępuje
        odprawy celnej.
      </p>
    </Card>
  );
}

function LeadForm({ wynik }: { wynik: VinCheckResult }) {
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!phone.trim()) return;
    setBusy(true);
    try {
      await zglosLead({
        name: name.trim() || undefined,
        phone: phone.trim(),
        website,
        message:
          `Pełna kalkulacja dla VIN ${wynik.vin} (${wynik.assembly_country}, ` +
          `cło ${wynik.duty_rate_pct}%). ${note.trim()}`.trim(),
      });
      setDone(true);
    } catch (error) {
      toast.error(`Nie udało się wysłać: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <Card className="flex items-start gap-3 p-6">
        <Check className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
        <div>
          <p className="font-medium">Zapisane.</p>
          <p className="text-sm text-muted-foreground">
            Odezwę się z pełną kalkulacją — z rozbiciem na pozycje i z tym, czego z aukcji nie da
            się ocenić.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card className="space-y-4 p-6">
      <div>
        <h2 className="font-medium">Chcę pełną kalkulację tego auta</h2>
        <p className="text-sm text-muted-foreground">
          Powyższa kwota to wyliczenie ze stawek. Pełna kalkulacja obejmuje transport z konkretnego
          stanu, stan auta z raportu aukcyjnego i to, czego z niego nie widać.
        </p>
      </div>
      <form onSubmit={onSubmit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="phone">Telefon</Label>
            <Input
              id="phone"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="600 100 200"
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="name">Imię (opcjonalnie)</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
        </div>
        <div className="space-y-1">
          <Label htmlFor="note">Czego szukasz (opcjonalnie)</Label>
          <Textarea
            id="note"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Budżet pod klucz, rocznik, na kiedy."
          />
        </div>
        {/* Pole-pułapka: ukryte przed człowiekiem, bot wypełnia wszystko, co znajdzie. */}
        <input
          type="text"
          name="website"
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          className="absolute left-[-9999px] h-0 w-0 opacity-0"
        />
        <Button type="submit" disabled={busy || !phone.trim()}>
          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          Poproś o kalkulację
        </Button>
      </form>
    </Card>
  );
}

function VinCheckPage() {
  const [vin, setVin] = useState("");
  const [bid, setBid] = useState("");
  const [state, setState] = useState("");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [wynik, setWynik] = useState<VinCheckResult | null>(null);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const numer = vin.trim().toUpperCase();
    if (numer.length < 8) {
      toast.error(
        "VIN jest za krótki — do ustalenia cła wystarczy początek, ale musi być poprawny.",
      );
      return;
    }
    setBusy(true);
    try {
      const stawka = Number.parseFloat(bid.replace(/[^\d.]/g, ""));
      setWynik(
        await sprawdzVin({
          vin: numer,
          bid_usd: Number.isFinite(stawka) && stawka > 0 ? stawka : undefined,
          state: state.trim().toUpperCase() || undefined,
          make: make.trim() || undefined,
          model: model.trim() || undefined,
        }),
      );
    } catch (error) {
      const msg = String(error);
      toast.error(
        msg.includes("422")
          ? "Nie rozpoznaję tego numeru VIN. Sprawdź, czy jest przepisany poprawnie."
          : `Nie udało się sprawdzić: ${msg}`,
      );
      setWynik(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-4 sm:p-8">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">
          Sprawdź, czy to auto z USA ma zerowe cło
        </h1>
        <p className="text-muted-foreground">
          Od 1 lipca 2026 auta zmontowane w Stanach wjeżdżają do Unii bez cła. Decyduje miejsce
          montażu, nie marka — BMW ze Spartanburga ma zerową stawkę, a Audi z Meksyku kupione na tej
          samej aukcji płaci pełne dziesięć procent. Rozstrzyga to pierwszy znak numeru VIN.
        </p>
        <p className="text-sm text-muted-foreground">
          Wklej VIN i zobacz wynik od razu. Bez podawania telefonu.
        </p>
      </header>

      <Card className="p-6">
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="vin">Numer VIN</Label>
            <Input
              id="vin"
              value={vin}
              onChange={(e) => setVin(e.target.value)}
              placeholder="5UX33EM0XV9489441"
              className="font-mono text-lg"
              autoFocus
            />
            <p className="text-xs text-muted-foreground">
              Copart ukrywa sześć ostatnich znaków — to nie przeszkadza, do cła wystarczy początek.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-4">
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="bid">Stawka na aukcji (USD)</Label>
              <Input
                id="bid"
                value={bid}
                onChange={(e) => setBid(e.target.value)}
                placeholder="35 000"
                inputMode="numeric"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="make">Marka</Label>
              <Input
                id="make"
                value={make}
                onChange={(e) => setMake(e.target.value)}
                placeholder="BMW"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="model">Model</Label>
              <Input
                id="model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="X5"
              />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-4">
            <div className="space-y-1">
              <Label htmlFor="state">Stan</Label>
              <Input
                id="state"
                value={state}
                onChange={(e) => setState(e.target.value)}
                placeholder="FL"
                maxLength={2}
              />
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            Markę i model warto podać: bez nich nie rozpoznam auta elektrycznego, a elektryki są z
            zerowego cła wyłączone.
          </p>

          <Button type="submit" disabled={busy} size="lg">
            {busy ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Search className="mr-2 h-4 w-4" />
            )}
            Sprawdź cło
          </Button>
        </form>
      </Card>

      {wynik ? (
        <>
          <ResultCard wynik={wynik} />
          <LeadForm wynik={wynik} />
        </>
      ) : null}

      <footer className="border-t pt-4 text-xs text-muted-foreground">
        Podstawa: rozporządzenie UE 2026/1455, preferencja obowiązuje do 31 grudnia 2029. Stawki
        akcyzy według ustawy o podatku akcyzowym wraz z interpretacją ogólną Ministra Finansów z 26
        lutego 2026 w sprawie hybryd. Kurs z tabeli NBP.
      </footer>
    </main>
  );
}

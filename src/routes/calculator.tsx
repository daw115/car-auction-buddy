import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import { decodeVin, fetchRecalls, getFxRates, type VinDecoded, type RecallItem, type FxRates } from "@/server/external.functions";
import { calculateCost, US_STATES, type CostBreakdown, type FuelType } from "@/lib/cost-calculator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Loader2, Calculator, Search, ArrowLeft, AlertTriangle } from "lucide-react";

export const Route = createFileRoute("/calculator")({
  component: CalculatorPage,
});

function CalculatorPage() {
  const fnDecodeVin = useServerFn(decodeVin);
  const fnFetchRecalls = useServerFn(fetchRecalls);
  const fnGetFx = useServerFn(getFxRates);

  const [vin, setVin] = useState("");
  const [vinResult, setVinResult] = useState<VinDecoded | null>(null);
  const [recalls, setRecalls] = useState<RecallItem[]>([]);
  const [fx, setFx] = useState<FxRates | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // kalkulator state
  const [carPrice, setCarPrice] = useState<number>(15000);
  const [repair, setRepair] = useState<number>(2500);
  const [state, setState] = useState<string>("NJ");
  const [engineCc, setEngineCc] = useState<number>(2000);
  const [fuel, setFuel] = useState<FuelType>("gasoline");
  const [margin, setMargin] = useState<number>(8);
  const [buffer, setBuffer] = useState<number>(3);

  useEffect(() => {
    void fnGetFx().then(setFx).catch(() => undefined);
  }, [fnGetFx]);

  const breakdown: CostBreakdown | null = useMemo(() => {
    if (!fx) return null;
    return calculateCost(
      {
        car_price_usd: carPrice,
        estimated_repair_usd: repair,
        state,
        engine_cc: engineCc,
        fuel,
        broker_margin_pct: margin,
        exchange_rate_buffer_pct: buffer,
      },
      { usd_pln: fx.usd_pln, usd_eur: fx.usd_eur },
    );
  }, [fx, carPrice, repair, state, engineCc, fuel, margin, buffer]);

  async function runVin() {
    if (vin.trim().length < 11) {
      toast.error("VIN musi mieć przynajmniej 11 znaków");
      return;
    }
    setBusy("vin");
    setRecalls([]);
    try {
      const r = (await fnDecodeVin({ data: { vin: vin.trim() } })) as VinDecoded;
      setVinResult(r);
      if (r.engine_cc) setEngineCc(r.engine_cc);
      if (r.fuel_type) {
        const f = r.fuel_type.toLowerCase();
        if (f.includes("electric")) setFuel("electric");
        else if (f.includes("diesel")) setFuel("diesel");
        else if (f.includes("hybrid")) setFuel("hybrid");
        else if (f.includes("lpg") || f.includes("propane")) setFuel("lpg");
        else setFuel("gasoline");
      }
      toast.success(`Zdekodowano: ${r.year ?? ""} ${r.make ?? ""} ${r.model ?? ""}`);
      // pobierz recall'e
      if (r.make && r.model && r.year) {
        try {
          const rec = (await fnFetchRecalls({ data: { make: r.make, model: r.model, year: r.year } })) as RecallItem[];
          setRecalls(rec);
        } catch {
          // ignoruj
        }
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <Link to="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
              <ArrowLeft className="h-4 w-4" /> Panel
            </Link>
            <Separator orientation="vertical" className="h-5" />
            <div className="flex items-center gap-2">
              <Calculator className="h-4 w-4 text-primary" />
              <h1 className="text-base font-semibold">Kalkulator importu + VIN decoder</h1>
            </div>
          </div>
          {fx && (
            <div className="text-xs text-muted-foreground">
              Kurs: 1 USD = {fx.usd_pln.toFixed(3)} PLN · {fx.usd_eur.toFixed(3)} EUR
              <span className="ml-2 opacity-60">({fx.fetched_at}, {fx.source})</span>
            </div>
          )}
        </div>
      </header>

      <main className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
        {/* VIN decoder */}
        <Card className="p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Search className="h-4 w-4" /> VIN decoder (NHTSA, darmowe)
          </h2>
          <div className="flex gap-2">
            <Input
              placeholder="np. 1HGCM82633A004352"
              value={vin}
              onChange={(e) => setVin(e.target.value.toUpperCase())}
              maxLength={17}
              className="font-mono"
            />
            <Button onClick={runVin} disabled={busy === "vin"}>
              {busy === "vin" ? <Loader2 className="h-4 w-4 animate-spin" /> : "Dekoduj"}
            </Button>
          </div>

          {vinResult && (
            <div className="mt-4 space-y-2 text-sm">
              <div className="grid grid-cols-2 gap-2">
                <Field label="Marka" value={vinResult.make} />
                <Field label="Model" value={vinResult.model} />
                <Field label="Rok" value={vinResult.year} />
                <Field label="Wersja" value={vinResult.trim} />
                <Field label="Nadwozie" value={vinResult.body_class} />
                <Field label="Paliwo" value={vinResult.fuel_type} />
                <Field label="Napęd" value={vinResult.drive_type} />
                <Field label="Skrzynia" value={vinResult.transmission} />
                <Field label="Pojemność (cc)" value={vinResult.engine_cc} />
                <Field label="Cylindry" value={vinResult.engine_cylinders} />
                <Field label="Moc (HP)" value={vinResult.engine_power_hp} />
                <Field label="Kraj produkcji" value={vinResult.plant_country} />
              </div>
              {vinResult.errors.length > 0 && (
                <div className="rounded-md border border-yellow-200 bg-yellow-50 p-2 text-xs text-yellow-900">
                  <div className="flex items-center gap-1 font-medium">
                    <AlertTriangle className="h-3 w-3" /> Uwagi NHTSA:
                  </div>
                  <ul className="ml-4 list-disc">
                    {vinResult.errors.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              )}
              {recalls.length > 0 && (
                <div className="mt-3">
                  <div className="mb-1 text-sm font-semibold">Recalle ({recalls.length}):</div>
                  <div className="max-h-64 space-y-2 overflow-auto pr-2">
                    {recalls.map((r) => (
                      <div key={r.campaign_number} className="rounded-md border border-border bg-muted/40 p-2 text-xs">
                        <div className="flex items-center justify-between">
                          <Badge variant="outline" className="font-mono">{r.campaign_number}</Badge>
                          <span className="text-muted-foreground">{r.report_received_date}</span>
                        </div>
                        <div className="mt-1 font-medium">{r.component}</div>
                        <div className="mt-1 text-muted-foreground">{r.summary}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>

        {/* Kalkulator */}
        <Card className="p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Calculator className="h-4 w-4" /> Kalkulator total cost (USD → PLN/EUR)
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Cena auta (USD)</Label>
              <Input type="number" value={carPrice} onChange={(e) => setCarPrice(Number(e.target.value) || 0)} />
            </div>
            <div>
              <Label className="text-xs">Naprawa (USD)</Label>
              <Input type="number" value={repair} onChange={(e) => setRepair(Number(e.target.value) || 0)} />
            </div>
            <div>
              <Label className="text-xs">Stan USA</Label>
              <select
                value={state}
                onChange={(e) => setState(e.target.value)}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
              >
                {US_STATES.map((s) => (
                  <option key={s.code} value={s.code}>{s.code} ({s.region})</option>
                ))}
              </select>
            </div>
            <div>
              <Label className="text-xs">Pojemność (cc)</Label>
              <Input type="number" value={engineCc} onChange={(e) => setEngineCc(Number(e.target.value) || 0)} />
            </div>
            <div>
              <Label className="text-xs">Paliwo</Label>
              <select
                value={fuel}
                onChange={(e) => setFuel(e.target.value as FuelType)}
                className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
              >
                <option value="gasoline">Benzyna</option>
                <option value="diesel">Diesel</option>
                <option value="hybrid">Hybryda</option>
                <option value="electric">Elektryk</option>
                <option value="lpg">LPG</option>
                <option value="other">Inne</option>
              </select>
            </div>
            <div>
              <Label className="text-xs">Marża brokera %</Label>
              <Input type="number" value={margin} onChange={(e) => setMargin(Number(e.target.value) || 0)} />
            </div>
            <div className="col-span-2">
              <Label className="text-xs">Bufor kursowy %</Label>
              <Input type="number" value={buffer} onChange={(e) => setBuffer(Number(e.target.value) || 0)} />
            </div>
          </div>

          {breakdown && (
            <div className="mt-4 space-y-1 rounded-md border border-border bg-muted/40 p-3 text-sm">
              <Row label="Cena auta" value={`$${breakdown.car_price_usd.toLocaleString()}`} />
              <Row label="Naprawa" value={`$${breakdown.repair_usd.toLocaleString()}`} />
              <Row label={`Transport USA→PL (${breakdown.region})`} value={`$${breakdown.transport_usa_to_pl_usd.toLocaleString()}`} />
              <Row label="Opłaty portowe + dokumenty" value={`$${breakdown.port_fees_usd.toLocaleString()}`} />
              <Row label="Cło 10%" value={`$${breakdown.customs_duty_usd.toLocaleString()}`} />
              <Row label={`Akcyza ${breakdown.excise_rate_pct}%`} value={`$${breakdown.excise_tax_usd.toLocaleString()}`} />
              <Row label="VAT 23%" value={`$${breakdown.vat_usd.toLocaleString()}`} />
              <Row label="Homologacja + rejestracja" value={`$${breakdown.homologation_usd.toLocaleString()}`} />
              <Row label="Marża brokera" value={`$${breakdown.broker_margin_usd.toLocaleString()}`} />
              <Separator className="my-2" />
              <Row label="RAZEM" value={`$${breakdown.total_usd.toLocaleString()}`} bold />
              <Row label="RAZEM (PLN)" value={`${breakdown.total_pln.toLocaleString()} zł`} bold accent />
              <Row label="RAZEM (EUR)" value={`€${breakdown.total_eur.toLocaleString()}`} bold accent />
              <div className="mt-2 text-xs text-muted-foreground">
                Kurs zastosowany: 1 USD = {breakdown.fx_usd_pln} PLN · {breakdown.fx_usd_eur} EUR
              </div>
            </div>
          )}
        </Card>
      </main>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="rounded-md border border-border bg-muted/30 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-sm font-medium">{value ?? "—"}</div>
    </div>
  );
}

function Row({ label, value, bold, accent }: { label: string; value: string; bold?: boolean; accent?: boolean }) {
  return (
    <div className={`flex items-center justify-between ${bold ? "font-semibold" : ""} ${accent ? "text-primary" : ""}`}>
      <span>{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}

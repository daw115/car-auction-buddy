/** Cztery kroki sprawy klienta, na jego karcie.
 *
 *  Etap leada mówi „gdzie jesteśmy", ale nie „co pokazaliśmy". Po tygodniu
 *  milczenia broker musi wiedzieć, czy klient nie odpisuje na trzy auta czy na
 *  jedno i który raport dostał — z rozmowy na WhatsAppie tego nie widać, bo idą
 *  tam PDF-y, których treści wątek nie pokazuje.
 *
 *  Krok 1 i 3 zapisują się SAME, przy wysyłce oferty i raportu. Ręcznie zaznacza
 *  się tylko to, czego system nie może wiedzieć: co klient wybrał i czy kupuje.
 */

import { useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Loader2, X } from "lucide-react";

import { getStanSprawy, zapiszDecyzje, zapiszWybor } from "@/functions/sales.functions";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";

const KROKI = ["Oferta wstępna", "Wybrane auta", "Raport szczegółowy", "Decyzja"] as const;

export function SprawaPanel({ leadId }: { leadId: number }) {
  const fnStan = useServerFn(getStanSprawy);
  const fnWybor = useServerFn(zapiszWybor);
  const fnDecyzja = useServerFn(zapiszDecyzje);
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
            <Button
              size="sm"
              className="mt-2"
              disabled={wybor.isPending}
              onClick={() => wybor.mutate()}
            >
              {wybor.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              Klient wybrał te ({zaznaczone.size})
            </Button>
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

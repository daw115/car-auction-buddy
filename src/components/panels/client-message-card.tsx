import { Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import type { ClientCriteria } from "@/lib/types";

export type ParsedCarsResult = {
  criteria_list: ClientCriteria[];
  summary: string;
  warnings: string[];
};

type Props = {
  clientMessage: string;
  setClientMessage: (v: string) => void;
  parsing: boolean;
  lastParseResult: { summary: string; warnings: string[] } | null;
  parsedCars: ParsedCarsResult | null;
  onParse: () => void;
  onBatchSearch: () => void;
};

export function ClientMessageCard({
  clientMessage,
  setClientMessage,
  parsing,
  lastParseResult,
  parsedCars,
  onParse,
  onBatchSearch,
}: Props) {
  return (
    <Card className="p-4 mb-4 border-primary/30 bg-primary/5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-lg">📝</span>
        <h3 className="font-semibold">Wiadomość od klienta</h3>
        <span className="text-xs text-muted-foreground">
          AI wyciągnie filtry (make, model, rocznik, budżet, przebieg, etc.)
        </span>
      </div>
      <Textarea
        placeholder='np. "Szukam BMW M5 z 2018-2020, najlepiej East Coast, budżet 30k USD, do 60 tys mil"'
        value={clientMessage}
        onChange={(e) => setClientMessage(e.target.value)}
        rows={3}
        className="mb-3"
      />
      <div className="flex items-center gap-3">
        <Button onClick={onParse} disabled={parsing || !clientMessage.trim()}>
          {parsing ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <span className="mr-1">🤖</span>}
          {parsing ? "Parsuję..." : "Parsuj filtry"}
        </Button>
      </div>
      {lastParseResult && (
        <div className="mt-3 p-3 rounded-md bg-muted/50">
          <div className="text-sm mb-2 italic">{lastParseResult.summary}</div>
          {lastParseResult.warnings.length > 0 && (
            <div className="mt-2 p-2 bg-amber-500/10 border border-amber-500/40 rounded">
              <div className="text-xs font-semibold mb-1">⚠️ Normalizacja modeli:</div>
              {lastParseResult.warnings.map((w, i) => (
                <div key={i} className="text-xs text-amber-700 dark:text-amber-400">• {w}</div>
              ))}
              <div className="text-xs text-muted-foreground mt-1 italic">
                Backend automatycznie znormalizował model do nazwy używanej przez Copart/IAAI
                (np. M440i → 4 Series). Cache zapisuje mapping żeby kolejne te same modele
                nie wymagały re-parsingu.
              </div>
            </div>
          )}
          {parsedCars && parsedCars.criteria_list.length > 1 && (
            <div className="mt-3 space-y-2">
              <div className="text-xs text-muted-foreground">
                Wykryto <span className="font-bold text-foreground">{parsedCars.criteria_list.length}</span> aut:{" "}
                {parsedCars.criteria_list.map((c, i) => (
                  <Badge key={i} variant="outline" className="mr-1 text-[10px]">
                    {c.make} {c.model || ""} {c.year_from ? `${c.year_from}` : ""}{c.year_to ? `-${c.year_to}` : ""}
                  </Badge>
                ))}
              </div>
              <Button onClick={onBatchSearch} size="sm">
                <Search className="h-4 w-4 mr-1" />
                Wyszukaj wszystkie ({parsedCars.criteria_list.length})
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

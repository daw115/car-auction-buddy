import { useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Search, RefreshCcw, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import type { ClientCriteria } from "@/lib/types";

export type ParseError = {
  status: number;
  detail: string;
};

type Props = {
  clientMessage: string;
  setClientMessage: (v: string) => void;
  parsing: boolean;
  parsedList: ClientCriteria[];
  summary: string;
  warnings: string[];
  error: ParseError | null;
  selected: Record<number, boolean>;
  toggleSelected: (idx: number) => void;
  onParse: () => void;
  onSearchSelected: () => void;
  onClear: () => void;
  disabled?: boolean;
};

function shortLabel(c: ClientCriteria): string {
  const yr =
    c.year_from || c.year_to ? ` ${c.year_from ?? "?"}-${c.year_to ?? "?"}` : "";
  const bud = c.budget_usd ? ` · $${c.budget_usd.toLocaleString()}` : "";
  const mi = c.max_odometer_mi ? ` · ≤${c.max_odometer_mi.toLocaleString()} mi` : "";
  return `${c.make ?? "?"} ${c.model ?? ""}${yr}${bud}${mi}`.trim();
}

function errorMessageFor(err: ParseError): string {
  if (err.status === 400)
    return "Nie rozpoznałem żadnego auta. Spróbuj opisać markę/model wprost.";
  if (err.status === 422)
    return `Rozpoznane dane nie przeszły walidacji: ${err.detail || "brak szczegółów"}`;
  if (err.status === 503)
    return "LLM jest chwilowo niedostępny (rate limit / provider down). Spróbuj ponownie za chwilę.";
  return `Błąd parsera (HTTP ${err.status}): ${err.detail || ""}`;
}

export function ClientMessageCard({
  clientMessage,
  setClientMessage,
  parsing,
  parsedList,
  summary,
  warnings,
  error,
  selected,
  toggleSelected,
  onParse,
  onSearchSelected,
  onClear,
  disabled,
}: Props) {
  const [open, setOpen] = useState(true);
  const count = parsedList.length;
  const selectedCount = parsedList.filter((_, i) => selected[i]).length;

  return (
    <Card className="border-primary/30 bg-primary/5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        {open ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        <span className="text-lg">📝</span>
        <h3 className="font-semibold">Wklej wiadomość od klienta</h3>
        <span className="text-xs text-muted-foreground">
          zamiast wypełniać formularz ręcznie
        </span>
        {count > 0 && (
          <Badge variant="outline" className="ml-auto text-[10px]">
            {count} {count === 1 ? "auto rozpoznane" : "aut rozpoznanych"}
          </Badge>
        )}
      </button>

      {open && (
        <div className="border-t border-primary/20 p-4">
          <Textarea
            placeholder='np. "Szukam BMW M5 z 2018-2020, budżet 30k USD, do 60 tys mil. Klient rozważa też Audi S5."'
            value={clientMessage}
            onChange={(e) => setClientMessage(e.target.value)}
            rows={4}
            className="mb-3"
            disabled={parsing}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={onParse}
              disabled={parsing || !clientMessage.trim() || disabled}
            >
              {parsing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <span className="mr-1">🤖</span>
              )}
              {parsing ? "Parsuję..." : "Parsuj filtry"}
            </Button>
            {(count > 0 || error) && (
              <Button variant="ghost" size="sm" onClick={onClear} disabled={parsing}>
                Wyczyść
              </Button>
            )}
            {error?.status === 503 && (
              <Button variant="outline" size="sm" onClick={onParse} disabled={parsing}>
                <RefreshCcw className="mr-1 h-3 w-3" /> Spróbuj ponownie
              </Button>
            )}
          </div>

          {error && (
            <div className="mt-3 flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              <div>{errorMessageFor(error)}</div>
            </div>
          )}

          {summary && count > 0 && (
            <div className="mt-3 rounded-md bg-muted/50 p-3">
              <div className="text-sm italic">{summary}</div>

              {count === 1 && (
                <div className="mt-2 text-xs text-muted-foreground">
                  Wypełniono formularz wyszukiwania poniżej — sprawdź/popraw i kliknij „🔎 Wyszukaj".
                </div>
              )}

              {count > 1 && (
                <div className="mt-3 space-y-2">
                  <div className="text-xs text-muted-foreground">
                    Zaznacz auta do wyszukania (batch, sekwencyjnie):
                  </div>
                  <ul className="space-y-1">
                    {parsedList.map((c, i) => (
                      <li
                        key={i}
                        className="flex items-center gap-2 rounded border bg-background/50 p-2 text-sm"
                      >
                        <Checkbox
                          checked={!!selected[i]}
                          onCheckedChange={() => toggleSelected(i)}
                        />
                        <span className="flex-1">{shortLabel(c)}</span>
                        <Badge variant="outline" className="text-[10px]">
                          #{i + 1}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                  <Button
                    onClick={onSearchSelected}
                    disabled={selectedCount === 0 || disabled}
                    size="sm"
                  >
                    <Search className="mr-1 h-4 w-4" />
                    Szukaj zaznaczone ({selectedCount})
                  </Button>
                </div>
              )}

              {warnings.length > 0 && (
                <div className="mt-3 rounded border border-amber-500/40 bg-amber-500/10 p-2">
                  <div className="mb-1 text-xs font-semibold">⚠️ Normalizacja / uwagi:</div>
                  {warnings.map((w, i) => (
                    <div key={i} className="text-xs text-amber-700 dark:text-amber-400">
                      • {w}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

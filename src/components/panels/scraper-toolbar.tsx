import { Loader2, Search, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

type Props = {
  listingsCount: number;
  disableAuctionFilter: boolean;
  setDisableAuctionFilter: (v: boolean) => void;
  busy: string | null;
  hasScraperUrl: boolean;
  hasListingsRaw: boolean;
  onParseFromText: () => void;
  onScrape: () => void;
  onClearCache: () => void;
};

export function ScraperToolbar({
  listingsCount,
  disableAuctionFilter,
  setDisableAuctionFilter,
  busy,
  hasScraperUrl,
  hasListingsRaw,
  onParseFromText,
  onScrape,
  onClearCache,
}: Props) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Loty z aukcji ({listingsCount})
      </h3>
      <div className="flex items-center gap-3">
        <label
          className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none"
          title="Domyślnie pokazujemy aukcje kończące się w ciągu 12–120h. Włącz, aby znaleźć też aukcje dalej w przyszłości oraz loty bez ustalonej daty aukcji."
        >
          <Checkbox
            checked={disableAuctionFilter}
            onCheckedChange={(v) => setDisableAuctionFilter(v === true)}
          />
          Pokaż też aukcje przyszłe (poza oknem 12–120h)
        </label>

        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={onParseFromText} disabled={!hasListingsRaw}>
            Wczytaj z JSON
          </Button>
          <Button
            size="sm"
            onClick={onScrape}
            disabled={busy === "scraper" || !hasScraperUrl}
            title={!hasScraperUrl ? "Ustaw SCRAPER_BASE_URL w sekretach" : ""}
          >
            {busy === "scraper" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            Wyszukaj online
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={onClearCache}
            title="Wyczyść cache wyników (wymusi nowy scrape)"
          >
            <Trash2 className="h-4 w-4" />
            Wyczyść cache
          </Button>
        </div>
      </div>
    </div>
  );
}

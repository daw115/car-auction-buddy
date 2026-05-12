import type { CarLot } from "@/lib/types";

type Props = {
  lot: Pick<CarLot, "raw_data">;
  compact?: boolean;
};

export function BidfaxBadge({ lot, compact = false }: Props) {
  const raw = lot?.raw_data;
  const soldPrice = raw?.bidfax_sold_price;
  if (!soldPrice) return null;

  const historyUrl = raw?.bidfax_history_url as string | undefined;
  const soldVin = raw?.bidfax_sold_vin as string | undefined;

  if (compact) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:text-amber-400"
        title={`Historycznie sprzedany za ${soldPrice}${soldVin ? ` (VIN: ${soldVin})` : ""}`}
      >
        📊 Hist. {String(soldPrice)}
        {historyUrl && (
          <a
            href={historyUrl as string}
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-amber-900 dark:hover:text-amber-200"
            onClick={(e) => e.stopPropagation()}
          >
            ↗
          </a>
        )}
      </span>
    );
  }

  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 mt-2">
      <div className="flex items-center gap-2 text-amber-900 dark:text-amber-300">
        <span className="text-xl">📊</span>
        <div className="flex-1">
          <div className="text-[10px] uppercase tracking-wide opacity-70">
            Historycznie sprzedany za
          </div>
          <div
            className="text-lg font-bold"
            title="Cena za jaką ten sam VIN lub bardzo podobny lot sprzedał się historycznie na bidfax.info. Użyj jako benchmark — porównaj z (current_bid + szacunek naprawy + transport)."
          >
            {String(soldPrice)}
          </div>
        </div>
        {historyUrl && (
          <a
            href={historyUrl as string}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs underline text-amber-800 dark:text-amber-300 hover:text-amber-950 dark:hover:text-amber-100"
          >
            Zobacz historię →
          </a>
        )}
      </div>
      {soldVin && (
        <div className="text-[10px] text-amber-700 dark:text-amber-400 mt-1 font-mono">
          VIN matchowany: {String(soldVin)}
        </div>
      )}
    </div>
  );
}

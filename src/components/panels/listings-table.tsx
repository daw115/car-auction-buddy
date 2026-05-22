import type { CarLot } from "@/lib/types";

export function ListingsTable({
  listings,
  selectedIds,
  onToggle,
  onToggleAll,
}: {
  listings: CarLot[];
  selectedIds?: Set<string>;
  onToggle?: (lotId: string) => void;
  onToggleAll?: () => void;
}) {
  const selectionMode = !!selectedIds && !!onToggle;
  const allSelected = selectionMode && listings.length > 0 && listings.every((l) => selectedIds!.has(l.lot_id));
  return (
    <div className="mt-3 max-h-[260px] overflow-auto rounded border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted">
          <tr className="text-left">
            {selectionMode && (
              <th className="w-8 px-2 py-1.5">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={() => onToggleAll?.()}
                  title={allSelected ? "Odznacz wszystkie" : "Zaznacz wszystkie"}
                />
              </th>
            )}
            <th className="px-2 py-1.5">Pojazd</th>
            <th className="px-2 py-1.5">Lot</th>
            <th className="px-2 py-1.5">Stan</th>
            <th className="px-2 py-1.5">Bid</th>
            <th className="px-2 py-1.5">Uszkodzenie</th>
            <th className="px-2 py-1.5">Tytuł</th>
            <th className="px-2 py-1.5">Sprzedawca</th>
          </tr>
        </thead>
        <tbody>
          {listings.map((l) => {
            const checked = selectionMode && selectedIds!.has(l.lot_id);
            return (
              <tr
                key={`${l.source}-${l.lot_id}`}
                className={`border-t ${checked ? "bg-primary/5" : ""}`}
              >
                {selectionMode && (
                  <td className="px-2 py-1">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggle!(l.lot_id)}
                    />
                  </td>
                )}
                <td className="px-2 py-1">
                  {l.year ?? "?"} {l.make ?? ""} {l.model ?? ""}
                </td>
                <td className="px-2 py-1 text-muted-foreground">
                  {l.source}/{l.lot_id}
                </td>
                <td className="px-2 py-1">{l.location_state ?? "—"}</td>
                <td className="px-2 py-1">${l.current_bid_usd ?? "—"}</td>
                <td className="px-2 py-1">{l.damage_primary ?? "—"}</td>
                <td className="px-2 py-1">{l.title_type ?? "—"}</td>
                <td className="px-2 py-1">{l.seller_type ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

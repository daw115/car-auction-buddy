import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Field } from "@/components/panels/form-helpers";
import type { ClientCriteria } from "@/lib/types";
import {
  AUCTION_SOURCES,
  DEFAULT_AUCTION_SOURCES,
  isAuctionSourceCapabilityAvailable,
  type AuctionSourceCapabilities,
} from "@/lib/auction-sources";

type Props = {
  criteria: ClientCriteria;
  setCriteria: (c: ClientCriteria) => void;
  capabilities?: AuctionSourceCapabilities | null;
  capabilitiesLoading?: boolean;
};

const SOURCE_UNAVAILABLE_MESSAGES: Record<string, string> = {
  backend_unconfigured: "backend nieskonfigurowany",
  backend_authorization_failed: "backend odrzucił autoryzację",
  capabilities_unreachable: "nie można potwierdzić capabilities backendu",
  invalid_capabilities_response: "backend zwrócił nieprawidłowe capabilities",
  credentials_or_adapter_missing: "brak adaptera lub poświadczeń API",
};

export function CriteriaForm({
  criteria,
  setCriteria,
  capabilities,
  capabilitiesLoading = false,
}: Props) {
  const selectedSources = criteria.sources ?? DEFAULT_AUCTION_SOURCES;

  function toggleSource(source: (typeof AUCTION_SOURCES)[number]["id"], checked: boolean) {
    const next = new Set(selectedSources);
    if (checked) next.add(source);
    else next.delete(source);
    setCriteria({ ...criteria, sources: Array.from(next) });
  }

  return (
    <>
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Kryteria
      </h3>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Marka *">
          <Input
            value={criteria.make}
            onChange={(e) => setCriteria({ ...criteria, make: e.target.value })}
            placeholder="Audi"
          />
        </Field>
        <Field label="Model">
          <Input
            value={criteria.model ?? ""}
            onChange={(e) => setCriteria({ ...criteria, model: e.target.value })}
            placeholder="A5"
          />
        </Field>
        <Field label="Rocznik od">
          <Input
            type="number"
            value={criteria.year_from ?? ""}
            onChange={(e) =>
              setCriteria({ ...criteria, year_from: e.target.value ? +e.target.value : null })
            }
          />
        </Field>
        <Field label="Rocznik do">
          <Input
            type="number"
            value={criteria.year_to ?? ""}
            onChange={(e) =>
              setCriteria({ ...criteria, year_to: e.target.value ? +e.target.value : null })
            }
          />
        </Field>
        <Field label="Budżet USD">
          <Input
            type="number"
            placeholder="(opcjonalne)"
            value={criteria.budget_usd ?? ""}
            onChange={(e) =>
              setCriteria({ ...criteria, budget_usd: e.target.value ? +e.target.value : null })
            }
          />
        </Field>
        <Field label="Max przebieg (mil)">
          <Input
            type="number"
            placeholder="(opcjonalne)"
            value={criteria.max_odometer_mi ?? ""}
            onChange={(e) =>
              setCriteria({
                ...criteria,
                max_odometer_mi: e.target.value ? +e.target.value : null,
              })
            }
          />
        </Field>
        <Field label="Rodzaj paliwa (opcjonalnie)">
          <Select
            value={criteria.fuel_type ?? "any"}
            onValueChange={(v) =>
              setCriteria({
                ...criteria,
                fuel_type: v === "any" ? null : (v as "Gas" | "Hybrid" | "Diesel" | "Electric"),
              })
            }
          >
            <SelectTrigger>
              <SelectValue placeholder="(dowolny)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">(dowolny)</SelectItem>
              <SelectItem value="Gas">Gas</SelectItem>
              <SelectItem value="Hybrid">Hybrid</SelectItem>
              <SelectItem value="Diesel">Diesel</SelectItem>
              <SelectItem value="Electric">Electric</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label="Max wyników (maks. 15)">
          <Input
            type="number"
            min={1}
            max={15}
            placeholder="Maks. 15"
            value={criteria.max_results ?? 15}
            onChange={(e) => {
              const raw = +e.target.value;
              if (!raw) return setCriteria({ ...criteria, max_results: 15 });
              const clamped = Math.min(Math.max(raw, 1), 15);
              setCriteria({ ...criteria, max_results: clamped });
            }}
          />
        </Field>
        <Field label="Wykluczone uszkodzenia">
          <Input
            value={(criteria.excluded_damage_types ?? []).join(", ")}
            onChange={(e) =>
              setCriteria({
                ...criteria,
                excluded_damage_types: e.target.value
                  .split(",")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
            placeholder="Flood, Fire"
          />
        </Field>
      </div>
      <div className="mt-4 space-y-2">
        <div className="text-xs font-medium text-muted-foreground">Źródła aukcji *</div>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {AUCTION_SOURCES.map((source) => {
            const selected = selectedSources.includes(source.id);
            const capability = capabilities?.sources[source.id];
            const available = capability
              ? isAuctionSourceCapabilityAvailable(source.id, capability)
              : source.id !== "manheim";
            const reason = capabilitiesLoading
              ? "sprawdzanie dostępności"
              : capability?.reason
                ? (SOURCE_UNAVAILABLE_MESSAGES[capability.reason] ?? capability.reason)
                : "brak potwierdzenia backendu";
            const showStatus = source.id === "manheim" || !available;
            return (
              <label
                key={source.id}
                className={`flex items-center gap-2 text-sm ${available || selected ? "cursor-pointer" : "cursor-not-allowed opacity-60"}`}
              >
                <Checkbox
                  checked={selected}
                  disabled={!available && !selected}
                  onCheckedChange={(value) => toggleSource(source.id, value === true)}
                  aria-label={`Uwzględnij ${source.label}`}
                  aria-describedby={showStatus ? `source-${source.id}-status` : undefined}
                />
                <span title={source.description}>{source.label}</span>
                {showStatus && (
                  <span
                    id={`source-${source.id}-status`}
                    className={`rounded px-1.5 py-0.5 text-[10px] ${
                      available
                        ? "bg-emerald-500/10 text-emerald-600"
                        : "bg-amber-500/10 text-amber-600"
                    }`}
                  >
                    {capabilitiesLoading
                      ? "sprawdzam…"
                      : available
                        ? "API aktywne"
                        : `niedostępne: ${reason}`}
                  </span>
                )}
              </label>
            );
          })}
        </div>
        {selectedSources.length === 0 && (
          <p className="text-xs text-destructive" role="alert">
            Wybierz co najmniej jedno źródło aukcji.
          </p>
        )}
        <p className="text-[11px] text-muted-foreground">
          Manheim jest dostępny tylko po potwierdzeniu oficjalnego adaptera Marketplace API przez
          backend. Aplikacja nie używa mocków ani nie omija logowania Manheim.
        </p>
      </div>
    </>
  );
}

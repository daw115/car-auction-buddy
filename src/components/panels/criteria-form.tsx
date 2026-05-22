import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Field } from "@/components/panels/form-helpers";
import type { ClientCriteria } from "@/lib/types";

type Props = {
  criteria: ClientCriteria;
  setCriteria: (c: ClientCriteria) => void;
};

export function CriteriaForm({ criteria, setCriteria }: Props) {
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
                fuel_type:
                  v === "any" ? null : (v as "Gas" | "Hybrid" | "Diesel" | "Electric"),
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
    </>
  );
}

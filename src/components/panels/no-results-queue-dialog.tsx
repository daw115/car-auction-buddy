import { useState } from "react";
import { Loader2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type NoResultsQueueDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultLabel?: string;
  busy?: boolean;
  onConfirm: (params: { interval_hours: number; label: string }) => void | Promise<void>;
};

const PRESETS = [
  { value: "6", label: "Co 6 godzin" },
  { value: "12", label: "Co 12 godzin" },
  { value: "24", label: "Co 24 godziny" },
  { value: "48", label: "Co 48 godzin" },
  { value: "custom", label: "Inne…" },
];

export function NoResultsQueueDialog({
  open,
  onOpenChange,
  defaultLabel = "",
  busy = false,
  onConfirm,
}: NoResultsQueueDialogProps) {
  const [preset, setPreset] = useState("12");
  const [custom, setCustom] = useState("12");
  const [label, setLabel] = useState(defaultLabel);

  const intervalHours = preset === "custom" ? Math.max(1, Math.min(168, Number(custom) || 12)) : Number(preset);
  const valid = intervalHours >= 1 && intervalHours <= 168;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Nie znaleziono aukcji</AlertDialogTitle>
          <AlertDialogDescription>
            Dodać to wyszukiwanie do kolejki ponownego sprawdzania? Worker będzie cyklicznie
            odpytywał scraper i powiadomi na Telegramie, gdy znajdzie pasujące loty.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label>Co ile godzin sprawdzać?</Label>
            <Select value={preset} onValueChange={setPreset}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRESETS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {preset === "custom" && (
              <Input
                type="number"
                min={1}
                max={168}
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                placeholder="1–168 godzin"
              />
            )}
          </div>

          <div className="space-y-2">
            <Label>Opis (opcjonalny)</Label>
            <Input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="np. Toyota Camry < 15k USD"
              maxLength={200}
            />
          </div>
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Anuluj</AlertDialogCancel>
          <AlertDialogAction
            disabled={!valid || busy}
            onClick={(e) => {
              e.preventDefault();
              if (!valid) return;
              void onConfirm({ interval_hours: intervalHours, label: label.trim() });
            }}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Dodaj do kolejki
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

import { Loader2, Save } from "lucide-react";
import { Button } from "@/components/ui/button";

type Props = {
  activeClient: { name: string } | null | undefined;
  activeRecordId: string | null;
  busy: string | null;
  onNewSession: () => void;
  onSave: () => void;
};

export function SessionHeader({
  activeClient,
  activeRecordId,
  busy,
  onNewSession,
  onSave,
}: Props) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <div>
        <h2 className="text-base font-semibold">
          {activeClient ? `Sesja: ${activeClient.name}` : "Nowa sesja"}
        </h2>
        <p className="text-xs text-muted-foreground">
          {activeRecordId ? `Rekord ${activeRecordId.slice(0, 8)}…` : "(nie zapisano)"}
        </p>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={onNewSession}>
          Nowa sesja
        </Button>
        <Button size="sm" onClick={onSave} disabled={busy === "save" || !activeClient}>
          {busy === "save" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Zapisz rekord
        </Button>
      </div>
    </div>
  );
}

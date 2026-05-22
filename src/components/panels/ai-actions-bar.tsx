import { AlertCircle, Brain, FileText, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

type Props = {
  busy: string | null;
  listingsCount: number;
  hasAnalysis: boolean;
  hasAnthropicKey: boolean;
  onRunAi: () => void;
  onMakeReport: () => void;
  onMakeLotReports: () => void;
};

export function AiActionsBar({
  busy,
  listingsCount,
  hasAnalysis,
  hasAnthropicKey,
  onRunAi,
  onMakeReport,
  onMakeLotReports,
}: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button onClick={onRunAi} disabled={busy === "ai" || listingsCount === 0}>
        {busy === "ai" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Brain className="h-4 w-4" />
        )}
        {hasAnalysis ? "Uruchom analizę AI ponownie" : "Uruchom analizę AI"}
      </Button>
      {hasAnalysis && (
        <Button
          variant="outline"
          onClick={onRunAi}
          disabled={busy === "ai" || listingsCount === 0}
          title="Ponowna analiza AI tych samych lotów (bez scrapingu)"
        >
          {busy === "ai" ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          Ponów analizę ({listingsCount} lotów)
        </Button>
      )}
      <Button variant="outline" onClick={onMakeReport} disabled={busy === "report" || !hasAnalysis}>
        {busy === "report" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <FileText className="h-4 w-4" />
        )}
        Wygeneruj raport (prosty)
      </Button>
      <Button
        onClick={onMakeLotReports}
        disabled={busy === "lot" || listingsCount === 0}
        className="bg-primary"
      >
        {busy === "lot" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <FileText className="h-4 w-4" />
        )}
        Generuj raporty LOT (broker + klient TOP3+2)
      </Button>
      {!hasAnthropicKey && (
        <span className="inline-flex items-center gap-1 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5" />
          Brak ANTHROPIC_API_KEY
        </span>
      )}
    </div>
  );
}

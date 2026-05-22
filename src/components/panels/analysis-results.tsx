import { Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { AnalyzedLot, AIAnalysis } from "@/lib/types";

function recommendationBadge(r: string) {
  if (r === "TAK") return "bg-[oklch(0.92_0.10_145)] text-[oklch(0.35_0.15_145)]";
  if (r === "MOŻE") return "bg-[oklch(0.92_0.10_85)] text-[oklch(0.35_0.15_85)]";
  return "bg-[oklch(0.92_0.10_25)] text-[oklch(0.35_0.15_25)]";
}

function auctionBadge(dateStr?: string | null) {
  if (!dateStr) return null;
  const diff = Math.ceil((new Date(dateStr).getTime() - Date.now()) / 86400000);
  if (diff <= 0) return null;
  const label = diff === 1 ? "⏰ jutro" : diff <= 3 ? `⏰ za ${diff} dni` : null;
  if (!label) return null;
  return <Badge variant="outline" className="text-[10px] ml-1">{label}</Badge>;
}

function LotCard({ a, onWatch }: { a: AnalyzedLot; onWatch: (a: AnalyzedLot) => void }) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 flex items-start justify-between">
        <div>
          <div className="font-semibold">
            {a.lot.year} {a.lot.make} {a.lot.model}
          </div>
          <div className="text-xs text-muted-foreground">
            {a.lot.source?.toUpperCase()} · Lot {a.lot.lot_id} ·{" "}
            {a.lot.location_state ?? "—"}
            {a.lot.auction_date && (
              <span className="ml-1">
                · Aukcja: {new Date(a.lot.auction_date).toLocaleDateString("pl-PL")}
              </span>
            )}
            {auctionBadge(a.lot.auction_date)}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold">{a.analysis.score.toFixed(1)}</span>
          <span
            className={`rounded px-2 py-0.5 text-xs font-semibold ${recommendationBadge(
              a.analysis.recommendation,
            )}`}
          >
            {a.analysis.recommendation}
          </span>
        </div>
      </div>
      <p className="text-sm">{a.analysis.client_description_pl}</p>
      {a.analysis.red_flags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {a.analysis.red_flags.map((f, i) => (
            <Badge key={i} variant="outline" className="text-xs">
              ⚠ {f}
            </Badge>
          ))}
        </div>
      )}
      <div className="mt-2 flex items-center justify-between">
        <div className="flex gap-2">
          {a.auto_reports?.client_hybrid_url && (
            <Button size="sm" variant="outline" asChild>
              <a href={a.auto_reports.client_hybrid_url} target="_blank" rel="noopener">
                📄 Klient
              </a>
            </Button>
          )}
          {a.auto_reports?.broker_hybrid_url && (
            <Button size="sm" variant="outline" asChild>
              <a href={a.auto_reports.broker_hybrid_url} target="_blank" rel="noopener">
                📋 Broker
              </a>
            </Button>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={() => onWatch(a)}
        >
          <Eye className="h-3 w-3 mr-1" /> Obserwuj
        </Button>
      </div>
    </div>
  );
}

type AiMeta = {
  provider: string;
  model: string;
  usedFallback?: boolean;
  usage: { input_tokens: number; output_tokens: number };
} | null;

type Props = {
  analysis: AnalyzedLot[];
  aiMeta: AiMeta;
  onWatch: (a: AnalyzedLot) => void;
};

export function AnalysisResults({ analysis, aiMeta, onWatch }: Props) {
  if (!analysis || analysis.length === 0) return null;

  const showcase = analysis.filter((a) => a.is_top_recommendation);
  const rest = analysis.filter((a) => !a.is_top_recommendation);
  const showcaseCount = showcase.length;

  return (
    <>
      {showcaseCount > 0 && (
        <Card className="p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              🎯 Showcase — auto-raporty ({showcaseCount})
            </h3>
            <Badge>🤖 Auto-raporty: {showcaseCount} wygenerowanych</Badge>
          </div>
          <div className="space-y-3">
            {showcase
              .sort((a, b) => {
                const da = a.lot.auction_date ? new Date(a.lot.auction_date).getTime() : Infinity;
                const db = b.lot.auction_date ? new Date(b.lot.auction_date).getTime() : Infinity;
                return da - db;
              })
              .map((a) => (
                <LotCard key={a.lot.lot_id} a={a} onWatch={onWatch} />
              ))}
          </div>
        </Card>
      )}

      {rest.length > 0 && (
        <Card className="p-4">
          <details>
            <summary className="cursor-pointer text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              📋 Pełna lista ({rest.length} pozostałych)
            </summary>
            <div className="mt-3 space-y-3">
              {rest.map((a) => (
                <LotCard key={a.lot.lot_id} a={a} onWatch={onWatch} />
              ))}
            </div>
          </details>
        </Card>
      )}

      {showcaseCount === 0 && (
        <Card className="p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Wyniki analizy AI ({analysis.length})
            </h3>
            {aiMeta && (
              <div className="flex items-center gap-2 text-xs">
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${
                    aiMeta.provider === "gemini"
                      ? "bg-blue-500/15 text-blue-700 dark:text-blue-400"
                      : "bg-amber-500/15 text-amber-700 dark:text-amber-400"
                  }`}
                >
                  {aiMeta.provider === "gemini" ? "Gemini" : "Anthropic"}
                  {aiMeta.usedFallback && " (fallback)"}
                </span>
                <span className="text-muted-foreground" title={`Model: ${aiMeta.model}`}>
                  {aiMeta.model}
                </span>
                <span className="text-muted-foreground">
                  {aiMeta.usage.input_tokens + aiMeta.usage.output_tokens} tok
                </span>
              </div>
            )}
          </div>
          <div className="space-y-3">
            {analysis.map((a) => (
              <LotCard key={a.lot.lot_id} a={a} onWatch={onWatch} />
            ))}
          </div>
        </Card>
      )}
    </>
  );
}

export type { AIAnalysis };

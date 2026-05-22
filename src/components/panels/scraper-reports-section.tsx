import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FileText, ExternalLink, Download, Loader2 } from "lucide-react";
import type { CarLot, ClientCriteria } from "@/lib/types";
import type { ScraperReportUrls } from "@/components/panels/batch-job-card";

export function ScraperReportsSection({
  reportUrls,
  listings,
  criteria,
}: {
  reportUrls: ScraperReportUrls;
  listings: CarLot[];
  criteria: ClientCriteria;
}) {
  const [loadingEndpoint, setLoadingEndpoint] = useState<string | null>(null);

  const hasAny =
    reportUrls.client_report_url ||
    reportUrls.polecane_index_url ||
    (reportUrls.client_reports_html?.length ?? 0) > 0 ||
    (reportUrls.broker_reports_html?.length ?? 0) > 0 ||
    reportUrls.artifact_urls?.analysis_json ||
    reportUrls.artifact_urls?.broker_bundle ||
    reportUrls.artifact_urls?.client_bundle ||
    reportUrls.artifact_urls?.client_short_bundle ||
    reportUrls.report_endpoints?.client_html ||
    reportUrls.report_endpoints?.broker_html;

  if (!hasAny) return null;

  async function openHtmlReport(endpoint: string, label: string) {
    setLoadingEndpoint(label);
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ criteria, listings }),
      });
      if (!res.ok) {
        const errText = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}: ${errText.slice(0, 200)}`);
      }
      const html = await res.text();
      const blob = new Blob([html], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(`Błąd generowania raportu: ${(e as Error).message}`);
    } finally {
      setLoadingEndpoint(null);
    }
  }

  return (
    <Card className="mt-4 p-4">
      <div className="flex items-center gap-2 mb-3">
        <FileText className="h-4 w-4 text-primary" />
        <span className="font-semibold text-sm">Raporty z analizy AI (Python)</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {reportUrls.polecane_index_url && (
          <Button variant="default" size="sm"
            onClick={() => window.open(reportUrls.polecane_index_url, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            🎯 Polecane oferty (klient + broker)
          </Button>
        )}
        {(reportUrls.client_reports_html?.length ?? 0) > 0 && reportUrls.client_reports_html!.map((url, i) => (
          <Button key={`client-${i}`} variant="outline" size="sm"
            onClick={() => window.open(url, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            📄 Klient #{i + 1}
          </Button>
        ))}
        {(reportUrls.broker_reports_html?.length ?? 0) > 0 && reportUrls.broker_reports_html!.map((url, i) => (
          <Button key={`broker-${i}`} variant="outline" size="sm"
            onClick={() => window.open(url, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            📊 Broker #{i + 1}
          </Button>
        ))}
        {reportUrls.client_report_url && (
          <Button variant="outline" size="sm"
            onClick={() => window.open(reportUrls.client_report_url, "_blank")}>
            <Download className="h-3.5 w-3.5" />
            Pobierz raport klienta (Markdown)
          </Button>
        )}
        {reportUrls.artifact_urls?.analysis_json && (
          <Button variant="outline" size="sm"
            onClick={() => window.open(reportUrls.artifact_urls!.analysis_json, "_blank")}>
            <Download className="h-3.5 w-3.5" />
            Pobierz pełną analizę (JSON)
          </Button>
        )}
        {reportUrls.artifact_urls?.broker_bundle && (
          <Button variant="default" size="sm"
            onClick={() => window.open(reportUrls.artifact_urls!.broker_bundle, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            📋 Zbiorczy raport brokerski (audyt wszystkich pojazdów)
          </Button>
        )}
        {reportUrls.artifact_urls?.client_bundle && (
          <Button variant="outline" size="sm"
            onClick={() => window.open(reportUrls.artifact_urls!.client_bundle, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            📄 Zbiorczy klient
          </Button>
        )}
        {reportUrls.artifact_urls?.client_short_bundle && (
          <Button variant="outline" size="sm"
            onClick={() => window.open(reportUrls.artifact_urls!.client_short_bundle, "_blank")}>
            <ExternalLink className="h-3.5 w-3.5" />
            ⚡ Zbiorczy krótki klient
          </Button>
        )}
        {reportUrls.report_endpoints?.client_html && (
          <Button variant="outline" size="sm"
            disabled={loadingEndpoint === "client"}
            onClick={() => openHtmlReport(reportUrls.report_endpoints!.client_html!, "client")}>
            {loadingEndpoint === "client" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ExternalLink className="h-3.5 w-3.5" />}
            Generuj raport HTML klienta
          </Button>
        )}
        {reportUrls.report_endpoints?.broker_html && (
          <Button variant="outline" size="sm"
            disabled={loadingEndpoint === "broker"}
            onClick={() => openHtmlReport(reportUrls.report_endpoints!.broker_html!, "broker")}>
            {loadingEndpoint === "broker" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ExternalLink className="h-3.5 w-3.5" />}
            Generuj raport HTML brokera
          </Button>
        )}
      </div>
    </Card>
  );
}

import { useDeferredValue, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, FileText, Loader2, RefreshCw, Search } from "lucide-react";

import { backendListRecords, type BackendRecord } from "@/functions/backend.functions";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const REPORT_LABELS: Record<string, string> = {
  client_bundle: "Raport klienta",
  client_short_bundle: "Skrócony raport klienta",
  broker_bundle: "Raport brokerski",
  pdf: "Raport PDF",
};

type ReportLink = { key: string; label: string; href: string };

function safeReportUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function getReportLinks(record: BackendRecord): ReportLink[] {
  return Object.entries(record.artifact_urls ?? {}).flatMap(([key, value]) => {
    const href = safeReportUrl(value);
    if (!href) return [];
    return [{ key, href, label: REPORT_LABELS[key] ?? key.replaceAll("_", " ") }];
  });
}

export function ReportsPanel() {
  const listRecords = useServerFn(backendListRecords);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim());
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["report-records", deferredQuery],
    queryFn: () =>
      listRecords({
        data: { limit: 200, query: deferredQuery || undefined },
      }),
    refetchInterval: 60000,
  });

  const reports = useMemo(
    () =>
      (data?.records ?? [])
        .map((record) => ({ record, links: getReportLinks(record) }))
        .filter(({ links }) => links.length > 0),
    [data?.records],
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
          <div className="relative min-w-0 flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Szukaj po kliencie, nazwie lub ID rekordu"
              className="pl-9"
            />
          </div>
          <Badge variant="secondary" className="w-fit">
            {reports.length} rekordów z raportami
          </Badge>
          <Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>
            {isFetching ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Odśwież
          </Button>
        </CardContent>
      </Card>

      {data && data.total > data.records.length && (
        <p className="text-xs text-muted-foreground">
          Pokazano pierwsze {data.records.length} z {data.total} pasujących rekordów. Zawęź
          wyszukiwanie, aby znaleźć starszy raport.
        </p>
      )}

      {isError ? (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Nie udało się pobrać raportów</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{error instanceof Error ? error.message : "Spróbuj ponownie za chwilę."}</span>
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              Spróbuj ponownie
            </Button>
          </AlertDescription>
        </Alert>
      ) : isLoading ? (
        <Card className="flex min-h-56 items-center justify-center">
          <Loader2 className="h-7 w-7 animate-spin text-muted-foreground" />
        </Card>
      ) : reports.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {reports.map(({ record, links }) => (
            <Card key={record.id} className="flex flex-col transition-shadow hover:shadow-md">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <CardTitle className="truncate text-base">
                      {record.title || `Rekord #${record.id}`}
                    </CardTitle>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {new Date(record.created_at).toLocaleString("pl-PL")}
                      {record.client?.name ? ` · ${record.client.name}` : ""}
                    </p>
                  </div>
                  <Badge variant="outline">#{record.id}</Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col gap-2">
                <div className="flex flex-wrap gap-2">
                  {links.map((link, index) => (
                    <Button
                      key={link.key}
                      asChild
                      size="sm"
                      variant={index === 0 ? "default" : "outline"}
                    >
                      <a href={link.href} target="_blank" rel="noopener noreferrer">
                        <FileText className="h-4 w-4" />
                        {link.label}
                      </a>
                    </Button>
                  ))}
                </div>
                <Button asChild variant="ghost" size="sm" className="mt-auto self-start px-0">
                  <Link to="/records" search={{ recordId: record.id }}>
                    Przejdź do szczegółów rekordu
                  </Link>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <Card className="p-10 text-center">
          <FileText className="mx-auto h-10 w-10 text-muted-foreground" />
          <h2 className="mt-3 text-base font-semibold">Brak gotowych raportów</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {query
              ? "Żaden raport nie pasuje do wyszukiwania."
              : "Raporty pojawią się tutaj po zakończeniu wyszukiwania i wygenerowaniu artefaktów."}
          </p>
        </Card>
      )}
    </div>
  );
}

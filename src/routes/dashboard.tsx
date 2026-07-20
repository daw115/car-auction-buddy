import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { getDashboardStats } from "@/functions/watchlist.functions";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { ErrorState } from "@/components/error-state";
import { Loader2, RefreshCw, BarChart3 } from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  LineChart,
  Line,
} from "recharts";

export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title: "Dashboard analityczny — USA Car Finder" },
      {
        name: "description",
        content:
          "Statystyki analiz, klientów i obserwowanych lotów. Wykresy TOP marek, najczęstszych red flag i timeline analiz z ostatnich 30 dni.",
      },
      { property: "og:title", content: "Dashboard analityczny — USA Car Finder" },
      {
        property: "og:description",
        content: "Analityka: TOP marki, red flagi i timeline analiz z ostatnich 30 dni.",
      },
      { property: "og:url", content: "https://car-auction-buddy.lovable.app/dashboard" },
    ],
    links: [{ rel: "canonical", href: "https://car-auction-buddy.lovable.app/dashboard" }],
  }),
  component: Dashboard,
});

function Dashboard() {
  const fetchStats = useServerFn(getDashboardStats);
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: () => fetchStats(),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard analityczny"
        description="Statystyki analiz, klientów i obserwowanych lotów z ostatnich 30 dni."
        icon={<BarChart3 className="h-5 w-5" />}
        actions={
          <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
            {isFetching ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            <span>Odśwież</span>
          </Button>
        }
      />

      {isError ? (
        <ErrorState
          description={
            error instanceof Error
              ? error.message
              : "Statystyki dashboardu są chwilowo niedostępne."
          }
          onRetry={() => void refetch()}
          retrying={isFetching}
        />
      ) : isLoading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : data ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat label="Analizy" value={data.totalRecords} />
            <Stat label="Klienci" value={data.totalClients} />
            <Stat label="Obserwowane loty" value={data.totalWatchlist} />
            <Stat label="Średni score" value={data.avgScore?.toFixed(1) ?? "—"} />
          </div>

          <Card className="p-4">
            <h2 className="text-sm font-semibold mb-3">Analizy w czasie (ostatnie 30 dni)</h2>
            <div className="h-64">
              <ResponsiveContainer>
                <LineChart data={data.timeline}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{
                      background: "var(--popover)",
                      border: "1px solid var(--border)",
                      color: "var(--popover-foreground)",
                      fontSize: 12,
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="count"
                    stroke="var(--primary)"
                    strokeWidth={2}
                    dot={{ r: 3, fill: "var(--primary)" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card className="p-4">
              <h2 className="text-sm font-semibold mb-3">TOP marki</h2>
              <div className="h-64">
                <ResponsiveContainer>
                  <BarChart data={data.topMakes}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{
                        background: "var(--popover)",
                        border: "1px solid var(--border)",
                        color: "var(--popover-foreground)",
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="value" fill="var(--primary)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card className="p-4">
              <h2 className="text-sm font-semibold mb-3">Najczęstsze red flagi</h2>
              <div className="h-64">
                <ResponsiveContainer>
                  <BarChart data={data.topFlags} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                    <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={120} />
                    <Tooltip
                      contentStyle={{
                        background: "var(--popover)",
                        border: "1px solid var(--border)",
                        color: "var(--popover-foreground)",
                        fontSize: 12,
                      }}
                    />
                    <Bar dataKey="value" fill="var(--destructive)" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
    </Card>
  );
}

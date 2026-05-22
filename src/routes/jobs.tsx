import { createFileRoute } from "@tanstack/react-router";
import { Activity } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { ActiveJobsPanel } from "@/components/panels/jobs-panel";
import { ConnectionStatusPanel } from "@/components/panels/connection-status-panel";
import { Card } from "@/components/ui/card";

export const Route = createFileRoute("/jobs")({
  head: () => ({
    meta: [
      { title: "Aktywne zadania — USA Car Finder" },
      {
        name: "description",
        content:
          "Podgląd aktywnych zadań scrapera: fazy, postęp, live logi i możliwość anulowania.",
      },
      { property: "og:title", content: "Aktywne zadania — USA Car Finder" },
      {
        property: "og:description",
        content: "Monitoruj w czasie rzeczywistym wszystkie uruchomione joby scrapera.",
      },
    ],
  }),
  component: JobsPage,
});

function JobsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Aktywne zadania"
        description="Joby scrapera w toku, w kolejce i niedawno zakończone. Lista odświeża się co 2 sekundy."
        icon={<Activity className="h-5 w-5" />}
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <ActiveJobsPanel
          emptyState={
            <Card className="p-8 text-center text-sm text-muted-foreground">
              Brak aktywnych zadań. Uruchom wyszukiwanie na stronie głównej, żeby zobaczyć tu postęp.
            </Card>
          }
        />
        <ConnectionStatusPanel />
      </div>
    </div>
  );
}


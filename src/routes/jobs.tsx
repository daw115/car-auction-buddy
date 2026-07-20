import { createFileRoute, Link } from "@tanstack/react-router";
import { Activity, Search } from "lucide-react";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { ActiveJobsPanel } from "@/components/panels/jobs-panel";
import { ConnectionStatusPanel } from "@/components/panels/connection-status-panel";
import { Button } from "@/components/ui/button";

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
            <EmptyState
              title="Brak aktywnych zadań"
              description="Uruchom wyszukiwanie, aby monitorować tutaj postęp scrapera."
              icon={<Activity className="h-6 w-6" />}
              action={
                <Button asChild>
                  <Link to="/">
                    <Search className="h-4 w-4" />
                    Uruchom wyszukiwanie
                  </Link>
                </Button>
              }
            />
          }
        />
        <ConnectionStatusPanel />
      </div>
    </div>
  );
}

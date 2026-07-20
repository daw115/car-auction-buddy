import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Database, FolderOpen } from "lucide-react";
import { z } from "zod";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { BackendRecordsPanel, RecordDetailView } from "@/components/panels/records-panel";

export const Route = createFileRoute("/records")({
  validateSearch: z.object({
    recordId: z.coerce.number().int().positive().optional(),
  }),
  head: () => ({
    meta: [
      { title: "Rekordy wyszukiwań — USA Car Finder" },
      {
        name: "description",
        content:
          "Historia wszystkich wyszukiwań scrapera i szczegółowe wyniki analizy AI dla każdego zadania.",
      },
      { property: "og:title", content: "Rekordy wyszukiwań — USA Car Finder" },
      {
        property: "og:description",
        content: "Przeglądaj historię wyszukiwań, otwieraj raporty i ponawiaj analizy.",
      },
    ],
  }),
  component: RecordsPage,
});

function RecordsPage() {
  const { recordId } = Route.useSearch();
  const [openedId, setOpenedId] = useState<number | null>(recordId ?? null);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Rekordy wyszukiwań"
        description="Lista zadań scrapera i szczegółowe wyniki analizy AI."
        icon={<Database className="h-5 w-5" />}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
        <aside>
          <BackendRecordsPanel activeRecordId={openedId} onSelectRecord={setOpenedId} />
        </aside>

        <section className="min-w-0">
          {openedId ? (
            <RecordDetailView recordId={openedId} onClose={() => setOpenedId(null)} />
          ) : (
            <EmptyState
              title="Wybierz rekord z listy"
              description="Kliknij wpis po lewej, aby zobaczyć kryteria, statystyki, listę lotów i linki do auto-zbiorczych raportów."
              icon={<FolderOpen className="h-6 w-6" />}
              className="min-h-64"
            />
          )}
        </section>
      </div>
    </div>
  );
}

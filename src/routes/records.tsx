import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Database } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import {
  BackendRecordsPanel,
  SearchAuditPanel,
  RecordDetailView,
} from "@/components/panels/records-panel";
import { Card } from "@/components/ui/card";

export const Route = createFileRoute("/records")({
  head: () => ({
    meta: [
      { title: "Rekordy wyszukiwań — USA Car Finder" },
      {
        name: "description",
        content:
          "Historia wszystkich wyszukiwań scrapera: lista rekordów backendu, audyt i szczegółowe wyniki analizy AI dla każdego zadania.",
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
  const [openedId, setOpenedId] = useState<number | null>(null);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Rekordy wyszukiwań"
        description="Lista zadań scrapera + audyt + szczegółowe wyniki analizy AI."
        icon={<Database className="h-5 w-5" />}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="space-y-3">
          <BackendRecordsPanel
            activeRecordId={openedId}
            onSelectRecord={setOpenedId}
          />
          <SearchAuditPanel />
        </aside>

        <section className="min-w-0">
          {openedId ? (
            <RecordDetailView recordId={openedId} onClose={() => setOpenedId(null)} />
          ) : (
            <Card className="p-12 text-center">
              <div className="text-4xl mb-2">📂</div>
              <h3 className="text-lg font-semibold text-foreground mb-1">
                Wybierz rekord z listy
              </h3>
              <p className="text-sm text-muted-foreground">
                Kliknij wpis po lewej, aby zobaczyć kryteria, statystyki, listę lotów
                i linki do auto-zbiorczych raportów.
              </p>
            </Card>
          )}
        </section>
      </div>
    </div>
  );
}

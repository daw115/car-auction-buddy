import { createFileRoute, Link } from "@tanstack/react-router";
import { Database, ScrollText, Stethoscope } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";

export const Route = createFileRoute("/settings/diagnostics")({
  head: () => ({
    meta: [
      { title: "Diagnostyka — USA Car Finder" },
      {
        name: "description",
        content: "Bezpieczne punkty diagnostyczne aplikacji dla zalogowanego operatora.",
      },
    ],
  }),
  component: DiagnosticsPage,
});

function DiagnosticsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Diagnostyka"
        description="Narzędzia operacyjne dostępne po zalogowaniu, bez ujawniania sekretów i danych sesji."
        icon={<Stethoscope className="h-5 w-5" />}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Link to="/database">
          <Card className="h-full p-5 transition-colors hover:bg-accent">
            <div className="flex items-center gap-2 font-semibold">
              <Database className="h-4 w-4 text-primary" />
              Stan danych i usług
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              Sprawdź połączenia, joby, rekordy oraz operacyjny stan backendu.
            </p>
          </Card>
        </Link>
        <Link to="/dev/logs">
          <Card className="h-full p-5 transition-colors hover:bg-accent">
            <div className="flex items-center gap-2 font-semibold">
              <ScrollText className="h-4 w-4 text-primary" />
              Logi aplikacji
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              Przejdź do logów deweloperskich, aby analizować błędy i przebieg zadań.
            </p>
          </Card>
        </Link>
      </div>
    </div>
  );
}

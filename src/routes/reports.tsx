import { createFileRoute } from "@tanstack/react-router";
import { FileText } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { ReportsPanel } from "@/components/panels/reports-panel";

export const Route = createFileRoute("/reports")({
  head: () => ({
    meta: [
      { title: "Raporty — USA Car Finder" },
      {
        name: "description",
        content: "Gotowe raporty klienta i brokera wygenerowane dla zakończonych wyszukiwań.",
      },
    ],
  }),
  component: ReportsPage,
});

function ReportsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Raporty"
        description="Gotowe materiały dla klienta i brokera zebrane w jednym miejscu."
        icon={<FileText className="h-5 w-5" />}
      />
      <ReportsPanel />
    </div>
  );
}

import { createFileRoute } from "@tanstack/react-router";
import { ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { SearchAuditPanel } from "@/components/panels/records-panel";

export const Route = createFileRoute("/audit")({
  head: () => ({
    meta: [
      { title: "Audyt wyszukiwań — USA Car Finder" },
      {
        name: "description",
        content:
          "Historia operacji wyszukiwania z użytkownikiem, kryteriami i powiązanym rekordem.",
      },
    ],
  }),
  component: AuditPage,
});

function AuditPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Audyt wyszukiwań"
        description="Historia uruchomień z informacją kto i kiedy rozpoczął wyszukiwanie."
        icon={<ShieldCheck className="h-5 w-5" />}
      />
      <SearchAuditPanel
        limit={200}
        className="mx-auto w-full max-w-5xl"
        maxHeightClassName="max-h-[calc(100vh-16rem)]"
      />
    </div>
  );
}

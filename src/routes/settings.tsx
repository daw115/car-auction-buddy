import { createFileRoute, Link } from "@tanstack/react-router";
import { Card } from "@/components/ui/card";
import { Sparkles, SlidersHorizontal } from "lucide-react";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Ustawienia — USA Car Finder" },
      { name: "description", content: "Konfiguracja providerów AI i filtrów pipeline." },
    ],
  }),
  component: SettingsHub,
});

function SettingsHub() {
  return (
    <div className="mx-auto max-w-3xl p-4 md:p-6 space-y-4">
      <h1 className="text-2xl font-bold">Ustawienia</h1>
      <p className="text-sm text-muted-foreground">
        Cała konfiguracja providerów LLM i filtrów pipeline'u jest po stronie backendu
        (<code>usacar-api</code>). Wybierz sekcję:
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <Link to="/settings/ai">
          <Card className="p-4 hover:bg-accent transition-colors h-full">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <h2 className="font-semibold">Providery AI</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              Wybór providera i modelu dla analizy ofert, generowania raportów,
              normalizacji modeli, wykrywania uszkodzeń ramy i agenta ofert.
            </p>
          </Card>
        </Link>
        <Link to="/settings/filters">
          <Card className="p-4 hover:bg-accent transition-colors h-full">
            <div className="flex items-center gap-2 mb-2">
              <SlidersHorizontal className="h-4 w-4 text-primary" />
              <h2 className="font-semibold">Filtry systemowe</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              Globalne przełączniki pipeline'u: tylko sprzedawcy typu insurance,
              wykluczenie kabrioletów itp.
            </p>
          </Card>
        </Link>
      </div>
    </div>
  );
}

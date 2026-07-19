import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Ustawienia — USA Car Finder" },
      { name: "description", content: "Konfiguracja providerów AI i filtrów pipeline." },
    ],
  }),
  component: () => <Outlet />,
});

import { useRouterState, Link } from "@tanstack/react-router";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { ActiveJobPill } from "@/components/active-job-pill";
import { Separator } from "@/components/ui/separator";

const ROUTE_LABELS: Record<string, string> = {
  "/": "Szukaj",
  "/database": "Rekordy",
  "/watchlist": "Watchlist",
  "/dashboard": "Dashboard",
  "/calculator": "Kalkulator",
  "/settings": "Ustawienia",
  "/dev/logs": "Logi (dev)",
};

export function AppTopbar() {
  const pathname = useRouterState({
    select: (router) => router.location.pathname,
  });

  const label =
    ROUTE_LABELS[pathname] ??
    (pathname.startsWith("/dev/") ? "Dev" : pathname.replace(/^\//, "") || "Strona");

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="h-5" />
      <nav className="flex items-center gap-1.5 text-sm text-muted-foreground min-w-0">
        <Link to="/" className="hover:text-foreground transition-colors">
          Panel
        </Link>
        <span className="text-muted-foreground/50">/</span>
        <span className="font-medium text-foreground truncate">{label}</span>
      </nav>
      <div className="ml-auto flex items-center gap-2">
        <ActiveJobPill />
        <ThemeToggle />
      </div>
    </header>
  );
}

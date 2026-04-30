import { Outlet, Link, createRootRoute, HeadContent, Scripts } from "@tanstack/react-router";
import { Toaster } from "@/components/ui/sonner";

import appCss from "../styles.css?url";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "USA Car Finder — panel operatora" },
      {
        name: "description",
        content:
          "Panel operacyjny do wyszukiwania aut z aukcji Copart i IAAI, analiza AI i raporty dla klientów.",
      },
      { property: "og:title", content: "USA Car Finder — panel operatora" },
      { property: "og:description", content: "Web application for searching US auction cars, managing clients, AI analysis, and report generation." },
      { property: "og:type", content: "website" },
      { name: "twitter:title", content: "USA Car Finder — panel operatora" },
      { name: "description", content: "Web application for searching US auction cars, managing clients, AI analysis, and report generation." },
      { name: "twitter:description", content: "Web application for searching US auction cars, managing clients, AI analysis, and report generation." },
      { property: "og:image", content: "https://pub-bb2e103a32db4e198524a2e9ed8f35b4.r2.dev/65dd55e3-8f53-4cfe-8132-d0a422ee2cdb/id-preview-a3a5a654--edf9b460-b0a8-4a4d-baf9-8b64e6cbcb5c.lovable.app-1777578956307.png" },
      { name: "twitter:image", content: "https://pub-bb2e103a32db4e198524a2e9ed8f35b4.r2.dev/65dd55e3-8f53-4cfe-8132-d0a422ee2cdb/id-preview-a3a5a654--edf9b460-b0a8-4a4d-baf9-8b64e6cbcb5c.lovable.app-1777578956307.png" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [
      {
        rel: "stylesheet",
        href: appCss,
      },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
});

function RootShell({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Toaster richColors position="top-right" />
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  return <Outlet />;
}

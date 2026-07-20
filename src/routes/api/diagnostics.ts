import { createFileRoute } from "@tanstack/react-router";
import { siteSessionGuard } from "@/server/site-session.server";

type Check = {
  name: string;
  present: boolean;
  required: boolean;
  category: "auth" | "backend" | "ai" | "supabase";
  description: string;
  hint?: string;
  minLength?: number;
  lengthOk?: boolean;
};

function check(
  name: string,
  category: Check["category"],
  description: string,
  required: boolean,
  opts: { minLength?: number; hint?: string } = {},
): Check {
  const raw = process.env[name];
  const present = typeof raw === "string" && raw.length > 0;
  const lengthOk = opts.minLength ? present && raw!.length >= opts.minLength : true;
  return {
    name,
    category,
    description,
    required,
    present,
    hint: opts.hint,
    minLength: opts.minLength,
    lengthOk,
  };
}

export const Route = createFileRoute("/api/diagnostics")({
  server: {
    handlers: {
      GET: async () => {
        const unauthorized = await siteSessionGuard();
        if (unauthorized) return unauthorized;

        const checks: Check[] = [
          check("SITE_SESSION_SECRET", "auth", "Sekret do podpisywania sesji PasswordGate", true, {
            minLength: 32,
            hint: "Wygeneruj losowy ciąg ≥32 znaków (np. openssl rand -hex 32) i zapisz w sekretach.",
          }),
          check("SITE_MASTER_PASSWORD", "auth", "Hasło nadrzędne do zarządzania profilami", true, {
            hint: "Wymagane do dodawania/usuwania kont w PasswordGate.",
          }),
          check("API_BASE_URL", "backend", "URL produkcyjnego backendu FastAPI", true, {
            hint: "np. https://moneybitches.organof.org",
          }),
          check("SCRAPER_BASE_URL", "backend", "URL zewnętrznego scrapera (legacy proxy)", false),
          check("SCRAPER_API_TOKEN", "backend", "Token do scrapera", false),
          check("ANTHROPIC_API_KEY", "ai", "Klucz Anthropic (opcjonalny — backend ma własny)", false),
          check("GEMINI_API_KEY", "ai", "Klucz Gemini (opcjonalny)", false),
          check("VITE_SUPABASE_URL", "supabase", "URL projektu Supabase", true),
          check("VITE_SUPABASE_PUBLISHABLE_KEY", "supabase", "Publiczny klucz Supabase", true),
        ];

        const missingRequired = checks.filter((c) => c.required && (!c.present || !c.lengthOk));

        return Response.json({
          ok: missingRequired.length === 0,
          checkedAt: new Date().toISOString(),
          runtime: {
            nodeEnv: process.env.NODE_ENV || "unknown",
          },
          checks,
          summary: {
            total: checks.length,
            ok: checks.filter((c) => c.present && c.lengthOk).length,
            missingRequired: missingRequired.length,
          },
        });
      },
    },
  },
});

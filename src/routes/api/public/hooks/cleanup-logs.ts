import { timingSafeEqual } from "node:crypto";
import { createFileRoute } from "@tanstack/react-router";
import { supabaseAdmin } from "@/integrations/supabase/client.server";

const DEFAULT_RETENTION_DAYS = 30;

function getRetentionDays(): number {
  const raw = process.env.LOG_RETENTION_DAYS;
  const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
  if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_RETENTION_DAYS;
  return Math.min(parsed, 3650);
}

export function isCleanupRequestAuthorized(request: Request, secret: string): boolean {
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Bearer ") || secret.length < 32) return false;
  const supplied = Buffer.from(authorization.slice("Bearer ".length), "utf8");
  const expected = Buffer.from(secret, "utf8");
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

async function runCleanup() {
  const days = getRetentionDays();
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
  const { error, count } = await supabaseAdmin
    .from("operation_logs")
    .delete({ count: "exact" })
    .lt("created_at", cutoff);
  if (error) throw error;
  return { retention_days: days, cutoff, deleted: count ?? 0 };
}

export const Route = createFileRoute("/api/public/hooks/cleanup-logs")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const secret = process.env.LOG_CLEANUP_SECRET;
        if (!secret || secret.length < 32) {
          return Response.json(
            { success: false, error: "Cleanup hook is not configured" },
            { status: 503 },
          );
        }
        if (!isCleanupRequestAuthorized(request, secret)) {
          return Response.json({ success: false, error: "Unauthorized" }, { status: 401 });
        }

        try {
          const result = await runCleanup();
          return Response.json({ success: true, ...result });
        } catch (error) {
          const message = error instanceof Error ? error.message : "cleanup failed";
          return Response.json({ success: false, error: message }, { status: 500 });
        }
      },
    },
  },
});

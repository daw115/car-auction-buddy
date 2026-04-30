// Login/logout for the /dev/logs panel. Sets a httpOnly cookie with the dev token.
// POST /api/dev/auth   { token }  -> sets cookie
// DELETE /api/dev/auth            -> clears cookie
// GET /api/dev/auth               -> { authenticated: boolean }

import { createFileRoute } from "@tanstack/react-router";
import {
  buildAuthCookie,
  checkDevAuth,
  checkLoginRateLimit,
  clearAuthCookie,
  getClientKey,
  getCookieTtlSeconds,
  getExpectedToken,
  registerFailedAttempt,
  resetAttempts,
} from "@/server/dev-auth.server";

export const Route = createFileRoute("/api/dev/auth")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const ttlSeconds = getCookieTtlSeconds();
        const result = checkDevAuth(request);
        if (result.ok) {
          return Response.json({ authenticated: true, ttlSeconds });
        }
        return Response.json(
          { authenticated: false, reason: result.reason, ttlSeconds },
          { status: result.status === 401 ? 200 : result.status },
        );
      },
      POST: async ({ request }) => {
        const expected = getExpectedToken();
        if (!expected) {
          return Response.json(
            { ok: false, reason: "DEV_LOGS_TOKEN is not configured" },
            { status: 503 },
          );
        }
        if ((process.env.NODE_ENV ?? "development") === "production") {
          return Response.json(
            { ok: false, reason: "Dev panel disabled in production" },
            { status: 403 },
          );
        }

        const clientKey = getClientKey(request);
        const limit = checkLoginRateLimit(clientKey);
        if (!limit.allowed) {
          return new Response(
            JSON.stringify({
              ok: false,
              reason: "Too many failed attempts. Try again later.",
              retryAfterSeconds: limit.retryAfterSeconds,
            }),
            {
              status: 429,
              headers: {
                "Content-Type": "application/json",
                "Retry-After": String(limit.retryAfterSeconds),
              },
            },
          );
        }

        let body: unknown;
        try {
          body = await request.json();
        } catch {
          return Response.json({ ok: false, reason: "Invalid JSON" }, { status: 400 });
        }
        const token =
          body && typeof body === "object" && "token" in body
            ? String((body as { token: unknown }).token ?? "")
            : "";
        if (!token) {
          return Response.json({ ok: false, reason: "Missing token" }, { status: 400 });
        }
        if (token !== expected) {
          const after = registerFailedAttempt(clientKey);
          if (!after.allowed) {
            return new Response(
              JSON.stringify({
                ok: false,
                reason: "Too many failed attempts. Try again later.",
                retryAfterSeconds: after.retryAfterSeconds,
              }),
              {
                status: 429,
                headers: {
                  "Content-Type": "application/json",
                  "Retry-After": String(after.retryAfterSeconds),
                },
              },
            );
          }
          return Response.json(
            { ok: false, reason: "Invalid token", attemptsRemaining: after.remaining },
            { status: 401 },
          );
        }
        resetAttempts(clientKey);
        return new Response(JSON.stringify({ ok: true, ttlSeconds: getCookieTtlSeconds() }), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "Set-Cookie": buildAuthCookie(token),
          },
        });
      },
      DELETE: async () => {
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "Set-Cookie": clearAuthCookie(),
          },
        });
      },
    },
  },
});

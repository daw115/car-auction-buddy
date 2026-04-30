// Server-function middleware that logs every RPC call: method, status, duration.
// Attach via `.middleware([devRequestLogger])` on createServerFn definitions,
// or import `withDevLogging` to wrap quickly.

import { createMiddleware } from "@tanstack/react-start";
import { logHttp, devLog } from "./dev-logger.server";

export const devRequestLogger = createMiddleware({ type: "function" }).server(
  async (ctx) => {
    const start = performance.now();
    // functionId / method are present at runtime but typings are loose across versions.
    const meta = ctx as unknown as { functionId?: string; method?: string };
    const fnId = meta.functionId ?? "unknown";
    const method = meta.method ?? "POST";
    try {
      const result = await ctx.next();
      const durationMs = performance.now() - start;
      logHttp({
        method,
        path: `fn:${fnId}`,
        status: 200,
        durationMs,
        scope: "server-fn",
      });
      return result;
    } catch (err) {
      const durationMs = performance.now() - start;
      const status =
        typeof (err as { status?: number })?.status === "number"
          ? (err as { status: number }).status
          : 500;
      logHttp({
        method,
        path: `fn:${fnId}`,
        status,
        durationMs,
        scope: "server-fn",
      });
      devLog("error", "server-fn", `${fnId} failed`, {
        message: (err as Error)?.message,
      });
      throw err;
    }
  },
);

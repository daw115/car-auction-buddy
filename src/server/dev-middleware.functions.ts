// Server-function middleware that logs every RPC call: method, status, duration.
// Attach via `.middleware([devRequestLogger])` on createServerFn definitions,
// or import `withDevLogging` to wrap quickly.

import { createMiddleware } from "@tanstack/react-start";
import { logHttp, devLog } from "./dev-logger.server";

export const devRequestLogger = createMiddleware({ type: "function" }).server(
  async ({ next, functionId, method }) => {
    const start = performance.now();
    try {
      const result = await next();
      const durationMs = performance.now() - start;
      logHttp({
        method: method ?? "POST",
        path: `fn:${functionId}`,
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
        method: method ?? "POST",
        path: `fn:${functionId}`,
        status,
        durationMs,
        scope: "server-fn",
      });
      devLog("error", "server-fn", `${functionId} failed`, {
        message: (err as Error)?.message,
      });
      throw err;
    }
  },
);

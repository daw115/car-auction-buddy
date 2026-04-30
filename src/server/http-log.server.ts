// Helper to wrap server route HTTP handlers with colored request/response logs.
// Usage:
//   GET: withHttpLog("api/health", async ({ request }) => new Response("ok"))

import { logHttp, devLog } from "./dev-logger.server";

type HandlerArgs = {
  request: Request;
  params?: Record<string, string>;
  context?: unknown;
};
type Handler = (args: HandlerArgs) => Promise<Response> | Response;

export function withHttpLog(scope: string, handler: Handler): Handler {
  return async (args) => {
    const start = performance.now();
    const url = new URL(args.request.url);
    const method = args.request.method;
    try {
      const res = await handler(args);
      logHttp({
        method,
        path: url.pathname + url.search,
        status: res.status,
        durationMs: performance.now() - start,
        scope,
      });
      return res;
    } catch (err) {
      const durationMs = performance.now() - start;
      logHttp({
        method,
        path: url.pathname + url.search,
        status: 500,
        durationMs,
        scope,
      });
      devLog("error", scope, `unhandled error in ${url.pathname}`, {
        message: (err as Error)?.message,
      });
      throw err;
    }
  };
}

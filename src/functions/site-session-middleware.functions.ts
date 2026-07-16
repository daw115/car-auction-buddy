import { createMiddleware } from "@tanstack/react-start";
import { requireSiteSession } from "@/server/site-session.server";

export const siteSessionMiddleware = createMiddleware({ type: "function" }).server(
  async ({ next }) => {
    const session = requireSiteSession();
    return next({
      context: {
        siteUser: session.sub,
      },
    });
  },
);

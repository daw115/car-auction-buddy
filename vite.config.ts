// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - tanstackStart, viteReact, tailwindcss, tsConfigPaths, cloudflare (build-only),
//     componentTagger (dev-only), VITE_* env injection, @ path alias, React/TanStack dedupe,
//     error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... } }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";

function safeExec(cmd: string, fallback = "unknown"): string {
  try {
    return execSync(cmd, { stdio: ["ignore", "pipe", "ignore"] }).toString().trim() || fallback;
  } catch {
    return fallback;
  }
}

// Build-time git metadata. Lovable / CI env vars take precedence over local git calls.
const commitSha =
  process.env.LOVABLE_COMMIT_SHA ||
  process.env.GITHUB_SHA ||
  process.env.CF_PAGES_COMMIT_SHA ||
  safeExec("git rev-parse HEAD");

const commitShort = commitSha === "unknown" ? "unknown" : commitSha.slice(0, 7);

const branch =
  process.env.LOVABLE_BRANCH ||
  process.env.GITHUB_REF_NAME ||
  process.env.CF_PAGES_BRANCH ||
  safeExec("git rev-parse --abbrev-ref HEAD");

let pkgVersion = "0.0.0";
try {
  pkgVersion = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")).version || "0.0.0";
} catch {
  /* ignore */
}

export default defineConfig({
  vite: {
    define: {
      __APP_COMMIT_SHA__: JSON.stringify(commitSha),
      __APP_COMMIT_SHORT__: JSON.stringify(commitShort),
      __APP_BUILD_TIME__: JSON.stringify(new Date().toISOString()),
      __APP_BRANCH__: JSON.stringify(branch),
      __APP_VERSION__: JSON.stringify(pkgVersion),
    },
  },
});

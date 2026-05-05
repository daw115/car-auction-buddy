#!/usr/bin/env node
/**
 * Parses Vite/TanStack Start build output and produces a clear,
 * actionable report for import-protection and other common errors.
 *
 * Usage: node scripts/parse-build-errors.mjs [build-log-file]
 *   If no file is given, reads from stdin.
 */
import { readFileSync } from "node:fs";

const input = process.argv[2]
  ? readFileSync(process.argv[2], "utf8")
  : readFileSync(0, "utf8"); // stdin

const lines = input.split("\n");

// ── Collect import-protection violations ────────────────────────────
const importProtectionRe =
  /import[- ]?protection|Import denied|not allowed.*server|server.*not allowed/i;
const fileRefRe = /(?:src\/\S+\.(?:ts|tsx|js|jsx))/g;

const violations = [];
let currentBlock = null;

for (const line of lines) {
  if (importProtectionRe.test(line)) {
    currentBlock = { message: line.trim(), files: [] };
    const refs = line.match(fileRefRe);
    if (refs) currentBlock.files.push(...refs);
    violations.push(currentBlock);
  } else if (currentBlock && fileRefRe.test(line)) {
    currentBlock.files.push(...line.match(fileRefRe));
  } else if (currentBlock && line.trim() === "") {
    currentBlock = null;
  }
}

// ── Collect TS serialization errors ─────────────────────────────────
const serializationRe = /SerializationError|not assignable to type.*Serializ/i;
const tsErrorRe = /^(src\/\S+)\((\d+),(\d+)\): error (TS\d+): (.+)/;
const serializationErrors = [];

for (const line of lines) {
  if (serializationRe.test(line)) {
    const match = line.match(tsErrorRe);
    if (match) {
      serializationErrors.push({
        file: match[1],
        line: match[2],
        col: match[3],
        code: match[4],
        message: match[5].slice(0, 200),
      });
    } else {
      serializationErrors.push({ message: line.trim() });
    }
  }
}

// ── Collect generic build errors ────────────────────────────────────
const genericErrors = [];
const errorRe = /\berror\b/i;
const ignoreRe = /node_modules|\.map|ExperimentalWarning|DeprecationWarning/;
for (const line of lines) {
  if (
    errorRe.test(line) &&
    !ignoreRe.test(line) &&
    !importProtectionRe.test(line) &&
    !serializationRe.test(line)
  ) {
    genericErrors.push(line.trim());
  }
}

// ── Report ──────────────────────────────────────────────────────────
const SEP = "─".repeat(70);
let hasIssues = false;

if (violations.length > 0) {
  hasIssues = true;
  console.log(`\n${SEP}`);
  console.log(`🚫  IMPORT-PROTECTION VIOLATIONS (${violations.length})`);
  console.log(SEP);
  console.log(
    "Server-only files (src/server/**) cannot be imported from client code."
  );
  console.log(
    "Move the import to a *.functions.ts file under src/functions/, or"
  );
  console.log("pass server data via props / loader.\n");

  for (const v of violations) {
    const uniqueFiles = [...new Set(v.files)];
    console.log(`  ▸ ${v.message}`);
    if (uniqueFiles.length) {
      console.log(`    Files: ${uniqueFiles.join(", ")}`);
    }
    console.log();
  }
}

if (serializationErrors.length > 0) {
  hasIssues = true;
  console.log(`\n${SEP}`);
  console.log(`⚠️  SERIALIZATION ERRORS (${serializationErrors.length})`);
  console.log(SEP);
  console.log(
    "TanStack's createServerFn requires all return types to be serializable."
  );
  console.log(
    'Replace `unknown` with concrete types (string | number | boolean | null).\n'
  );

  for (const e of serializationErrors) {
    if (e.file) {
      console.log(`  ▸ ${e.file}:${e.line}:${e.col} [${e.code}]`);
      console.log(`    ${e.message}\n`);
    } else {
      console.log(`  ▸ ${e.message}\n`);
    }
  }
}

if (!hasIssues && genericErrors.length > 0) {
  console.log(`\n${SEP}`);
  console.log(`❌  BUILD ERRORS (${Math.min(genericErrors.length, 20)} shown)`);
  console.log(SEP);
  for (const e of genericErrors.slice(0, 20)) {
    console.log(`  ${e}`);
  }
  console.log();
}

if (!hasIssues && genericErrors.length === 0) {
  console.log("\n✅  No import-protection or serialization issues detected.\n");
}

#!/usr/bin/env node
// Scans client-side code for forbidden imports from @/server/* or relative ../server/*.
// Exits with code 1 if violations found, 0 otherwise.

import { readFileSync, readdirSync, statSync } from "fs";
import { join, relative } from "path";

const CLIENT_DIRS = ["src/components", "src/hooks", "src/lib", "src/routes"];
const EXCLUDE_DIRS = ["src/routes/api"];
const EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx"]);

const IMPORT_PATTERNS = [
  /from\s+['"]@\/server\//,
  /from\s+['"]\.\.?\/.*server\//,
  /import\s*\(\s*['"]@\/server\//,
  /require\s*\(\s*['"]@\/server\//,
];

function walk(dir) {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!EXCLUDE_DIRS.some((ex) => full.startsWith(ex))) files.push(...walk(full));
    } else if (EXTENSIONS.has(full.slice(full.lastIndexOf(".")))) {
      files.push(full);
    }
  }
  return files;
}

const violations = [];

for (const dir of CLIENT_DIRS) {
  try {
    statSync(dir);
  } catch {
    continue;
  }
  for (const file of walk(dir)) {
    const content = readFileSync(file, "utf-8");
    const lines = content.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      for (const pat of IMPORT_PATTERNS) {
        if (pat.test(line)) {
          violations.push({ file: relative(".", file), line: i + 1, text: line.trim() });
          break;
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log("✅ No forbidden @/server/* imports found in client code.");
  process.exit(0);
}

console.log(`\n🚫 Found ${violations.length} forbidden server import(s) in client code:\n`);
for (const v of violations) {
  console.log(`  ${v.file}:${v.line}`);
  console.log(`    ${v.text}\n`);
}
console.log("ℹ️  Move server logic to *.functions.ts (createServerFn) and import from there.\n");
process.exit(1);

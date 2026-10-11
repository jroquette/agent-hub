// Generate src/api/schema.d.ts from the API's committed OpenAPI document, formatted by Prettier.
// `--check` compares instead of writing and exits 1 when the types are stale.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";
import prettier from "prettier";

const SOURCE = new URL("../../../packages/api/openapi.json", import.meta.url);
const TARGET = new URL("../src/api/schema.d.ts", import.meta.url);
const HEADER =
  "// Generated from packages/api/openapi.json by scripts/gen-api.mjs (make openapi); do not edit.\n\n";

const ast = await openapiTS(JSON.parse(readFileSync(SOURCE, "utf8")));
const options = (await prettier.resolveConfig(fileURLToPath(TARGET))) ?? {};
const text = await prettier.format(HEADER + astToString(ast), { ...options, parser: "typescript" });

if (process.argv.includes("--check")) {
  let current = null;
  try {
    current = readFileSync(TARGET, "utf8");
  } catch {
    current = null;
  }
  if (current !== text) {
    console.error("apps/web/src/api/schema.d.ts is stale: run make openapi");
    process.exit(1);
  }
} else {
  writeFileSync(TARGET, text);
  console.log("wrote src/api/schema.d.ts");
}

// Generate src/api/schema.d.ts from the API's committed OpenAPI document, and src/api/launchCookie.ts
// (every operation the document marks `x-agent-hub-launch-cookie`), formatted by Prettier.
// `--check` compares instead of writing and exits 1 when either file is stale.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";
import prettier from "prettier";

const SOURCE = new URL("../../../packages/api/openapi.json", import.meta.url);
const TARGET = new URL("../src/api/schema.d.ts", import.meta.url);
const HEADER =
  "// Generated from packages/api/openapi.json by scripts/gen-api.mjs (make openapi); do not edit.\n\n";

const COOKIE_TARGET = new URL("../src/api/launchCookie.ts", import.meta.url);
const COOKIE_MARK = "x-agent-hub-launch-cookie";

const document = JSON.parse(readFileSync(SOURCE, "utf8"));
const ast = await openapiTS(document);
const options = (await prettier.resolveConfig(fileURLToPath(TARGET))) ?? {};
const text = await prettier.format(HEADER + astToString(ast), { ...options, parser: "typescript" });

const marked = Object.entries(document.paths)
  .flatMap(([path, operations]) =>
    Object.entries(operations)
      .filter(([, operation]) => operation[COOKIE_MARK] === true)
      .map(([method]) => `${method.toUpperCase()} ${path}`),
  )
  .sort();
const cookieText = await prettier.format(
  HEADER +
    "/** Every operation that needs the launch cookie, as `METHOD /path/{template}`. */\n" +
    `export const LAUNCH_COOKIE_ROUTES: ReadonlySet<string> = new Set(${JSON.stringify(marked)});\n`,
  { ...options, parser: "typescript" },
);

const outputs = [
  [TARGET, text, "src/api/schema.d.ts"],
  [COOKIE_TARGET, cookieText, "src/api/launchCookie.ts"],
];

if (process.argv.includes("--check")) {
  for (const [target, expected, name] of outputs) {
    let current = null;
    try {
      current = readFileSync(target, "utf8");
    } catch {
      current = null;
    }
    if (current !== expected) {
      console.error(`apps/web/${name} is stale: run make openapi`);
      process.exit(1);
    }
  }
} else {
  for (const [target, expected, name] of outputs) {
    writeFileSync(target, expected);
    console.log(`wrote ${name}`);
  }
}

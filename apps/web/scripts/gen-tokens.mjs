// Generate src/styles/tokens.css from design/tokens.json (a port of the design's tokens2css.py).
// `--check` compares instead of writing and exits 1 when the CSS is stale.
import { readFileSync, writeFileSync } from "node:fs";

const SOURCE = new URL("../design/tokens.json", import.meta.url);
const TARGET = new URL("../src/styles/tokens.css", import.meta.url);
const HEADER = "/* Generated from design/tokens.json by scripts/gen-tokens.mjs; do not edit. */";

/** `{name}` refers to another token: `var(--name)`; any other value is kept. */
function reference(value) {
  const match = /^\{(.+)\}$/.exec(value);
  return match ? `var(--${match[1]})` : value;
}

function themed(token, theme) {
  return typeof token.value === "string" ? token.value : token.value[theme];
}

export function renderTokens(tokens) {
  const themes = tokens.color.themes.map((theme) => theme.id);
  const shadows = tokens.shadow?.tokens ?? [];
  const [first, ...others] = themes;
  const blocks = [];

  const base = [
    ...tokens.color.tokens.map((t) => `  --${t.name}: ${reference(themed(t, first))};`),
    ...shadows.map((t) => `  --${t.name}: ${themed(t, first)};`),
  ];
  blocks.push(`:root, [data-theme="${first}"] {\n${base.join("\n")}\n}`);

  for (const theme of others) {
    const lines = [...tokens.color.tokens, ...shadows]
      .filter((t) => typeof t.value === "object" && theme in t.value)
      .map((t) => `  --${t.name}: ${reference(t.value[theme])};`);
    blocks.push(`[data-theme="${theme}"] {\n${lines.join("\n")}\n}`);
  }

  const scalars = [];
  for (const [family, group] of Object.entries(tokens)) {
    if (
      group &&
      typeof group === "object" &&
      "tokens" in group &&
      !["color", "shadow"].includes(family)
    ) {
      for (const t of group.tokens) {
        scalars.push(`  --${t.name.replaceAll(".", "\\.")}: ${t.value};`);
      }
    }
  }
  for (const [name, stack] of Object.entries(tokens.type.families)) {
    scalars.push(`  --font-${name}: ${stack};`);
  }
  blocks.push(`:root {\n${scalars.join("\n")}\n}`);

  return `${HEADER}\n${blocks.join("\n")}\n`;
}

const css = renderTokens(JSON.parse(readFileSync(SOURCE, "utf8")));
if (process.argv.includes("--check")) {
  let current = null;
  try {
    current = readFileSync(TARGET, "utf8");
  } catch {
    current = null;
  }
  if (current !== css) {
    console.error("src/styles/tokens.css is stale: run npm run gen:tokens");
    process.exit(1);
  }
} else {
  writeFileSync(TARGET, css);
  console.log("wrote src/styles/tokens.css");
}

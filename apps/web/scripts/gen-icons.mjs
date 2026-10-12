// Generate src/components/icons.ts from node_modules/lucide (a port of the design's genicons.mjs):
// the Lucide icon nodes the design uses, bundled so the app needs no CDN (D19).
// `--check` compares instead of writing and exits 1 when the file is stale.
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import prettier from "prettier";

const NAMES =
  `activity layout-dashboard stamp radio list square-terminal route workflow library book-open sprout
split layers list-checks chart-line flask-conical stethoscope list-todo settings hand circle-check circle-x octagon-x
octagon-alert moon clock shield-x shield-alert shield-check square file-text file-pen file-plus terminal text-search
folder-search network globe plug user message-square message-square-dashed hourglass check-check play rotate-ccw
folder-kanban warehouse book circle-dot git-pull-request git-merge git-commit-horizontal chevron-right chevron-down
chevron-left chevron-up x copy check link external-link search funnel ellipsis sun monitor arrow-down arrow-up
arrow-right eye-off lock file folder folder-open refresh-cw pause info triangle-alert circle-alert wifi-off keyboard
command bookmark columns-3 panel-left plus minus coins timer hash braces lightbulb git-compare trending-up
trending-down scroll-text clipboard-list gauge package tag cpu box file-minus file-x circle-pause flag milestone pin
arrow-up-right corner-down-right list-filter circle-dashed loader git-branch server database cable shield gavel
circle-play circle-stop square-user scan-eye`.split(/\s+/);

const LUCIDE = new URL("../node_modules/lucide/", import.meta.url);
const TARGET = new URL("../src/components/icons.ts", import.meta.url);

const version = JSON.parse(readFileSync(new URL("package.json", LUCIDE), "utf8")).version;
const icons = {};
for (const name of NAMES) {
  const module = await import(new URL(`dist/esm/icons/${name}.mjs`, LUCIDE).href);
  for (const [, attrs] of module.default) {
    for (const key of Object.keys(attrs)) {
      if (key.includes("-")) throw new Error(`${name}: attribute ${key} needs a React name`);
    }
  }
  icons[name] = module.default;
}

const source = `// Generated from lucide ${version} (ISC) by scripts/gen-icons.mjs; do not edit.
// Icon nodes: [tag, attributes][] on a 24 grid, drawn with a 2px stroke by .ah-icon.

export type IconNode = readonly (readonly [string, Readonly<Record<string, string>>])[];

export const ICONS = ${JSON.stringify(icons)} as const satisfies Record<string, IconNode>;

/** A Lucide icon name the app bundles. */
export type IconName = keyof typeof ICONS;

export const ICON_NAMES = Object.keys(ICONS) as IconName[];
`;
const options = (await prettier.resolveConfig(fileURLToPath(TARGET))) ?? {};
const text = await prettier.format(source, { ...options, parser: "typescript" });

if (process.argv.includes("--check")) {
  let current = null;
  try {
    current = readFileSync(TARGET, "utf8");
  } catch {
    current = null;
  }
  if (current !== text) {
    console.error("src/components/icons.ts is stale: run node scripts/gen-icons.mjs");
    process.exit(1);
  }
} else {
  writeFileSync(TARGET, text);
  console.log(`wrote src/components/icons.ts (${NAMES.length} icons)`);
}

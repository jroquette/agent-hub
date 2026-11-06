// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

// scripts/check-changed.mjs, the web steps `make check-changed` runs for a change it narrows
// (scripts/check_changed.py), on a scratch project of its own: a Vitest, ESLint and Prettier
// config and a few modules. Each run starts Vitest, ESLint or Prettier afresh in a child process.
const SCRIPT = resolve(import.meta.dirname, "../../scripts/check-changed.mjs");
const RUN_TIMEOUT_MS = 60_000;

const PROJECT: Record<string, string> = {
  "vitest.config.mjs":
    'export default { test: { globals: true, include: ["src/**/*.test.mjs"] } };\n',
  "eslint.config.mjs": 'export default [{ rules: { "no-unused-vars": "error" } }];\n',
  ".prettierrc.json": "{}\n",
  "src/sum.mjs": "export const sum = (a, b) => a + b;\n",
  "src/sum.test.mjs":
    'import { sum } from "./sum.mjs";\n\ntest("adds", () => {\n  expect(sum(1, 2)).toBe(3);\n});\n',
  // Broken on purpose: its test fails.
  "src/half.mjs": "export const half = (n) => n / 3;\n",
  "src/half.test.mjs":
    'import { half } from "./half.mjs";\n\ntest("halves", () => {\n  expect(half(4)).toBe(2);\n});\n',
  "src/alone.mjs": "export const alone = 1;\n",
  "src/unused.mjs": "const unused = 1;\nexport const kept = 2;\n",
  "src/messy.mjs": "export const messy   =  1\n",
};

let root: string;

beforeAll(async () => {
  root = await mkdtemp(join(tmpdir(), "ah-check-changed-"));
  for (const [name, text] of Object.entries(PROJECT)) {
    await mkdir(dirname(join(root, name)), { recursive: true });
    await writeFile(join(root, name), text);
  }
});

afterAll(async () => {
  await rm(root, { recursive: true, force: true });
});

interface Run {
  status: number | null;
  output: string;
}

// The changed files go one a line in a file, as check_changed.py writes them; the child gets
// no VITEST variable, so the Vitest it starts is not taken for a worker of this one.
async function run(mode: string, files: string[]): Promise<Run> {
  const list = join(root, "changed.txt");
  await writeFile(list, files.map((file) => `${file}\n`).join(""));
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([name]) => !name.startsWith("VITEST")),
  );
  const done = spawnSync(process.execPath, [SCRIPT, mode, list], {
    cwd: root,
    env,
    encoding: "utf8",
    timeout: RUN_TIMEOUT_MS,
  });
  return { status: done.status, output: `${done.stdout}${done.stderr}` };
}

describe("related", () => {
  it(
    "runs only the test files that import a changed file, and exits 1 when one fails",
    async () => {
      const { status, output } = await run("related", ["src/half.mjs"]);

      expect(output).toContain("half.test.mjs");
      expect(output).not.toContain("sum.test.mjs");
      expect(status).toBe(1);
    },
    RUN_TIMEOUT_MS,
  );

  it(
    "exits 0 when the tests a changed file reaches pass",
    async () => {
      const { status, output } = await run("related", ["src/sum.mjs"]);

      expect(output).toContain("sum.test.mjs");
      expect(output).not.toContain("half.test.mjs");
      expect(status).toBe(0);
    },
    RUN_TIMEOUT_MS,
  );

  it(
    "exits 0 and runs no test file when no test reaches the changed files",
    async () => {
      const { status, output } = await run("related", ["src/alone.mjs"]);

      expect(output).not.toContain(".test.mjs");
      expect(status).toBe(0);
    },
    RUN_TIMEOUT_MS,
  );
});

describe("lint", () => {
  it(
    "reports the ESLint and Prettier problems of the changed files and exits 1",
    async () => {
      const { status, output } = await run("lint", ["src/unused.mjs", "src/messy.mjs"]);

      expect(output).toContain("no-unused-vars");
      expect(output).toContain("src/messy.mjs");
      expect(status).toBe(1);
    },
    RUN_TIMEOUT_MS,
  );

  it(
    "exits 0 when the changed files are clean, and skips one that was deleted",
    async () => {
      const { status, output } = await run("lint", ["src/sum.mjs", "src/gone.mjs"]);

      expect(output).not.toContain("gone.mjs");
      expect(status).toBe(0);
    },
    RUN_TIMEOUT_MS,
  );
});

it(
  "exits 2 with its usage when the mode is unknown",
  async () => {
    const { status, output } = await run("other", ["src/sum.mjs"]);

    expect(output).toContain("usage:");
    expect(status).toBe(2);
  },
  RUN_TIMEOUT_MS,
);

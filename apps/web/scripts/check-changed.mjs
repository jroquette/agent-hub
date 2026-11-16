// The web steps `make check-changed` runs for a change it can narrow (scripts/check_changed.py):
//   node scripts/check-changed.mjs lint <list>     ESLint (no warning allowed) and the Prettier
//                                                  check, on the changed files that still exist
//   node scripts/check-changed.mjs related <list>  the Vitest files that import a changed file,
//                                                  directly or not, without coverage
// <list> holds the changed files, one a line, relative to the folder this runs in (the web app,
// through npm run): a path is never a command-line argument. Vitest's own rule applies to
// `related`: a change to its config, to package.json or to a setup file runs every test file.
// Exits 1 when a check or a test fails, 2 on a usage error.
import { existsSync, readFileSync } from "node:fs";
import { relative } from "node:path";
import process from "node:process";

const USAGE = "usage: node scripts/check-changed.mjs lint|related <file listing the changed files>";

function changedFiles(list) {
  return readFileSync(list, "utf8")
    .split("\n")
    .filter((line) => line !== "");
}

async function lint(files) {
  const present = files.filter((file) => existsSync(file));
  if (present.length === 0) {
    return 0;
  }
  const { ESLint } = await import("eslint");
  const eslint = new ESLint({ warnIgnored: false });
  const results = await eslint.lintFiles(present);
  const report = await (await eslint.loadFormatter("stylish")).format(results);
  if (report) {
    process.stdout.write(report);
  }
  const problems = results.reduce(
    (sum, result) => sum + result.errorCount + result.warningCount,
    0,
  );
  const unformatted = await unformattedFiles(present);
  for (const file of unformatted) {
    console.log(`[warn] ${file}`);
  }
  if (unformatted.length > 0) {
    console.log("[warn] Code style issues found in the above file(s). Run Prettier with --write.");
  }
  return problems === 0 && unformatted.length === 0 ? 0 : 1;
}

// As `prettier --check` reads them: its ignore files, the file's config and .editorconfig.
async function unformattedFiles(files) {
  const prettier = await import("prettier");
  const unformatted = [];
  for (const file of files) {
    const info = await prettier.getFileInfo(file, {
      ignorePath: [".gitignore", ".prettierignore"],
    });
    if (info.ignored || info.inferredParser === null) {
      continue;
    }
    const options = await prettier.resolveConfig(file, { editorconfig: true });
    const source = readFileSync(file, "utf8");
    if (!(await prettier.check(source, { ...options, filepath: file }))) {
      unformatted.push(file);
    }
  }
  return unformatted;
}

// As `vitest related --run` does, then the test files it ran; no test file reached is a pass.
async function related(files) {
  const { startVitest } = await import("vitest/node");
  const ran = [];
  const listing = {
    onTestRunEnd(testModules) {
      ran.push(...testModules.map((testModule) => relative(process.cwd(), testModule.moduleId)));
    },
  };
  const vitest = await startVitest([], {
    run: true,
    watch: false,
    related: files,
    passWithNoTests: true,
    reporters: ["default", listing],
  });
  if (!vitest.shouldKeepServer()) {
    await vitest.exit();
  }
  console.log(`test:related: ${ran.length} test file(s) import the changed files`);
  for (const file of ran.sort()) {
    console.log(`  ${file}`);
  }
  return process.exitCode ?? 0;
}

const MODES = { lint, related };
const [mode, list, ...rest] = process.argv.slice(2);
if (!Object.hasOwn(MODES, mode ?? "") || list === undefined || rest.length > 0) {
  console.error(USAGE);
  process.exit(2);
}
process.exitCode = await MODES[mode](changedFiles(list));

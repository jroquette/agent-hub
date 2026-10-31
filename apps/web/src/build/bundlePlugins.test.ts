// @vitest-environment node
import { mkdir, mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { compressPlugin } from "./bundlePlugins";

let outDir: string;

beforeEach(async () => {
  outDir = await mkdtemp(join(tmpdir(), "ah-plugin-"));
  await mkdir(join(outDir, "assets"));
});

afterEach(async () => {
  await rm(outDir, { recursive: true, force: true });
});

// `this.error` as the bundler gives it to a plugin: it throws, which stops the build.
function errorSpy() {
  return vi.fn((message: string): never => {
    throw new Error(message);
  });
}

// Runs the plugin's writeBundle hook as Vite does once a build is on disk, in output folder `dir`.
async function writeBundle(dir: string | undefined, error: ReturnType<typeof errorSpy>) {
  const hook = compressPlugin().writeBundle;
  if (typeof hook !== "function") throw new Error("the plugin has no writeBundle function");
  const context = { error } as unknown as ThisParameterType<typeof hook>;
  const options = { dir } as unknown as Parameters<typeof hook>[0];
  await hook.call(context, options, {});
}

describe("compressPlugin", () => {
  it("writes the Brotli variants into the output folder Vite names", async () => {
    await writeFile(join(outDir, "assets", "app-AbCd1234.js"), "const answer = 42;\n".repeat(100));
    const error = errorSpy();

    await writeBundle(outDir, error);

    expect((await readdir(join(outDir, "assets"))).sort()).toEqual([
      "app-AbCd1234.js",
      "app-AbCd1234.js.br",
    ]);
    expect(error).not.toHaveBeenCalled();
  });

  it("stops the build with this.error when Vite names no output folder", async () => {
    const error = errorSpy();

    await expect(writeBundle(undefined, error)).rejects.toThrow("no output folder");

    expect(error).toHaveBeenCalledOnce();
  });
});

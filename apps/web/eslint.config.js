// @ts-check
import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "dist/",
      "coverage/",
      "node_modules/",
      "test-results/",
      "playwright-report/",
      "src/api/schema.d.ts",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    ...jsxA11y.flatConfigs.strict,
  },
  reactHooks.configs.flat["recommended-latest"],
  {
    // AGH-201 marks Session.agent, LiveTile.agent and Learning.target deprecated in the API (they
    // stay served). The screens move to label, actors and note_path in their own changes, which
    // then drop this allowance.
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-deprecated": [
        "error",
        { allow: [{ from: "file", name: ["agent", "target"], path: "src/api/schema.d.ts" }] },
      ],
    },
  },
  {
    // Fixtures come from src/testing/builders.ts, never from JSON files (AC-200.64).
    files: ["src/**/*.test.{ts,tsx}", "e2e/**/*.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            { group: ["*.json"], message: "Build fixtures with src/testing/builders.ts." },
          ],
        },
      ],
    },
  },
  {
    files: ["**/*.{js,mjs}"],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: {
      parserOptions: { projectService: false },
      globals: { process: "readonly", console: "readonly", URL: "readonly" },
    },
  },
);

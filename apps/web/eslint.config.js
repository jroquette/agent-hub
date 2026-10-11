// @ts-check
import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "coverage/", "node_modules/", "src/api/schema.d.ts"] },
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

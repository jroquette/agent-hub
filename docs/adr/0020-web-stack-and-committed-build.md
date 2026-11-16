# 0020. Web stack, generated client and the committed production build

- Status: accepted
- Date: 2026-10-11
- Deciders: José Henrique Roquette (delegated to the lead for AGH-200)

## Context and Problem Statement

`apps/web` must implement the approved design (React 18), use a client generated from the committed OpenAPI, and be
served by `hub web` from a `uvx` install that has no Node.

## Considered Options

1. Build in CI and publish an artifact; `hub web` downloads it.
2. Commit the production build into the `api` package (`agent_hub/api/web_dist/`), checked for drift.
3. Require Node at install time.

## Decision Outcome

Option 2, with: Node 22 (`apps/web/.node-version` = `22`, `engines.node` `>=22.12`; the machines that build it have
Node 22, so every pin is a release that supports it), npm + `package-lock.json`, exact pins; Vite 8,
React 18.3.1, TypeScript 5.9.3 (typescript-eslint and openapi-typescript do not support 6+), React Router 7.18.4
(8.x needs React 19), TanStack Query 5.104.0 and Virtual 3.14.13, `openapi-typescript` 7.13.0 + `openapi-fetch` 0.17.0,
ESLint 9.39.5 (jsx-a11y supports up to 9), Prettier 3.9.9, Vitest 5.0.2 + Testing Library + axe-core 4.13.0,
Playwright 1.63.0 (Chromium) for the smoke, launched with a Chromium found on the machine when its own download is
missing (the smoke never downloads a browser). Tokens CSS is generated from the design's `tokens.json`; Geist fonts
(`@fontsource`) and the Lucide 1.47.0 icon subset are bundled; no CDN. `make openapi` regenerates
`packages/api/openapi.json` (from the app) and `apps/web/src/api/schema.d.ts`; `check-fast` fails on drift.
`make check` rebuilds the app into a temp dir and compares it byte for byte with `web_dist/`.

### Consequences

- Good: `uvx` installs serve the app; contract drift fails fast; no external request from the browser.
- Bad: build diffs in PRs; reproducibility depends on the pinned Node and lockfile; `check-fast` needs Node 22.
- The bundle may name only an exact list of inert absolute URLs (React's and React Router's error-text doc links, XML
  namespace ids, `http://localhost` as a parsing base); the smoke fails on any request to another host.

## More Information

Control-plane feature spec (AGH-200) D19, D26, AC-200.30, 56, 61, 62; [TESTING.md](../TESTING.md).

# Security policy

agent-hub is experimental (0.x). It runs on your machine, steers Claude Code sessions through hooks and a guard, and
serves its control plane on loopback only. A flaw in any of those can reach real repos and credentials, so please
report it privately.

## Supported versions

Only the latest release (the newest `vX.Y.Z` tag) gets security fixes. A hub pins its release in `hub.json` →
`platform.version`; upgrade by bumping it and running `./hub sync`.

## Reporting a vulnerability

Do not open a public issue. Use GitHub's private vulnerability reporting: the repository's **Security** tab →
**Report a vulnerability**. Include the version, what you ran, what happened and, if you can, a minimal reproduction.

You get an acknowledgement within 7 days. A confirmed issue is fixed in a patch release, and the advisory credits you
unless you ask otherwise.

## In scope

- The `hub` CLI and the files it generates: shims, `.claude/settings.json`, the hooks (`guard.py`, `stop_gate.py`,
  `event_sensor.py`, …) and the `hub-workflow` plugin.
- A way around the guard or the sandbox settings a hub enables, beyond the limits the spec already documents
  ([docs/SPEC.md](docs/SPEC.md)).
- The control plane (`hub web`, the API and the web app) and the container image.
- Redaction: a secret, prompt or tool output that reaches the event store despite
  [ADR 0019](docs/adr/0019-metadata-only-events-and-redaction.md).
- Credential handling in `hub run`, `hub ship` and `hub start` (`LINEAR_API_KEY`, `GH_TOKEN`).

## Out of scope

- Claude Code, the model provider, Linear, GitHub and `uv` themselves: report those to their vendors.
- What an agent does with the permissions you granted it outside the guard's rules.

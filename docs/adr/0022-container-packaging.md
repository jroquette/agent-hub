# 0022. Container packaging of the control plane, and the bind rule

- Status: accepted
- Date: 2026-10-11
- Deciders: José Henrique Roquette (owner request of 2026-10-11 for AGH-200, Wave 4)

## Context and Problem Statement

The owner asked for commands that bring the whole system up, including a Docker setup. `hub web` binds `127.0.0.1`
with no host option ([ADR 0017](0017-api-second-composition-root.md), spec D25): the server has no authentication, so
anything that can reach the port can read every session's metadata. A process in a container that binds its own
loopback cannot be reached through a published port, so the container must bind another address. How is the control
plane packaged, and how does the bind stay safe?

## Considered Options

1. No image: `make run` (`uv run hub web`) only.
2. An image whose server binds `0.0.0.0` through a `--host` option that is refused outside the container, published
   by Compose on the host's `127.0.0.1` only.
3. An image that runs `hub web` on loopback with host networking (`network_mode: host`).
4. An image with a reverse proxy in front of a loopback `hub web`.

## Decision Outcome

Option 2.

- **Bind rule.** `hub web --host ADDR` takes a loopback address (or `localhost`) anywhere. Any other address exits 2
  with `binding outside loopback needs AGENT_HUB_IN_CONTAINER=1` unless that variable is exactly `1`; only the image
  sets it. The Host and Origin checks of D25 do not change: they still accept only the loopback names at the server's
  port, plus the exact `host[:port]` names of `AGENT_HUB_ALLOWED_HOSTS` (a comma list; `*` and any other wildcard,
  URL or path are refused, exit 2). Compose sets that variable to `127.0.0.1` and `localhost` at the published port,
  which may differ from the container's 7420. The startup line stays `agent-hub at http://127.0.0.1:<port>`, followed
  by `listening on <address>:<port>` when the bound address is another one.
- **Image (`Dockerfile`).** Multi-stage: `node:22-slim` runs `npm ci` and `vite build` (the web app the image serves
  is built from the lockfile and equals the committed `web_dist`, tested); `python:3.14-slim` installs uv 0.12.19
  (the CI release, from PyPI with its wheels' hashes) and runs `uv sync --locked --no-dev --no-editable --package
  agent-hub` into `/opt/venv`; the runtime stage holds only the venv and, by default, git (Health lists a hub's files
  with git, as `hub doctor` does; `safe.directory` is `*` because the hubs belong to the host user, and the doctor runs
  git with `core.fsmonitor` off). Base images are pinned by digest. It runs as uid 10001, keeps its data in the `/data`
  volume (`AGENT_HUB_DB=/data/agent-hub.db`, the registry under `/data/config`), has a stdlib `HEALTHCHECK` and the
  entry point `hub web --host 0.0.0.0 --port 7420`. Builds behind a TLS-intercepting proxy pass its CA as the
  optional `build_ca` secret, which never reaches a layer.
- **Service (`compose.yaml`).** Published as `127.0.0.1:${AGENT_HUB_PORT:-7420}:7420`; `read_only: true` with a
  `/tmp` tmpfs, `cap_drop: [ALL]`, `no-new-privileges`, `user: 10001:10001`, the health check, `restart:
  unless-stopped`. The hubs root (`AGENT_HUB_HUBS_ROOT`, required; `make up` defaults it to the folder that holds the
  repo) and Claude Code's transcripts folder are mounted read-only at their host paths, so registered hub paths and
  the transcript paths the hooks send mean the same in the container; `AGENT_HUB_CLAUDE_PROJECTS` points the tail
  there. No secret is in the image or the Compose file: the control plane needs none.
- **Commands.** `make run`, `make up`/`down`/`logs`/`ps`, `make dev` (API plus the Vite dev server, whose `/api`
  proxy sends the API's own Host and drops Origin, so the server needs no dev exception), `make demo` (synthetic data
  only) and `make connect HUB=<path>`. `make test-docker` (marker `docker`, its own CI job, not in `make check`) builds
  the image and checks the service from the host: the API and app on loopback, a hook event read back, a hub
  registered by its host path, uid 10001, a read-only root and the refused bind without the variable.

### Consequences

- Good: one command starts the control plane without a local Python or Node; the host still sees it on loopback
  only; the container cannot write outside `/data` and `/tmp` and holds no capability.
- Good: the bind rule is enforced in `hub web` itself, so a mistaken `--host 0.0.0.0` on a laptop fails loudly
  instead of exposing the API to the network.
- Bad: inside Docker's network, other containers on the same bridge network could reach port 7420 (Host checks still
  apply; there is no authentication). The Compose project uses its own network, and nothing else should join it.
- Bad: the container reads transcripts as uid 10001; on Linux `~/.claude/projects` is usually 0700, so live token and
  cost figures need a read grant (documented in `.env.example`); hook events arrive either way.
- Bad: a registered hub must sit under the mounted hubs root, and paths must not depend on host symlinks the
  container cannot see.
- Option 3 was rejected: host networking is Linux-only and would expose the server on every host interface under the
  same flag. Option 4 adds a second process and configuration for what Compose's loopback publish already gives.

## More Information

[ADR 0017](0017-api-second-composition-root.md) (local-only server), [ADR 0020](0020-web-stack-and-committed-build.md)
(committed web build), [ADR 0021](0021-hook-event-sensor.md) (hook sensor, `AGENT_HUB_WEB_URL`);
[USING.md](../USING.md) "Run the control plane"; [ARCHITECTURE.md](../ARCHITECTURE.md) "Deployment".

# Control plane: `hub web`

The control plane is `hub web`: a REST API and a web app that show your hubs' live sessions, workflow runs, approvals,
features and health as they happen. It listens on `127.0.0.1` only (port 7420) and stores metadata only: never
prompts, outputs or file contents. The commands below run from a clone of this repo.

**In Docker (three commands).** The image runs as a non-root user on a read-only file system, and the port is
published on the host's loopback only. The folder that holds this clone (your workspace with the hubs) is mounted
read-only; set `AGENT_HUB_HUBS_ROOT` to use another one (see `.env.example`).

```bash
make up                              # build and start; prints http://127.0.0.1:7420
make connect HUB=../my-project-hub   # register a hub and check that it sends events
make down                            # stop (the data volume is kept); make logs, make ps
```

**Locally (one command).** No Docker; the database is `~/.local/share/agent-hub/agent-hub.db` unless `AGENT_HUB_DB`
says otherwise.

```bash
make run                             # the same as uv run hub web
```

**See it with sample data.** With the app running (either way), `make demo` loads a synthetic demo hub, a live session
with a guard denial, a session waiting on a guard ask, a failed run, an ended session with its cost, an ended
chat driven from the app, and two scenarios with their actions and three scenario runs (passed, failed, running), so
every screen has content. It never reads your real transcripts.

**Work on the web app.** `make dev` starts the API on 7420 and the Vite dev server with hot reload on
`http://127.0.0.1:5173`, which forwards `/api` to the API; Ctrl C stops both.

A hub sends events once its release has the sensor (`plugin/hub-workflow/hooks/event_sensor.py`, from 0.9.0): move
`platform.version` in its `hub.json` and run `./hub sync`. `make connect` tells you when a hub needs it. The design
and its safety rules: [ADR 0022](adr/0022-container-packaging.md); the guide for other projects:
[docs/USING.md](USING.md).

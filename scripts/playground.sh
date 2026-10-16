#!/usr/bin/env bash
# `make playground`: the live playground, from nothing to the browser open on it. Safe to run again.
#
#   http://127.0.0.1:5173  the only address you use: this checkout's web app, hot reload
#   7420  conductor: a copy of this checkout taken at each start; runs the Claude sessions, so a
#         change to the code never ends one (no UI to open: the playground signs you in)
#   7421  this checkout's API, restarted on each Python change (make live)
#
# A hub for agent-hub itself makes this checkout a session folder, so a shake opens Claude in it.
set -euo pipefail

AH="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$(dirname "$AH")"
AHH="$WORKSPACE/agent-hub-hub"
CONDUCTOR="$AH/.claude/worktrees/conductor"
LOGS="${TMPDIR:-/tmp}"
step() { printf '\n== %s\n' "$*"; }
up() { curl -s -o /dev/null --max-time 2 "$1"; }
wait_for() {
  for _ in $(seq 1 150); do up "$1" && return 0; sleep 2; done
  echo "no answer from $1" >&2
  return 1
}

step "stop the old servers"
pkill -f "[h]ub web" || true
pkill -f "[n]ode_modules/.bin/vite" || true
pkill -f "[s]cripts.live_api" || true
pkill -f "[a]gent_hub.cli web" || true
sleep 2

step "a hub for agent-hub (once)"
if [ ! -f "$AHH/hub.json" ]; then
  mkdir -p "$AHH"
  git -C "$AHH" init -q -b main
  (cd "$AHH" && uv run --project "$AH" --locked --all-packages hub init agent-hub \
    --repos jroquette/agent-hub --tracker linear:AGH --branch-prefix roquettejh/ \
    --author-name "José Henrique Roquette" --author-email roquettejh@gmail.com \
    --hub-repo jroquette/agent-hub-hub)
fi

step "conductor on 7420"
if [ ! -d "$CONDUCTOR" ]; then
  git -C "$AH" worktree add --detach "$CONDUCTOR" HEAD
else
  git -C "$CONDUCTOR" checkout -q --detach "$(git -C "$AH" rev-parse HEAD)"
fi
git -C "$CONDUCTOR" log --oneline -1
(cd "$CONDUCTOR" && nohup uv run --locked --all-packages hub web --port 7420 \
  > "$LOGS/agent-hub-conductor.log" 2>&1 &)
wait_for http://127.0.0.1:7420/

step "register the hubs"
for hub in "$AHH" "$WORKSPACE"/*-hub; do
  [ -f "$hub/hub.json" ] || continue
  for attempt in 1 2 3 4 5 6; do
    make -s -C "$AH" connect HUB="$hub" && break
    [ "$attempt" = 6 ] && exit 1
    sleep 5
  done
done

step "playground (make live)"
if [ -s "$HOME/.nvm/nvm.sh" ]; then
  # shellcheck disable=SC1091
  . "$HOME/.nvm/nvm.sh"
  nvm install "$(cat "$AH/apps/web/.node-version")" > /dev/null
  nvm use "$(cat "$AH/apps/web/.node-version")" > /dev/null
fi
(cd "$AH" && nohup make live > "$LOGS/agent-hub-live.log" 2>&1 &)
wait_for http://127.0.0.1:7421/
wait_for http://127.0.0.1:5173/

# The playground trades the conductor's token for its session cookie (devProxy.ts), so the one
# address to open signs you in and lands on the playground.
token=$(grep -o 'http://127.0.0.1:7420/?token=[^ "]*' "$LOGS/agent-hub-conductor.log" | tail -1)
url="http://127.0.0.1:5173/__playground/session?token=${token##*token=}"
if command -v open > /dev/null; then open "$url"; fi
cat <<EOF

Playground ready: $url
  (opened in your browser; later visits: http://127.0.0.1:5173/)
Shake the mouse on any screen to talk to Claude: it opens in this checkout and you see its edits live.
Logs: $LOGS/agent-hub-conductor.log  $LOGS/agent-hub-live.log
Stop: make playground-stop
EOF

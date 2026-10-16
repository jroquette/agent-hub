#!/usr/bin/env bash
# `make playground`: the live playground, from nothing to the browser open on it. Safe to run again.
# `scripts/playground.sh stop` (`make playground-stop`) stops its servers.
#
#   http://127.0.0.1:5173  the only address you use: this checkout's web app, hot reload
#   7420  conductor: a copy of this checkout taken at each start; runs the Claude sessions, so a
#         change to the code never ends one (no UI to open: the playground signs you in)
#   7421  this checkout's API, restarted on each Python change (make live)
#
# A hub for agent-hub itself makes this checkout a session folder, so a shake opens Claude in it.
set -euo pipefail
# The conductor's log holds its launch address (token included): nothing here is for other users.
umask 077

AH="$(cd "$(dirname "$0")/.." && pwd -P)"
WORKSPACE="$(dirname "$AH")"
AHH="$WORKSPACE/agent-hub-hub"
CONDUCTOR="$AH/.claude/worktrees/conductor"
LOGS="${TMPDIR:-/tmp}/agent-hub-playground-$(id -u)"
step() { printf '\n== %s\n' "$*"; }
up() { curl -s -o /dev/null --max-time 2 "$1"; }
wait_for() {
  for _ in $(seq 1 150); do up "$1" && return 0; sleep 2; done
  echo "no answer from $1" >&2
  return 1
}

# Only the playground's own servers: the conductor on 7420, the live API on 7421 and this checkout's
# Vite. Any other `hub web` (another hub's, `make run`) keeps running.
stop_servers() {
  pkill -f "[h]ub web --port 7420" || true
  pkill -f "[s]cripts.live_api" || true
  pkill -f "[a]gent_hub.cli web --port 7421" || true
  pkill -f "$AH/apps/web/node_modules/[.]bin/vite" || true
}

if [ "${1:-}" = "stop" ]; then
  stop_servers
  exit 0
fi

step "stop the old servers"
stop_servers
sleep 2

# A private folder for the logs, refused when someone else owns it or can read it.
mkdir -p "$LOGS"
if [ -L "$LOGS" ] || [ ! -O "$LOGS" ]; then
  echo "$LOGS is not yours: remove it, or set TMPDIR" >&2
  exit 1
fi
chmod 700 "$LOGS"

step "a hub for agent-hub (once)"
if [ ! -f "$AHH/hub.json" ]; then
  mkdir -p "$AHH"
  git -C "$AHH" init -q -b main
  (cd "$AHH" && uv run --project "$AH" --locked --all-packages hub init agent-hub \
    --repos jroquette/agent-hub --tracker linear:AGH --branch-prefix roquettejh/ \
    --author-name "$(git -C "$AH" config user.name)" --author-email "$(git -C "$AH" config user.email)" \
    --hub-repo jroquette/agent-hub-hub)
fi

step "conductor on 7420"
# A folder there that is not a worktree of its own (an interrupted `worktree add`) would send the
# git commands below up to this checkout, whose uncommitted work `checkout -f` would drop.
if [ -d "$CONDUCTOR" ] && [ "$(git -C "$CONDUCTOR" rev-parse --show-toplevel 2> /dev/null)" != "$CONDUCTOR" ]; then
  git -C "$AH" worktree remove --force "$CONDUCTOR" 2> /dev/null || rm -rf "$CONDUCTOR"
  git -C "$AH" worktree prune
fi
if [ ! -d "$CONDUCTOR" ]; then
  git -C "$AH" worktree add --detach "$CONDUCTOR" HEAD
else
  # The copy is disposable (nothing is ever made in it): drop what the last start copied over,
  # then move it to the checkout's commit. Ignored files (.venv, node_modules) stay.
  git -C "$CONDUCTOR" checkout -q -f --detach "$(git -C "$AH" rev-parse HEAD)"
  git -C "$CONDUCTOR" clean -fdq
fi
# The conductor runs the checkout as it is now, committed or not: copy the uncommitted changes over
# the commit (modified and new files git would track, never .venv or node_modules; a deleted file
# is deleted there too).
changed=0
while IFS= read -r -d '' file; do
  if [ -e "$AH/$file" ]; then
    mkdir -p "$CONDUCTOR/$(dirname "$file")"
    cp -p "$AH/$file" "$CONDUCTOR/$file"
  else
    rm -f "$CONDUCTOR/$file"
  fi
  changed=$((changed + 1))
done < <(cd "$AH" && git ls-files -z --modified --others --exclude-standard)
git -C "$CONDUCTOR" log --oneline -1
echo "plus $changed uncommitted file(s)"
# The playground's sessions are the developer's own: the most the platform allows live at once (16)
# and a day before an idle one closes, instead of 4 sessions and 30 minutes.
(cd "$CONDUCTOR" && AGENT_HUB_SESSIONS_MAX=16 AGENT_HUB_SESSION_IDLE_SECONDS=86400 \
  nohup uv run --locked --all-packages hub web --port 7420 \
  > "$LOGS/agent-hub-conductor.log" 2>&1 &)
wait_for http://127.0.0.1:7420/
wait_for http://127.0.0.1:7420/api/v1/hubs
sleep 2

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
token=$(grep -o 'http://127.0.0.1:7420/?token=[^ "]*' "$LOGS/agent-hub-conductor.log" | tail -1) || {
  echo "no launch address in $LOGS/agent-hub-conductor.log" >&2
  exit 1
}
url="http://127.0.0.1:5173/__playground/session?token=${token##*token=}"
if command -v open > /dev/null; then open "$url"; fi
cat <<EOF

Playground ready: $url
  (opened in your browser; later visits: http://127.0.0.1:5173/)
Shake the mouse on any screen to talk to Claude: it opens in this checkout and you see its edits live.
Logs: $LOGS/agent-hub-conductor.log  $LOGS/agent-hub-live.log
Stop: make playground-stop
EOF

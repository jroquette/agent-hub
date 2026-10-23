"""The example action and scenario ``hub init`` writes (docs/design/scenarios.md § Contract).

They are the project's files from the start: not registry entries, not managed or seeded, so
``hub sync`` never adds them and ``hub.lock`` never lists them (spec AM-6). Init writes each one
only when its path is absent (``file_adapter.write_absent``). Every name is synthetic (``demo-*``)
and the example reaches only the endpoint the project's environment declares; plan mode prints
the URL it would read and reads nothing.

``without_examples`` takes them out of what init's planner sees: an example already there is kept
as it is, so the planner must not refuse it, or the folders above it, as not part of the hub.
"""

from typing import Final

from agent_hub.core.hub_files.plan_init import FileWrite
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, TreeSnapshot

_ACTION: Final = """\
# An example action, written by hub init (docs/design/scenarios.md): change it or delete it.
# It reads one path of a service and changes nothing, so its effect is read.
version: 1
name: demo-get-status
description: Read the HTTP status of one path of a service
effect: read
runtime: python
script: scripts/demo_get_status.py
timeout: 1m
inputs:
  target: {type: service, required: true, description: "A service of repos[].services"}
  path: {type: string, default: /health, description: "The path to read, from /"}
output_format:
  type: object
  required: [status]
  properties:
    status: {type: integer}
"""

_SCRIPT: Final = '''\
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""The example action's script (docs/design/scenarios.md § Actions and the script contract).

It reads one JSON object on stdin:
{"mode": "plan" | "run", "inputs": {"target": ..., "path": ...},
 "endpoint": {"target": {"url": ..., "resource": ...}}}
In plan mode it changes nothing and prints {"summary": "<one line>"}; in run mode it prints
one JSON value that matches the action's output_format: the HTTP status, a redirect's own, or 0
when the service refuses, resets or times out (any other error fails the action).
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# Not up yet: the expect polls again. Any other error is the endpoint's or the path's: it fails.
UNREACHABLE = (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError, TimeoutError)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: its 3xx status is the answer, so no other host is read."""

    def redirect_request(self, *args, **kwargs):
        return None


call = json.load(sys.stdin)
endpoint = urllib.parse.urlsplit(str(call["endpoint"]["target"]["url"]))
path = str(call["inputs"]["path"])
# A path starting with / follows the endpoint's host, so it can never change it; printable
# ASCII alone, so no space, control character or line break reaches the request.
if not path.startswith("/") or not all("!" <= char <= "~" for char in path):
    sys.exit(
        "demo-get-status: path must start with / and hold only printable ASCII"
        f" without spaces: {path!r}"
    )
# The endpoint's user and password, if any, are never sent or printed.
host = endpoint.netloc.rpartition("@")[2]
url = urllib.parse.urlunsplit((endpoint.scheme, host, endpoint.path.rstrip("/") + path, "", ""))
if call["mode"] == "plan":
    print(json.dumps({"summary": f"GET {url}"}))
    sys.exit(0)
urllib.request.install_opener(urllib.request.build_opener(NoRedirect))
try:
    with urllib.request.urlopen(url, timeout=10) as response:
        status = response.status
except urllib.error.HTTPError as error:
    status = error.code
except Exception as error:
    reason = getattr(error, "reason", error)
    if not isinstance(error, UNREACHABLE) and not isinstance(reason, UNREACHABLE):
        sys.exit(f"demo-get-status: GET {url}: {reason}")
    status = 0
print(json.dumps({"status": status}))
'''

_SCENARIO: Final = """\
# An example scenario, written by hub init (docs/design/scenarios.md): change it or delete it.
# Declare an environment and a service with an endpoint in it (hub env add), commit, then:
#   ./hub scenario plan demo-service-up --env <environment> --input service=<service>
version: 1
kind: scenario
name: demo-service-up
revision: 1
description: Wait until a service answers its health check, then read its root path
inputs:
  service: {type: string, required: true}
nodes:
  - id: service-up
    type: expect
    action: demo-get-status
    with: {target: $INPUTS.service}
    every: 10s
    timeout: 2m
    until_when: "$self.output.status == 200"
  - id: read-root
    type: action
    depends_on: [service-up]
    action: demo-get-status
    with: {target: $INPUTS.service, path: /}
"""

EXAMPLE_FILES: Final = (
    FileWrite(path="actions/demo/demo-get-status.yaml", content=_ACTION.encode(), executable=False),
    FileWrite(
        path="actions/demo/scripts/demo_get_status.py", content=_SCRIPT.encode(), executable=False
    ),
    FileWrite(
        path="scenarios/demo/demo-service-up.yaml", content=_SCENARIO.encode(), executable=False
    ),
)


def without_examples(tree: TreeSnapshot) -> TreeSnapshot:
    """``tree`` without the example files it holds as regular files and the real folders above
    them; any other entry at those paths stays, for the planner to refuse."""
    entries = dict(tree.entries)
    for example in EXAMPLE_FILES:
        if isinstance(entries.get(example.path), FileEntry):
            del entries[example.path]
        parts = example.path.split("/")
        for end in range(1, len(parts)):
            folder = "/".join(parts[:end])
            if isinstance(entries.get(folder), FolderEntry):
                del entries[folder]
    return TreeSnapshot(entries=entries, git_present=tree.git_present)

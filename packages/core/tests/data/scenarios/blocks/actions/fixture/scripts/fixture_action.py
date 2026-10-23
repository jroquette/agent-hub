"""The reference scenario's fixture actions: no system is reached.

Plan mode prints a summary. Run mode prints the JSON object in the file the environment variable
FIXTURE_OUTPUT names (a test writes it), else {"ok": true}.
"""

import json
import os
import sys

call = json.load(sys.stdin)
if call["mode"] == "plan":
    print(json.dumps({"summary": f"fixture call with {sorted(call['inputs'])}"}))
    sys.exit(0)
path = os.environ.get("FIXTURE_OUTPUT")
if path:
    with open(path, encoding="utf-8") as file:
        print(json.dumps(json.load(file)))
else:
    print(json.dumps({"ok": True}))

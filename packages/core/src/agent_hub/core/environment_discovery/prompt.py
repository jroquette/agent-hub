"""The first and only prompt of a discovery's read-only session, built by the server.

Its first line is the session's title. It lists the picked repos (folder and absolute path),
the environments to look for, where to look, what never to do, and the JSON block that must
end the final reply (the shape ``proposal.read_proposal`` checks, with a tiny example).
"""

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Final

TITLE: Final = "Find the environments and services of these repos (read-only)"

_EXAMPLE: Final = """```json
{
  "environments": [
    {"name": "staging", "preset": "staging", "description": "Shared test environment",
     "aws_profile": "acme-staging", "env_file": null,
     "evidence": [{"path": "api/serverless.yml", "line": 12}]}
  ],
  "services": [
    {"repo": "api", "name": "orders-api", "kind": "api", "description": "Orders REST API",
     "evidence": [{"path": "api/serverless.yml", "line": 30}],
     "addresses": [
       {"environment": "staging", "address": "https://api.staging.example.com",
        "note": null, "evidence": [{"path": "api/serverless.yml", "line": 41}]},
       {"environment": "local", "address": "http://localhost:3000", "note": "npm run dev",
        "evidence": [{"path": "api/package.json", "line": null}]}
     ]}
  ],
  "missing": [
    {"repo": "api", "name": "orders-table", "kind": "dynamodb",
     "why": "the table name is built at deploy time", "evidence": []}
  ],
  "not_read": [{"path": "api/infra/big.tf", "reason": "too large"}]
}
```"""


def discovery_prompt(
    *,
    workspace: str,
    repos: Sequence[str],
    environments: Sequence[str],
    suggest_environments: bool,
) -> str:
    """The prompt for the picked ``repos`` (folders next to the hub, under ``workspace``)."""
    repo_lines = "\n".join(f"- {repo}: {PurePosixPath(workspace, repo)}" for repo in repos)
    if environments:
        wanted = ", ".join(environments)
        env_line = f"Look for these environments only: {wanted}."
    else:
        env_line = "No environment was picked."
    if suggest_environments:
        env_line += " You may also propose other environments you find (a new name each)."
    else:
        env_line += " Do not propose any other environment."
    return f"""{TITLE}

You are reading these repos read-only. You can only read files (Read, Grep, Glob); never try to
change anything or run a command.

{repo_lines}

{env_line}

Find the services each repo runs (APIs, frontends, databases and tables, queues and topics,
buckets, functions and jobs) and each one's address in each environment: a URL, or a resource
name such as a table, queue or function name. Look in serverless.yml, CDK stacks, template.yaml
(SAM), docker-compose files, Terraform, package.json scripts and .env.example (variable names
only).

Rules:
- Never open .env files or any other file that holds secrets.
- Never write a secret value (a key, token or password) anywhere in your reply.
- Paths are relative to {workspace}, starting with the repo folder (api/serverless.yml).
- For each environment pick a preset: local (this machine), staging (a shared test
  environment), production (real customers), mine (a personal sandbox) or other.
- List what you saw but could not place under "missing", and files you could not read under
  "not_read".

End your final reply with exactly one ```json block in this shape (null where unknown):

{_EXAMPLE}
"""

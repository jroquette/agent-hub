"""Claude Code session adapter: the ``SessionDriver`` port over the user's own ``claude`` CLI.

ADR 0027: ``hub web`` drives the installed, unmodified Claude Code; this package is its only user
of the Claude Agent SDK.
"""

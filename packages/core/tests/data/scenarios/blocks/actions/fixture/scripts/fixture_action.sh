# The reference scenario's fixture actions: no system is reached.
# Plan mode prints a summary. Run mode prints the JSON in the file FIXTURE_OUTPUT names (a test
# writes it), else {"ok": true}.
call=$(cat)
case $call in
  *'"mode": "plan"'* | *'"mode":"plan"'*) printf '{"summary": "fixture call"}\n' ;;
  *) if [ -n "${FIXTURE_OUTPUT:-}" ]; then cat "$FIXTURE_OUTPUT"; else printf '{"ok": true}\n'; fi ;;
esac

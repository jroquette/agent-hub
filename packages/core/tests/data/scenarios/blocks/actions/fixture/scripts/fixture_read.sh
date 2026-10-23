# The reference scenario's read action (order-state), as a fixture: no system is reached.
# Plan mode prints a summary; run mode prints the JSON object in the file FIXTURE_ORDER_STATE names (a
# test writes it, and may change it between polls), else {}.
call=$(cat)
case $call in
  *'"mode": "plan"'* | *'"mode":"plan"'*) printf '{"summary": "fixture read"}\n' ;;
  *) if [ -n "${FIXTURE_ORDER_STATE:-}" ]; then cat "$FIXTURE_ORDER_STATE"; else printf '{}\n'; fi ;;
esac

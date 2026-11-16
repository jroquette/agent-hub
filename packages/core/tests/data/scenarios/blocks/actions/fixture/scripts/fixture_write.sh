# The reference scenario's write actions, as fixtures: no system is reached.
# Plan mode prints a summary; run mode prints {"ok": true}.
call=$(cat)
case $call in
  *'"mode": "plan"'* | *'"mode":"plan"'*) printf '{"summary": "fixture write"}\n' ;;
  *) printf '{"ok": true}\n' ;;
esac

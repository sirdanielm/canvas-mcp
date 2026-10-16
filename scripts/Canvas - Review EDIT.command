#!/bin/zsh
# Fresh Canvas reads and private score review only; no publisher registration.
set -u
# Resolve the checked-out script even when launched through a Desktop symlink.
repo="${0:A:h:h}"
export PYTHON_DOTENV_DISABLED=1
if [[ ! -x "$repo/.venv/bin/python" || ! -f "$repo/scripts/sdm_gradebook_desktop.py" ]]; then
  print -r -- 'The Canvas gradebook installation is unavailable. Ask Codex to repair the installed path.'
  [[ -t 0 ]] && read -r '?Press Return to close.'
  exit 2
fi
"$repo/.venv/bin/python" "$repo/scripts/sdm_gradebook_desktop.py" review "$@"
result=$?
[[ -t 0 ]] && read -r '?Press Return to close.'
exit "$result"

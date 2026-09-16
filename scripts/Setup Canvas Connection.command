#!/bin/zsh
set -u
script_dir="${0:A:h}"
"$script_dir/../.venv/bin/python" "$script_dir/sdm_canvas_launcher.py" --setup
setup_exit=$?
printf '\nPress Return to close this setup window.'
read -r
exit "$setup_exit"

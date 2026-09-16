#!/bin/zsh
set -eu
script_dir="${0:A:h}"
"$script_dir/../.venv/bin/python" "$script_dir/sdm_canvas_launcher.py" --setup
printf '\nPress Return to close this setup window.'
read -r

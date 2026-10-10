#!/bin/sh
# Linux: run ./seahorse.sh (or double-click) to open Seahorse.
cd "$(dirname "$0")"
exec python3 seahorse_app.py "$@"

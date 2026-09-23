#!/usr/bin/env bash
# Serve the example app, record demo/record.py against it, stop the server.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
"$here/../serve" --port 8901 > /dev/null 2>&1 &
server=$!
trap 'kill $server' EXIT
for _ in $(seq 50); do curl -sf http://127.0.0.1:8901/ > /dev/null && break; sleep 0.1; done
uv run -q "$here/record.py"

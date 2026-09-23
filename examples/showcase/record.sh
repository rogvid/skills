#!/usr/bin/env bash
# Record the README's showcase: the ticket-queue web app, then its CLI, joined
# into showcase.mp4. Narrated when ELEVENLABS_API_KEY is set (the repo's .env).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../.."
if [ -f "$root/.env" ]; then set -a; . "$root/.env"; set +a; fi
"$root/examples/ticket-queue/serve" --port 8901 > /dev/null 2>&1 &
server=$!
trap 'kill $server' EXIT
for _ in $(seq 50); do curl -sf http://127.0.0.1:8901/ > /dev/null && break; sleep 0.1; done
uv run -q "$here/web.py"
uv run -q "$here/terminal.py"
printf "file '%s'\n" "$here/web/demo.mp4" "$here/terminal/demo.mp4" > "$here/parts.txt"
ffmpeg -v error -y -f concat -safe 0 -i "$here/parts.txt" -c copy -movflags +faststart "$here/showcase.mp4"
rm "$here/parts.txt"
echo "showcase: $here/showcase.mp4"

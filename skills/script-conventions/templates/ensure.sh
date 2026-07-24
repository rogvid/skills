#!/usr/bin/env bash
# ensure.sh — make this skill's scripts runnable.
#
# Idempotent and cheap to re-run: exits in ~50ms once everything is in place.
# Copy this file verbatim into any skill that ships scripts; it needs no
# per-skill edits. Unix only (Linux/macOS).
#
#   bash /path/to/<skill>/ensure.sh
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="$(basename "$DIR")"

log() { printf '%s/ensure.sh: %s\n' "$NAME" "$*" >&2; }
die() {
  log "$*"
  exit 1
}

# ---------------------------------------------------------------------------
# 1. Locate uv, installing it if we have to.
#
# Prefer `pip install uv` over the astral.sh installer: sandboxes commonly
# allowlist PyPI and nothing else, and uv ships as a wheel.
# ---------------------------------------------------------------------------
find_uv() {
  command -v uv 2>/dev/null && return 0
  local c
  for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    [[ -x "$c" ]] && {
      printf '%s\n' "$c"
      return 0
    }
  done
  return 1
}

if ! UV="$(find_uv)"; then
  log 'uv not found, installing'
  pip install --quiet --break-system-packages uv >&2 2>/dev/null ||
    pip install --quiet uv >&2 ||
    curl -LsSf https://astral.sh/uv/install.sh | sh >&2 ||
    die 'could not install uv — is PyPI (or astral.sh) reachable from here?'
  UV="$(find_uv)" || die 'uv reported installed but no binary found'
  log "installed uv at $UV"
fi

# ---------------------------------------------------------------------------
# 2. Confirm uv is reachable *via PATH*, not merely present on disk.
#
# The `#!/usr/bin/env -S uv run --script` shebang resolves uv through PATH in
# whatever non-interactive shell the agent spawns. A uv sitting in ~/.local/bin
# that isn't on PATH fails there with a confusing `env: 'uv': No such file or
# directory`, so fail here instead, with the fix in the message.
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  die "uv is installed at $UV but is not on PATH, so the script shebangs will fail. Fix with: export PATH=\"$(dirname "$UV"):\$PATH\""
fi

# ---------------------------------------------------------------------------
# 3. Restore exec bits — they often don't survive packaging/unzipping.
#    Only touch files that actually start with a shebang.
# ---------------------------------------------------------------------------
if [[ -d "$DIR/scripts" ]]; then
  while IFS= read -r f; do
    [[ "$(head -c2 "$f" 2>/dev/null)" == '#!' ]] && chmod +x "$f"
  done < <(find "$DIR/scripts" -maxdepth 1 -type f)
fi

# ---------------------------------------------------------------------------
# 4. Optional: non-Python tooling, if this skill ships a mise.toml.
#    Use `mise exec --` at call time; `mise activate` relies on shell hooks
#    that don't exist in the one-shot non-interactive shells agents use.
# ---------------------------------------------------------------------------
if [[ -f "$DIR/mise.toml" ]]; then
  command -v mise >/dev/null 2>&1 ||
    die 'mise.toml present but mise is not installed — see https://mise.jdx.dev, or the jdx/mise GitHub releases if that domain is blocked'
  (cd "$DIR" && mise install >&2) || die 'mise install failed'
  log "mise tools ready — invoke them as: (cd $DIR && mise exec -- <cmd>)"
fi

log 'ready'

#!/usr/bin/env bash
# Writes frontend/openapi.json from the FastAPI app, in-process: no server needs to be running.
#
# Runs from backend/ with the repository's .venv, the same way the backend is started. Keys are sorted and the output
# is indented, so running it twice on the same backend gives a byte-identical file (and a clean git diff).
# `npm run gen:api` runs this, then openapi-typescript to regenerate src/api/schema.d.ts.
set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$FRONTEND_DIR/.." && pwd)"
PYTHON="$REPO_ROOT/.venv/bin/python"
OUT="$FRONTEND_DIR/openapi.json"

if [ ! -x "$PYTHON" ]; then
  echo "error: $PYTHON not found. Create the backend venv first (see the root CLAUDE.md, Commands)." >&2
  exit 1
fi

# Write to a temp file and only replace openapi.json once the output parses as JSON, so a failed import (or a
# module printing to stdout) never leaves a broken spec behind.
TMP="$(mktemp "${TMPDIR:-/tmp}/openapi.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

cd "$REPO_ROOT/backend"
"$PYTHON" -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))" >"$TMP"
"$PYTHON" -c "import json, sys; json.load(open(sys.argv[1]))" "$TMP"

chmod 0644 "$TMP"
mv "$TMP" "$OUT"
trap - EXIT
echo "wrote $OUT"

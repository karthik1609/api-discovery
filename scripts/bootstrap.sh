#!/usr/bin/env bash
set -euo pipefail

echo "[bootstrap] uv sync (with headless extra)"
uv sync --extra headless

echo "[bootstrap] install Chromium (best-effort)"
if ! uv run playwright install chromium --with-deps; then
  echo "[bootstrap] playwright install failed or skipped; continuing"
fi

echo "[bootstrap] install local package (console entry)"
uv pip install .

echo "[bootstrap] verifying CLI"

uv run api-discovery --help | sed -n '1,40p'

echo "[bootstrap] done"


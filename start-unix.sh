#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if command -v uv >/dev/null 2>&1; then
    exec uv run --python 3.12 --frozen --no-dev python -m app.desktop
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "Install Python and uv, then run this file again."
    exit 1
fi
if ! python3 -m uv --version >/dev/null 2>&1; then
    echo "Install uv with the instructions at docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi
exec python3 -m uv run --python 3.12 --frozen --no-dev python -m app.desktop

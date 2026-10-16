#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UV_PROJECT_ENVIRONMENT="$ROOT/.pythonlibs" uv sync --locked --no-dev

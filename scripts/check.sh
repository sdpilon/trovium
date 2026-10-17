#!/usr/bin/env bash
# trovium quality gate — the single canonical check (constitution XXVI).
# Humans and CI run the same command through uv, so a green local run and a
# green pipeline are the same signal.
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest

#!/usr/bin/env bash
# trovium quality gate — the single canonical check (constitution XXVI).
# Everything the quality gate runs, in one place: humans and CI run the same
# command through uv, so a green local run and a green pipeline are the same
# signal. The verify-quality orchestrator invokes this script directly.
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

# Python: ruff lint, format check, strict mypy, pytest.
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest

# Markdown, file formatting, and shell. The gates orchestrator routes a
# "none" policy through its per-tool walk; with "custom" it runs only this
# command, so the walk lives here — calling the same dispatcher keeps the
# exclude lists single-sourced instead of duplicated (constitution XVIII).
for tool in prettier markdownlint shellcheck; do
    bash .specify/gates/lib/formatter-dispatch.sh --check --tool "$tool" --project-root . || exit 1
done

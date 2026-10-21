#!/usr/bin/env bash
# trovium quality gate — the single canonical check (constitution XXVI).
# Everything the quality gate runs, in one place: humans and CI run the same
# command through uv, so a green local run and a green pipeline are the same
# signal. The verify-quality orchestrator invokes this script directly.
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

# Progress banners keep a long gate legible in CI logs and when the command is
# streamed to a terminal or file. Each phase reports its wall time so a slow
# step is visible while it runs instead of only after the fact.
run_phase() {
    local label="$1"
    shift
    local began=$SECONDS
    printf '\n==> %s\n' "$label"
    "$@"
    printf '<== %s (%ss)\n' "$label" "$((SECONDS - began))"
}

# Python: ruff lint, format check, strict mypy, pytest.
run_phase "ruff lint" uv run ruff check .
run_phase "ruff format" uv run ruff format --check .
run_phase "mypy" uv run mypy .
run_phase "pytest" uv run pytest

# Markdown, file formatting, and shell. The gates orchestrator routes a
# "none" policy through its per-tool walk; with "custom" it runs only this
# command, so the walk lives here — calling the same dispatcher keeps the
# exclude lists single-sourced instead of duplicated (constitution XVIII).
for tool in prettier markdownlint shellcheck; do
    run_phase "$tool" bash .specify/gates/lib/formatter-dispatch.sh --check \
        --tool "$tool" --project-root .
done

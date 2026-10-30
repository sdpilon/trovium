#!/usr/bin/env bash
# trovium quality gate — the single canonical check (constitution XXVI).
# Everything the quality gate runs, in one place: humans and CI run the same
# command through uv, so a green local run and a green pipeline are the same
# signal. The verify-quality orchestrator invokes this script directly.
set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

# Progress log. The pre-commit hook and verify.sh capture a gate's stdout, so a
# successful run would otherwise leave no trace of where the time went. Mirror
# every phase (and the command output of each) to a stable file while still
# printing to stdout. Override with TROVIUM_GATE_LOG; set it to "off" to
# disable. The default lives under TMPDIR so it never lands in the repository.
GATE_LOG="${TROVIUM_GATE_LOG:-${TMPDIR:-/tmp}/trovium-gate.log}"
case "$GATE_LOG" in
    off | 0) GATE_LOG="" ;;
esac
if [ -n "$GATE_LOG" ]; then
    if ! : >"$GATE_LOG" 2>/dev/null; then
        printf 'warning: cannot write gate log %s; continuing without it\n' "$GATE_LOG" >&2
        GATE_LOG=""
    fi
fi

# Progress banners keep a long gate legible in CI logs and when the command is
# streamed to a terminal or the stable log. Each phase reports its wall time so
# a slow step is visible while it runs instead of only after the fact.
say() {
    printf '%s\n' "$*"
    if [ -n "$GATE_LOG" ]; then
        printf '%s\n' "$*" >>"$GATE_LOG"
    fi
}

run_phase() {
    local label="$1"
    shift
    local began=$SECONDS
    say ""
    say "==> $label ($(date -u +%H:%M:%SZ))"
    if [ -n "$GATE_LOG" ]; then
        if ! "$@" 2>&1 | tee -a "$GATE_LOG"; then
            say "<== $label failed after $((SECONDS - began))s"
            return 1
        fi
    elif ! "$@"; then
        say "<== $label failed after $((SECONDS - began))s"
        return 1
    fi
    say "<== $label ($((SECONDS - began))s)"
}

GATE_STARTED=$SECONDS
say "gate log: ${GATE_LOG:-disabled}"

# Python: ruff lint, format check, strict mypy, pytest.
run_phase "ruff lint" uv run ruff check .
run_phase "ruff format" uv run ruff format --check .
run_phase "mypy" uv run mypy .
run_phase "pytest" env PYTHONUNBUFFERED=1 uv run pytest

# Markdown, file formatting, and shell. The gates runtime's built-in walk is
# the stable entry point for the policy-enabled tools (spec-gates 0.5.0); it
# keeps the exclude lists single-sourced and reports each tool on its own line
# (constitution XVIII).
run_phase "built-in walk" bash .specify/gates/verify.sh --walk

say ""
say "==> gate passed ($((SECONDS - GATE_STARTED))s)"

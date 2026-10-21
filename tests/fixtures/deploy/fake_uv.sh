#!/usr/bin/env bash
# A deterministic stand-in for the real uv binary.
#
# Unit tests point TROVIUM_* overrides at this script to assert how the deploy
# CLI constructs subprocess arguments without installing anything. Every
# invocation is appended to $TROVIUM_FAKE_UV_LOG (one argv per line, NUL-free).
set -euo pipefail

log="${TROVIUM_FAKE_UV_LOG:-}"

record() {
    if [ -n "$log" ]; then
        printf '%s\n' "$*" >> "$log"
    fi
}

if [ "${1:-}" = "--version" ]; then
    printf 'uv 0.12.19\n'
    exit 0
fi

if [ "${TROVIUM_FAKE_UV_FAIL:-0}" = "1" ]; then
    printf 'fake uv: forced failure\n' >&2
    exit 1
fi

case "${1:-}" in
    tool)
        record "tool ${*:2}"
        exit 0
        ;;
    run)
        record "run ${*:2}"
        exit 0
        ;;
    *)
        record "${*:-}"
        exit 0
        ;;
esac

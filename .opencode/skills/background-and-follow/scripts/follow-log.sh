#!/usr/bin/env bash
# Follow a log and exit when REGEX matches, without leaving a tail child.
#
# Usage: follow-log.sh LOG [REGEX]
#
# Prints the completion line, phase transitions (==> / <==), and lines
# containing FAILED or ERROR. Exits 0 on the success REGEX, 1 on a failed
# phase, and 2 on usage errors.
# Unlike `tail -f | awk '... exit'`, this script terminates its own reader
# through a FIFO, so the caller does not hang after the gate finishes.
set -euo pipefail

log="${1:-}"
pattern="${2:-(==> gate (passed|failed)|<== .* failed)}"
if [[ -z "$log" ]]; then
    printf 'usage: %s LOG [REGEX]\n' "${0##*/}" >&2
    exit 2
fi
if [[ ! -r "$log" ]]; then
    printf 'follow-log: cannot read %s\n' "$log" >&2
    exit 2
fi

tmp="$(mktemp -d "${TMPDIR:-/tmp}/trovium-follow.XXXXXX")"
fifo="$tmp/log"
mkfifo "$fifo"
tail -n +1 -f "$log" >"$fifo" &
tail_pid=$!

# shellcheck disable=SC2329  # invoked by the EXIT trap
cleanup() {
    kill "$tail_pid" 2>/dev/null || true
    wait "$tail_pid" 2>/dev/null || true
    rm -rf "$tmp"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

while IFS= read -r line; do
    case "$line" in
        *"<== "*" failed"* | *"==> gate failed"*)
            printf '%s\n' "$line"
            exit 1
            ;;
    esac
    if [[ "$line" =~ $pattern ]]; then
        printf '%s\n' "$line"
        exit 0
    fi
    case "$line" in
        *"==>"* | *"<=="* | *FAILED* | *ERROR*)
            printf '%s\n' "$line"
            ;;
    esac
done <"$fifo"

exit 1

#!/usr/bin/env bash
# Shared harness for the spec conformance `accept` blocks and quickstart runs.
#
# Every helper is safe to use from a caller running under `bash -e`: failures
# are returned, not swallowed, and no global traps are installed. The functions
# drive the shipped `install.sh` and `trovium-deploy` entry points only.

accept_repo_root() {
    cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd
}

accept_platform() {
    local system machine
    system="$(uname -s | tr '[:upper:]' '[:lower:]')"
    machine="$(uname -m)"
    case "$machine" in
        x86_64 | amd64) machine="x86_64" ;;
        aarch64 | arm64) machine="aarch64" ;;
        *)
            printf 'unsupported machine: %s\n' "$machine" >&2
            return 3
            ;;
    esac
    case "$system" in
        linux | darwin) ;;
        *)
            printf 'unsupported system: %s\n' "$system" >&2
            return 3
            ;;
    esac
    printf '%s-%s\n' "$system" "$machine"
}

accept_bundle_cache() {
    printf '%s\n' "${TROVIUM_ACCEPT_CACHE:-${TMPDIR:-/tmp}/trovium-accept-bundles}"
}

# accept_init creates an isolated home, library, source, config, state, data,
# cache, and bin tree, then exports every TROVIUM_* override the deployment
# honours. ACCEPT_* variables name the paths for the block that sourced us.
accept_init() {
    ACCEPT_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/trovium-accept.XXXXXX")"
    ACCEPT_HOME="$ACCEPT_ROOT/home"
    ACCEPT_LIBRARY="$ACCEPT_ROOT/library"
    ACCEPT_SOURCE="$ACCEPT_ROOT/source"
    ACCEPT_CONFIG_DIR="$ACCEPT_ROOT/config"
    ACCEPT_BIN="$ACCEPT_ROOT/bin"
    ACCEPT_STATE="$ACCEPT_ROOT/state"
    ACCEPT_DATA="$ACCEPT_ROOT/data"
    ACCEPT_CACHE="$ACCEPT_ROOT/cache"
    mkdir -p \
        "$ACCEPT_HOME" \
        "$ACCEPT_LIBRARY" \
        "$ACCEPT_SOURCE/Show.S01" \
        "$ACCEPT_CONFIG_DIR" \
        "$ACCEPT_BIN"
    printf 'episode' > "$ACCEPT_SOURCE/Show.S01/Show.S01E01.mkv"
    # A --local/--fast bundle carries no toolchain, so install.sh resolves the
    # host interpreter through uv. Redirect HOME below (for XDG isolation), so
    # keep uv's managed Python directory reachable first.
    if [ -z "${UV_PYTHON_INSTALL_DIR:-}" ]; then
        UV_PYTHON_INSTALL_DIR="$(uv python dir 2>/dev/null || true)"
        if [ -n "$UV_PYTHON_INSTALL_DIR" ]; then
            export UV_PYTHON_INSTALL_DIR
        fi
    fi
    export HOME="$ACCEPT_HOME"
    export TROVIUM_BIN_DIR="$ACCEPT_BIN"
    export TROVIUM_CONFIG_FILE="$ACCEPT_CONFIG_DIR/config.ini"
    export TROVIUM_STATE_HOME="$ACCEPT_STATE"
    export TROVIUM_DATA_HOME="$ACCEPT_DATA"
    export TROVIUM_CACHE_HOME="$ACCEPT_CACHE"
    UV_CACHE_DIR="$(accept_bundle_cache)/uv-cache"
    export UV_CACHE_DIR
    export PATH="$TROVIUM_BIN_DIR:$PATH"
    mkdir -p "$UV_CACHE_DIR"
}

# accept_bundle [version] prints the path of a cached local test bundle. The
# bundle is built once per version and platform with the host toolchain; the
# release bundle's toolchain path is exercised separately by the release
# workflow. Build output goes to stderr so callers can capture stdout.
accept_bundle() {
    local version="${1:-0.1.0}" platform cache build bundle
    platform="$(accept_platform)"
    cache="$(accept_bundle_cache)/$version/$platform"
    build="$cache/build"
    bundle="$cache/trovium-$version-$platform.tar.gz"
    if [ -f "$bundle" ] && [ -f "$bundle.sha256" ]; then
        printf '%s\n' "$bundle"
        return 0
    fi
    rm -rf "$build"
    mkdir -p "$build"
    (
        cd "$(accept_repo_root)" || exit 1
        uv run python tools/release/build_bundle.py \
            --fast --version "$version" --out "$build" >&2
    )
    cp "$build/trovium-$version-$platform.tar.gz" "$bundle"
    cp "$build/trovium-$version-$platform.tar.gz.sha256" "$bundle.sha256"
    rm -rf "$build"
    printf '%s\n' "$bundle"
}

# accept_broken_bundle prints a bundle whose staged self-check fails. It uses a
# version distinct from the upgrade pair (0.2.1 by default) so the install path
# cannot short-circuit as a no-op, and is built for the local platform.
accept_broken_bundle() {
    local version="${TROVIUM_ACCEPT_BROKEN_VERSION:-0.2.1}" good platform cache broken
    good="$(accept_bundle "$version")"
    platform="$(accept_platform)"
    cache="$(accept_bundle_cache)/broken/$version/$platform"
    broken="$cache/broken-bundle.tar.gz"
    if [ -f "$broken" ] && [ -f "$broken.sha256" ]; then
        printf '%s\n' "$broken"
        return 0
    fi
    mkdir -p "$cache"
    (
        cd "$(accept_repo_root)" || exit 1
        uv run python tests/fixtures/deploy/make_broken_bundle.py \
            "$good" "$broken" >&2
    )
    printf '%s\n' "$broken"
}

# accept_inventory prints a stable digest of every file under the library and
# source trees, used to prove deployment never touches media.
accept_inventory() {
    local roots=()
    if [ -d "$ACCEPT_LIBRARY" ]; then
        roots+=("$ACCEPT_LIBRARY")
    fi
    if [ -d "$ACCEPT_SOURCE" ]; then
        roots+=("$ACCEPT_SOURCE")
    fi
    if [ ${#roots[@]} -eq 0 ]; then
        return 0
    fi
    find "${roots[@]}" -type f -exec cksum {} + | sort
}

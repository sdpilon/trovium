#!/usr/bin/env bash
# trovium bootstrap: resolve, verify, extract a release bundle, then hand
# install/status/uninstall to the typed trovium-deploy CLI.
set -Eeuo pipefail

RELEASE_BASE="${TROVIUM_RELEASE_BASE_URL:-https://github.com/sdpilon/trovium/releases}"
MODE="install"
PURGE="0"
VERSION=""
BUNDLE=""
EXPECTED_SHA=""
TMP_DIR=""
BUNDLE_DIR=""
BUNDLE_FILE=""
MODE_ARGS=()
CONFIG_ARGS=0
REPORT_EMITTED=0

usage() {
    cat <<'EOF'
Usage: install.sh [bootstrap-options] [mode-options]

Bootstrap options:
  --version VERSION        Use a specific release version
  --bundle PATH            Use a local .tar.gz bundle
  --sha256 HEX             Expected SHA-256 for a local bundle
  --release-base-url URL   Release base (default: trovium GitHub releases)
  --status                 Report installation state
  --uninstall              Remove the installation
  --purge                  With --uninstall, remove the config too
  -h, --help               Print this help

Mode options: --non-interactive, --library-root PATH, --source PATH,
--client-url URL, --config PATH, --force, --json {compact,pretty}
EOF
}

json_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\n' ' '
}

json_error() {
    local operation="$1" code="$2" message="$3" remedy="$4"
    local escaped_message escaped_remedy stamp
    escaped_message="$(json_escape "$message")"
    escaped_remedy="$(json_escape "$remedy")"
    stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '{"schema_version":1,"operation":"%s","status":"error","version":null,"previous_version":null,"config_path":null,"install_root":null,"bin_dir":null,"commands":[],"actions":[],"checks":[],"next_steps":[],"error":{"code":"%s","message":"%s","remedy":"%s","path":null},"finished_at":"%s"}\n' \
        "$operation" "$code" "$escaped_message" "$escaped_remedy" "$stamp"
}

die() {
    local code="$1" message="$2" remedy="$3" status="${4:-3}"
    REPORT_EMITTED=1
    json_error "$MODE" "$code" "$message" "$remedy"
    printf 'error: %s\nremedy: %s\n' "$message" "$remedy" >&2
    exit "$status"
}

# first_path <dir> <glob> <-f|-d>: print the first match. Never pipes find into
# head: with pipefail that SIGPIPEs a multi-match find and turns a malformed
# bundle into an "internal" abort instead of a named bundle_invalid refusal.
first_path() {
    local dir="$1" pattern="$2" kind="${3:--f}" candidate
    for candidate in "$dir"/$pattern; do
        [ -e "$candidate" ] || continue
        if [ "$kind" = "-d" ]; then
            [ -d "$candidate" ] || continue
            printf '%s\n' "${candidate%/}"
            return 0
        fi
        [ -f "$candidate" ] || continue
        printf '%s\n' "$candidate"
        return 0
    done
    return 1
}

# path_count <dir> <glob> <-f|-d>: count matches. A bundle with more than one
# toolchain artifact or trovium wheel is malformed; refuse it by name instead
# of silently selecting one.
path_count() {
    local dir="$1" pattern="$2" kind="${3:--f}" candidate count=0
    for candidate in "$dir"/$pattern; do
        [ -e "$candidate" ] || continue
        if [ "$kind" = "-d" ]; then
            [ -d "$candidate" ] || continue
        else
            [ -f "$candidate" ] || continue
        fi
        count=$((count + 1))
    done
    printf '%s\n' "$count"
}

# shellcheck disable=SC2317,SC2329  # invoked indirectly by trap
on_unexpected_failure() {
    local status=$?
    if [ "$REPORT_EMITTED" != "1" ]; then
        REPORT_EMITTED=1
        json_error "$MODE" "internal" \
            "installer aborted unexpectedly (exit $status)" \
            "Re-run with --help, check the prerequisites, and report this failure."
    fi
    exit "$status"
}

validate_release_base() {
    case "$RELEASE_BASE" in
        http://*|https://*) ;;
        *)
            die "misuse" "--release-base-url must be an absolute http or https URL" \
                "Pass a URL such as https://github.com/sdpilon/trovium/releases." 2
            ;;
    esac
    case "${RELEASE_BASE#*://}" in
        *@*)
            die "misuse" "--release-base-url must not contain credentials" \
                "Remove the userinfo from the URL before retrying." 2
            ;;
    esac
}

check_current_install() {
    local requested="$1" candidate
    if [ "$CONFIG_ARGS" != "0" ]; then
        return 1
    fi
    candidate="${TROVIUM_BIN_DIR:-$HOME/.local/bin}/trovium-deploy"
    if [ ! -x "$candidate" ]; then
        candidate="$(command -v trovium-deploy || true)"
    fi
    if [ -z "$candidate" ] || [ ! -x "$candidate" ]; then
        return 1
    fi
    if "$candidate" check --version "$requested"; then
        exit 0
    fi
    return 1
}

need_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        die "missing_prerequisite" "required command not found: $1" \
            "Install $1 and retry the installer." 3
    fi
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

verify_sha() {
    local file="$1" expected="$2"
    local actual
    actual="$(sha256_of "$file")"
    if [ "$actual" != "$expected" ]; then
        die "bundle_integrity" "bundle checksum mismatch for $file" \
            "Download the bundle again and verify its .sha256 sidecar." 4
    fi
}

download() {
    local url="$1" destination="$2"
    if command -v curl >/dev/null 2>&1; then
        if ! curl -fsSL "$url" -o "$destination"; then
            die "bundle_download" "could not download $url" \
                "Check network access and the release URL." 4
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -qO "$destination" "$url"; then
            die "bundle_download" "could not download $url" \
                "Check network access and the release URL." 4
        fi
    else
        die "missing_prerequisite" "neither curl nor wget is available" \
            "Install curl or wget and retry the installer." 3
    fi
}

download_text() {
    local url="$1"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$url"
    else
        die "missing_prerequisite" "neither curl nor wget is available" \
            "Install curl or wget and retry the installer." 3
    fi
}

resolve_bundle() {
    local platform="$1"
    local cache sidecar
    if [ -n "$BUNDLE" ]; then
        if [ -d "$BUNDLE" ]; then
            die "bundle_invalid" "install.sh requires a bundle .tar.gz, not a directory" \
                "Pass the release tarball, or use trovium-deploy install --bundle DIR." 4
        fi
        BUNDLE_FILE="$BUNDLE"
        if [ -n "$EXPECTED_SHA" ]; then
            verify_sha "$BUNDLE_FILE" "$EXPECTED_SHA"
        elif [ -f "$BUNDLE_FILE.sha256" ]; then
            verify_sha "$BUNDLE_FILE" "$(awk '{print $1}' "$BUNDLE_FILE.sha256")"
        else
            die "bundle_integrity" "local bundle has no checksum sidecar" \
                "Pass --sha256 HEX or place $BUNDLE_FILE.sha256 next to the bundle." 4
        fi
        return
    fi
    if [ -z "$VERSION" ]; then
        if ! VERSION="$(download_text "$RELEASE_BASE/latest/download/VERSION" | tr -d '[:space:]')"; then
            die "bundle_download" "could not resolve the latest trovium version" \
                "Pass --version explicitly or retry when the release is available." 4
        fi
        if [ -z "$VERSION" ]; then
            die "bundle_download" "could not resolve the latest trovium version" \
                "Pass --version explicitly or retry when the release is available." 4
        fi
    fi
    cache="${TROVIUM_CACHE_HOME:-$HOME/.cache}/trovium/bundles/$VERSION"
    mkdir -p "$cache"
    BUNDLE_FILE="$cache/trovium-$VERSION-$platform.tar.gz"
    sidecar="$BUNDLE_FILE.sha256"
    if [ ! -f "$BUNDLE_FILE" ] || [ ! -f "$sidecar" ]; then
        download "$RELEASE_BASE/download/v$VERSION/trovium-$VERSION-$platform.tar.gz" "$BUNDLE_FILE"
        download "$RELEASE_BASE/download/v$VERSION/trovium-$VERSION-$platform.tar.gz.sha256" "$sidecar"
    fi
    verify_sha "$BUNDLE_FILE" "$(awk '{print $1}' "$sidecar")"
}

extract_bundle() {
    TMP_DIR="$(mktemp -d)"
    if ! tar -xzf "$BUNDLE_FILE" -C "$TMP_DIR"; then
        die "bundle_invalid" "cannot extract bundle: $BUNDLE_FILE" \
            "Download the release bundle again." 4
    fi
    BUNDLE_DIR="$(first_path "$TMP_DIR" '*' -d || true)"
    if [ -z "$BUNDLE_DIR" ] || [ ! -f "$BUNDLE_DIR/manifest.json" ]; then
        die "bundle_invalid" "bundle does not contain a manifest.json" \
            "Download the release bundle again." 4
    fi
}

# shellcheck disable=SC2317,SC2329  # invoked indirectly by trap
cleanup() {
    if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT
# shellcheck disable=SC2317,SC2329  # invoked indirectly by trap
trap on_unexpected_failure ERR

while [ $# -gt 0 ]; do
    case "$1" in
        --version|--bundle|--sha256|--release-base-url)
            if [ $# -lt 2 ] || [ -z "$2" ]; then
                die "misuse" "option $1 needs a value" "Check install.sh --help." 2
            fi
            case "$1" in
                --version) VERSION="$2" ;;
                --bundle) BUNDLE="$2" ;;
                --sha256) EXPECTED_SHA="$2" ;;
                --release-base-url) RELEASE_BASE="$2" ;;
            esac
            shift 2 ;;
        --status) MODE="status"; shift ;;
        --uninstall) MODE="uninstall"; shift ;;
        --purge) PURGE="1"; shift ;;
        -h|--help) usage; exit 0 ;;
        --non-interactive)
            MODE_ARGS+=("$1"); shift ;;
        --force)
            CONFIG_ARGS=1; MODE_ARGS+=("$1"); shift ;;
        --library-root|--source|--client-url|--config)
            CONFIG_ARGS=1
            if [ $# -lt 2 ]; then
                die "misuse" "option $1 needs a value" "Check install.sh --help." 2
            fi
            MODE_ARGS+=("$1" "$2"); shift 2 ;;
        --json)
            if [ $# -lt 2 ]; then
                die "misuse" "option $1 needs a value" "Check install.sh --help." 2
            fi
            MODE_ARGS+=("$1" "$2"); shift 2 ;;
        *)
            die "misuse" "unknown option: $1" "Check install.sh --help." 2 ;;
    esac
done

if [ -n "$BUNDLE" ] && [ -n "$VERSION" ]; then
    die "misuse" "--bundle and --version are mutually exclusive" \
        "Use one or the other." 2
fi
if [ "$PURGE" = "1" ] && [ "$MODE" != "uninstall" ]; then
    die "misuse" "--purge requires --uninstall" "Run install.sh --uninstall --purge." 2
fi
validate_release_base
if [ "$MODE" != "install" ] && [ ${#MODE_ARGS[@]} -gt 0 ]; then
    for arg in "${MODE_ARGS[@]}"; do
        case "$arg" in
            --json|compact|pretty) ;;
            *) die "misuse" "mode option not allowed with --$MODE: $arg" \
                "Use only --json with --status/--uninstall." 2 ;;
        esac
    done
fi

need_command tar
need_command mktemp
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
    die "missing_prerequisite" "no SHA-256 tool found" \
        "Install coreutils or shasum and retry." 3
fi
if [ -z "$BUNDLE" ] && ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    die "missing_prerequisite" "neither curl nor wget is available" \
        "Install curl or wget, or pass a local --bundle, and retry." 3
fi
need_command find
need_command awk

system="$(uname -s | tr '[:upper:]' '[:lower:]')"
machine="$(uname -m)"
case "$machine" in
    x86_64|amd64) arch="x86_64" ;;
    aarch64|arm64) arch="aarch64" ;;
    *) die "unsupported_platform" "unsupported architecture: $machine" \
        "Server deployment supports x86_64 and aarch64." 3 ;;
esac
case "$system" in
    linux|darwin) ;;
    *) die "unsupported_platform" "unsupported operating system: $system" \
        "Server deployment supports Linux and macOS development hosts." 3 ;;
esac
if [ "$system" = "linux" ] && { [ "$(uname -m)" = "aarch64" ] || [ "$(uname -m)" = "x86_64" ]; }; then
    if ls /lib/ld-musl-* >/dev/null 2>&1 && [ "${TROVIUM_ALLOW_MUSL:-0}" != "1" ]; then
        die "unsupported_platform" "musl-based Linux is not verified for deployment" \
            "Use a glibc-based server, or set TROVIUM_ALLOW_MUSL=1 after verification." 3
    fi
fi
platform="$system-$arch"

if [ "$MODE" = "install" ] && [ -z "$BUNDLE" ] && [ "$CONFIG_ARGS" = "0" ]; then
    if [ -z "$VERSION" ]; then
        VERSION="$(download_text "$RELEASE_BASE/latest/download/VERSION" | tr -d '[:space:]' || true)"
    fi
    if [ -n "$VERSION" ]; then
        check_current_install "$VERSION"
    fi
fi

resolve_bundle "$platform"
extract_bundle

uv_path="${TROVIUM_TEST_UV:-}"
python_path="${TROVIUM_TEST_PYTHON:-}"
if [ -z "$uv_path" ] && [ -d "$BUNDLE_DIR/toolchain" ]; then
    if [ "$(path_count "$BUNDLE_DIR/toolchain" 'uv-*' -f)" -gt 1 ]; then
        die "bundle_invalid" "bundle contains multiple uv toolchain files" \
            "Download the release bundle again; the toolchain is duplicated." 4
    fi
    uv_path="$(first_path "$BUNDLE_DIR/toolchain" 'uv-*' -f || true)"
fi
if [ -z "$uv_path" ]; then
    uv_path="$(command -v uv || true)"
fi
if [ -z "$uv_path" ]; then
    die "missing_prerequisite" "no uv toolchain is available" \
        "Download a complete release bundle or install uv." 3
fi
if [ -z "$python_path" ] && [ -d "$BUNDLE_DIR/toolchain" ]; then
    if [ "$(path_count "$BUNDLE_DIR/toolchain" 'python-*.tar.gz' -f)" -gt 1 ]; then
        die "bundle_invalid" "bundle contains multiple Python toolchain files" \
            "Download the release bundle again; the toolchain is duplicated." 4
    fi
    python_path="$(first_path "$BUNDLE_DIR/toolchain" 'python-*.tar.gz' -f || true)"
fi
if [ -z "$python_path" ]; then
    python_path="$(command -v python3.13 || true)"
fi
if [ -z "$python_path" ]; then
    # A --local/--fast bundle carries no toolchain (T101). Prefer a uv-managed
    # CPython over an older system python3: Ubuntu 24.04 ships 3.12, which
    # cannot run the wheel. Without one, the version check below names the cause.
    python_path="$("$uv_path" python find --no-project --managed-python \
        --resolve-links 3.13 2>/dev/null || true)"
fi
if [ -z "$python_path" ]; then
    python_path="$(command -v python3 || true)"
fi
if [ -z "$python_path" ]; then
    die "missing_prerequisite" "no Python toolchain is available" \
        "Download a complete release bundle or install Python 3.13." 3
fi
if [ -f "$python_path" ] && [ "${python_path##*.}" = "gz" ]; then
    python_dir="$TMP_DIR/python"
    mkdir -p "$python_dir"
    tar -xzf "$python_path" -C "$python_dir"
    python_path="$python_dir/bin/python3"
fi
if [ ! -x "$python_path" ]; then
    die "missing_prerequisite" "Python interpreter is not executable: $python_path" \
        "Check the bundle toolchain or install Python 3.13." 3
fi
# The wheel requires Python >=3.13. Refuse an older fallback interpreter here,
# with a cause the operator can act on, instead of letting `uv run` fail later
# with a resolver error that looks like a damaged bundle.
python_minor="$("$python_path" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
case "$python_minor" in
    3.1[3-9] | 3.[2-9][0-9] | [4-9].*) ;;
    *)
        die "missing_prerequisite" \
            "Python 3.13 or newer is required, but ${python_path} reports ${python_minor:-no version}" \
            "Download a complete release bundle or install Python 3.13, then retry." 3
        ;;
esac

if [ "$(path_count "$BUNDLE_DIR/wheelhouse" 'trovium-*.whl' -f)" -gt 1 ]; then
    die "bundle_invalid" "bundle contains multiple trovium wheels" \
        "Download the release bundle again; the wheelhouse is duplicated." 4
fi
wheel="$(first_path "$BUNDLE_DIR/wheelhouse" 'trovium-*.whl' -f || true)"
if [ -z "$wheel" ]; then
    die "bundle_invalid" "bundle contains no trovium wheel" \
        "Download the release bundle again." 4
fi

deploy_args=("$MODE")
if [ "$MODE" = "install" ]; then
    deploy_args+=("--bundle" "$BUNDLE_DIR")
    if [ -z "${TROVIUM_TEST_UV:-}" ] && [ -n "$(first_path "$BUNDLE_DIR/toolchain" 'uv-*' -f || true)" ]; then
        :
    else
        deploy_args+=("--uv" "$uv_path" "--python" "$python_path")
    fi
fi
if [ "$MODE" = "uninstall" ] && [ "$PURGE" = "1" ]; then
    deploy_args+=("--purge")
fi
if [ "${#MODE_ARGS[@]}" -gt 0 ]; then
    deploy_args+=("${MODE_ARGS[@]}")
fi

trap - ERR
set +e
deploy_out="$TMP_DIR/deploy.out"
deploy_err="$TMP_DIR/deploy.err"
"$uv_path" run --no-project --python "$python_path" \
    --no-index --find-links "$BUNDLE_DIR/wheelhouse" \
    --with "$wheel" trovium-deploy "${deploy_args[@]}" \
    >"$deploy_out" 2>"$deploy_err"
status=$?
set -e
trap on_unexpected_failure ERR
cat "$deploy_out"
cat "$deploy_err" >&2
if [ "$status" -ne 0 ] && [ ! -s "$deploy_out" ]; then
    REPORT_EMITTED=1
    cause="$(head -n 1 "$deploy_err" | cut -c1-200)"
    if [ -z "$cause" ]; then
        cause="the bundled deploy CLI could not start (exit $status)"
    fi
    json_error "$MODE" "bundle_invalid" "$cause" \
        "Download the release bundle again and verify its .sha256 sidecar."
    exit 4
fi
exit "$status"

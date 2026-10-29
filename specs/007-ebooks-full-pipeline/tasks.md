# Tasks: Ebooks Through the Full Pipeline

**Feature**: `007-ebooks-full-pipeline` | **Plan**: [plan.md](plan.md) |
**Spec**: [spec.md](spec.md) | **Contracts**:
[config-cli.md](contracts/config-cli.md), [record-schema.md](contracts/record-schema.md)

## Phase 1: Setup

**Purpose**: Record the current behavior before the defaults change.

- [x] T001 Run the targeted suites as the baseline:

  ```sh
  uv run pytest -n 0 \
    tests/unit/test_placement.py tests/unit/test_library.py \
    tests/unit/test_rename.py tests/unit/test_run.py \
    tests/unit/deploy/test_config_install.py \
    tests/contract/test_ingest_config.py \
    tests/integration/test_client_ingest.py \
    tests/integration/test_run_pipeline.py
  ```

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The adaptive mode must exist and resolve before any story uses it.

- [x] T002 [P] Add `AUTO = "auto"` to `Mode` in `src/trovium/record.py`, accept
      it in `src/trovium/config.py` (`IngestSettings.mode` default `AUTO`) and
      `src/trovium/cli.py` (`--mode` choices), and cover the new value in
      `tests/contract/test_ingest_config.py` and
      `tests/contract/test_cli_contract.py`.
- [x] T003 Implement `effective_mode(mode, candidate, destination)` and expose
      the existing filesystem probe in `src/trovium/placement.py`: explicit
      values pass through; `auto` resolves disk and non-seeding sources to
      `move`, and seeding client items to `hardlink` on the same filesystem or
      `copy` otherwise. Wire it into `src/trovium/cli.py` for planning, applying,
      and the move guard (the guard applies to an effective `move`). Add the
      matrix to `tests/unit/test_placement.py`, including a monkeypatched
      cross-filesystem case.

**Checkpoint**: `--mode auto` parses and resolves, but install and client
behavior are unchanged until the story tasks land.

---

## Phase 3: User Story 1 - Install a server for ebooks (P1) 🎯 MVP

**Goal**: The operator selects the books profile at install time and gets a
config that runs without per-invocation flags.

**Independent Test**: Install non-interactively with `--profile books`; inspect
the config; install with an unknown profile and verify the refusal.

- [x] T004 [US1] Add `--profile` to `trovium-deploy install` in
      `src/trovium/deploy/cli.py` and `InstallOptions`, validate it through
      `get_profile` in `src/trovium/deploy/installer.py`, write
      `IngestSettings(profile=..., mode=Mode.AUTO)`, and warn when an existing
      config retains a different profile. Update
      `tests/unit/deploy/test_config_install.py` and
      `tests/contract/deploy/test_install_cli.py` for the new default
      (`mode = auto`) and the refusal.
- [x] T005 [US1] Forward `--profile` through `install.sh` as a mode option
      (usage text and argument parsing) and prove it end to end in
      `tests/integration/deploy/test_install_local.py`: config holds
      `profile = books` and `mode = auto`; an unknown profile exits 7 and writes
      no config.

**Checkpoint**: A fresh books install is usable by `trovium-run` with no flags.

---

## Phase 4: User Story 2 - Download an ebook and find it named (P1)

**Goal**: One `trovium-run` turns a folder ebook torrent into a canonical
library file plus its sidecars, with hardlinks on a shared filesystem and
copies across filesystems, while the torrent keeps seeding.

**Independent Test**: Drive the client path against a stubbed client with a
folder torrent and inspect the library tree, the record actions, and the client
calls.

- [x] T006 [US2] In `src/trovium/sources.py`, expand a completed client entry
      through `profile.groups()`: exactly one group becomes the candidate with
      its sidecars; more than one group sets `unresolved_reason` naming the
      groups. Add the field to `Candidate` and report it as `unresolvable` in
      `src/trovium/cli.py` before classification. Cover the single-book and
      multi-book shapes in `tests/integration/test_client_ingest.py`.
- [x] T007 [US2] Make `compare_existing` in `src/trovium/library.py` recognize a
      destination file by content when the source name is absent (size first,
      then digest, one destination scan per candidate). Add renamed-destination
      cases to `tests/unit/test_library.py`.
- [x] T008 [US2] In `src/trovium/rename.py`, drop the declared-mode gate and
      keep the client-relocated skip; in `src/trovium/run.py`, stop skipping
      rename for copy and hardlink records while keeping dry-run and
      `--skip-rename`. Update `tests/unit/test_rename.py` and
      `tests/unit/test_run.py`, including the relocated item still skipping.
- [x] T009 [US2] Add the client integration test in
      `tests/integration/test_client_ingest.py`: folder torrent with EPUB,
      `metadata.opf`, and `cover.jpg`; actions are `hardlink`; destination and
      canonical rename; sidecars keep their names; no `setLocation`, pause, or
      delete call; the torrent state is untouched.
- [x] T010 [US2] Add the disk integration case in
      `tests/integration/test_run_pipeline.py`: `mode = auto` with a disk
      source reports a `move` action, renames the placed book, and leaves the
      source gone.

**Checkpoint**: US2 works independently of the installer and rerun stories.

---

## Phase 5: User Story 3 - Rerun without duplicates (P1)

**Goal**: A second run after a rename is a no-op.

**Independent Test**: Ingest with `--mode copy`, rename, run ingest again, and
compare the library tree and the second record.

- [x] T011 [US3] Add the rerun test in `tests/integration/test_run_pipeline.py`:
      first run copies and renames; second run reports `already_handled`, adds
      no file, and does not rename again. Fix any gap this exposes in
      `src/trovium/library.py` or `src/trovium/rename.py`.

**Checkpoint**: The pipeline is safe to run from cron.

---

## Phase 6: User Story 4 - Refuse ambiguous shapes (P2)

**Goal**: A multi-book torrent and an explicit folder-torrent move are named
refusals, not guesses.

**Independent Test**: Drive the client path with two distinct EPUBs and with
`--mode move` on a folder torrent; inspect the records and the library.

- [x] T012 [US4] Add the refusal cases in
      `tests/integration/test_client_ingest.py`: two distinct EPUBs produce
      `unresolvable` with both files named and no placement; a folder torrent
      with explicit `--mode move` keeps the actionable refusal and places
      nothing. Adjust `src/trovium/cli.py` only if the tests expose a gap.

**Checkpoint**: Ambiguous input fails loudly.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T013 [P] Update `README.md`, `docs/profiles.md`, and the two feature
      contracts so the install flag, the `auto` default, the resolution matrix,
      and the rename/rerun behavior match the implementation.
- [x] T014 Run `scripts/check.sh` in the background, follow the gate log until
      it passes, then walk the quickstart scenarios that do not need the live
      rig.
- [x] T015 Mark `specs/007-ebooks-full-pipeline/spec.md` **Status: Complete**,
      check every task above, and run
      `.specify/gates/verify.sh --accept 007-ebooks-full-pipeline` to execute
      the acceptance blocks below.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: T002 → T003; blocks every story.
- **US1 (Phase 3)**: depends on T003 (installer writes `auto`).
- **US2 (Phase 4)**: depends on T003; T006, T007, and T008 touch different
  files and can run in parallel; T009 depends on T006–T008; T010 depends on
  T003.
- **US3 (Phase 5)**: depends on T007 and T008.
- **US4 (Phase 6)**: depends on T006.
- **Polish (Phase 7)**: depends on all stories; T013 and T014 can run in
  parallel, T015 last.

### Within Each Story

- Write the failing test first where the task includes tests, then implement.
- Story checkpoints are independently testable.

### Parallel Opportunities

- T002 and T001 touch different areas; T002 can start after the baseline run.
- US1 and US2 can proceed in parallel once T003 lands (different files:
  deploy vs ingest).
- T006, T007, T008 are separate files and can run together.
- T013 (docs) runs alongside T014 (gate) once behavior is settled.

---

## Parallel Example: User Story 2

```bash
# Different files, no shared dependency:
Task: "Client grouping in src/trovium/sources.py (T006)"
Task: "Content identity in src/trovium/library.py (T007)"
Task: "Rename/run gates in src/trovium/rename.py and src/trovium/run.py (T008)"

# After those, the end-to-end proof:
Task: "Client folder torrent integration test in tests/integration/test_client_ingest.py (T009)"
```

---

## Implementation Strategy

### MVP First

1. T001–T003: baseline and adaptive mode plumbing.
2. T004–T005: install selection.
3. T009–T010: one ebook through the pipeline.
4. Stop and validate with `trovium-run` before adding rerun and refusal tests.

### Incremental Delivery

Each phase ends at a testable checkpoint; the acceptance blocks run only when
the spec is marked Complete.

---

## Notes

- [P] tasks touch different files and have no incomplete dependency.
- Do not change the books grammar, sidecar rules, or the client adapter.
- The live rig (`tools/qbt-live-rig/`) is Linux-only; the integration tests use
  `httpx.MockTransport` and the quickstart names the live scenario separately.

---

## Acceptance

```accept
# verifies: SC-001 — a books install writes the adaptive default and an unknown profile is refused
tmp=$(mktemp -d)
tmp=$(cd "$tmp" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/home" "$tmp/library" "$tmp/source" "$tmp/config" "$tmp/bin"
export HOME="$tmp/home"
export TROVIUM_BIN_DIR="$tmp/bin"
export TROVIUM_CONFIG_FILE="$tmp/config/config.ini"
export TROVIUM_STATE_HOME="$tmp/state"
export TROVIUM_DATA_HOME="$tmp/data"
export TROVIUM_CACHE_HOME="$tmp/cache"
version=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -1)
uv run --quiet python tools/release/build_bundle.py --local --version "$version" --out "$tmp/dist" >/dev/null
bundle=$(find "$tmp/dist" -name "trovium-$version-*.tar.gz" | head -1)
bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$tmp/library" --source "$tmp/source" \
  --profile books --json compact >/dev/null
grep -qx 'profile = books' "$TROVIUM_CONFIG_FILE"
grep -qx 'mode = auto' "$TROVIUM_CONFIG_FILE"
mkdir -p "$tmp/other/config"
TROVIUM_CONFIG_FILE="$tmp/other/config/config.ini" \
TROVIUM_BIN_DIR="$tmp/other/bin" \
TROVIUM_STATE_HOME="$tmp/other/state" \
TROVIUM_DATA_HOME="$tmp/other/data" \
TROVIUM_CACHE_HOME="$tmp/other/cache" \
  bash install.sh --bundle "$bundle" --non-interactive \
  --library-root "$tmp/library" --source "$tmp/source" \
  --profile nope --json compact >/dev/null 2>&1 && exit 1
test ! -e "$tmp/other/config/config.ini"
```

```accept
# verifies: SC-002 — a folder ebook torrent hardlinks, carries sidecars, renames, and keeps seeding
tmp=$(mktemp -d)
tmp=$(cd "$tmp" && pwd -P)
trap 'kill "${srv:-0}" 2>/dev/null || true; rm -rf "$tmp"' EXIT
mkdir -p "$tmp/downloads/Some Book" "$tmp/library"
printf 'epub' > "$tmp/downloads/Some Book/Some.Book.epub"
printf '<package><metadata><title>Some Book</title><creator>Jane Doe</creator><date>2020</date></metadata></package>' \
  > "$tmp/downloads/Some Book/metadata.opf"
printf 'jpg' > "$tmp/downloads/Some Book/cover.jpg"
cat > "$tmp/qbt.py" <<'PY'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
root = Path(sys.argv[1])
torrent = {"hash": "h" + "0" * 39, "name": root.name, "progress": 1.0,
           "state": "uploading", "save_path": str(root.parent),
           "content_path": str(root), "root_path": str(root), "category": "books"}
class H(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json"):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        self._send(json.dumps([torrent]) if self.path == "/api/v2/torrents/info" else "Ok.", "text/plain")
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with open(root.parent / "calls.log", "a") as log:
            log.write(self.path + "\n")
        self._send("Ok.", "text/plain")
    def log_message(self, *args):
        pass
HTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()
PY
port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
python3 "$tmp/qbt.py" "$tmp/downloads/Some Book" "$port" & srv=$!
python3 - "$port" <<'PY'
import socket, sys, time
for _ in range(100):
    try:
        socket.create_connection(("127.0.0.1", int(sys.argv[1])), 0.1).close()
        break
    except OSError:
        time.sleep(0.05)
PY
TROVIUM_CLIENT_USERNAME=admin TROVIUM_CLIENT_PASSWORD=secret \
uv run --quiet trovium-run --client-url "http://127.0.0.1:$port" \
  --library-root "$tmp/library" --profile books --json compact > "$tmp/run.json"
jq -e '[.ingest.items[0].actions[].op] | all(. == "hardlink")' "$tmp/run.json" >/dev/null
jq -e '.rename.counts.renamed == 1' "$tmp/run.json" >/dev/null
test -f "$tmp/library/Books/Jane Doe/Some Book (2020)/Jane Doe - Some Book (2020).epub"
test -f "$tmp/library/Books/Jane Doe/Some Book (2020)/metadata.opf"
test -f "$tmp/library/Books/Jane Doe/Some Book (2020)/cover.jpg"
! grep -Eq '/setLocation|/delete|/stop|/pause' "$tmp/downloads/calls.log"
```

```accept
# verifies: SC-003 — a renamed library file is already handled on the next run
tmp=$(mktemp -d)
tmp=$(cd "$tmp" && pwd -P)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source/Some Book" "$tmp/library"
printf 'epub' > "$tmp/source/Some Book/Some.Book.epub"
printf '<package><metadata><title>Some Book</title><creator>Jane Doe</creator><date>2020</date></metadata></package>' \
  > "$tmp/source/Some Book/metadata.opf"
uv run --quiet trovium-ingest --profile books --source "$tmp/source" \
  --library-root "$tmp/library" --mode copy --json compact > "$tmp/ingest.json"
uv run --quiet trovium-rename --record "$tmp/ingest.json" --json compact > "$tmp/rename.json"
uv run --quiet trovium-ingest --profile books --source "$tmp/source" \
  --library-root "$tmp/library" --mode copy --json compact > "$tmp/rerun.json"
jq -e '.items[0].disposition == "already_handled"' "$tmp/rerun.json" >/dev/null
test "$(find "$tmp/library" -name '*.epub' | wc -l)" -eq 1
```

```accept
# verifies: SC-004 — a multi-book torrent and an explicit folder move are named refusals
tmp=$(mktemp -d)
tmp=$(cd "$tmp" && pwd -P)
trap 'kill "${srv:-0}" 2>/dev/null || true; rm -rf "$tmp"' EXIT
mkdir -p "$tmp/downloads/Two Books" "$tmp/library"
printf 'one' > "$tmp/downloads/Two Books/Book One.epub"
printf 'two' > "$tmp/downloads/Two Books/Book Two.epub"
printf '<package><metadata><title>Some Book</title><creator>Jane Doe</creator><date>2020</date></metadata></package>' \
  > "$tmp/downloads/Two Books/metadata.opf"
cat > "$tmp/qbt.py" <<'PY'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
root = Path(sys.argv[1])
torrent = {"hash": "h" + "0" * 39, "name": root.name, "progress": 1.0,
           "state": "uploading", "save_path": str(root.parent),
           "content_path": str(root), "root_path": str(root), "category": "books"}
class H(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json"):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        self._send(json.dumps([torrent]) if self.path == "/api/v2/torrents/info" else "Ok.", "text/plain")
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send("Ok.", "text/plain")
    def log_message(self, *args):
        pass
HTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()
PY
port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
python3 "$tmp/qbt.py" "$tmp/downloads/Two Books" "$port" & srv=$!
python3 - "$port" <<'PY'
import socket, sys, time
for _ in range(100):
    try:
        socket.create_connection(("127.0.0.1", int(sys.argv[1])), 0.1).close()
        break
    except OSError:
        time.sleep(0.05)
PY
TROVIUM_CLIENT_USERNAME=admin TROVIUM_CLIENT_PASSWORD=secret \
uv run --quiet trovium-run --client-url "http://127.0.0.1:$port" \
  --library-root "$tmp/library" --profile books --json compact > "$tmp/multi.json"
jq -e '.ingest.items[0].disposition == "unresolvable"' "$tmp/multi.json" >/dev/null
jq -e '.ingest.items[0].reason | test("Book One.epub")' "$tmp/multi.json" >/dev/null
jq -e '.ingest.items[0].reason | test("Book Two.epub")' "$tmp/multi.json" >/dev/null
test -z "$(find "$tmp/library" -type f)"
rm "$tmp/downloads/Two Books/Book Two.epub"
TROVIUM_CLIENT_USERNAME=admin TROVIUM_CLIENT_PASSWORD=secret \
uv run --quiet trovium-run --client-url "http://127.0.0.1:$port" \
  --library-root "$tmp/library" --profile books --mode move --json compact > "$tmp/move.json"
jq -e '.ingest.items[0].disposition == "error"' "$tmp/move.json" >/dev/null
jq -e '.ingest.items[0].reason | test("multi-file torrent")' "$tmp/move.json" >/dev/null
test -z "$(find "$tmp/library" -type f)"
```

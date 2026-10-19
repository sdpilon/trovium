# qbt-live-rig

A root-free, self-contained qBittorrent test rig for exercising the ingest step
against **real** BitTorrent transfers over loopback.

Two qBittorrent instances and a local tracker:

```text
                announce                announce
   instance A  -------->  tracker  <-------- instance B
   webui :8080            :6969              webui :8081
   torrent :46052                            torrent :6882
   work/a/downloads                          work/b/downloads
        |                                         ^
        +----------- peer transfer --------------+
```

Instance B seeds a fixture; instance A downloads it; the CLI under test then
runs against A, whose download directory holds genuinely downloaded files. A
stubbed HTTP transport can prove request shapes, but it cannot prove what a
real client does with the files afterwards — that is what this rig is for.

Nothing is installed system-wide, no root is needed, and every path lives under
this directory (`work/` unless `$QBT_RIG_WORK` says otherwise).

## Requirements

- Linux with `apt-get` and `dpkg` (Debian/Ubuntu) for `setup.sh`; on other
  distributions install `qbittorrent-nox` yourself and point `QBT_RIG_CLIENT` at
  the tree containing `usr/bin/qbittorrent-nox`.
- Python 3.13 (the rig itself is stdlib only).
- Free local ports: 22150, 8080, 8081, 6969, 46052, 6882, 6883 (overridable,
  see Configuration).

## Quick start

```sh
./setup.sh                                   # one-time: fetch qbittorrent-nox
./qbt_rig.py up                              # tracker + both instances
./qbt_rig.py fixture movie \
    --title Movie.Production.2024.1080p-iGor.mkv --size-mb 3
./qbt_rig.py fixture tv --root Show.Name.S02 --files 2 --size-mb 2
./qbt_rig.py seed movie                      # add + place + recheck + seed on B
./qbt_rig.py seed tv
./qbt_rig.py fetch movie                     # add + download + verify on A
./qbt_rig.py fetch tv

eval "$(./qbt_rig.py env)"                   # TROVIUM_CLIENT_URL/USERNAME/PASSWORD
uv run trovium-ingest --library-root "$QBT_RIG_LIBRARY" --json pretty

./qbt_rig.py snapshot after-ingest           # evidence/after-ingest.json
./qbt_rig.py status
./qbt_rig.py reset                           # remove torrents + downloads (not the library)
./qbt_rig.py down
```

`fetch` verifies sha256 against the fixture manifest **and** requires the torrent
to have downloaded peer bytes, so a successful run proves the payload travelled
over the peer protocol rather than being satisfied from files already on disk.
Run `reset` before re-fetching a case.

## Commands

| Command                 | Purpose                                                                                                                                                                                   |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `up` / `down`           | start/stop tracker + both instances (idempotent, pid files in `work/`)                                                                                                                    |
| `status`                | torrent states, progress, save paths, transfer totals for A and B                                                                                                                         |
| `fixture NAME`          | build payload + `.torrent` + manifest; `--title` (single file), `--root`/`--files` (multi; `--root` alone makes a folder torrent with one media file), `--size-mb`, `--seed`, `--tracker` |
| `seed NAME`             | on B: add, place payload, recheck, start, wait complete                                                                                                                                   |
| `fetch NAME`            | on A: add, start, wait complete, verify sha256                                                                                                                                            |
| `snapshot LABEL`        | write both instances' state to `work/evidence/LABEL.json`                                                                                                                                 |
| `reset`                 | delete all torrents (with files) on A/B and clear their downloads                                                                                                                         |
| `env [--instance a\|b]` | print shell exports for the CLI under test                                                                                                                                                |

Fixtures and manifests are stored under `work/fixtures/`. `fixture` generates
deterministic random payloads; for playable media, replace the payload files
before `seed` (the ingest step only looks at names and bytes).

## Configuration

| Env var                                     | Default              | Meaning                                            |
| ------------------------------------------- | -------------------- | -------------------------------------------------- |
| `QBT_RIG`                                   | this directory       | rig root (scripts, `setup.sh`, docs)               |
| `QBT_RIG_WORK`                              | `$RIG/work`          | profiles, downloads, fixtures, evidence, pid files |
| `QBT_RIG_CLIENT`                            | `$RIG/client`        | extracted qBittorrent tree                         |
| `QBT_RIG_PASSWORD`                          | `rig-test-pw`        | WebUI password for both instances (user `admin`)   |
| `QBT_RIG_A_WEBUI` / `_A_TORRENT` / `_A_SSL` | 8080 / 46052 / 22150 | instance A ports                                   |
| `QBT_RIG_B_WEBUI` / `_B_TORRENT` / `_B_SSL` | 8081 / 6882 / 6883   | instance B ports                                   |
| `QBT_RIG_TRACKER_PORT`                      | 6969                 | local tracker port                                 |

All listeners bind `127.0.0.1` for the WebUI and tracker; the torrent port binds
all interfaces (qBittorrent default) unless you set `Session\Interface` in the
generated profile.

## Layout

```text
setup.sh            fetch + extract qbittorrent-nox (no root)
qbt_rig.py          orchestration CLI (stdlib only)
tracker.py          minimal HTTP tracker (compact peer lists)
.gitignore          excludes client/, work/, and downloaded packages
work/               generated: profiles, downloads, fixtures, evidence, logs
client/             generated: extracted qBittorrent + Qt/libtorrent libs
```

## Gotchas encoded here (learned the hard way)

- **qBittorrent 5.x moved the config file** to
  `<profile>/qBittorrent/config/qBittorrent.conf`; the 4.x path is silently
  ignored and the client comes up with a temporary session password.
- WebUI password must be **PBKDF2-HMAC-SHA512, 100 000 iterations, 16-byte
  salt, 64-byte digest**, stored as `@ByteArray(<b64salt>:<b64hash>)`.
- `WebUI\Address` defaults to `*`; the rig pins `127.0.0.1`.
- `WebUI\MaxAuthenticationFailCount` defaults to 5 with a ban; the rig raises it
  so wrong-password tests do not lock the client out.
- `torrents/add` ignores `paused` on 5.x; the rig sends `stopped` as well.
- `torrents/pause` returns **404** on 5.x; use `torrents/stop` (the rig's
  `pause()` tries `stop` first).
- `content_path` is the **file** for a folder torrent holding one video plus
  sidecars; `root_path` is the directory. Use `root_path` to tell a folder
  torrent from a single-file torrent.
- Disable DHT/LSD/UPnP so discovery can only go through the tracker; otherwise a
  broken tracker can be masked by local peer discovery.
- A recheck needs a real poll: a snapshot taken immediately after the API call
  can still show the pre-recheck state.

## Using it for a future feature

1. `./qbt_rig.py fixture ...` for each candidate shape you need (single-file
   movie, folder torrent with one or more videos, incomplete control by not
   seeding it).
2. `seed` the ones that should be complete; for an incomplete control, create
   the fixture and add it to A without seeding its payload (or run `fetch` and
   stop it early with `pause`).
3. Run the CLI under test with `eval "$(./qbt_rig.py env)"`.
4. `snapshot` after each step; records + instance JSON are the evidence.

For a genuinely partial download, truncate the seeded payload before `seed`
(e.g. keep only the first half of a file) — qBittorrent verifies only the
pieces it has, and A will stall mid-download.

## Scope and safety

This is development tooling, not part of the shipped pipeline: it downloads a
third-party client, binds fixed local ports, and writes only under `work/` and
`client/` (both ignored by git). The WebUI and tracker listen on `127.0.0.1`
only. Run it against a scratch library root, never a real one, and stop it with
`./qbt_rig.py down` when finished.

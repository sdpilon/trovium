#!/usr/bin/env bash
# Fetch qbittorrent-nox + its dependency closure from Debian/Ubuntu packages and
# extract them into ./client — no root, no system install.
#
# Works on Debian 13 (trixie) and should work on any apt-based distro; the
# package list is resolved by apt itself, so version drift is handled.
# Re-run is a no-op once client/usr/bin/qbittorrent-nox exists (delete client/
# to refresh).
set -euo pipefail

RIG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT="${QBT_RIG_CLIENT:-$RIG/client}"
LIB="$CLIENT/usr/lib/x86_64-linux-gnu"

if [ -x "$CLIENT/usr/bin/qbittorrent-nox" ]; then
  echo "client already present: $(LD_LIBRARY_PATH="$LIB:$LIB/libproxy" "$CLIENT/usr/bin/qbittorrent-nox" --version 2>/dev/null || echo 'version unknown')"
  exit 0
fi

for tool in apt-get dpkg ldd; do
  command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 1; }
done

mkdir -p "$CLIENT/debs"
cd "$CLIENT/debs"

echo "resolving qbittorrent-nox dependency closure..."
apt-get install -s qbittorrent-nox 2>/dev/null | awk '/^Inst/{print $2}' > packages.txt
test -s packages.txt || {
  echo "could not resolve qbittorrent-nox (is the package index available?)" >&2
  exit 1
}
echo "downloading $(wc -l < packages.txt) packages..."
while read -r package; do
  apt-get download "$package" >/dev/null
done < packages.txt

echo "extracting into $CLIENT"
for deb in *.deb; do
  dpkg -x "$deb" "$CLIENT"
done

missing="$(LD_LIBRARY_PATH="$CLIENT/usr/lib/x86_64-linux-gnu:$CLIENT/usr/lib/x86_64-linux-gnu/libproxy" \
  ldd "$CLIENT/usr/bin/qbittorrent-nox" | awk '/not found/{print $1}')"
if [ -n "$missing" ]; then
  echo "still missing libraries:" >&2
  echo "$missing" >&2
  exit 1
fi

echo "client ready: $(LD_LIBRARY_PATH="$LIB:$LIB/libproxy" "$CLIENT/usr/bin/qbittorrent-nox" --version 2>/dev/null || echo 'version unknown')"

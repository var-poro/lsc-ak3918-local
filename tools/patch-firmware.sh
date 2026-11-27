#!/usr/bin/env bash
# Build a local-only appfs image from a stock appfs (mtd3) dump.
#
#   ./patch-firmware.sh stock-mtd3.bin appfs-patched.sqfs
#
# Two patches, both baked into the firmware so the camera needs no SD card and
# no cloud after flashing:
#   1) yy_cam:   yy_prompt_get_secret_mode_onoff() -> always return 0
#      (privacy/"secret" mode permanently OFF, so the RTSP/ONVIF servers always
#       start; the firmware does NOT need the cloud at boot, only secret_mode=0).
#   2) start.sh: blackhole the WAN after Wi-Fi comes up (keeps the LAN; cuts the
#      Tuya cloud). Removes the need for the SD-card yy_local_only flag.
#
# Requires: radare2 (brew install radare2), squashfs-tools (brew install squashfs).
# Reversing notes: docs/findings.md.
set -euo pipefail
IN="${1:?usage: patch-firmware.sh <stock-mtd3.bin> <out.sqfs>}"
OUT="${2:?usage: patch-firmware.sh <stock-mtd3.bin> <out.sqfs>}"
PART_SIZE=$(wc -c < "$IN")                 # the mtd3 partition size (image must fit)
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

echo ">> read squashfs params from the stock image"
COMP=$(unsquashfs -s "$IN" | awk '/Compression/{print $2}')
BLK=$(unsquashfs -s "$IN"  | awk '/Block size/{print $3}')
echo "   compression=$COMP block=$BLK partition=$PART_SIZE"

echo ">> unpack appfs"
unsquashfs -q -d "$WORK/root" "$IN" >/dev/null

echo ">> patch 1: force yy_prompt_get_secret_mode_onoff() to return 0"
BIN="$WORK/root/bin/yy_cam"
ADDR=$(rabin2 -qs "$BIN" | awk '/ yy_prompt_get_secret_mode_onoff$/{print $3; exit}')
[ -n "${ADDR:-}" ] || { echo "!! symbol not found -- firmware variant differs, see docs"; exit 1; }
# mov r0, #0 ; bx lr   (ARM little-endian)  -> function returns 0 immediately
r2 -w -q -c "s $ADDR; wx 0000a0e31eff2fe1" "$BIN" >/dev/null
echo "   patched yy_cam at $ADDR"

echo ">> patch 2: blackhole the WAN in start.sh"
SS="$WORK/root/script/start.sh"
if ! grep -q 'blackhole' "$SS"; then
  python3 - "$SS" <<'PY'
import sys
f=sys.argv[1]; s=open(f,encoding="utf-8").read()
block=("# [local-only] blackhole WAN, keep LAN (no SD card, no cloud)\n"
"( n=0; while [ $n -lt 60 ]; do /sbin/ip addr show wlan0 2>/dev/null | grep -q \"inet \" && break; sleep 1; n=$((n+1)); done\n"
"  /sbin/ip route add blackhole 0.0.0.0/1   2>/dev/null\n"
"  /sbin/ip route add blackhole 128.0.0.0/1 2>/dev/null ) &\n\n")
m="# 启动应用程序"            # "start the application"
anchor=m if m in s else "nvram get STATUS"
s=s.replace(anchor, block+anchor, 1)
open(f,"w",encoding="utf-8").write(s)
PY
fi
echo "   start.sh hooked"

echo ">> repack ($COMP, block $BLK, root-owned)"
rm -f "$OUT"
mksquashfs "$WORK/root" "$OUT" -comp "$COMP" -b "$BLK" -noappend -all-root -no-xattrs >/dev/null
SZ=$(wc -c < "$OUT")
echo "   size=$SZ / partition=$PART_SIZE"
[ "$SZ" -lt "$PART_SIZE" ] || { echo "!! image too big for the partition"; exit 1; }
echo ">> OK: $OUT  (sha256 $(shasum -a256 "$OUT" | cut -d' ' -f1))"

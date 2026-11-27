#!/usr/bin/env bash
# Pull a full flash backup + the Tuya key DB from the camera over telnet.
# Requires: the SD-card root payload booted (telnet up), tools/cam.py.
#
#   CAM_HOST=192.168.1.34 ./backup.sh ./backup-dir
#
# mtd0=uboot mtd1=kernel mtd2=rootfs mtd3=appfs mtd4=config mtd5=factory
# The backup is also written to the SD card by hack.sh (/mnt/sdcard/flash_backup).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-./camera-backup}"; mkdir -p "$OUT/flash_backup" "$OUT/tuya"
CAM="${CAM_HOST:-192.168.1.34}"
cam() { CAM_HOST="$CAM" python3 "$HERE/cam.py" "$@"; }

echo ">> flash backup -> $OUT/flash_backup (also on the SD card)"
cam 'ls -la /mnt/sdcard/flash_backup/ 2>/dev/null || echo "no SD backup (hack.sh makes it on first boot)"'
echo ">> copying Tuya key DB (for offline local-key recovery)"
# serve /config over the SD busybox httpd, then curl it
cam '/mnt/sdcard/busybox httpd -p 8088 -h / 2>/dev/null; echo ok'
sleep 1
for f in config/tuya/tuya_user.db config/tuya/tuya_enckey.db config/param.conf; do
  curl -s -o "$OUT/tuya/$(basename "$f")" "http://$CAM:8088/$f" && echo "  got $f"
done
echo ">> pull the raw partitions from the SD backup (if present):"
for i in 0 1 2 3 4 5; do
  curl -s -o "$OUT/flash_backup/mtd$i.bin" "http://$CAM:8088/mnt/sdcard/flash_backup/mtd$i.bin" 2>/dev/null \
    && [ -s "$OUT/flash_backup/mtd$i.bin" ] && echo "  mtd$i.bin" || rm -f "$OUT/flash_backup/mtd$i.bin"
done
echo ">> done. KEEP $OUT PRIVATE (contains device keys)."

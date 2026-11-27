#!/usr/bin/env bash
# Recovery: reflash the ORIGINAL appfs from the SD-card backup.
# Use this if a patched flash left the camera unable to start the app.
# Needs the SD card in (telnet up via the root payload) + /mnt/sdcard/flash_backup/mtd3.bin.
#
#   CAM_HOST=192.168.1.34 ./restore-stock.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CAM="${CAM_HOST:-192.168.1.34}"
cam() { CAM_HOST="$CAM" python3 "$HERE/cam.py" "$@"; }

cam 'test -s /mnt/sdcard/flash_backup/mtd3.bin && echo OK || echo MISSING' \
  | grep -q OK || { echo "!! /mnt/sdcard/flash_backup/mtd3.bin missing -- cannot restore"; exit 1; }

echo ">> reflashing stock appfs from the SD backup (detached)..."
cam '/mnt/sdcard/busybox nohup /usr/sbin/flashcp /mnt/sdcard/flash_backup/mtd3.bin /dev/mtd3 </dev/null >/tmp/restore.log 2>&1 & echo started'
for i in $(seq 1 15); do
  r=$(cam '/mnt/sdcard/busybox pidof flashcp >/dev/null 2>&1 && echo RUN || echo DONE' | grep -Eo 'RUN|DONE' | tail -1)
  echo "   ...$r"; [ "$r" = DONE ] && break; sleep 6
done
cam 'echo 3 > /proc/sys/vm/drop_caches; sync; cmp /dev/mtd3 /mnt/sdcard/flash_backup/mtd3.bin && echo "RESTORED (identical to stock)" || echo "MISMATCH -- retry"'
echo ">> reboot the camera to boot the restored firmware."

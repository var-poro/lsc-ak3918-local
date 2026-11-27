#!/usr/bin/env bash
# Flash a patched appfs image to /dev/mtd3 — safely.
#
#   # 1) serve the image on your LAN (any machine the camera can reach):
#   #    cd dir-with-image && python3 -m http.server 8099
#   # 2) flash it (needs telnet up via the SD root payload):
#   CAM_HOST=192.168.1.34 ./flash-firmware.sh http://192.168.1.50:8099/appfs-patched.sqfs
#
# Safety:
#   * refuses to flash unless a stock backup exists on the SD (recovery path),
#   * verifies the sha256 on the camera BEFORE flashing,
#   * runs flashcp detached (nohup) so a dropped telnet never interrupts it
#     (an interrupted flashcp leaves a half-erased, non-booting appfs),
#   * verifies the written partition after.
# Only touches mtd3 (appfs). Never writes mtd0/uboot or mtd1/kernel.
set -euo pipefail
URL="${1:?usage: flash-firmware.sh <http-url-of-appfs-image>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
CAM="${CAM_HOST:-192.168.1.34}"
cam() { CAM_HOST="$CAM" python3 "$HERE/cam.py" "$@" "${2:-8}"; }

echo ">> safety check: stock appfs backup on the SD?"
cam 'test -s /mnt/sdcard/flash_backup/mtd3.bin && echo RECOVERY_OK || echo NO_BACKUP' \
  | grep -q RECOVERY_OK || { echo "!! no /mnt/sdcard/flash_backup/mtd3.bin -- run backup first"; exit 1; }

echo ">> download image onto the camera + verify"
cam "/mnt/sdcard/busybox wget -q -O /tmp/fw.sqfs '$URL'; /mnt/sdcard/busybox sha256sum /tmp/fw.sqfs; ls -la /tmp/fw.sqfs"
read -rp ">> confirm the sha above matches your local image, then type YES: " ok
[ "$ok" = "YES" ] || { echo "aborted"; exit 1; }

echo ">> flashing mtd3 (detached)..."
cam '/mnt/sdcard/busybox nohup /usr/sbin/flashcp /tmp/fw.sqfs /dev/mtd3 </dev/null >/tmp/flash.log 2>&1 & echo started'
for i in $(seq 1 15); do
  r=$(cam '/mnt/sdcard/busybox pidof flashcp >/dev/null 2>&1 && echo RUN || echo DONE' | grep -Eo 'RUN|DONE' | tail -1)
  echo "   ...$r"; [ "$r" = DONE ] && break; sleep 6
done

echo ">> verify written partition"
N=$(python3 -c "import math,sys;print(math.ceil($(stat -f%z /dev/stdin 2>/dev/null || echo 0)/4096))" 2>/dev/null || true)
cam 'echo 3 > /proc/sys/vm/drop_caches; sync; SZ=$(wc -c < /tmp/fw.sqfs); BL=$(( (SZ+4095)/4096 )); echo "flash sha: $(dd if=/dev/mtd3 bs=4096 count=$BL 2>/dev/null | /mnt/sdcard/busybox sha256sum)"; echo "image sha: $(/mnt/sdcard/busybox sha256sum /tmp/fw.sqfs)"'
echo ">> if the two sha above match, reboot the camera. RTSP/ONVIF come up on"
echo "   8554/5000; the WAN is blackholed. Then you can remove the SD card."
echo "   Recovery if it ever won't boot: reinsert the SD (telnet returns) and run restore-stock.sh."

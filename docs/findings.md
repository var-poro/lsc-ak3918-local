# Findings — LSC 3225722 / Anyka AK3918AV130 / YYOS (TuyaOS 6.3.0)

Reverse-engineering notes behind the two-patch, SD-free, cloud-free setup.

## Hardware / boot
- SoC Anyka AK3918AV130_B, ARM926EJ-S (ARMv5TEJ), 64 MB DDR2, Linux 4.4.302.
- Flash: 8 MB SPI NOR, MTD layout:
  - `mtd0` uboot 256K — **locked console + secure boot; never write it**
  - `mtd1` kernel 1.5M, `mtd2` rootfs 1.3M (squashfs), `mtd3` appfs 4.6M (squashfs)
  - `mtd4` config 256K (jffs2, `/config`, writable), `mtd5` factory 128K
- Boot: uboot → kernel → rootfs → `/etc/init.d/rcS` → `init.sh` → `start.sh`.
  All boot scripts live in **read-only squashfs**; only `/config` (mtd4) and
  nvram are writable, and **nothing executes from them at boot**. So persistent
  changes to boot behaviour require repacking + reflashing a squashfs partition
  (we touch only `appfs`/mtd3, which is recoverable; rootfs/kernel/uboot stay
  stock, so the camera always boots far enough for SD recovery).
- `init.sh` reads `/mnt/sdcard/yy_debug.ini`; without the SD it runs `start.sh`
  normally. Alternative firmware (OpenIPC/Thingino) does **not** support AK3918.

## The real gate: RTSP depends only on "secret mode"
RTSP/ONVIF are driven by `yy_rtsp_manager_th` / `yy_onvif_manager_th`. The
manager loop (decompiled) is, in effect:

```
if (yy_prompt_get_secret_mode_onoff())   // privacy ON
    yy_rtsp_stop();
else if (rtsp_on_off)                     // from /config/param.conf
    yy_rtsp_start();                      // bind :8554 / :5000
```

So the servers start **iff** secret mode is OFF and `rtsp_on_off=1`. **No cloud
check.** The camera serves video fully offline. The earlier "it needs the cloud
at boot" conclusion was wrong: the symptom was a stale `secret_mode = 1`.

`yy_prompt_get_secret_mode_onoff` just returns a byte from a global struct
(`*(g + 0x294)`). It is set only by the Tuya DP handler and a cloud-event
thread — and its boot value is **restored locally** (persisted), not fetched
from the cloud. Once set to 0 it stays 0 across reboots, offline.

### Patch
Force privacy permanently off by making the getter return 0:
```
yy_prompt_get_secret_mode_onoff:
    mov r0, #0        ; 00 00 a0 e3
    bx  lr            ; 1e ff 2f e1
```
`tools/patch-firmware.sh` finds the symbol with radare2 and writes these 8
bytes, so it adapts to a firmware whose address differs.

## Cutting the WAN without an SD card
Add to `appfs/script/start.sh`, before it launches `yy_cam`, a background wait
for `wlan0`'s IP then:
```
ip route add blackhole 0.0.0.0/1
ip route add blackhole 128.0.0.0/1
```
This blackholes all WAN while the `192.168.x/24` LAN route (more specific)
keeps working. The Tuya cloud/MQTT is unreachable; RTSP/ONVIF/LAN are fine.
(The same trick is what the SD `hack.sh` `yy_local_only` flag does — baking it
into the firmware removes the SD dependency.)

## RTSP/ONVIF config (local, in /config/param.conf)
`param.conf` holds `[rtsp]`/`[onvif]` with `*_on_off`, `*_username`,
`*_password` (plaintext). `rtsp_password`/`onvif_password` being set is what
makes DP 239 ("password set") true; you do **not** need the balky DP 238 path.
`secret_mode_onoff` is also mirrored into `[dp]` but is **write-only** there
(the firmware never reads it back at boot — don't rely on editing it).

## Tuya DP map (this firmware)
From `tuya_ipc_dp_report` call sites:
- **105 = secret/privacy mode** (`secret_mode_onoff`) — the RTSP gate.
- **237 = RTSP/ONVIF master switch**, **239 = native password set** (indicator),
  238 = change native password (JSON `{"oldpwd","newpwd"}`, unreliable over LAN).
- 101 indicator · 103 flip · 104 OSD · 106 motion sens · 108 night mode ·
  119 ptz_control (enum 0..7) · 116 ptz_stop · 134 motion switch · 150/151 record.

## Local-key DB (offline recovery)
`/config/tuya/tuya_user.db` is a custom AES-128-ECB key-value store; the AES key
is **derived** from `/config/tuya/tuya_enckey.db` (swap the two 8-byte halves,
then swap adjacent bytes). `gw_di.id` = device_id, `gw_ai.lckey` = local key.
`tools/recover-local-key.py` implements it. With those, TinyTuya drives the
camera over the LAN (protocol 3.5) even with the WAN blocked.

## appfs squashfs format (for repacking)
SQUASHFS 4.0, **xz**, **128 KiB** blocks, all files root-owned. `patch-firmware.sh`
reads these from the stock image and matches them (`mksquashfs -comp xz -b 131072
-all-root -no-xattrs`). The image must fit the mtd3 partition size.

## Gotchas learned the hard way
- **Never run `flashcp` in the foreground over a short-lived telnet helper** — a
  dropped connection sends SIGHUP and leaves a half-erased, non-booting appfs.
  Always `busybox nohup flashcp ... &` and poll. (Recoverable from the SD backup.)
- `/dev/mtdblock3` reads are page-cached; verify writes via the char device
  `/dev/mtd3` (or `echo 3 > /proc/sys/vm/drop_caches` first).
- The AK3918 Wi-Fi module's MAC is an **AltoBeam (ATBM)** OUI, not "Tuya".

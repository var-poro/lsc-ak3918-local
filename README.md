# LSC Smart Connect (Anyka AK3918 / YYOS) — fully local, no SD card, no cloud

Turn a cloud-only **LSC Smart Connect** camera (Action; Anyka AK3918AV130,
TuyaOS "YYOS") into a **local-only** camera:

- **RTSP + ONVIF** on the LAN (works in Home Assistant, Frigate, VLC…),
- **cloud cut** (the camera can't reach the internet),
- **no SD card required** after setup — everything is baked into the firmware,
- nothing bricked: the stock firmware is backed up and restorable.

This is what I did to one **LSC 3225722 / SZ F26312 / firmware 14.1.5**
(SoC Anyka AK3918AV130, Linux 4.4.302). A similar Anyka/YYOS model should follow
the same path; the scripts are written to adapt (they locate the patch point by
symbol, not by a hard-coded address).

> ⚠️ For devices **you own**. The telnet root here has weak/no auth — keep it on
> a trusted LAN only. Don't redistribute the manufacturer's firmware.

---

## The short version

The firmware's RTSP/ONVIF servers only start when **"secret mode" (privacy) is
OFF**. The camera does **not** need the cloud to serve video — the earlier belief
that it did was wrong; the real blocker was a stale `secret_mode = 1`.

So the fix is two tiny firmware patches, flashed into the `appfs` partition:

1. **`yy_cam`**: patch `yy_prompt_get_secret_mode_onoff()` to **always return 0**
   → privacy mode is permanently off → RTSP/ONVIF always start, with no cloud.
2. **`start.sh`**: **blackhole the WAN** once Wi-Fi is up (keep the LAN, cut the
   cloud) → no SD-card flag needed.

After flashing you can pull the SD card out. The camera boots offline, serves
RTSP/ONVIF, and never phones home.

See [docs/findings.md](docs/findings.md) for how this was reverse-engineered.

---

## What's in here

```
sdcard/       SD-card root payload (telnet) — from alex-so-3 (credit below)
tools/
  cam.py                 one-shot telnet client for the camera's root shell
  backup.sh              full flash backup + Tuya key DB  (DO FIRST)
  recover-local-key.py   decrypt device_id + local key OFFLINE from the backup
  tuya-dp.py             read/set Tuya DPs over the LAN (no cloud)
  patch-firmware.sh      build the patched appfs from a stock mtd3 dump
  flash-firmware.sh      flash it safely (verify + detached flashcp)
  restore-stock.sh       recovery: reflash the stock appfs from the SD backup
docs/findings.md         reverse-engineering notes, DP map, ports, DB format
```

No firmware, keys, passwords or backups are committed. The scripts pull what
they need from your own camera.

---

## Procedure (for a fresh, similar camera)

Tools on your computer: `python3`, `radare2`, `squashfs-tools`, `ffmpeg`,
`pip install tinytuya cryptography`.

### 0. Get root over the SD card
These cameras only honour the SD debug hook **once activated**, so:
1. Put a FAT32 micro-SD with the four `sdcard/` files **+ a static busybox**
   (`busybox` on the card root; build or grab one for ARMv5TE — see
   alex-so-3's repo). First boot writes a full flash backup to the card.
2. **Pair once** with the LSC/Tuya app (a throwaway account), on 2.4 GHz Wi-Fi,
   and **refuse any firmware update**.
3. Reboot with the card in → `telnet <camera-ip>` gives a root shell (root/root
   on UART; passwordless over the network).

`sdcard/hack.sh` also supports a `yy_local_only` flag (blackhole the WAN from the
SD) — handy before the firmware patch exists.

### 1. Back up (do this first)
```bash
CAM_HOST=192.168.1.34 tools/backup.sh ./camera-backup
```
Keep `./camera-backup` private — it holds the device keys. The stock `appfs`
(`mtd3.bin`) is both here and on the SD card (your recovery image).

### 2. Recover the local key (offline)
```bash
python3 tools/recover-local-key.py camera-backup/tuya/tuya_user.db \
                                    camera-backup/tuya/tuya_enckey.db
```
Gives `device_id` + `local_key`. With those you drive the camera over the LAN:
```bash
export TUYA_ID=... TUYA_KEY=... CAM_HOST=192.168.1.34
python3 tools/tuya-dp.py status
python3 tools/tuya-dp.py set 105 false   # turn privacy OFF (RTSP comes up)
```
(On this model DP 105 = secret/privacy mode, DP 237 = RTSP/ONVIF switch. Your
model's DP numbers may differ — check `tuya-dp.py status` and docs/findings.md.)

### 3. Enable RTSP/ONVIF in the camera's config (once)
Over telnet, in `/config/param.conf`, add under the right sections:
```
[rtsp]
rtsp_on_off   = 1
rtsp_username = admin
rtsp_password = <choose one, 8-15 chars>
[onvif]
onvif_on_off   = 1
onvif_username = admin
onvif_password = <same>
```
Reboot. RTSP is `rtsp://admin:<pw>@<ip>:8554/stream0`, ONVIF on `:5000`.

### 4. Build + flash the local-only firmware
```bash
tools/patch-firmware.sh camera-backup/flash_backup/mtd3.bin appfs-patched.sqfs
# serve it on the LAN, e.g. from your always-on box:
#   python3 -m http.server 8099     (in the folder with appfs-patched.sqfs)
CAM_HOST=192.168.1.34 tools/flash-firmware.sh http://<server>:8099/appfs-patched.sqfs
```
Reboot, check `rtsp://.../stream0`, then **pull the SD card out**. Done.

### Recovery
If a patched flash ever won't boot: reinsert the SD (telnet returns via the root
payload) and `CAM_HOST=... tools/restore-stock.sh`.

---

## Credits

- **[alex-so-3/lsc-ak3918-yyos-root](https://github.com/alex-so-3/lsc-ak3918-yyos-root)**
  — the SD-card root method and `sdcard/` payload.
- **[dev-zetta/LSCamoflash](https://github.com/dev-zetta/LSCamoflash)** — the
  offline Tuya key-DB decryption scheme.
- **[themactep/thingino-firmware](https://github.com/themactep/thingino-firmware)**
  — reference for the LSC/Anyka hardware (note: Thingino supports the *Ingenic*
  revision, **not** this Anyka one).

MIT licensed. No warranty — you can brick hardware.

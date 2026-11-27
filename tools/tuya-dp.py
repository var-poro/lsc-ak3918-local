#!/usr/bin/env python3
"""
Read or set Tuya data-points (DPs) over the LAN (no cloud).

    pip install tinytuya
    export TUYA_ID=...  TUYA_KEY=...  CAM_HOST=192.168.1.x
    python3 tuya-dp.py status
    python3 tuya-dp.py set 105 false     # 105 = secret/privacy mode (this model)
    python3 tuya-dp.py set 237 true      # 237 = RTSP/ONVIF master switch

Get TUYA_ID / TUYA_KEY from tools/recover-local-key.py (offline, from a backup).
Protocol version defaults to 3.5 (use TUYA_VER to override).
Works even when the camera's WAN is blocked — the DP protocol is LAN-local.
"""
import os, sys, json, tinytuya

ID   = os.environ.get("TUYA_ID")
KEY  = os.environ.get("TUYA_KEY")
HOST = os.environ.get("CAM_HOST", "192.168.1.34")
VER  = float(os.environ.get("TUYA_VER", "3.5"))


def coerce(v):
    if v.lower() in ("true", "on", "1"):  return True
    if v.lower() in ("false", "off", "0"): return False
    try: return int(v)
    except ValueError: return v


def main():
    if not ID or not KEY:
        sys.exit("set TUYA_ID and TUYA_KEY (see tools/recover-local-key.py)")
    d = tinytuya.Device(ID, HOST, KEY, version=VER, connection_timeout=6)
    d.set_socketPersistent(True)
    a = sys.argv[1] if len(sys.argv) > 1 else "status"
    if a == "status":
        print(json.dumps(d.status().get("dps", {}), indent=2))
    elif a == "set" and len(sys.argv) >= 4:
        dp, val = sys.argv[2], coerce(sys.argv[3])
        print("set", dp, "->", val, ":", d.set_value(int(dp), val))
    else:
        sys.exit("usage: tuya-dp.py status | set <dp> <true|false|int|str>")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Local control bridge: Tuya DP (LAN) <-> MQTT, with Home Assistant auto-discovery.

Runs on an always-on LAN host (the NAS). No cloud. It:
  * exposes the camera's features as HA entities over MQTT (switches, selects,
    PTZ buttons),
  * keeps the live stream up after a camera reboot (restores the "stream" state),
  * syncs the camera's clock over ONVIF (the OSD timestamp) since the WAN is cut.

Config comes from the environment (see mqtt-bridge.env):
  TUYA_ID, TUYA_KEY, CAM_HOST, TUYA_VER
  MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS
  ONVIF_USER, ONVIF_PASS, TZ (e.g. Europe/Paris)

Deps: pip install tinytuya paho-mqtt
"""
import os, sys, json, time, threading, datetime, urllib.request

import tinytuya
import paho.mqtt.client as mqtt

ID   = os.environ["TUYA_ID"]; KEY = os.environ["TUYA_KEY"]
HOST = os.environ.get("CAM_HOST", "192.168.1.34")
VER  = float(os.environ.get("TUYA_VER", "3.5"))
MQTT_HOST = os.environ.get("MQTT_HOST", "192.168.1.50")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER"); MQTT_PASS = os.environ.get("MQTT_PASS")
ONVIF_USER = os.environ.get("ONVIF_USER", "admin")
ONVIF_PASS = os.environ.get("ONVIF_PASS", "")
TZ_OFFSET = int(os.environ.get("TZ_OFFSET_HOURS", "1"))   # Europe/Paris winter = +1

DEV = {"identifiers": ["lsc_ak3918"], "name": "Caméra LSC",
       "manufacturer": "LSC/Anyka", "model": "AK3918 YYOS (local)"}
BASE = "lsccam"; DISC = "homeassistant"
STATE_FILE = os.environ.get("STATE_FILE", "/var/lib/lsccam/state.json")

# --- feature map: dp -> HA entity -------------------------------------------
# kind: switch (bool), switch_inv (bool inverted), select (enum)
SWITCHES = {
    # object_id:      (dp, label, inverted)
    "flux":          ("105", "Flux caméra", True),    # secret_mode inverted
    "mouvement":     ("134", "Détection mouvement", False),
    "led":           ("101", "LED témoin", False),
    "osd":           ("104", "Horodatage à l'image", False),
    "flip":          ("103", "Image retournée", False),
    "suivi":         ("139", "Suivi de mouvement", False),
}
SELECTS = {
    "mode_nuit":     ("108", "Mode nuit",      {"0": "Auto", "1": "Activé", "2": "Désactivé"}),
    "sensibilite":   ("106", "Sensibilité mouvement", {"0": "Basse", "1": "Moyenne", "2": "Haute"}),
}
# PTZ buttons -> (dp119 direction value)
PTZ = {"haut": "0", "droite": "2", "bas": "4", "gauche": "6"}

dev = tinytuya.Device(ID, HOST, KEY, version=VER, connection_timeout=6)
dev.set_socketPersistent(True)
lock = threading.Lock()


def tset(dp, val, stop_after=None):
    with lock:
        try:
            dev.set_value(int(dp), val, nowait=(stop_after is not None))
            if stop_after:
                time.sleep(stop_after); dev.set_value(116, "1")   # ptz_stop
        except Exception as e:
            print("set", dp, val, "err", e, file=sys.stderr)


def tstatus():
    with lock:
        try:
            return dev.status().get("dps", {})
        except Exception:
            return {}


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {"flux_on": True}   # default: streaming on


def save_state(s):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        json.dump(s, open(STATE_FILE, "w"))
    except Exception:
        pass


# --- ONVIF clock sync (SetSystemDateAndTime, WS-Security auth) ---------------
import hashlib, base64

def _wsse():
    nonce = os.urandom(16)
    created = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + ONVIF_PASS.encode()).digest()).decode()
    return (f'<wsse:Security s:mustUnderstand="1" xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">'
            f'<wsse:UsernameToken><wsse:Username>{ONVIF_USER}</wsse:Username>'
            f'<wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</wsse:Password>'
            f'<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
            f'<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security>')

def onvif_set_time():
    now = datetime.datetime.utcnow()
    body = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
            f'<s:Header>{_wsse()}</s:Header>'
            f'<s:Body xmlns:t="http://www.onvif.org/ver10/device/wsdl"><t:SetSystemDateAndTime>'
            f'<t:DateTimeType>Manual</t:DateTimeType><t:DaylightSavings>false</t:DaylightSavings>'
            f'<t:TimeZone><t:TZ>GMT-{TZ_OFFSET:02d}:00:00</t:TZ></t:TimeZone>'
            f'<t:UTCDateTime><t:Time xmlns="http://www.onvif.org/ver10/schema">'
            f'<Hour>{now.hour}</Hour><Minute>{now.minute}</Minute><Second>{now.second}</Second></t:Time>'
            f'<t:Date xmlns="http://www.onvif.org/ver10/schema">'
            f'<Year>{now.year}</Year><Month>{now.month}</Month><Day>{now.day}</Day></t:Date>'
            f'</t:UTCDateTime></t:SetSystemDateAndTime></s:Body></s:Envelope>')
    try:
        req = urllib.request.Request(
            f"http://{HOST}:5000/onvif/device_service", data=body.encode(),
            headers={"Content-Type": "application/soap+xml"})
        urllib.request.urlopen(req, timeout=5).read()
        print("onvif: clock set", now, "UTC"); return True
    except Exception as e:
        print("onvif set time err", e, file=sys.stderr); return False


# --- MQTT discovery ----------------------------------------------------------
def publish_discovery(c):
    for oid, (dp, label, inv) in SWITCHES.items():
        cfg = {"name": label, "unique_id": f"lsccam_{oid}", "device": DEV,
               "state_topic": f"{BASE}/{oid}/state",
               "command_topic": f"{BASE}/{oid}/set",
               "payload_on": "ON", "payload_off": "OFF"}
        c.publish(f"{DISC}/switch/lsccam_{oid}/config", json.dumps(cfg), retain=True)
    for oid, (dp, label, opts) in SELECTS.items():
        cfg = {"name": label, "unique_id": f"lsccam_{oid}", "device": DEV,
               "state_topic": f"{BASE}/{oid}/state",
               "command_topic": f"{BASE}/{oid}/set",
               "options": list(opts.values())}
        c.publish(f"{DISC}/select/lsccam_{oid}/config", json.dumps(cfg), retain=True)
    for oid in list(PTZ) + ["stop"]:
        cfg = {"name": f"PTZ {oid}", "unique_id": f"lsccam_ptz_{oid}", "device": DEV,
               "command_topic": f"{BASE}/ptz/{oid}/set"}
        c.publish(f"{DISC}/button/lsccam_ptz_{oid}/config", json.dumps(cfg), retain=True)


def publish_states(c, dps):
    for oid, (dp, label, inv) in SWITCHES.items():
        if dp in dps:
            v = bool(dps[dp]); v = (not v) if inv else v
            c.publish(f"{BASE}/{oid}/state", "ON" if v else "OFF", retain=True)
    for oid, (dp, label, opts) in SELECTS.items():
        if dp in dps and str(dps[dp]) in opts:
            c.publish(f"{BASE}/{oid}/state", opts[str(dps[dp])], retain=True)


def on_connect(c, u, f, rc, props=None):
    print("mqtt connected", rc)
    publish_discovery(c)
    c.subscribe(f"{BASE}/+/set")
    c.subscribe(f"{BASE}/ptz/+/set")


def on_message(c, u, msg):
    parts = msg.topic.split("/"); payload = msg.payload.decode()
    if parts[1] == "ptz":
        d = parts[2]
        if d == "stop": tset(116, "1")
        elif d in PTZ: tset(119, PTZ[d], stop_after=0.6)
        return
    oid = parts[1]
    if oid in SWITCHES:
        dp, _, inv = SWITCHES[oid]
        on = (payload == "ON"); val = (not on) if inv else on
        tset(dp, val)
        if oid == "flux":
            st = load_state(); st["flux_on"] = on; save_state(st)
    elif oid in SELECTS:
        dp, _, opts = SELECTS[oid]
        rev = {v: k for k, v in opts.items()}
        if payload in rev: tset(dp, rev[payload])


def main():
    c = mqtt.Client()
    if MQTT_USER: c.username_pw_set(MQTT_USER, MQTT_PASS)
    c.on_connect = on_connect; c.on_message = on_message
    c.connect(MQTT_HOST, MQTT_PORT, 60); c.loop_start()

    last_online = False; time_synced_at = 0.0
    while True:
        dps = tstatus()
        online = bool(dps)
        c.publish(f"{BASE}/availability", "online" if online else "offline", retain=True)
        if online:
            publish_states(c, dps)
            # 1) restore the stream first (secret_mode off) so ONVIF/RTSP come up
            st = load_state()
            if not last_online and st.get("flux_on", True) and dps.get("105") is True:
                print("restore stream (secret_mode -> off)")
                tset(105, False)
            # 2) sync the clock once ONVIF is reachable, then hourly
            if time.time() - time_synced_at > 3600 and dps.get("105") is not True:
                if onvif_set_time(): time_synced_at = time.time()
        else:
            time_synced_at = 0.0                  # resync after the camera returns
        last_online = online
        time.sleep(15)


if __name__ == "__main__":
    main()

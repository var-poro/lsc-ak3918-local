#!/usr/bin/env python3
"""
Recover the Tuya device_id + local key OFFLINE from a camera backup.

Decrypts the YYOS / TuyaOS key-value database (config/tuya/tuya_user.db) using
the on-device encryption key (config/tuya/tuya_enckey.db). No cloud, no account.

    pip install cryptography
    python3 recover-local-key.py tuya_user.db tuya_enckey.db

Key derivation + DB layout reverse-engineered from the stock firmware; the same
scheme is used by dev-zetta/LSCamoflash's offline credential recovery.
Output goes to stdout as JSON. Treat it as a secret (don't commit it).
"""
import struct, json, sys
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def derive_key(enckey: bytes) -> bytes:
    assert len(enckey) == 16, "enckey must be 16 bytes"
    halves = enckey[8:] + enckey[:8]              # swap the two 8-byte halves
    return bytes(halves[i ^ 1] for i in range(16))  # then swap adjacent bytes


def decode_db(db: bytes, enckey: bytes) -> dict:
    count = struct.unpack_from("<I", db, 24)[0]
    recs = {}
    cipher = Cipher(algorithms.AES(derive_key(enckey)), modes.ECB())
    for n in range(count):
        p = 28 + n * 56
        active = struct.unpack_from("<I", db, p)[0]
        name = db[p + 4:p + 37].split(b"\0", 1)[0].decode("ascii", "replace")
        off = struct.unpack_from("<I", db, p + 44)[0]
        length = struct.unpack_from("<H", db, p + 48)[0]
        if active != 1 or length == 0 or length % 16:
            continue
        d = cipher.decryptor()
        plain = d.update(db[off:off + length]) + d.finalize()
        pad = plain[-1]
        if 1 <= pad <= 16 and plain[-pad:] == bytes([pad]) * pad:
            plain = plain[:-pad]
        recs[name] = plain
    return recs


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: recover-local-key.py <tuya_user.db> <tuya_enckey.db>")
    db = open(sys.argv[1], "rb").read()
    enc = open(sys.argv[2], "rb").read()
    recs = decode_db(db, enc)
    di = json.loads(recs["gw_di"].rstrip(b"\0")) if "gw_di" in recs else {}
    ai = json.loads(recs["gw_ai"].rstrip(b"\0")) if "gw_ai" in recs else {}
    out = {
        "device_id": di.get("id"),
        "local_key": ai.get("lckey"),
        "firmware": di.get("swv"),
        "protocol": di.get("lpv"),
        "records": sorted(recs.keys()),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Minimal telnet client for the camera's root shell (busybox telnetd -l /bin/sh).
Handles IAC negotiation. Runs ONE command and prints the output.

    CAM_HOST=192.168.1.34 python3 cam.py 'uname -a; id'

The camera's telnet is opened by the SD-card root payload (../sdcard/). It gives
a passwordless root shell on the LAN. Keep it on a trusted network only.

NOTE: this helper reads for a few seconds then disconnects. Never run a long
foreground command (e.g. flashcp) through it directly: the disconnect sends
SIGHUP and kills it. Detach long commands with `busybox nohup ... &` instead.
"""
import socket, sys, os, time

HOST = os.environ.get("CAM_HOST", "192.168.1.34")
PORT = int(os.environ.get("CAM_PORT", "23"))
cmd  = sys.argv[1] if len(sys.argv) > 1 else "id"
WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0


def recv_clean(sock, timeout):
    sock.settimeout(timeout)
    out = bytearray(); buf = b""
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            buf += data
            i = 0; clean = bytearray(); reply = bytearray()
            while i < len(buf):
                b = buf[i]
                if b == 255:                      # IAC
                    if i + 2 >= len(buf):
                        break                     # incomplete, wait for more
                    c, opt = buf[i + 1], buf[i + 2]
                    if c in (253, 251):           # DO / WILL -> refuse
                        reply += bytes([255, 252 if c == 251 else 254, opt])
                    i += 3; continue
                clean.append(b); i += 1
            buf = buf[i:]
            out += clean
            if reply:
                sock.sendall(bytes(reply))
    except socket.timeout:
        pass
    return bytes(out)


def main():
    s = socket.create_connection((HOST, PORT), timeout=5)
    recv_clean(s, 2.0)                            # swallow negotiation + prompt
    s.sendall((cmd + "\n").encode())
    time.sleep(1.0)
    sys.stdout.write(recv_clean(s, WAIT).decode("utf-8", "replace"))
    s.close()


if __name__ == "__main__":
    main()

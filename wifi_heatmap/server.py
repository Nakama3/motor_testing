#!/usr/bin/env python3
"""
WiFi Heatmap - local server.

Reads the current WiFi signal strength (RSSI, in dBm) from the operating
system and serves the browser UI that turns your samples into a 3D map.

Browsers cannot read WiFi signal strength themselves, so this small server
does it for them. Run it on the laptop you carry around the house:

    python3 server.py            # then open http://localhost:8000
    python3 server.py --demo     # simulated signal, to try the app anywhere

Standard library only - no pip installs needed.
"""

import argparse
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# RSSI readers, one per platform. Each returns dict(dbm=..., ssid=..., method=...)
# or raises RuntimeError.
# --------------------------------------------------------------------------

def _run(cmd, timeout=8):
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return out.stdout + "\n" + out.stderr


def pct_to_dbm(pct):
    """Approximate conversion used by Windows/NetworkManager quality %."""
    return round(pct / 2.0 - 100.0, 1)


def read_linux():
    # 1) iw - gives real dBm and the SSID
    if shutil.which("iw"):
        dev_out = _run(["iw", "dev"])
        for iface in re.findall(r"Interface\s+(\S+)", dev_out):
            link = _run(["iw", "dev", iface, "link"])
            m = re.search(r"signal:\s*(-?\d+)\s*dBm", link)
            if m:
                ssid = re.search(r"SSID:\s*(.+)", link)
                return {"dbm": float(m.group(1)),
                        "ssid": ssid.group(1).strip() if ssid else None,
                        "method": f"iw ({iface})"}
    # 2) /proc/net/wireless - level column is dBm on most drivers
    try:
        with open("/proc/net/wireless") as f:
            for line in f.readlines()[2:]:
                parts = line.split()
                if len(parts) >= 4:
                    level = float(parts[3].rstrip("."))
                    if level > 0:  # some drivers report 0..255
                        level -= 256
                    if level < 0:
                        return {"dbm": level, "ssid": None,
                                "method": f"/proc/net/wireless ({parts[0].rstrip(':')})"}
    except OSError:
        pass
    # 3) nmcli - only a 0..100 quality value
    if shutil.which("nmcli"):
        out = _run(["nmcli", "-t", "-f", "IN-USE,SIGNAL,SSID", "dev", "wifi"])
        for line in out.splitlines():
            if line.startswith("*"):
                _, sig, ssid = (line.split(":", 2) + ["", ""])[:3]
                return {"dbm": pct_to_dbm(float(sig)), "ssid": ssid or None,
                        "method": "nmcli (quality %, approximated)"}
    raise RuntimeError("No connected WiFi interface found (tried iw, /proc/net/wireless, nmcli).")


def read_macos():
    # 1) CoreWLAN through PyObjC, if available (fast, accurate)
    try:
        import CoreWLAN  # type: ignore
        iface = CoreWLAN.CWWiFiClient.sharedWiFiClient().interface()
        rssi = iface.rssiValue()
        if rssi:
            return {"dbm": float(rssi), "ssid": iface.ssid(), "method": "CoreWLAN"}
    except Exception:
        pass
    # 2) legacy airport tool (removed in macOS 14.4+)
    airport = ("/System/Library/PrivateFrameworks/Apple80211.framework/"
               "Versions/Current/Resources/airport")
    if os.path.exists(airport):
        out = _run([airport, "-I"])
        m = re.search(r"agrCtlRSSI:\s*(-?\d+)", out)
        if m:
            ssid = re.search(r"\sSSID:\s*(.+)", out)
            return {"dbm": float(m.group(1)),
                    "ssid": ssid.group(1).strip() if ssid else None,
                    "method": "airport"}
    # 3) system_profiler - slow (a few seconds) but needs no extras
    out = _run(["system_profiler", "SPAirPortDataType"], timeout=20)
    sec = out.split("Current Network Information:", 1)
    if len(sec) == 2:
        m = re.search(r"Signal / Noise:\s*(-?\d+)\s*dBm", sec[1])
        if m:
            ssid = re.search(r"^\s*(.+?):\s*$", sec[1].strip("\n"), re.M)
            return {"dbm": float(m.group(1)),
                    "ssid": ssid.group(1).strip() if ssid else None,
                    "method": "system_profiler (slow; `pip install pyobjc-framework-CoreWLAN` for speed)"}
    raise RuntimeError("Could not read WiFi signal on macOS. Is WiFi connected?")


def read_windows():
    out = _run(["netsh", "wlan", "show", "interfaces"])
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    ssid = ssid.group(1).strip() if ssid else None
    m = re.search(r"^\s*Rssi\s*:\s*(-?\d+)", out, re.M | re.I)  # newer Windows 11
    if m:
        return {"dbm": float(m.group(1)), "ssid": ssid, "method": "netsh (Rssi)"}
    m = re.search(r"^\s*Signal\s*:\s*(\d+)\s*%", out, re.M)
    if m:
        return {"dbm": pct_to_dbm(float(m.group(1))), "ssid": ssid,
                "method": "netsh (Signal %, approximated)"}
    raise RuntimeError("Could not read WiFi signal from `netsh wlan show interfaces`.")


def read_demo(q):
    """Simulated log-distance path loss from the router plus walls and noise."""
    def f(name, default=0.0):
        try:
            return float(q.get(name, [default])[0])
        except ValueError:
            return default
    x, y, z = f("x"), f("y"), f("z")
    rx, ry, rz = f("rx", 0), f("ry", 0), f("rz", 1)
    d = max(0.5, math.dist((x, y, z), (rx, ry, rz)))
    floors_between = abs(int(z // 2.7) - int(rz // 2.7))
    walls = int(abs(x - rx) // 4) + int(abs(y - ry) // 4)
    dbm = -32 - 28 * math.log10(d) - 4 * walls - 12 * floors_between
    dbm += 3 * math.sin(x * 1.7) * math.cos(y * 1.3) + random.gauss(0, 1.5)
    return {"dbm": round(max(-98.0, min(-25.0, dbm)), 1), "ssid": "DemoNet",
            "method": "demo (simulated)"}


def read_rssi(demo=False, query=None):
    if demo:
        return read_demo(query or {})
    system = platform.system()
    if system == "Linux":
        return read_linux()
    if system == "Darwin":
        return read_macos()
    if system == "Windows":
        return read_windows()
    raise RuntimeError(f"Unsupported platform: {system}")


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------

def lan_ip():
    """Best guess at this machine's address on the home network."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


class Handler(BaseHTTPRequestHandler):
    demo = False
    project_file = os.path.join(HERE, "project.json")
    pose = None  # latest pose from the iPhone tracker app

    def log_message(self, fmt, *args):  # quieter console
        line = str(args[0]) if args else ""
        if "/api/rssi" not in line and "/api/pose" not in line:
            sys.stderr.write("%s\n" % (fmt % args))

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if url.path == "/api/rssi":
            q = parse_qs(url.query)
            n = max(1, min(20, int(q.get("n", ["1"])[0])))
            readings, info = [], None
            try:
                for i in range(n):
                    info = read_rssi(self.demo, q)
                    readings.append(info["dbm"])
                    if i < n - 1:
                        time.sleep(0.25 if not self.demo else 0.02)
            except Exception as e:  # report the reason to the UI
                return self._send(503, json.dumps({"error": str(e)}))
            readings.sort()
            median = readings[len(readings) // 2]
            return self._send(200, json.dumps({
                "dbm": median, "readings": readings, "ssid": info["ssid"],
                "method": info["method"], "demo": self.demo}))
        if url.path == "/api/pose":
            p = Handler.pose
            if p is None:
                return self._send(200, "null")
            return self._send(200, json.dumps({**p, "age": round(time.time() - p["received"], 3)}))
        if url.path == "/api/project":
            if os.path.exists(self.project_file):
                with open(self.project_file, "rb") as f:
                    return self._send(200, f.read())
            return self._send(200, "null")
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if path == "/api/pose":  # from the iPhone tracker app
            try:
                j = json.loads(body)
                Handler.pose = {"x": float(j["x"]), "y": float(j["y"]), "z": float(j["z"]),
                                "ok": bool(j.get("ok", True)), "state": str(j.get("state", ""))[:80],
                                "session": str(j.get("session", ""))[:64], "received": time.time()}
            except (ValueError, KeyError, TypeError):
                return self._send(400, json.dumps({"error": "bad pose"}))
            return self._send(200, json.dumps({"ok": True}))
        if path != "/api/project":
            return self._send(404, json.dumps({"error": "not found"}))
        try:
            json.loads(body)
        except ValueError:
            return self._send(400, json.dumps({"error": "invalid JSON"}))
        tmp = self.project_file + ".tmp"
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, self.project_file)
        self._send(200, json.dumps({"ok": True}))


def main():
    ap = argparse.ArgumentParser(description="WiFi signal heatmap server")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1",
                    help="use 0.0.0.0 to open the UI from another device on your LAN")
    ap.add_argument("--demo", action="store_true", help="simulate signal strength")
    ap.add_argument("--project", default=os.path.join(HERE, "project.json"),
                    help="where samples are auto-saved")
    args = ap.parse_args()

    Handler.demo = args.demo
    Handler.project_file = os.path.abspath(args.project)

    if not args.demo:
        try:
            r = read_rssi()
            print(f"WiFi OK: {r['dbm']} dBm on {r['ssid'] or '?'} via {r['method']}")
        except Exception as e:
            print(f"WARNING: could not read WiFi signal yet: {e}")
            print("         (the UI still works with manual entry, or restart with --demo)")
    else:
        print("Demo mode: signal strength is simulated.")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Open http://localhost:{args.port}  (Ctrl+C to stop)")
    if args.host in ("0.0.0.0", "::"):
        ip = lan_ip()
        print(f"iPhone tracker app: enter  {ip or '<this computer IP>'}:{args.port}  as the laptop address")
    else:
        print("To use the iPhone tracker app, restart with  --host 0.0.0.0")
    print(f"Samples auto-save to {Handler.project_file}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

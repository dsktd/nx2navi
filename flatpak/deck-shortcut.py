#!/usr/bin/env python3
"""Add or refresh the "NX2navi" entry in Steam's shortcuts.vdf (runs on the Steam Deck, python3 only).

    deck-shortcut.py [--steam ~/.local/share/Steam] [--exe /usr/bin/flatpak] [--options "run io.github.dsktd.NX2navi"]

Writes every user's config/shortcuts.vdf (a .bak beside it), refuses while Steam runs: Steam keeps the file in memory
and overwrites it on exit. Uses the `vdf` module when installed, else the small binary-VDF reader and writer below.
"""

import argparse
import os
import subprocess
import sys
import zlib

NAME = "NX2navi"


# Binary VDF (the KeyValues format): a map is a sequence of typed entries, ended by 0x08.
# 0x00 <key>\0 <map>    0x01 <key>\0 <string>\0    0x02 <key>\0 <int32 LE>
def load(data):
    pos = 0

    def read_str():
        nonlocal pos
        end = data.index(b"\0", pos)
        s = data[pos:end].decode("utf-8", "surrogateescape")
        pos = end + 1
        return s

    def read_map():
        nonlocal pos
        out = {}
        while True:
            t = data[pos]
            pos += 1
            if t == 0x08:
                return out
            key = read_str()
            if t == 0x00:
                out[key] = read_map()
            elif t == 0x01:
                out[key] = read_str()
            elif t == 0x02:
                out[key] = int.from_bytes(data[pos : pos + 4], "little", signed=True)
                pos += 4
            else:
                raise ValueError(f"unknown vdf type 0x{t:02x} at {pos - 1}")

    return read_map()


def dump(obj):
    out = bytearray()
    for key, val in obj.items():
        k = key.encode("utf-8", "surrogateescape") + b"\0"
        if isinstance(val, dict):
            out += b"\0" + k + dump(val)
        elif isinstance(val, int):
            out += b"\x02" + k + val.to_bytes(4, "little", signed=True)
        else:
            out += b"\x01" + k + val.encode("utf-8", "surrogateescape") + b"\0"
    out += b"\x08"
    return bytes(out)


try:
    import vdf  # SteamOS does not ship it; used when present

    load, dump = vdf.binary_loads, vdf.binary_dumps
except ImportError:
    pass


def appid(exe, name):
    # what Steam derives for a non-Steam game: crc32 of exe+name with the top bit set, stored as int32
    v = (zlib.crc32((exe + name).encode()) | 0x80000000) & 0xFFFFFFFF
    return v - (1 << 32) if v >= 1 << 31 else v


def entry(exe, start_dir, options):
    return {
        "appid": appid(exe, NAME),
        "AppName": NAME,
        "Exe": exe,
        "StartDir": start_dir,
        "icon": "",
        "ShortcutPath": "",
        "LaunchOptions": options,
        "IsHidden": 0,
        "AllowDesktopConfig": 1,
        "AllowOverlay": 1,
        "OpenVR": 0,
        "Devkit": 0,
        "DevkitGameID": "",
        "DevkitOverrideAppID": 0,
        "LastPlayTime": 0,
        "FlatpakAppID": "",
        "tags": {},
    }


def upsert(path, new):
    data = {"shortcuts": {}}
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = load(f.read())
    shortcuts = data.setdefault("shortcuts", {})
    for v in shortcuts.values():
        if isinstance(v, dict) and v.get("AppName", v.get("appname")) == NAME:
            for f in ("Exe", "StartDir", "LaunchOptions"):  # keep Steam's appid, artwork, tags and play time
                v[f] = new[f]
            action = "updated"
            break
    else:
        shortcuts[str(max([int(k) for k in shortcuts if k.isdigit()] + [-1]) + 1)] = new
        action = "added"
    if os.path.exists(path):
        os.replace(path, path + ".bak")
    with open(path + ".tmp", "wb") as f:
        f.write(dump(data))
    os.replace(path + ".tmp", path)
    return action


def steam_running():
    try:
        return subprocess.run(["pgrep", "-x", "steam"], check=False, capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steam", default=os.path.expanduser("~/.local/share/Steam"))
    ap.add_argument("--exe", default="/usr/bin/flatpak")
    ap.add_argument("--start-dir", default=os.path.expanduser("~"))
    ap.add_argument("--options", default="run io.github.dsktd.NX2navi")
    ap.add_argument("--force", action="store_true", help="write even while Steam runs (it will overwrite the file)")
    a = ap.parse_args()
    if steam_running() and not a.force:
        print("deck-shortcut: Steam is running; switch to Desktop Mode and quit Steam first", file=sys.stderr)
        return 2
    userdata = os.path.join(a.steam, "userdata")
    users = [u for u in (os.listdir(userdata) if os.path.isdir(userdata) else []) if u.isdigit() and u != "0"]
    users = [u for u in users if os.path.isdir(os.path.join(userdata, u, "config"))]
    if not users:
        print(f"deck-shortcut: no Steam user under {userdata} (log in to Steam once)", file=sys.stderr)
        return 3
    new = entry(f'"{a.exe}"', f'"{a.start_dir}"', a.options)
    for u in users:
        path = os.path.join(userdata, u, "config", "shortcuts.vdf")
        print(f"{upsert(path, new)} {NAME} in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

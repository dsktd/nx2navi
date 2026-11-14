#!/usr/bin/env python3
"""pick_test.py: pick.py's input handling fed with SDL3 event structs built here (no SDL, no devices).

    python3 -I tools/deck/pick_test.py
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pick  # noqa: E402

GAMEPADS = {2}  # device ids SDL has a mapping for; 5 is a bare joystick (hat D-pad)


def ev(t, which=0, b20=0, b21=0, key=0):
    head = struct.pack("<IIQI", t, 0, 0, which) + bytes([b20, b21]) + bytes(6) + struct.pack("<I", key)
    return head + bytes(128 - len(head))


def pad(button):
    return ev(pick.EV_PAD_DOWN, 2, button)


def hat(value, which=5):
    return ev(pick.EV_JOY_HAT, which, 0, value)


def run(events, start=0):
    """The selection after the events and the pick (key) or 'quit' or None, as main()'s loop does it."""
    keys = [k for k, _ in pick.CHOICES]
    sel = start
    for e in events:
        _, _, move, act = pick.handle(e, lambda w: w in GAMEPADS)
        sel = (sel + move) % len(keys)
        if act == -1:
            return sel, "quit"
        if act == 1:
            return sel, keys[sel]
    return sel, None


def main():
    down, up, a, b = pad(pick.PAD_DOWN), pad(pick.PAD_UP), pad(pick.PAD_A), pad(pick.PAD_B)
    noise = [ev(0x650, 2, 1), ev(0x659, 2), ev(0x65A, 2), ev(0x600, 2), ev(0x602, 2, 0, 4)]  # axis, sensor, update, a mapped pad's hat
    cases = [
        ("5 down 5 up A (buttons)", [down] * 5 + [up] * 5 + [a], pick.CHOICES[0][0]),
        ("down A", [down, a], pick.CHOICES[1][0]),
        ("down down A", [down, down, a], pick.CHOICES[2][0]),
        ("up A wraps to the last", [up, a], pick.CHOICES[3][0]),
        ("noise between presses", [down] + noise * 200 + [down] + noise + [a], pick.CHOICES[2][0]),
        ("B quits", [down, down, b], "quit"),
        ("hat of an unmapped pad", [hat(4), hat(0), hat(4), hat(0), hat(1), hat(0), pad(pick.PAD_A)], pick.CHOICES[1][0]),
        ("keyboard", [ev(pick.EV_KEY_DOWN, key=pick.KEY_DOWN), ev(pick.EV_KEY_DOWN, key=pick.KEY_RETURN)], pick.CHOICES[1][0]),
        ("window quit", [ev(pick.EV_QUIT)], "quit"),
        ("axis 1 is not B", [ev(0x650, 2, 1)] * 50 + [a], pick.CHOICES[0][0]),
    ]
    bad = 0
    for name, events, want in cases:
        got = run(events)[1]
        ok = got == want
        bad += not ok
        print(("ok  " if ok else "FAIL"), name, "->", got, "" if ok else f"(want {want})")
    kinds = [pick.handle(ev(pick.EV_PAD_ADDED, 2), lambda w: True)[0], pick.handle(ev(pick.EV_JOY_ADDED, 5), lambda w: False)[0],
             pick.handle(ev(pick.EV_JOY_ADDED, 2), lambda w: True)[0]]
    ok = kinds == ["pad", "joy", None]
    bad += not ok
    print(("ok  " if ok else "FAIL"), "opens: gamepad, bare joystick, not a mapped pad twice ->", kinds)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

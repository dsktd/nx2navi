#!/usr/bin/env python3
"""pick.py: the build picker of the "NX2navi" Steam entry (play.sh runs it when Steam starts the entry).

A fullscreen SDL3 window (SteamOS's /usr/lib/libSDL3.so.0 through ctypes, text by SDL_RenderDebugText): D-pad or arrow
keys move, A or Enter starts, B or Escape quits. Prints the chosen key on stdout and exits 0; quitting exits 1.
The last pick is the default next time (~/nx2navi/pick.last).
"""
import ctypes as C
import os
import sys

CHOICES = [
    ("slim2", "NX2navi slim2"),
    ("stutter", "NX2navi slim2 + stutter map"),
    ("deck5", "NX2navi deck5 (fallback)"),
    ("upstream", "NX2navi upstream v0.10.1"),
]
LAST = os.path.expanduser("~/nx2navi/pick.last")
AUTO = os.path.expanduser("~/nx2navi/pick.auto")

INIT_VIDEO, INIT_GAMEPAD = 0x20, 0x2000
EV_QUIT, EV_KEY_DOWN, EV_PAD_DOWN, EV_PAD_ADDED = 0x100, 0x300, 0x651, 0x653  # 0x650 is axis motion
EV_JOY_HAT, EV_JOY_ADDED, HAT_UP, HAT_DOWN = 0x602, 0x605, 0x01, 0x04
PAD_A, PAD_B, PAD_UP, PAD_DOWN = 0, 1, 11, 12
KEY_UP, KEY_DOWN, KEY_RETURN, KEY_ESCAPE = 0x40000052, 0x40000051, 0x0D, 0x1B


def load_sdl():
    sdl = C.CDLL("/usr/lib/libSDL3.so.0")
    sdl.SDL_CreateWindow.restype = C.c_void_p
    sdl.SDL_CreateWindow.argtypes = [C.c_char_p, C.c_int, C.c_int, C.c_uint64]
    sdl.SDL_CreateRenderer.restype = C.c_void_p
    sdl.SDL_CreateRenderer.argtypes = [C.c_void_p, C.c_char_p]
    sdl.SDL_SetRenderDrawColor.argtypes = [C.c_void_p] + [C.c_uint8] * 4
    sdl.SDL_RenderClear.argtypes = [C.c_void_p]
    sdl.SDL_RenderPresent.argtypes = [C.c_void_p]
    sdl.SDL_SetRenderScale.argtypes = [C.c_void_p, C.c_float, C.c_float]
    sdl.SDL_RenderDebugText.argtypes = [C.c_void_p, C.c_float, C.c_float, C.c_char_p]
    sdl.SDL_OpenGamepad.restype = C.c_void_p
    sdl.SDL_OpenGamepad.argtypes = [C.c_uint32]
    sdl.SDL_PollEvent.restype = C.c_bool
    sdl.SDL_PollEvent.argtypes = [C.c_void_p]
    sdl.SDL_IsGamepad.restype = C.c_bool
    sdl.SDL_IsGamepad.argtypes = [C.c_uint32]
    sdl.SDL_OpenJoystick.restype = C.c_void_p
    sdl.SDL_OpenJoystick.argtypes = [C.c_uint32]
    sdl.SDL_Delay.argtypes = [C.c_uint32]
    sdl.SDL_Init.restype = C.c_bool
    sdl.SDL_GetRenderOutputSize.argtypes = [C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)]
    return sdl


def draw(sdl, ren, sel):
    w, h = C.c_int(), C.c_int()
    sdl.SDL_GetRenderOutputSize(ren, C.byref(w), C.byref(h))
    scale = max(1, min(h.value // 200, w.value // (8 * 46)))  # the debug font is 8x8: 25 lines, the longest line fits
    sdl.SDL_SetRenderScale(ren, scale, scale)
    sdl.SDL_SetRenderDrawColor(ren, 12, 14, 20, 255)
    sdl.SDL_RenderClear(ren)
    x, y = 16, 16
    sdl.SDL_SetRenderDrawColor(ren, 150, 160, 180, 255)
    sdl.SDL_RenderDebugText(ren, x, y, b"NX2navi: pick a build")
    for i, (_, label) in enumerate(CHOICES):
        on = i == sel
        sdl.SDL_SetRenderDrawColor(ren, *((255, 220, 120) if on else (200, 200, 200)), 255)
        sdl.SDL_RenderDebugText(ren, x, y + 24 + 14 * i, (("> " if on else "  ") + label).encode())
    sdl.SDL_SetRenderDrawColor(ren, 120, 130, 150, 255)
    sdl.SDL_RenderDebugText(ren, x, y + 34 + 14 * len(CHOICES), b"D-pad: move   A: start   B: back to Steam")
    sdl.SDL_RenderPresent(ren)


def handle(ev, is_gamepad):
    """One SDL_Event (its bytes) -> (open "pad"|"joy"|None, device id, move -1/0/1, act -1 quit/0/1 start).
    Every event type not named here is ignored (axis motion 0x650, sensors, touchpads, window events)."""
    t = int.from_bytes(ev[0:4], "little")
    which = int.from_bytes(ev[16:20], "little")
    if t == EV_QUIT:
        return None, which, 0, -1
    if t == EV_PAD_ADDED:
        return "pad", which, 0, 0
    if t == EV_JOY_ADDED and not is_gamepad(which):
        return "joy", which, 0, 0
    if t == EV_PAD_DOWN:
        b = ev[20]
        return None, which, -1 if b == PAD_UP else 1 if b == PAD_DOWN else 0, 1 if b == PAD_A else -1 if b == PAD_B else 0
    if t == EV_JOY_HAT and not is_gamepad(which):
        return None, which, -1 if ev[21] & HAT_UP else 1 if ev[21] & HAT_DOWN else 0, 0
    if t == EV_KEY_DOWN:
        k = int.from_bytes(ev[28:32], "little")
        return None, which, -1 if k == KEY_UP else 1 if k == KEY_DOWN else 0, 1 if k == KEY_RETURN else -1 if k == KEY_ESCAPE else 0
    return None, which, 0, 0


def main():
    keys = [k for k, _ in CHOICES]
    try:
        sel = keys.index(open(LAST).read().strip())
    except (OSError, ValueError):
        sel = 0
    sdl = load_sdl()
    if not sdl.SDL_Init(INIT_VIDEO | INIT_GAMEPAD):
        return 2
    win = sdl.SDL_CreateWindow(b"NX2navi", 1280, 800, 0x1)  # SDL_WINDOW_FULLSCREEN
    ren = sdl.SDL_CreateRenderer(win, None)
    ev = (C.c_uint8 * 128)()
    pick = None
    dirty, running, rounds = True, True, 0
    # Test hook: ~/nx2navi/pick.auto holding a row number (1-based) is read once, deleted, and picks that row after
    # about 2 s on screen, as if A were pressed there (lets a test start every entry through the real Steam launch).
    auto = None
    try:
        auto = int(open(AUTO).read().strip()) - 1
        os.unlink(AUTO)
    except (OSError, ValueError):
        pass
    # Poll, never block: the Deck's own pad sends thousands of axis and sensor events a second, so every event is
    # drained each round, unknown ones ignored, and the screen drawn once a round only after a change (a draw per
    # event made the queue grow behind vsync: the menu froze after a few presses).
    while running and pick is None:
        while sdl.SDL_PollEvent(ev):
            kind, which, move, act = handle(bytes(ev), sdl.SDL_IsGamepad)
            if kind == "pad":
                sdl.SDL_OpenGamepad(which)
            elif kind == "joy":
                sdl.SDL_OpenJoystick(which)  # a pad SDL has no mapping for: its hat events count
            if move:
                sel, dirty = (sel + move) % len(CHOICES), True
            if act == -1:
                running = False
            elif act == 1 and pick is None:
                pick = keys[sel]
        rounds += 1
        if auto is not None and rounds == 120 and 0 <= auto < len(keys):
            sel, pick = auto, keys[auto]
        if dirty or rounds % 30 == 0:  # and twice a second, for a compositor that dropped a frame
            draw(sdl, ren, sel)
            dirty = False
        sdl.SDL_Delay(16)
    sdl.SDL_Quit()
    if pick is None:
        return 1
    try:
        with open(LAST + ".tmp", "w") as f:
            f.write(pick + "\n")
        os.replace(LAST + ".tmp", LAST)
    except OSError:
        pass
    print(pick)
    return 0


if __name__ == "__main__":
    sys.exit(main())

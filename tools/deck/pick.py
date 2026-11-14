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
    ("deck5", "NX2navi deck5"),
    ("stutter", "NX2navi deck5 + stutter map"),
    ("deck4", "NX2navi deck4 (previous)"),
    ("upstream", "NX2navi upstream v0.10.1"),
]
LAST = os.path.expanduser("~/nx2navi/pick.last")

INIT_VIDEO, INIT_GAMEPAD = 0x20, 0x2000
EV_QUIT, EV_KEY_DOWN, EV_PAD_DOWN, EV_PAD_ADDED = 0x100, 0x300, 0x651, 0x653  # 0x650 is axis motion
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
    sdl.SDL_WaitEventTimeout.argtypes = [C.c_void_p, C.c_int32]
    sdl.SDL_GetRenderOutputSize.argtypes = [C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)]
    return sdl


def draw(sdl, ren, sel):
    w, h = C.c_int(), C.c_int()
    sdl.SDL_GetRenderOutputSize(ren, C.byref(w), C.byref(h))
    scale = max(1, h.value // 200)  # the debug font is 8x8: about 25 lines a screen
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
    while pick is None:
        draw(sdl, ren, sel)
        if not sdl.SDL_WaitEventTimeout(ev, 500):
            continue
        t = int.from_bytes(bytes(ev[0:4]), "little")
        move = act = 0
        if t == EV_QUIT:
            break
        if t == EV_PAD_ADDED:
            sdl.SDL_OpenGamepad(int.from_bytes(bytes(ev[16:20]), "little"))
        elif t == EV_PAD_DOWN:
            b = ev[20]
            move = -1 if b == PAD_UP else 1 if b == PAD_DOWN else 0
            act = 1 if b == PAD_A else -1 if b == PAD_B else 0
        elif t == EV_KEY_DOWN:
            k = int.from_bytes(bytes(ev[28:32]), "little")
            move = -1 if k == KEY_UP else 1 if k == KEY_DOWN else 0
            act = 1 if k == KEY_RETURN else -1 if k == KEY_ESCAPE else 0
        sel = (sel + move) % len(CHOICES)
        if act == -1:
            break
        if act == 1:
            pick = keys[sel]
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

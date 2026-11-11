"""Cross-reference the strings in the game's main to the lifted functions that load their address.

    strxref.py [--grep REGEX] [--out build/v111/re/strxref.tsv]

Reads generated/v111/main/*.c (the lift) and build/extracted/v111/exefs/main (through recomp/nso.py). An ADRP+ADD
pair lifts to `r = (uint64_t)(0x<page>ull);` then `r = (uint64_t)(r + 0x<off>ull);`; every such address that holds a
NUL-terminated printable UTF-8 string of 4+ bytes is one row: function, string address, string. The TSV is derived
from game code, so it stays under build/. Run with NX2navi/.venv/bin/python (lz4).
"""

import argparse
import re
import sys
from pathlib import Path

TREE = Path.home() / "claude/nx2navi/NX2navi"
BASE = 0x7000000000
FUNC = re.compile(r"^void (f_[0-9a-f]+)\(Cpu \*c\) \{")
PAGE = re.compile(r"^\s*(\S+) = \(uint64_t\)\((0x[0-9a-f]+)ull\);")
ADD = re.compile(r"^\s*(\S+) = \(uint64_t\)\((\S+) \+ (0x[0-9a-f]+)ull\);")


def load_image():
    sys.path.insert(0, str(TREE / "recomp"))
    from nso import Nso

    return Nso(str(TREE / "build/extracted/v111/exefs/main")).image


def string_at(image, addr):
    at = addr - BASE
    if not 0 <= at < len(image):
        return None
    end = image.find(b"\0", at, at + 512)
    if end - at < 4:
        return None
    try:
        s = image[at:end].decode()
    except UnicodeDecodeError:
        return None
    return s if s.isprintable() else None


def address_loads(path):
    """(function, address) of every ADRP+ADD pair in one lifted file."""
    func, pages = None, {}
    for line in path.open(errors="replace"):
        m = FUNC.match(line)
        if m:
            func, pages = m[1], {}
            continue
        m = ADD.match(line)
        if m and m[2] in pages:
            yield func, pages.pop(m[2]) + int(m[3], 16)
            continue
        m = PAGE.match(line)
        if m and int(m[2], 16) & 0xFFF == 0:
            pages[m[1]] = int(m[2], 16)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--grep", help="print only rows whose string matches")
    ap.add_argument("--out", type=Path, default=TREE / "build/v111/re/strxref.tsv")
    args = ap.parse_args()
    image = load_image()
    rows = set()
    for path in sorted((TREE / "generated/v111/main").glob("*.c")):
        for func, addr in address_loads(path):
            s = string_at(image, addr)
            if s is not None:
                rows.add((func, addr, s))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as out:
        for func, addr, s in sorted(rows):
            out.write(f"{func}\t{addr:#x}\t{s}\n")
    print(f"{len(rows)} rows -> {args.out}", file=sys.stderr)
    if args.grep:
        pattern = re.compile(args.grep)
        for func, addr, s in sorted(rows):
            if pattern.search(s):
                print(f"{func}\t{addr:#x}\t{s}")


if __name__ == "__main__":
    main()

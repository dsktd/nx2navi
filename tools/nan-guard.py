#!/usr/bin/env python3
"""NaN guard for translated shaders in the NX2navi shader cache (a stopgap, not a fix).

Every OpImageWrite of a vec4 texel gets NMax(texel, 0): a NaN channel is written as 0 (GLSL.std.450 NMax returns the
non-NaN operand) and negatives are clamped, which unsigned formats like r11g11b10f do anyway. Used on the volumetric
fog light-injection compute shader, whose NaN output blacks the whole picture at the first outdoor scene
(NOTES-fog-nan.md). The cache file keeps its name, so the runtime loads the guarded SPIR-V; the original is kept as
<name>.spv.orig (restore it with --restore).

    nan-guard.py <cache-dir> --sha256 <hex of the original .spv> [--restore]

Needs spirv-dis, spirv-as and spirv-val on PATH (the nx2navi dev shell).
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path


def run(*cmd, data=None):
    return subprocess.run(cmd, input=data, capture_output=True, check=True).stdout


def guard(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    glsl = next(m.group(1) for ln in lines if (m := re.match(r'(%\S+) = OpExtInstImport "GLSL\.std\.450"', ln)))
    floats = {m.group(1) for ln in lines if (m := re.match(r"(%\S+) = OpTypeFloat 32$", ln))}
    vec4 = next(
        m.group(1)
        for ln in lines
        if (m := re.match(r"(%\S+) = OpTypeVector (%\S+) 4$", ln)) and m.group(2) in floats
    )
    rtype = {m.group(1): m.group(2) for ln in lines if (m := re.match(r"(%\S+) = Op\w+ (%\S+)", ln))}
    out, n = [], 0
    for ln in lines:
        m = re.match(r"OpImageWrite (%\S+) (%\S+) (%\S+)(.*)$", ln)
        if m and rtype.get(m.group(3)) == vec4:
            n += 1
            fixed = f"%nan_guard_{n}"
            out.append(f"{fixed} = OpExtInst {vec4} {glsl} NMax {m.group(3)} %nan_guard_zero")
            ln = f"OpImageWrite {m.group(1)} {m.group(2)} {fixed}{m.group(4)}"
        out.append(ln)
        if re.match(rf"{re.escape(vec4)} = OpTypeVector ", ln):
            out.append(f"%nan_guard_zero = OpConstantNull {vec4}")
    return "\n".join(out) + "\n", n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cache", type=Path)
    ap.add_argument("--sha256", required=True)
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()
    if a.restore:
        for orig in sorted(a.cache.glob("*.spv.orig")):
            if hashlib.sha256(orig.read_bytes()).hexdigest() == a.sha256:
                shutil.move(orig, orig.with_suffix(""))
                print(f"restored {orig.with_suffix('').name}")
        return 0
    targets = [p for p in sorted(a.cache.glob("*.spv")) if hashlib.sha256(p.read_bytes()).hexdigest() == a.sha256]
    if not targets:
        print(f"nan-guard: no .spv with sha256 {a.sha256[:16]}.. in {a.cache} (already guarded, or not translated yet)")
        return 0
    src = run("spirv-dis", "--no-indent", "--raw-id", str(targets[0])).decode()
    text, n = guard(src)
    spv = run("spirv-as", "--target-env", "vulkan1.1", "-o", "-", "-", data=text.encode())
    run("spirv-val", "--target-env", "vulkan1.1", "-", data=spv)
    for p in targets:
        orig = p.with_suffix(".spv.orig")
        if not orig.exists():
            shutil.copy2(p, orig)
        p.write_bytes(spv)
        print(f"guarded {p.name}: {n} image writes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

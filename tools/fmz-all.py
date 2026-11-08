#!/usr/bin/env python3
"""Blanket FMZ test pass (NOTES-fog-nan.md, frame 1100 ambient): every scalar OpFMul and GLSL Fma gets FMZ semantics,
0 * x = 0 even for inf/NaN x. Superset of fmz-pow.py (the pow multiply is an OpFMul). Diagnostic: the SPIR-V does not
say which guest multiplies had .FMZ, so this applies it to all of them.

    fmz-all.py <cache-file.spv>...   (source: <name>.orig if present, else the file; writes via temp + rename, so a
                                      hard-linked cache copy never touches the original's inode)
"""
import os
import re
import subprocess
import sys
from pathlib import Path


def run(*cmd, data=None):
    return subprocess.run(cmd, input=data, capture_output=True, check=True).stdout


def fix(text: str) -> tuple[str, int]:
    lines = [ln.strip() for ln in text.splitlines()]
    flt = next(m.group(1) for ln in lines if (m := re.match(r"(%\S+) = OpTypeFloat 32$", ln)))
    boo = next((m.group(1) for ln in lines if (m := re.match(r"(%\S+) = OpTypeBool$", ln))), None)
    out, n = [], 0
    for ln in lines:
        mul = re.match(rf"(%\S+) = OpFMul {flt} (%\S+) (%\S+)$", ln)
        fma = re.match(rf"(%\S+) = OpExtInst {flt} (%\S+) Fma (%\S+) (%\S+) (%\S+)$", ln)
        if mul or fma:
            n += 1
            r, a, b = (mul or fma).group(1), *(mul.groups()[1:] if mul else fma.group(3, 4))
            out += [
                f"%fmz_a{n} = OpFOrdEqual %fmz_bool {a} %fmz_zero",
                f"%fmz_b{n} = OpFOrdEqual %fmz_bool {b} %fmz_zero",
                f"%fmz_o{n} = OpLogicalOr %fmz_bool %fmz_a{n} %fmz_b{n}",
                f"%fmz_p{n} = " + ln.split(" = ", 1)[1],
                f"{r} = OpSelect {flt} %fmz_o{n} {'%fmz_zero' if mul else fma.group(5)} %fmz_p{n}",
            ]
            continue
        out.append(ln)
        if ln == f"{flt} = OpTypeFloat 32":
            out.append(f"%fmz_zero = OpConstant {flt} 0")
            if not boo:
                out.append("%fmz_bool = OpTypeBool")
    text = "\n".join(out) + "\n"
    return text.replace("%fmz_bool", boo) if boo else text, n


def main() -> int:
    for f in map(Path, sys.argv[1:]):
        orig = f.with_name(f.name + ".orig")
        src = orig if orig.exists() else f
        new, n = fix(run("spirv-dis", "--no-indent", "--no-header", str(src)).decode())
        spv = run("spirv-as", "--target-env", "vulkan1.1", "--preserve-numeric-ids", "-o", "-", "-", data=new.encode())
        run("spirv-val", "--target-env", "vulkan1.1", "-", data=spv)
        tmp = f.with_name(f.name + ".fmzall.tmp")
        tmp.write_bytes(spv)
        os.replace(tmp, f)
        print(f"{f.name}: {n} multiplies get FMZ")
    return 0


if __name__ == "__main__":
    sys.exit(main())

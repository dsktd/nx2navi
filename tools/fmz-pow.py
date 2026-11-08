#!/usr/bin/env python3
"""FMZ pow fix for translated shaders in the NX2navi shader cache (NOTES-fog-nan.md).

NVIDIA's compiler builds pow(x, y) as MUFU.LG2; FMUL.FMZ; MUFU.EX2. FMZ makes 0 * anything = +0, so pow(0, 0) = 1.
The vendored Ryujinx decoder reads the Fmz field but no emitter uses it, so the SPIR-V does an IEEE multiply:
log2(0) * 0 = -inf * 0 = NaN. This rewrites every OpFMul that takes a Log2 result and feeds an Exp2 into
(a == 0 || b == 0) ? 0 : a * b. Each file is rewritten from <name>.orig (made on first use), so it is idempotent.

    fmz-pow.py <cache-file.spv>...       (restore: copy each .orig over its name)

Needs spirv-dis, spirv-as and spirv-val on PATH (the nx2navi dev shell).
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path


def run(*cmd, data=None):
    return subprocess.run(cmd, input=data, capture_output=True, check=True).stdout


def fix(text: str) -> tuple[str, int]:
    lines = [ln.strip() for ln in text.splitlines()]
    flt = next(m.group(1) for ln in lines if (m := re.match(r"(%\S+) = OpTypeFloat 32$", ln)))
    boo = next((m.group(1) for ln in lines if (m := re.match(r"(%\S+) = OpTypeBool$", ln))), None)
    logs = {m.group(1) for ln in lines if (m := re.match(rf"(%\S+) = OpExtInst {flt} %\S+ Log2 ", ln))}
    exps = {m.group(1) for ln in lines if (m := re.match(rf"%\S+ = OpExtInst {flt} %\S+ Exp2 (%\S+)$", ln))}
    out, n = [], 0
    for ln in lines:
        m = re.match(rf"(%\S+) = OpFMul {flt} (%\S+) (%\S+)$", ln)
        if m and m.group(1) in exps and (m.group(2) in logs or m.group(3) in logs):
            n += 1
            r, a, b = m.groups()
            out += [
                f"%fmz_a{n} = OpFOrdEqual %fmz_bool {a} %fmz_zero",
                f"%fmz_b{n} = OpFOrdEqual %fmz_bool {b} %fmz_zero",
                f"%fmz_o{n} = OpLogicalOr %fmz_bool %fmz_a{n} %fmz_b{n}",
                f"%fmz_p{n} = OpFMul {flt} {a} {b}",
                f"{r} = OpSelect {flt} %fmz_o{n} %fmz_zero %fmz_p{n}",
            ]
            continue
        out.append(ln)
        if ln == f"{flt} = OpTypeFloat 32":
            out.append(f"%fmz_zero = OpConstant {flt} 0")
            if not boo:
                out.append("%fmz_bool = OpTypeBool")
    text = "\n".join(out) + "\n"
    if boo:
        text = text.replace("%fmz_bool", boo)
    return text, n


def main() -> int:
    for f in map(Path, sys.argv[1:]):
        orig = f.with_name(f.name + ".orig")
        if not orig.exists():
            shutil.copy2(f, orig)
        asm = run("spirv-dis", "--no-indent", "--no-header", str(orig)).decode()
        new, n = fix(asm)
        if not n:
            print(f"{f.name}: no pow idiom")
            continue
        spv = run("spirv-as", "--target-env", "vulkan1.1", "--preserve-numeric-ids", "-o", "-", "-", data=new.encode())
        run("spirv-val", "--target-env", "vulkan1.1", "-", data=spv)
        f.write_bytes(spv)
        print(f"{f.name}: {n} pow multiplies get FMZ")
    return 0


if __name__ == "__main__":
    sys.exit(main())

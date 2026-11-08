#!/usr/bin/env python3
"""cas-nan-guard.py <cache.spv>...: in each float atomic-add CAS loop (the translator's RED.ADD.F32 emulation), an old value
that is NaN counts as 0, so a NaN in the sky-SH accumulator (0x25a4c7f00, cs a806b657) cannot stick (NOTES-fog-nan.md).
Stopgap: writes in place via temp + rename; the original stays wherever the caller backed it up."""
import os, re, subprocess, sys
from pathlib import Path
def run(*c, data=None): return subprocess.run(c, input=data, capture_output=True, check=True).stdout
for f in map(Path, sys.argv[1:]):
    t = [l.strip() for l in run("spirv-dis", "--no-indent", "--no-header", str(f)).decode().splitlines()]
    boo = next(m.group(1) for l in t if (m := re.match(r"(%\S+) = OpTypeBool$", l)))
    cas = [i for i, l in enumerate(t) if "OpAtomicCompareExchange" in l]
    n = 0
    for i in cas:
        for j in range(i - 1, i - 12, -1):
            m = re.match(r"(%\S+) = OpFAdd (%\S+) (%\S+) (%\S+)$", t[j])
            if m:
                r, ty, a, b = m.groups(); n += 1
                t[j:j + 1] = [f"%cg_n{n} = OpIsNan {boo} {a}", f"%cg_a{n} = OpSelect {ty} %cg_n{n} %float_0 {a}", f"{r} = OpFAdd {ty} %cg_a{n} {b}"]
                break
    if not any(l.startswith("%float_0 = OpConstant") for l in t):
        k = next(i for i, l in enumerate(t) if re.match(r"%float = OpTypeFloat 32$", l)); t.insert(k + 1, "%float_0 = OpConstant %float 0")
    spv = run("spirv-as", "--target-env", "vulkan1.1", "--preserve-numeric-ids", "-o", "-", "-", data=("\n".join(t) + "\n").encode())
    run("spirv-val", "--target-env", "vulkan1.1", "-", data=spv)
    tmp = f.with_name(f.name + ".cg.tmp"); tmp.write_bytes(spv); os.replace(tmp, f)
    print(f"{f.name}: {n} CAS adds guarded")

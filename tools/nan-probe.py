#!/usr/bin/env python3
"""nan-probe.py <orig.spv> <cache-dir> <names...> TEMPS... : bisect tool for the fog NaN (NOTES-fog-nan.md).

Rewrites the img0 stores (%5839 site 1, %10355 site 2) of the fog injection shader so channel k holds a NaN flag of
probe k (up to 3): site 1 NaN 1.0 / finite 0.25, site 2 NaN 0.75 / finite 0.125. A probe is a GLSL temp number
(temp_N = Nth Function OpVariable, loaded at the store) or %id (an SSA id; must dominate the store). Other image
writes get the nan-guard NMax. Writes the result over each <cache-dir>/<name>.
"""
import re, subprocess, sys, importlib.util
from pathlib import Path
here = Path(__file__).parent
spec = importlib.util.spec_from_file_location("ng", here / "nan-guard.py"); ng = importlib.util.module_from_spec(spec); spec.loader.exec_module(ng)
orig, cache, *rest = sys.argv[1:]
names = [r for r in rest if r.endswith(".spv")]; probes = [r for r in rest if not r.endswith(".spv")]
text = subprocess.run(["spirv-dis", "--no-indent", orig], capture_output=True, check=True, text=True).stdout
lines = text.splitlines()
fvars = [m.group(1) for l in lines if (m := re.match(r"(%\S+) = OpVariable %\S+ Function", l))]
consts = "\n".join(f"%np_c{i} = OpConstant %float {v}" for i, v in enumerate(["1", "0.25", "0.75", "0.125"]))
out = []
for l in lines:
    m = re.match(r"(%5839|%10355) = OpCompositeConstruct %v4float (%\S+) (%\S+) (%\S+) (\S+)$", l)
    if m:
        s = m.group(1)[1:]; nan_c, fin_c = ("%np_c0", "%np_c1") if s == "5839" else ("%np_c2", "%np_c3")
        comps = [m.group(2), m.group(3), m.group(4)]
        for k, p in enumerate(probes):
            src = p if p.startswith("%") else f"%np_l{s}_{k}"
            if not p.startswith("%"):
                out.append(f"{src} = OpLoad %float {fvars[int(p)]}")
            out.append(f"%np_b{s}_{k} = OpIsNan %bool {src}")
            out.append(f"%np_s{s}_{k} = OpSelect %float %np_b{s}_{k} {nan_c} {fin_c}")
            comps[k] = f"%np_s{s}_{k}"
        l = f"{m.group(1)} = OpCompositeConstruct %v4float {' '.join(comps)} {m.group(5)}"
    out.append(l)
    if l.startswith("%float = OpTypeFloat 32"):
        out.append(consts)
asm, n = ng.guard("\n".join(out) + "\n")
tmp = Path(cache) / "probe.tmp.spvasm"; tmp.write_text(asm)
spv = subprocess.run(["spirv-as", "--target-env", "vulkan1.1", "--preserve-numeric-ids", str(tmp), "-o", "-"], capture_output=True, check=True).stdout
tmp.unlink()
subprocess.run(["spirv-val", "--target-env", "vulkan1.1", "-"], input=spv, check=True)
for nm in names: (Path(cache) / nm).write_bytes(spv)
print("probes", probes, "guarded writes", n)

#!/usr/bin/env python3
"""cas-reset.py <cache.spv>...: the sky-SH projection (cs a806b657, one 32x32 workgroup) adds into 12 words at
c1[0] + {0,4,8,16,...,56} of storage slot 0 (0x25a4c7f00) and nothing on our side ever zeroes them, so the sum
grows every frame (NOTES-fog-nan.md). This makes invocation (0,0) store 0 into those words first, then a workgroup
barrier, so each dispatch starts from 0. --abs w,w,...: also zero these absolute words of the binding (32-35:
the 4x4x6 cs e9b99bf2's sums, also never reset; it runs earlier in the frame, so readers before a806 still see them). Stopgap: writes in place via temp + rename; back up the original first."""
import os, re, subprocess, sys
from pathlib import Path

OFFS = [0, 4, 8, 16, 20, 24, 32, 36, 40, 48, 52, 56]


def run(*c, data=None):
    return subprocess.run(c, input=data, capture_output=True, check=True).stdout


def patch(t, absw):
    if any(l.startswith("%rz_m = OpLabel") for l in t):
        return t, False
    main = next(m.group(1) for l in t if (m := re.match(r'OpEntryPoint GLCompute (%\S+) "main"', l)))
    k = next(i for i, l in enumerate(t) if l == "%_ptr_Uniform_uint = OpTypePointer Uniform %uint")
    t[k + 1:k + 1] = [
        "%rz_u0 = OpConstant %uint 0", "%rz_u2 = OpConstant %uint 2", "%rz_sem = OpConstant %uint 72",
        "%rz_i0 = OpConstant %int 0", "%rz_i1 = OpConstant %int 1", "%rz_i2 = OpConstant %int 2",
        "%rz_pin = OpTypePointer Input %uint",
    ] + [f"%rz_o{o} = OpConstant %int {o}" for o in OFFS] + [f"%rz_k{w} = OpConstant %int {w}" for w in absw]
    f = next(i for i, l in enumerate(t) if l.startswith(f"{main} = OpFunction "))
    j = f + 2
    while t[j].split(" = ")[-1].startswith("OpVariable"):
        j += 1
    body = [
        "%rz_px = OpAccessChain %rz_pin %gl_LocalInvocationID %rz_i0", "%rz_x = OpLoad %uint %rz_px",
        "%rz_py = OpAccessChain %rz_pin %gl_LocalInvocationID %rz_i1", "%rz_y = OpLoad %uint %rz_py",
        "%rz_or = OpBitwiseOr %uint %rz_x %rz_y", "%rz_c = OpIEqual %bool %rz_or %rz_u0",
        "OpSelectionMerge %rz_m None", "OpBranchConditional %rz_c %rz_t %rz_m", "%rz_t = OpLabel",
        "%rz_bp = OpAccessChain %_ptr_Uniform_float %cp_c1 %int_0 %int_0 %int_0", "%rz_bf = OpLoad %float %rz_bp",
        "%rz_b = OpBitcast %int %rz_bf",
    ]
    for o in OFFS:
        body += [f"%rz_a{o} = OpIAdd %int %rz_b %rz_o{o}", f"%rz_w{o} = OpShiftRightLogical %int %rz_a{o} %rz_i2",
                 f"%rz_p{o} = OpAccessChain %_ptr_Uniform_uint %cp_s0 %rz_i0 %rz_w{o}", f"OpStore %rz_p{o} %rz_u0"]
    for w in absw:
        body += [f"%rz_q{w} = OpAccessChain %_ptr_Uniform_uint %cp_s0 %rz_i0 %rz_k{w}", f"OpStore %rz_q{w} %rz_u0"]
    body += ["OpBranch %rz_m", "%rz_m = OpLabel", "OpControlBarrier %rz_u2 %rz_u2 %rz_sem"]
    t[j:j] = body
    return t, True


args = sys.argv[1:]
absw = []
if args[:1] == ["--abs"]:
    absw = [int(w) for w in args[1].split(",")]
    args = args[2:]
for f in map(Path, args):
    t = [l.strip() for l in run("spirv-dis", "--no-indent", "--no-header", str(f)).decode().splitlines()]
    t, changed = patch(t, absw)
    if not changed:
        print(f"{f.name}: already reset")
        continue
    spv = run("spirv-as", "--target-env", "vulkan1.1", "--preserve-numeric-ids", "-o", "-", "-",
              data=("\n".join(t) + "\n").encode())
    run("spirv-val", "--target-env", "vulkan1.1", "-", data=spv)
    tmp = f.with_name(f.name + ".rz.tmp")
    tmp.write_bytes(spv)
    os.replace(tmp, f)
    print(f"{f.name}: reset added")

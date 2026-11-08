#!/usr/bin/env python3
"""Print the cache files (and counts) whose SPIR-V has pow(x, y) with a variable y: OpFMul of a Log2 result feeding Exp2 (fmz-pow.py fixes them)."""
import re,sys,subprocess
for f in sys.argv[1:]:
    t=subprocess.run(['spirv-dis','--no-indent','--no-header',f],capture_output=True,text=True).stdout.splitlines()
    consts={m.group(1) for l in t if (m:=re.match(r'(%\S+) = OpConstant ',l))}
    logs={m.group(1) for l in t if (m:=re.match(r'(%\S+) = OpExtInst %float %\S+ Log2 ',l))}
    exps={m.group(1) for l in t if (m:=re.match(r'%\S+ = OpExtInst %float %\S+ Exp2 (%\S+)$',l))}
    n=0
    for l in t:
        m=re.match(r'(%\S+) = OpFMul %float (%\S+) (%\S+)$',l)
        if m and m.group(1) in exps and (m.group(2) in logs or m.group(3) in logs):
            other = m.group(3) if m.group(2) in logs else m.group(2)
            if other not in consts: n+=1
    if n: print(f, n)

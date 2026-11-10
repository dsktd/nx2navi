#!/usr/bin/env python3
"""Retype a 2D texture whose size query extracts component 2 as a 2D array.

The translator types a texture without a PC type as plain 2D. When the shader then reads the layer count
(TXQ .z), it emits OpCompositeExtract index 2 of the ivec2 from OpImageQuerySizeLod: invalid SPIR-V, Mesa's
spirv_to_nir rejects the module and RADV faults (libvulkan_radeon.so+0x19be92). This rewrites such a texture to
an arrayed image and the query to ivec3. Only textures used for nothing but size queries are touched.

usage: txq-array-fix.py <in.spv> <out.spv>     exit 0 rewritten, 3 nothing to do, 2 cannot fix
       txq-array-fix.py --cache <shader-cache> <backup dir>
           every affected <key>.spv of a cache: original copied to the backup dir (kept if already there), the
           rewrite put in place by temp file + rename, so a game running with NX2NAVI_SHADER_RELOAD=1 picks it up
"""

import os
import shutil
import struct
import sys
from pathlib import Path

OP_TYPE_INT, OP_TYPE_VECTOR, OP_TYPE_IMAGE, OP_TYPE_SAMPLED_IMAGE, OP_TYPE_POINTER = 21, 23, 25, 27, 32
OP_FUNCTION, OP_VARIABLE, OP_LOAD, OP_COMPOSITE_EXTRACT, OP_IMAGE, OP_QUERY_SIZE_LOD = 54, 59, 61, 81, 100, 103
UNIFORM_CONSTANT = 0


def parse(words):
    out, i = [], 5
    while i < len(words):
        n = words[i] >> 16
        if n == 0 or i + n > len(words):
            raise ValueError("malformed SPIR-V")
        out.append(list(words[i : i + n]))
        i += n
    return out


def op(ins):
    return ins[0] & 0xFFFF


def make(opcode, *operands):
    return [(len(operands) + 1) << 16 | opcode, *operands]


def rewrite(words):
    ins = parse(words)
    bound = words[3]
    defs = {}
    for x in ins:
        o = op(x)
        if o in (OP_TYPE_INT, OP_TYPE_VECTOR, OP_TYPE_IMAGE, OP_TYPE_SAMPLED_IMAGE, OP_TYPE_POINTER):
            defs[x[1]] = x
        elif o in (OP_VARIABLE, OP_LOAD, OP_IMAGE, OP_QUERY_SIZE_LOD):
            defs[x[2]] = x

    # queries whose 2-component result has component 2 extracted
    bad = set()
    for x in ins:
        if op(x) == OP_COMPOSITE_EXTRACT and len(x) == 5 and x[4] == 2:
            q = defs.get(x[3])
            if q and op(q) == OP_QUERY_SIZE_LOD and defs[q[1]][3] == 2:
                bad.add(q[2])
    if not bad:
        return None

    variables = set()
    for q in bad:
        image = defs[defs[q][3]]
        load = defs.get(image[3]) if op(image) == OP_IMAGE else None
        var = defs.get(load[3]) if load and op(load) == OP_LOAD else None
        if not var or op(var) != OP_VARIABLE:
            raise ValueError("a size query does not come from a texture variable")
        variables.add(var[2])

    # every use of those variables must be load -> OpImage -> size query with component 2 taken
    loads, images = set(), set()
    first = next(i for i, x in enumerate(ins) if op(x) == OP_FUNCTION)
    body = ins[first:]  # the declarations before it carry literals that may equal an id
    for x in body:
        o = op(x)
        if o == OP_LOAD and x[3] in variables:
            loads.add(x[2])
        elif any(w in variables for w in x[1:]):
            raise ValueError("a texture variable has another use")
    for x in body:
        o = op(x)
        if o == OP_IMAGE and x[3] in loads:
            images.add(x[2])
        elif o != OP_LOAD and any(w in loads for w in x[1:]):
            raise ValueError("the texture is used for more than a size query")
    for x in body:
        o = op(x)
        if o == OP_QUERY_SIZE_LOD and x[3] in images:
            if x[2] not in bad:
                raise ValueError("a size query of the texture does not read component 2")
        elif o != OP_IMAGE and any(w in images for w in x[1:]):
            raise ValueError("the texture's image is used for more than a size query")

    new_types, new_vec = [], []

    def find(pred):  # called at once: the lambdas below never outlive their loop turn
        for d in list(defs.values()) + new_types + new_vec:
            if pred(d):
                return d[1]
        return None

    def fresh():
        nonlocal bound
        bound += 1
        return bound - 1

    retype = {}  # old type id -> new type id (pointer, sampled image, image)
    for v in variables:
        ptr = defs[defs[v][1]]
        sampled = defs[ptr[3]]
        image = defs[sampled[2]]
        if op(sampled) != OP_TYPE_SAMPLED_IMAGE or image[3] != 1 or image[5] != 0:
            raise ValueError("the texture is not a plain combined 2D sampler")
        want = image[:1] + [0] + image[2:5] + [1] + image[6:]
        img = find(lambda d: op(d) == OP_TYPE_IMAGE and d[2:] == want[2:])
        if img is None:
            img = fresh()
            new_types.append(want[:1] + [img] + want[2:])
        smp = find(lambda d: op(d) == OP_TYPE_SAMPLED_IMAGE and d[2] == img)
        if smp is None:
            smp = fresh()
            new_types.append(make(OP_TYPE_SAMPLED_IMAGE, smp, img))
        np = find(lambda d: op(d) == OP_TYPE_POINTER and d[2] == UNIFORM_CONSTANT and d[3] == smp)
        if np is None:
            np = fresh()
            new_types.append(make(OP_TYPE_POINTER, np, UNIFORM_CONSTANT, smp))
        retype[ptr[1]], retype[sampled[1]], retype[image[1]] = np, smp, img

    vec3 = {}  # ivec2 type id -> ivec3 type id
    for q in bad:
        v2 = defs[defs[q][1]]
        if v2[1] in vec3:
            continue
        v3 = find(lambda d: op(d) == OP_TYPE_VECTOR and d[2] == v2[2] and d[3] == 3)
        if v3 is None:
            v3 = fresh()
            new_vec.append(make(OP_TYPE_VECTOR, v3, v2[2], 3))
        vec3[v2[1]] = v3

    out = []
    placed, moved = False, []
    for x in ins:
        o = op(x)
        if o == OP_VARIABLE and x[2] in variables:  # moved to the end of the globals, after every type it may reuse
            moved.append([x[0], retype[x[1]]] + x[2:])
            continue
        if o == OP_FUNCTION and not placed:
            out.extend(new_types + new_vec + moved)
            placed = True
        elif (o == OP_LOAD and x[2] in loads) or (o == OP_IMAGE and x[2] in images):
            x = [x[0], retype[x[1]]] + x[2:]
        elif o == OP_QUERY_SIZE_LOD and x[2] in bad:
            x = [x[0], vec3[x[1]]] + x[2:]
        out.append(x)
    head = list(words[:5])
    head[3] = bound
    return head + [w for x in out for w in x]


def read_words(path):
    data = Path(path).read_bytes()
    if len(data) % 4 or len(data) < 20:
        return None
    words = struct.unpack(f"<{len(data) // 4}I", data)
    return words if words[0] == 0x07230203 else None


def fix_cache(cache, backup):
    os.makedirs(backup, exist_ok=True)
    fixed = refused = 0
    for e in os.scandir(cache):
        if not e.name.endswith(".spv"):
            continue
        words = read_words(e.path)
        try:
            res = rewrite(words) if words else None
        except ValueError as err:
            print(f"{e.name}: {err}", file=sys.stderr)
            refused += 1
            continue
        if res is None:
            continue
        kept = os.path.join(backup, e.name)
        if not os.path.exists(kept):
            shutil.copyfile(e.path, kept)
        tmp = os.path.join(cache, "." + e.name + ".tmp")
        Path(tmp).write_bytes(struct.pack(f"<{len(res)}I", *res))
        os.rename(tmp, e.path)
        fixed += 1
    print(f"{fixed} rewritten, {refused} refused")


def main():
    if sys.argv[1] == "--cache":
        return fix_cache(*sys.argv[2:4])
    src, dst = sys.argv[1:3]
    words = read_words(src)
    if words is None:
        sys.exit("not SPIR-V")
    try:
        res = rewrite(words)
    except ValueError as e:
        print(f"{src}: {e}", file=sys.stderr)
        sys.exit(2)
    if res is None:
        sys.exit(3)
    Path(dst).write_bytes(struct.pack(f"<{len(res)}I", *res))


if __name__ == "__main__":
    main()

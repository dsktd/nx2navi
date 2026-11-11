"""Export a model from the game's RomFS to glTF 2.0 (.glb) for Blender.

Private use: output goes under NX2navi/build/v111/export/ and never enters a
repository (game content boundary, NX2navi/AGENTS.md).

    python tools/modelx.py <out-dir> <Model/x.bfres.zs>

Textures are found in Tex/ from the material texture references.

Reads BFRES v10 (Switch 2, "Ounce") models and BNTX textures (BC4, BC5, ASTC),
deswizzles the block-linear surfaces and writes one .glb with PBR materials.
Needs numpy, pillow and texture2ddecoder.
"""

import argparse
import io
import json
import pathlib
import struct
import sys

import numpy as np
import texture2ddecoder
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import msgmod  # RomFS reader and zstd dictionaries

TREE = pathlib.Path(__file__).resolve().parent.parent / "NX2navi"


# ---- Little-endian reader


class Blob:
    def __init__(self, data):
        self.data = data

    def u8(self, o):
        return self.data[o]

    def u16(self, o):
        return struct.unpack_from("<H", self.data, o)[0]

    def u32(self, o):
        return struct.unpack_from("<I", self.data, o)[0]

    def u64(self, o):
        return struct.unpack_from("<Q", self.data, o)[0]

    def string(self, o):
        """String behind the offset at o (u16 length prefix)."""
        p = self.u64(o)
        if not p:
            return None
        return self.data[p + 2 : p + 2 + self.u16(p)].decode()


# ---- BFRES v10

FVTX_SIZE, FSHP_SIZE, FMAT_SIZE, MESH_SIZE, ATTR_SIZE = 0x58, 0x60, 0xB0, 0x38, 0x10


def read_bfres(data):
    """[(shape name, material dict, attribute arrays, triangle indices)] for LOD 0."""
    b = Blob(data)
    if data[:4] != b"FRES" or b.u32(8) >> 16 != 10:
        raise ValueError("not a BFRES v10 file")
    gpu = b.u64(b.u64(0xB0) + 8)
    model = b.u64(0x28)
    vbufs, shapes, mats = b.u64(model + 0x20), b.u64(model + 0x28), b.u64(model + 0x38)
    nvb, nshape, nmat = struct.unpack_from("<HHH", data, model + 0x68)
    vertices = [read_vertices(b, vbufs + i * FVTX_SIZE, gpu) for i in range(nvb)]
    materials = [read_material(b, mats + i * FMAT_SIZE) for i in range(nmat)]
    out = []
    for i in range(nshape):
        p = shapes + i * FSHP_SIZE
        mat, _bone, vb = struct.unpack_from("<HHH", data, p + 0x52)
        indices = read_indices(b, b.u64(p + 0x18), gpu)
        out.append((b.string(p + 8), materials[mat], vertices[vb], indices))
    return out


def read_material(b, p):
    names = b.u64(p + 0x20)
    count = b.u8(p + 0xA3)
    return {"name": b.string(p + 8), "textures": [b.string(names + 8 * i) for i in range(count)]}


def read_indices(b, mesh, gpu):
    size = b.u32(b.u64(mesh + 0x18))
    offset, prim, fmt, count, first = struct.unpack_from("<IIIII", b.data, mesh + 0x20)
    if prim != 3:
        raise ValueError(f"primitive type {prim} is not a triangle list")
    dtype = {0: np.uint8, 1: np.uint16, 2: np.uint32}[fmt]
    raw = np.frombuffer(b.data, dtype, count, gpu + offset)
    assert raw.nbytes <= size
    return raw.astype(np.uint32) + first


def read_vertices(b, v, gpu):
    attrs, sizes, strides = b.u64(v + 8), b.u64(v + 0x30), b.u64(v + 0x38)
    offset, nattr, nbuf, _, count = struct.unpack_from("<iBBHI", b.data, v + 0x48)
    align = b.u16(v + 0x56) or 1
    starts, at = [], gpu + offset
    for k in range(nbuf):
        at = -(-at // align) * align
        starts.append(at)
        at += b.u32(sizes + 16 * k)
    out = {}
    for a in range(nattr):
        ao = attrs + a * ATTR_SIZE
        fmt = struct.unpack_from(">H", b.data, ao + 8)[0]
        rel, buf = struct.unpack_from("<HH", b.data, ao + 12)
        stride = b.u32(strides + 16 * buf)
        out[b.string(ao)] = decode_attribute(b.data, starts[buf] + rel, stride, count, fmt)
    return out


def strided(data, start, stride, count, width):
    rows = np.frombuffer(data, np.uint8, stride * (count - 1) + width, start)
    return np.lib.stride_tricks.as_strided(rows, (count, width), (stride, 1)).copy()


def decode_attribute(data, start, stride, count, fmt):
    """Vertex attribute as a float32 (or uint for integers) array."""
    simple = {
        0x0515: (8, np.float16, None),
        0x0512: (4, np.float16, None),
        0x0518: (12, np.float32, None),
        0x0517: (8, np.float32, None),
        0x0519: (16, np.float32, None),
        0x0112: (4, np.uint16, 65535.0),
        0x0212: (4, np.int16, 32767.0),
        0x0115: (8, np.uint16, 65535.0),
        0x010B: (4, np.uint8, 255.0),
        0x0109: (2, np.uint8, 255.0),
        0x020B: (4, np.int8, 127.0),
        0x0302: (1, np.uint8, None),
        0x0309: (2, np.uint8, None),
        0x030B: (4, np.uint8, None),
        0x0102: (1, np.uint8, 255.0),
    }
    if fmt == 0x020E:
        return decode_10_10_10_2(strided(data, start, stride, count, 4))
    if fmt not in simple:
        raise ValueError(f"vertex format {fmt:#06x} is not handled")
    width, dtype, scale = simple[fmt]
    values = strided(data, start, stride, count, width).view(dtype)
    if scale is None:
        return values.astype(np.float32) if dtype in (np.float16, np.float32) else values
    return np.maximum(values.astype(np.float32) / scale, -1.0)


def decode_10_10_10_2(raw):
    """Three signed 10-bit normals plus a 2-bit sign (tangent handedness)."""
    v = raw.view(np.uint32)[:, 0]
    xyz = [((v >> s) & 0x3FF).astype(np.int32) for s in (0, 10, 20)]
    xyz = [np.where(c >= 512, c - 1024, c) / 511.0 for c in xyz]
    w = ((v >> 30) & 3).astype(np.int32)
    w = np.where(w >= 2, w - 4, w).astype(np.float32)
    return np.stack([*xyz, w], 1).astype(np.float32)


# ---- BNTX


def read_bntx(data):
    """(name, RGBA uint8 array) for mip 0 of the single texture."""
    b = Blob(data)
    info = data.index(b"BRTI")
    _mips, fmt = struct.unpack_from("<HxxxxI", data, info + 0x16)
    width, height, _depth, _layers, layout = struct.unpack_from("<5i", data, info + 0x24)
    size = b.u32(info + 0x50)
    mip0 = b.u64(b.u64(info + 0x70))
    kind, (bw, bh, bpb) = fmt >> 8, block_shape(fmt >> 8)
    wb, hb = -(-width // bw), -(-height // bh)
    gob_rows = 1 << layout
    linear = deswizzle(np.frombuffer(data, np.uint8, size, mip0), wb, hb, bpb, gob_rows)
    return b.string(info + 0x60), decode_blocks(bytes(linear), kind, width, height, bw, bh)


ASTC = {0x2D: (4, 4), 0x2E: (5, 4), 0x2F: (5, 5), 0x30: (6, 5), 0x31: (6, 6), 0x32: (8, 5)}
ASTC |= {0x33: (8, 6), 0x34: (8, 8), 0x35: (10, 5), 0x36: (10, 6), 0x37: (10, 8)}
ASTC |= {0x38: (10, 10), 0x39: (12, 10), 0x3A: (12, 12)}
BC = {0x1A: 8, 0x1B: 16, 0x1C: 16, 0x1D: 8, 0x1E: 16, 0x20: 16}


def block_shape(kind):
    if kind in ASTC:
        return (*ASTC[kind], 16)
    if kind in BC:
        return 4, 4, BC[kind]
    raise ValueError(f"texture format {kind:#04x} is not handled")


def deswizzle(src, wb, hb, bpb, gob_rows):
    """Block-linear (64 B x 8 row GOBs) to linear rows of blocks.

    The GOB order is Switch 1's, but inside a GOB the 16-byte units are
    ordered (msb to lsb) x/32, y/4, x/16, y/2, y on Switch 2 ("Ounce"),
    found by searching all bit orders for the smoothest image.
    """
    row_bytes = wb * bpb
    gobs_x = -(-row_bytes // 64)
    y, x = np.mgrid[0:hb, 0:row_bytes]
    addr = (y // (8 * gob_rows)) * gobs_x * gob_rows * 512
    addr += (x // 64) * gob_rows * 512 + ((y % (8 * gob_rows)) // 8) * 512
    addr += ((x % 64) // 32) * 256 + ((y % 8) // 4) * 128 + ((x % 32) // 16) * 64
    addr += ((y % 4) // 2) * 32 + (y % 2) * 16 + x % 16
    padded = np.zeros(max(int(addr.max()) + 1, src.size), np.uint8)
    padded[: src.size] = src
    return padded[addr].reshape(-1)


def decode_blocks(data, kind, width, height, bw, bh):
    if kind in ASTC:
        bgra = texture2ddecoder.decode_astc(data, width, height, bw, bh)
    else:
        decoder = {0x1A: "bc1", 0x1B: "bc2", 0x1C: "bc3", 0x1D: "bc4", 0x1E: "bc5", 0x20: "bc7"}
        bgra = getattr(texture2ddecoder, f"decode_{decoder[kind]}")(data, width, height)
    img = np.frombuffer(bgra, np.uint8).reshape(height, width, 4)
    return img[..., [2, 1, 0, 3]].copy()


# ---- Material mapping

COAT_ALPHA = 0.35  # *_Coat shells sit on the same surface; a guess, not the game's shader
SUFFIX = {"Alb": "albedo", "Nrm": "normal", "Rgh": "rough", "Mtl": "metal", "AO": "ao"}


def texture_roles(names):
    """role -> texture name, from the _Alb/_Nrm/... suffix convention."""
    out = {}
    for name in names:
        role = SUFFIX.get(name.rsplit("_", 1)[-1])
        if role:
            out[role] = name
    return out


def normal_map(rg):
    """BC5 two-channel normal to a three-channel tangent-space map."""
    xy = rg[..., :2].astype(np.float32) / 127.5 - 1.0
    z = np.sqrt(np.clip(1.0 - (xy**2).sum(-1), 0.0, 1.0))
    xyz = np.concatenate([xy, z[..., None]], -1)
    return np.round((xyz * 0.5 + 0.5) * 255).astype(np.uint8)


def orm_map(ao, rough, metal):
    """glTF occlusion (R) / roughness (G) / metallic (B) from single-channel maps."""
    shape = next(m.shape[:2] for m in (rough, metal, ao) if m is not None)
    channels = [resized(m, shape) for m in (ao, rough, metal)]
    channels = [c if c is not None else np.full(shape, d, np.uint8) for c, d in zip(channels, (255, 128, 0))]
    return np.stack(channels, -1)


def resized(img, shape):
    if img is None:
        return None
    r = img[..., 0]
    if r.shape == shape:
        return r
    return np.asarray(Image.fromarray(r).resize(shape[::-1], Image.BILINEAR))


# ---- glTF writer


class Gltf:
    def __init__(self):
        self.doc = {"asset": {"version": "2.0", "generator": "nx2navi modelx"}}
        self.blob = bytearray()

    def add(self, key, item):
        self.doc.setdefault(key, []).append(item)
        return len(self.doc[key]) - 1

    def view(self, data, target=None):
        while len(self.blob) % 4:
            self.blob.append(0)
        view = {"buffer": 0, "byteOffset": len(self.blob), "byteLength": len(data)}
        if target:
            view["target"] = target
        self.blob += data
        return self.add("bufferViews", view)

    def accessor(self, array, kind, target=34962):
        array = np.ascontiguousarray(array)
        ctype = {np.dtype(np.float32): 5126, np.dtype(np.uint32): 5125}[array.dtype]
        acc = {"bufferView": self.view(array.tobytes(), target), "componentType": ctype}
        acc |= {"count": len(array), "type": kind}
        if kind == "VEC3" and ctype == 5126:
            acc |= {"min": array.min(0).tolist(), "max": array.max(0).tolist()}
        return self.add("accessors", acc)

    def image(self, name, rgba, mode):
        png = io.BytesIO()
        Image.fromarray(rgba).convert(mode).save(png, "PNG")
        img = self.add(
            "images", {"name": name, "mimeType": "image/png", "bufferView": self.view(png.getvalue())}
        )
        return self.add("textures", {"source": img, "sampler": 0})

    def save(self, path):
        while len(self.blob) % 4:
            self.blob.append(0)
        self.doc["buffers"] = [{"byteLength": len(self.blob)}]
        text = json.dumps(self.doc, separators=(",", ":")).encode()
        text += b" " * (-len(text) % 4)
        body = struct.pack("<II", len(text), 0x4E4F534A) + text
        body += struct.pack("<II", len(self.blob), 0x004E4942) + self.blob
        path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def add_material(gltf, mat, textures, pngs, fallback):
    """glTF material; `fallback` fills roles a material does not name (shared atlas)."""
    roles = {r: textures.get(n) for r, n in (fallback | texture_roles(mat["textures"])).items()}
    pbr = {"metallicFactor": 1.0, "roughnessFactor": 1.0}
    out = {"name": mat["name"], "pbrMetallicRoughness": pbr}
    if roles.get("albedo") is not None:
        pbr["baseColorTexture"] = {"index": gltf.image(f"{mat['name']}_basecolor", roles["albedo"], "RGB")}
        pngs[f"{mat['name']}_basecolor"] = roles["albedo"][..., :3]
    if roles.get("normal") is not None:
        nrm = normal_map(roles["normal"])
        out["normalTexture"] = {"index": gltf.image(f"{mat['name']}_normal", nrm, "RGB")}
        pngs[f"{mat['name']}_normal"] = nrm
    if any(roles.get(r) is not None for r in ("rough", "metal", "ao")):
        orm = orm_map(roles.get("ao"), roles.get("rough"), roles.get("metal"))
        tex = gltf.image(f"{mat['name']}_orm", orm, "RGB")
        pbr["metallicRoughnessTexture"] = {"index": tex}
        if roles.get("ao") is not None:
            out["occlusionTexture"] = {"index": tex}
        pngs[f"{mat['name']}_orm"] = orm
    if mat["name"].endswith("_Coat"):
        out["alphaMode"] = "BLEND"
        pbr["baseColorFactor"] = [1.0, 1.0, 1.0, COAT_ALPHA]
    return gltf.add("materials", out)


def add_shape(gltf, name, vertices, indices, material):
    attrs = {"POSITION": gltf.accessor(vertices["_p0"][:, :3], "VEC3")}
    if "_n0" in vertices:
        n = vertices["_n0"][:, :3]
        attrs["NORMAL"] = gltf.accessor(n / np.linalg.norm(n, axis=1, keepdims=True).clip(1e-6), "VEC3")
    if "_t0" in vertices:
        t = vertices["_t0"].copy()
        t[:, :3] /= np.linalg.norm(t[:, :3], axis=1, keepdims=True).clip(1e-6)
        t[:, 3] = np.where(t[:, 3] < 0, -1.0, 1.0)
        attrs["TANGENT"] = gltf.accessor(t, "VEC4")
    for k in range(4):
        if f"_u{k}" in vertices:
            attrs[f"TEXCOORD_{k}"] = gltf.accessor(vertices[f"_u{k}"][:, :2], "VEC2")
    if "_c0" in vertices:
        attrs["COLOR_0"] = gltf.accessor(vertices["_c0"][:, :4].astype(np.float32), "VEC4")
    prim = {"attributes": attrs, "indices": gltf.accessor(indices, "SCALAR", 34963), "material": material}
    mesh = gltf.add("meshes", {"name": name, "primitives": [prim]})
    return gltf.add("nodes", {"name": name, "mesh": mesh})


def export(shapes, textures, path, scale):
    gltf = Gltf()
    gltf.doc["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
    materials, pngs, nodes = {}, {}, []
    albedos = [n for _, m, _, _ in shapes for r, n in texture_roles(m["textures"]).items() if r == "albedo"]
    fallback = {"albedo": albedos[0]} if albedos else {}
    for name, mat, vertices, indices in shapes:
        if mat["name"] not in materials:
            materials[mat["name"]] = add_material(gltf, mat, textures, pngs, fallback)
        nodes.append(add_shape(gltf, name, vertices, indices, materials[mat["name"]]))
    root = gltf.add("nodes", {"name": path.stem, "children": nodes, "scale": [scale] * 3})
    gltf.doc["scenes"] = [{"nodes": [root]}]
    gltf.doc["scene"] = 0
    gltf.save(path)
    return pngs


# ---- Command line


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=pathlib.Path)
    ap.add_argument("model", help="RomFS path, e.g. Model/Weapon_Sword_Master.Weapon_Sword_Master.bfres.zs")
    ap.add_argument("--scale", type=float, default=1.0, help="game units to metres")
    args = ap.parse_args()
    read = msgmod.romfs_reader(TREE)
    dicts = msgmod.dictionaries(read)
    unpack = lambda path: msgmod.unpack_zs(read(path), dicts)[0]
    shapes = read_bfres(unpack(args.model))
    names = {n for _, m, _, _ in shapes for n in m["textures"]}
    textures = {}
    for name in sorted(names):
        try:
            textures[name] = read_bntx(unpack(f"Tex/{name}.bntx.zs"))[1]
        except KeyError:
            print(f"missing texture {name}", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.model.rsplit("/", 1)[-1].split(".")[0]
    pngs = export(shapes, textures, args.out / f"{stem}.glb", args.scale)
    for name, img in pngs.items():
        Image.fromarray(img).save(args.out / f"{name}.png")
    for name, img in textures.items():
        Image.fromarray(img).save(args.out / f"src_{name}.png")
    for name, mat, vertices, indices in shapes:
        print(f"{name}: {len(vertices['_p0'])} vertices, {len(indices) // 3} triangles, {mat['textures']}")


if __name__ == "__main__":
    main()

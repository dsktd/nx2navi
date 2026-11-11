"""Text mods for NX2navi: export the game's messages to editable files and build a RomFS mod from edits.

    msgmod.py export [--lang USen]          -> build/v111/msg/<lang>/<msbt path>.json  (label -> text)
    msgmod.py build  [--lang USen] --mod <name>
        reads build/v111/msg-edit/<lang>/<msbt path>.json (only the labels you change), writes
        build/v111/mods-dev/<name>/romfs (load with NX2NAVI_MODS_DIR)/Mals/<lang>.Product.110.sarc.zs, recompressed with its own zstd dictionary.
    msgmod.py tags   [--lang USen]          -> count of every control tag (group.type) and a sample label
    msgmod.py rename [--lang USen] --old Link --new Cal --edits <dir>
        writes an edits tree (as msg-edit) with every whole-word <old> in display text replaced; tags are left alone
    build/check take --edits <dir> (default msg-edit) and --mods-dir <dir> (default mods-dev)
    msgmod.py check  [--lang USen] --mod <name>  -> re-reads the built mod: edited labels equal the edits, the rest
        byte-identical to the game's

Messages are UTF-8 in 1.1.1 (MSBT encoding byte 0; UTF-16LE handled too). Message text: control tags are written {group.type:hexparams} (0x0E) and {/group.type} (0x0F), a literal
brace is {{ or }}. Game data: everything read or written stays under build/ (NX2navi/AGENTS.md).
Run with NX2navi/.venv-py314/bin/python (compression.zstd).
"""

import argparse
import json
import re
import struct
import sys
from pathlib import Path

from compression import zstd

TREE = Path.home() / "claude/nx2navi/NX2navi"
VERSION = "v111"
MALS_VERSION = "110"


# ---- RomFS and zstd


def romfs_reader(tree):
    romfs = tree / "build/extracted" / VERSION / "romfs"
    index = json.loads((romfs / "index.json").read_text())
    files = {f["path"]: f for f in index["files"]}
    image = (romfs / "romfs.bin").open("rb")

    def read(path):
        f = files[path]
        image.seek(f["offset"])
        return image.read(f["size"])

    return read


def dictionaries(read):
    pack = zstd.decompress(read("Pack/ZsDic.pack.zs"))
    out = {}
    for lo, hi in sarc_members(pack).values():
        d = zstd.ZstdDict(pack[lo:hi])
        out[d.dict_id] = d
    return out


def unpack_zs(raw, dicts):
    """(contents, dictionary used)."""
    d = dicts.get(zstd.get_frame_info(raw).dictionary_id)
    return zstd.decompress(raw, zstd_dict=d), d


# ---- SARC


def sarc_nodes(data):
    """(name, node offset, absolute start, end) of every member, in SFAT order."""
    assert data[:4] == b"SARC" and data[6:8] == b"\xff\xfe"
    header, _, start = struct.unpack_from("<HxxII", data, 4)
    count = struct.unpack_from("<H", data, header + 6)[0]
    names = header + 12 + count * 16 + 8
    out = []
    for i in range(count):
        node = header + 12 + i * 16
        _, attribute, lo, hi = struct.unpack_from("<4I", data, node)
        at = names + (attribute & 0xFFFFFF) * 4
        out.append((data[at : data.index(0, at)].decode(), node, start + lo, start + hi))
    return out


def sarc_members(data):
    return {name: (lo, hi) for name, _, lo, hi in sarc_nodes(data)}


def sarc_replace(data, new):
    """data with the members named in new replaced; layout and alignment as tools/make_romfs_patches.py."""
    start = struct.unpack_from("<I", data, 12)[0]
    out = bytearray(data[:start])
    for name, node, lo, hi in sorted(sarc_nodes(data), key=lambda n: n[2]):
        align = min(lo & -lo, 0x2000) if lo else 0x2000
        out += bytes(-len(out) % align)
        body = new.get(name, data[lo:hi])
        struct.pack_into("<II", out, node + 8, len(out) - start, len(out) - start + len(body))
        out += body
    struct.pack_into("<I", out, 8, len(out))
    return bytes(out)


# ---- MSBT


def msbt_sections(data):
    """magic -> (body offset, body size)."""
    assert data[:8] == b"MsgStdBn" and data[0x0C] in (0, 1), "not a UTF-8 or UTF-16 MSBT"
    sections, pos = {}, 0x20
    for _ in range(struct.unpack_from("<H", data, 0x0E)[0]):
        size = struct.unpack_from("<I", data, pos + 4)[0]
        sections[bytes(data[pos : pos + 4])] = (pos + 16, size)
        pos = (pos + 16 + size + 15) & ~15
    return sections


def msbt_labels(data, sections):
    """message index -> label."""
    labels, (base, _) = {}, sections[b"LBL1"]
    for g in range(struct.unpack_from("<I", data, base)[0]):
        count, at = struct.unpack_from("<II", data, base + 4 + 8 * g)
        at += base
        for _ in range(count):
            n = data[at]
            labels[struct.unpack_from("<I", data, at + 1 + n)[0]] = data[at + 1 : at + 1 + n].decode()
            at += 1 + n + 4
    return labels


def msbt_raw_texts(data, sections):
    base, size = sections[b"TXT2"]
    count = struct.unpack_from("<I", data, base)[0]
    offsets = list(struct.unpack_from(f"<{count}I", data, base + 4)) + [size]
    return [data[base + offsets[i] : base + offsets[i + 1]] for i in range(count)]


def decode_text(raw, wide):
    """message (with its NUL; UTF-16LE when wide, else UTF-8) -> editable text."""
    w = 2 if wide else 1
    unit = "<H" if wide else "<B"
    codec = "utf-16-le" if wide else "utf-8"
    out, run, i = [], bytearray(), 0

    def flush():
        s = run.decode(codec)
        out.append(s.replace("{", "{{").replace("}", "}}"))
        run.clear()

    while i + w <= len(raw):
        c = struct.unpack_from(unit, raw, i)[0]
        if c == 0x0E:
            flush()
            group, kind, n = struct.unpack_from("<3H", raw, i + w)
            params = raw[i + w + 6 : i + w + 6 + n].hex()
            out.append(f"{{{group}.{kind}:{params}}}" if params else f"{{{group}.{kind}}}")
            i += w + 6 + n
        elif c == 0x0F:
            flush()
            group, kind = struct.unpack_from("<2H", raw, i + w)
            out.append(f"{{/{group}.{kind}}}")
            i += w + 4
        elif c == 0:
            i += w
        else:
            run += raw[i : i + w]
            i += w
    flush()
    return "".join(out)


TOKEN = re.compile(r"\{\{|\}\}|\{(/?)(\d+)\.(\d+)(?::([0-9a-fA-F]*))?\}")


def encode_text(text, wide):
    """editable text -> message with its NUL (UTF-16LE when wide, else UTF-8)."""
    codec = "utf-16-le" if wide else "utf-8"
    unit = "<H" if wide else "<B"
    out, pos = bytearray(), 0
    for m in TOKEN.finditer(text):
        plain = text[pos : m.start()]
        assert "{" not in plain and "}" not in plain, f"stray brace in {text!r}"
        out += plain.encode(codec)
        pos = m.end()
        if m[0] in ("{{", "}}"):
            out += m[0][0].encode(codec)
        elif m[1]:
            out += struct.pack(unit, 0x0F) + struct.pack("<2H", int(m[2]), int(m[3]))
        else:
            params = bytes.fromhex(m[4] or "")
            out += struct.pack(unit, 0x0E) + struct.pack("<3H", int(m[2]), int(m[3]), len(params)) + params
    rest = text[pos:]
    assert "{" not in rest and "}" not in rest, f"stray brace in {text!r}"
    return bytes(out + rest.encode(codec) + bytes(2 if wide else 1))


def msbt_messages(data):
    """label -> editable text, in message order."""
    sections = msbt_sections(data)
    labels = msbt_labels(data, sections)
    return {
        labels.get(i, f"#{i}"): decode_text(t, data[0x0C] == 1) for i, t in enumerate(msbt_raw_texts(data, sections))
    }


def msbt_replace(data, edits):
    """data with the messages labelled in edits (label -> text) replaced; every other section unchanged."""
    sections = msbt_sections(data)
    labels = {v: k for k, v in msbt_labels(data, sections).items()}
    unknown = sorted(set(edits) - set(labels))
    assert not unknown, f"labels not in the MSBT: {unknown}"
    texts = msbt_raw_texts(data, sections)
    for label, text in edits.items():
        texts[labels[label]] = encode_text(text, data[0x0C] == 1)
    table = 4 + 4 * len(texts)
    offsets, at = [], table
    for t in texts:
        offsets.append(at)
        at += len(t)
    body = struct.pack(f"<I{len(texts)}I", len(texts), *offsets) + b"".join(texts)
    base, size = sections[b"TXT2"]
    head = base - 16
    end = (base + size + 15) & ~15
    section = bytearray(data[head:base]) + body
    struct.pack_into("<I", section, 4, len(body))
    section += b"\xab" * (-len(section) % 16)
    out = bytearray(data[:head]) + section + data[end:]
    struct.pack_into("<I", out, 0x12, len(out))
    return bytes(out)


# ---- commands


def mals_path(lang):
    return f"Mals/{lang}.Product.{MALS_VERSION}.sarc.zs"


def load_sarc(lang):
    read = romfs_reader(TREE)
    dicts = dictionaries(read)
    data, d = unpack_zs(read(mals_path(lang)), dicts)
    return data, d


def msbts(sarc):
    return {n: sarc[lo:hi] for n, (lo, hi) in sarc_members(sarc).items() if n.endswith(".msbt")}


def cmd_export(args):
    sarc, _ = load_sarc(args.lang)
    out = TREE / "build" / VERSION / "msg" / args.lang
    files = msbts(sarc)
    for name, data in files.items():
        path = out / (name + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(msbt_messages(data), ensure_ascii=False, indent=1) + "\n")
    print(f"{len(files)} MSBT files -> {out}")


def edits_dir(args):
    return (Path(args.edits) if args.edits else TREE / "build" / VERSION / "msg-edit") / args.lang


def mod_path(args):
    mods = Path(args.mods_dir) if args.mods_dir else TREE / "build" / VERSION / "mods-dev"
    return mods / args.mod / "romfs" / mals_path(args.lang)


def load_edits(args):
    edits = edits_dir(args)
    return {str(p.relative_to(edits))[: -len(".json")]: json.loads(p.read_text()) for p in sorted(edits.rglob("*.json"))}


def cmd_build(args):
    sarc, d = load_sarc(args.lang)
    edits = edits_dir(args)
    files = msbts(sarc)
    new = {}
    for path in sorted(edits.rglob("*.json")):
        name = str(path.relative_to(edits))[: -len(".json")]
        assert name in files, f"{name} is not in {mals_path(args.lang)}"
        new[name] = msbt_replace(files[name], json.loads(path.read_text()))
    assert new, f"no edits under {edits}"
    packed = zstd.compress(sarc_replace(sarc, new), level=19, zstd_dict=d)
    out = mod_path(args)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(packed)
    print(f"{len(new)} MSBT files edited -> {out} ({len(packed)} bytes, dict {d.dict_id if d else 0})")


def rename_text(text, old, new):
    """whole-word old -> new in display text only: control tags {...} and escaped braces are kept as they are."""
    word = re.compile(rf"\b{re.escape(old)}\b")
    parts = re.split(r"(\{\{|\}\}|\{[^{}]*\})", text)
    return "".join(p if i % 2 else word.sub(new, p) for i, p in enumerate(parts))


def cmd_rename(args):
    sarc, _ = load_sarc(args.lang)
    out = edits_dir(args)
    files = labels = 0
    for name, data in msbts(sarc).items():
        changed = {k: n for k, t in msbt_messages(data).items() if (n := rename_text(t, args.old, args.new)) != t}
        if changed:
            path = out / (name + ".json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(changed, ensure_ascii=False, indent=1) + "\n")
            files, labels = files + 1, labels + len(changed)
    print(f"{labels} messages in {files} MSBT files -> {out}")


def cmd_check(args):
    sarc, _ = load_sarc(args.lang)
    mod, _ = unpack_zs(mod_path(args).read_bytes(), dictionaries(romfs_reader(TREE)))
    game, built = msbts(sarc), msbts(mod)
    assert set(game) == set(built), "member list differs"
    edits = load_edits(args)
    bad = 0
    for name, data in game.items():
        want = msbt_messages(data) | edits.get(name, {})
        if name not in edits:
            bad += data != built[name]
        elif msbt_messages(built[name]) != want or msbt_replace(data, edits[name]) != built[name]:
            bad += 1
            print(f"mismatch: {name}")
    print(f"{len(game)} MSBT files, {len(edits)} edited, {bad} mismatches")
    return 1 if bad else 0


def cmd_tags(args):
    sarc, _ = load_sarc(args.lang)
    seen = {}
    for name, data in msbts(sarc).items():
        for label, text in msbt_messages(data).items():
            for m in re.finditer(r"\{(\d+\.\d+)(?::[0-9a-f]*)?\}", text):
                count, sample = seen.get(m[1], (0, f"{name}:{label}"))
                seen[m[1]] = (count + 1, sample)
    for tag, (count, sample) in sorted(seen.items(), key=lambda kv: -kv[1][0]):
        print(f"{tag:>8} {count:6} {sample}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    cmds = {"export": cmd_export, "build": cmd_build, "check": cmd_check, "rename": cmd_rename, "tags": cmd_tags}
    for name in cmds:
        p = sub.add_parser(name)
        p.add_argument("--lang", default="USen")
        if name in ("build", "check"):
            p.add_argument("--mod", required=True)
            p.add_argument("--mods-dir")
        if name in ("build", "check", "rename"):
            p.add_argument("--edits")
        if name == "rename":
            p.add_argument("--old", required=True)
            p.add_argument("--new", required=True)
    args = ap.parse_args()
    return cmds[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

"""Item names and descriptions for NX2navi text mods.

    itemtext.py init  --export <msg/USen> --out <items.toml>
        writes every item (labels <Item>_Name / <Item>_Caption in ActorMsg/PouchContent) as an editable TOML file;
        refuses to overwrite an existing file
    itemtext.py apply --export <msg/USen> --items <items.toml> --edits <msg-edit/USen>
        merges every changed name or description into the edits tree that msgmod.py build reads

Text keeps the game's tags as written in the export ({201.13} and similar) and \\n for line breaks.
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

POUCH = "ActorMsg/PouchContent.msbt.json"
FIELDS = {"name": "_Name", "description": "_Caption"}


def load_pouch(export):
    return json.loads((Path(export) / POUCH).read_text())


def items(pouch):
    """item id -> {field: text} for every item that has a name."""
    ids = sorted(label[: -len("_Name")] for label in pouch if label.endswith("_Name"))
    return {i: {f: pouch[i + s] for f, s in FIELDS.items() if i + s in pouch} for i in ids}


def toml_string(text):
    return json.dumps(text, ensure_ascii=False)


def cmd_init(args):
    out = Path(args.out)
    if out.exists():
        sys.exit(f"{out} exists; edit it, or delete it to start over")
    lines = [
        "# Item names and descriptions shown on the Items screen. Edit the text, keep the ids.",
        "# \\n is a line break; {201.13} and similar are game tags, leave them in place.",
        "# Delete an item, or leave it unchanged, to keep the game's text.",
        "",
    ]
    for item, fields in items(load_pouch(args.export)).items():
        lines.append(f"[{item}]")
        lines += [f"{f} = {toml_string(t)}" for f, t in fields.items()]
        lines.append("")
    out.write_text("\n".join(lines))
    print(f"{len(items(load_pouch(args.export)))} items -> {out}")


def changes(pouch, wanted):
    """label -> new text for every field in wanted that differs from the game's text."""
    out = {}
    for item, fields in wanted.items():
        for field, text in fields.items():
            if field not in FIELDS:
                sys.exit(f"[{item}] {field}: unknown field (use {', '.join(FIELDS)})")
            label = item + FIELDS[field]
            if label not in pouch:
                sys.exit(f"[{item}] {field}: the game has no {label}")
            if text != pouch[label]:
                out[label] = text
    return out


def cmd_apply(args):
    wanted = tomllib.loads(Path(args.items).read_text())
    edited = changes(load_pouch(args.export), wanted)
    target = Path(args.edits) / POUCH
    merged = json.loads(target.read_text()) if target.exists() else {}
    merged.update(edited)
    if merged:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f"{len(edited)} item texts changed -> {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init")
    init.add_argument("--export", required=True)
    init.add_argument("--out", required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--export", required=True)
    apply.add_argument("--items", required=True)
    apply.add_argument("--edits", required=True)
    args = parser.parse_args()
    {"init": cmd_init, "apply": cmd_apply}[args.cmd](args)


if __name__ == "__main__":
    main()

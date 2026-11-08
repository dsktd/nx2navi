"""Run the checkout's tools/build_xlate.py with our private translator patches (../patches/*-xlate-*.patch) applied
on top of its own, so the checkout stays untouched. The identity hashes the patched tree, so the cache re-keys.

    python build-xlate-private.py <checkout> [build_xlate args...]
"""
import subprocess
import sys
from pathlib import Path

PATCHES = sorted((Path(__file__).resolve().parent.parent / "patches").glob("*-xlate-*.patch"))

root = Path(sys.argv.pop(1)).resolve()
sys.path.insert(0, str(root / "tools"))
import build_xlate  # noqa: E402

upstream_prepare = build_xlate.prepare_sources


def prepare_sources() -> Path:
    src = upstream_prepare()
    for patch in PATCHES:
        subprocess.run(["git", "apply", "--whitespace=nowarn", "--directory", str(src.relative_to(build_xlate.BUILD)),
                        str(patch)], cwd=build_xlate.BUILD, check=True)
        print(f"applied private {patch.name}")
    return src


build_xlate.prepare_sources = prepare_sources
build_xlate.main()

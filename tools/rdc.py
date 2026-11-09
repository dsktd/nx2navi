# tools/rdc's body; see that file's header. Runs under the renderdoc-py build's interpreter (tools/rdc.nix).
import hashlib
import sys
import time

# renderdoc.so finds librenderdoc.so through its rpath ($ORIGIN/../lib). Never dlopen librenderdoc.so RTLD_GLOBAL first:
# its exported vk* layer entry points then shadow the loader's and the replay segfaults in OpenCapture.
import renderdoc as rd

STAGES = {"vs": rd.ShaderStage.Vertex, "fs": rd.ShaderStage.Pixel, "cs": rd.ShaderStage.Compute,
          "gs": rd.ShaderStage.Geometry, "ms": rd.ShaderStage.Mesh, "ts": rd.ShaderStage.Task}


def die(msg):
    print(f"rdc: {msg}", file=sys.stderr)
    sys.exit(1)


def rid(r):
    return str(r).replace("ResourceId::", "")


def open_capture(path):
    t0 = time.time()
    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    cap = rd.OpenCaptureFile()
    res = cap.OpenFile(path, "", None)
    if not res.OK():
        die(f"cannot open {path}: {res.Message()}")
    if cap.LocalReplaySupport() != rd.ReplaySupport.Supported:
        die(f"{path}: no local replay support")
    res, ctrl = cap.OpenCapture(rd.ReplayOptions(), None)
    if not res.OK():
        die(f"replay failed: {res.Message()}")
    print(f"rdc: replay open in {time.time() - t0:.1f} s", file=sys.stderr)
    return cap, ctrl


def shader_hash(state, stage):
    refl = state.GetShaderReflection(stage)
    if refl is None or not len(refl.rawBytes):
        return "-"
    return hashlib.sha1(bytes(refl.rawBytes)).hexdigest()[:10]


def flatten(actions, out, passno):
    # DFS in order; render passes (BeginPass actions) number the draws after them
    for a in actions:
        if a.flags & rd.ActionFlags.BeginPass:
            passno[0] += 1
        if a.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.MeshDispatch | rd.ActionFlags.Dispatch):
            out.append((a, passno[0]))
        flatten(a.children, out, passno)


def collect(ctrl):
    """One dict per draw or dispatch, with the pipeline state at that event."""
    t0 = time.time()
    tex = {rid(t.resourceId): t for t in ctrl.GetTextures()}
    items = []
    flatten(ctrl.GetRootActions(), items, [0])
    rows = []
    for a, p in items:
        ctrl.SetFrameEvent(a.eventId, True)
        st = ctrl.GetPipelineState()
        vk = ctrl.GetVulkanPipelineState()
        dispatch = bool(a.flags & rd.ActionFlags.Dispatch)
        row = {"eid": a.eventId, "pass": p, "name": a.GetName(ctrl.GetStructuredFile()),
               "kind": "dispatch" if dispatch else ("mesh" if a.flags & rd.ActionFlags.MeshDispatch else "draw"),
               "pipe": rid(st.GetComputePipelineObject() if dispatch else st.GetGraphicsPipelineObject())}
        if dispatch:
            row.update(count="x".join(str(d) for d in a.dispatchDimension), cs=shader_hash(st, rd.ShaderStage.Compute),
                       vs="-", fs="-", viewport="-", blend="-", depth="-", targets="-")
        else:
            row.update(count=f"{a.numIndices}x{a.numInstances}", cs="-",
                       vs=shader_hash(st, rd.ShaderStage.Mesh if row["kind"] == "mesh" else rd.ShaderStage.Vertex),
                       fs=shader_hash(st, rd.ShaderStage.Pixel))
            vps = vk.viewportScissor.viewportScissors
            row["viewport"] = f"{vps[0].vp.x:g},{vps[0].vp.y:g} {vps[0].vp.width:g}x{vps[0].vp.height:g}" if len(vps) else "-"
            bl = []
            for i, b in enumerate(vk.colorBlend.blends):
                m = f"{int(b.writeMask):x}"
                bl.append(f"{str(b.colorBlend.source).split('.')[-1]}/{str(b.colorBlend.destination).split('.')[-1]}"
                          f"/{str(b.colorBlend.operation).split('.')[-1]}:{m}" if b.enabled else f"off:{m}")
            row["blend"] = " ".join(bl) or "-"
            ds = vk.depthStencil
            row["depth"] = (f"test={int(ds.depthTestEnable)} write={int(ds.depthWriteEnable)} "
                            f"{str(ds.depthFunction).split('.')[-1]}")
            tg = []
            for i, t in enumerate(st.GetOutputTargets()):
                if t.resource == rd.ResourceId.Null():
                    continue
                d = tex.get(rid(t.resource))
                tg.append(f"t{i}:{rid(t.resource)} {d.width}x{d.height} {d.format.Name()}" if d else f"t{i}:{rid(t.resource)}")
            dt = st.GetDepthTarget()
            if dt.resource != rd.ResourceId.Null():
                d = tex.get(rid(dt.resource))
                tg.append(f"td:{rid(dt.resource)} {d.format.Name()}" if d else f"td:{rid(dt.resource)}")
            row["targets"] = " ".join(tg) or "-"
        rows.append(row)
    print(f"rdc: {len(rows)} draws walked in {time.time() - t0:.1f} s", file=sys.stderr)
    return rows


def cmd_info(ctrl, args):
    fi = ctrl.GetFrameInfo()
    rows = collect(ctrl)
    draws = sum(r["kind"] != "dispatch" for r in rows)
    print(f"frame {fi.frameNumber}: {draws} draws, {len(rows) - draws} dispatches, {max([r['pass'] for r in rows] or [0])} passes, "
          f"{len({r['pipe'] for r in rows})} pipelines; file {fi.compressedFileSize / 1e6:.1f} MB "
          f"({fi.uncompressedFileSize / 1e6:.1f} MB uncompressed, init data {fi.initDataSize / 1e6:.1f} MB)")
    pipes = {}
    for r in rows:
        e = pipes.setdefault(r["pipe"], {"n": 0, "first": r["eid"], "pass": r["pass"], "vs": r["vs"], "fs": r["fs"], "cs": r["cs"]})
        e["n"] += 1
    print("pipeline   draws  first-eid  pass  vs/ms       fs          cs")
    for pid, e in sorted(pipes.items(), key=lambda kv: kv[1]["first"]):
        print(f"{pid:<10} {e['n']:>5}  {e['first']:>9}  {e['pass']:>4}  {e['vs']:<11} {e['fs']:<11} {e['cs']}")


def cmd_draws(ctrl, args):
    print("eid     pass kind     pipeline   vs/ms       fs          count      viewport               depth                   blend | targets")
    for r in collect(ctrl):
        print(f"{r['eid']:<7} {r['pass']:<4} {r['kind']:<8} {r['pipe']:<10} {r['vs']:<11} {r['fs'] if r['kind'] != 'dispatch' else r['cs']:<11} "
              f"{r['count']:<10} {r['viewport']:<22} {r['depth']:<23} {r['blend']} | {r['targets']}")


def cmd_save(ctrl, args):
    if len(args) < 2:
        die("save x.rdc <eventId> out.png [i|depth]")
    eid, out = int(args[0]), args[1]
    which = args[2] if len(args) > 2 else "0"
    ctrl.SetFrameEvent(eid, True)
    st = ctrl.GetPipelineState()
    if which == "depth":
        res = st.GetDepthTarget().resource
    else:
        tg = st.GetOutputTargets()
        if int(which) >= len(tg):
            die(f"event {eid} has {len(tg)} colour targets")
        res = tg[int(which)].resource
    if res == rd.ResourceId.Null():
        die(f"event {eid}: no such target bound")
    ts = rd.TextureSave()
    ts.resourceId = res
    ts.destType = rd.FileType.PNG
    ts.mip = 0
    ts.slice.sliceIndex = 0
    ts.alpha = rd.AlphaMapping.Discard
    if which == "depth":
        ts.channelExtract = 0
    r = ctrl.SaveTexture(ts, out)
    if not r.OK():
        die(f"save failed: {r.Message()}")
    print(f"{out}: target {rid(res)} after event {eid}")


def cmd_shader(ctrl, args):
    if len(args) < 2 or args[1] not in STAGES:
        die("shader x.rdc <eventId> vs|fs|cs|gs|ms|ts [target]")
    eid, stage = int(args[0]), STAGES[args[1]]
    ctrl.SetFrameEvent(eid, True)
    st = ctrl.GetPipelineState()
    refl = st.GetShaderReflection(stage)
    if refl is None:
        die(f"event {eid}: no {args[1]} bound")
    pipe = st.GetComputePipelineObject() if stage == rd.ShaderStage.Compute else st.GetGraphicsPipelineObject()
    targets = ctrl.GetDisassemblyTargets(True)
    want = [t for t in targets if len(args) > 2 and args[2].lower() in t.lower()] or targets[:1]
    if not want:
        die("no disassembly target")
    print(f"; event {eid} {args[1]} sha1 {hashlib.sha1(bytes(refl.rawBytes)).hexdigest()[:10]}, target: {want[0]} "
          f"(available: {', '.join(targets)})")
    print(ctrl.DisassembleShader(pipe, refl, want[0]))


def main():
    cmds = {"info": cmd_info, "draws": cmd_draws, "save": cmd_save, "shader": cmd_shader}
    if len(sys.argv) < 3 or sys.argv[1] not in cmds:
        die("usage: rdc info|draws|save|shader <file.rdc> [...]")
    cap, ctrl = open_capture(sys.argv[2])
    try:
        cmds[sys.argv[1]](ctrl, sys.argv[3:])
    finally:
        ctrl.Shutdown()
        cap.Shutdown()
        rd.ShutdownReplay()


main()

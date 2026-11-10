# Uncertain settings

Things that are on or available without proof they help. One line each; remove a line when it is settled.

| Setting | Default | Status | Turn off / on |
|---|---|---|---|
| CPU pinning to one cache domain | on (`just play`) | unmeasured; lab A/B pending | `NX2NAVI_CPUS=off` |
| `NX2NAVI_GPU_WAIT` | 0 | off fixed the horizon bands by observation, not re-proven | `=1` |
| `NX2NAVI_FINISH_DEFER` | 0 | built, lab numbers pending | `=1` |
| `NX2NAVI_EVENT_WAITS` | off | fixes AO flicker, causes fullscreen flicker and a soft picture | `=1` |
| `NX2NAVI_ONESHOT_WAIT_MS` | 30000 | a low cap would cut combat hitches; picture untested | `=<ms>` |
| `NX2NAVI_TEX_RELEASED_MIB` | 3072 | graveyard may want more; higher risks video memory | `=<MiB>` |
| `NX2NAVI_MOTION_PAD` | auto | no effect while yakin holds the controller | `=off` |
| Host huge pages `always` | host | may fight the runtime's write protection; untested | host: `madvise` |

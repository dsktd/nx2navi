//! The start checks: few, each green (fine), yellow (plays, but slower or with stutter) or red (will not start).
//! Everything is read from files and sysfs; nothing opens the GPU, so the checks are safe beside a running game.

use std::path::Path;

use crate::game::Pick;
use crate::run::Plan;

/// Below this the game's textures and render targets no longer fit (lab-run waits for 10 GiB free).
const VRAM_MIN_TOTAL: u64 = 8 << 30;
const VRAM_MIN_FREE: u64 = 6 << 30;
/// A warm shader cache holds hundreds of thousands of translated shaders; counting stops here.
const SHADERS_WARM: usize = 20_000;
/// A warm pipeline cache is hundreds of MB.
const PIPELINES_WARM: u64 = 64 << 20;

#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub enum Status {
    Green,
    Yellow,
    Red,
}
impl std::fmt::Display for Status {
    fn fmt(
        &self,
        f: &mut std::fmt::Formatter<'_>,
    ) -> std::fmt::Result {
        f.write_str(match self {
            Self::Green => "green",
            Self::Yellow => "yellow",
            Self::Red => "red",
        })
    }
}

#[derive(Clone, Debug)]
pub struct Check {
    pub name: &'static str,
    pub status: Status,
    pub reason: String,
    /// How to make it green; None when it is.
    pub hint: Option<String>,
}
impl Check {
    fn green(
        name: &'static str,
        reason: impl Into<String>,
    ) -> Self {
        Self {
            name,
            status: Status::Green,
            reason: reason.into(),
            hint: None,
        }
    }

    fn yellow(
        name: &'static str,
        reason: impl Into<String>,
        hint: impl Into<String>,
    ) -> Self {
        Self {
            name,
            status: Status::Yellow,
            reason: reason.into(),
            hint: Some(hint.into()),
        }
    }

    fn red(
        name: &'static str,
        reason: impl Into<String>,
        hint: impl Into<String>,
    ) -> Self {
        Self {
            name,
            status: Status::Red,
            reason: reason.into(),
            hint: Some(hint.into()),
        }
    }
}

/// All checks, in the order shown.
pub fn all(
    pick: Option<&Pick>,
    plan: &anyhow::Result<Plan>,
) -> Vec<Check> {
    vec![
        game(pick),
        build(plan),
        udmabuf(plan),
        gpu(),
        caches(plan),
        cpu(),
    ]
}

pub fn worst(checks: &[Check]) -> Status {
    checks
        .iter()
        .map(|c| c.status)
        .max()
        .unwrap_or(Status::Green)
}

const GAME: &str = "Game files";

fn game(pick: Option<&Pick>) -> Check {
    match pick {
        None => Check::red(
            GAME,
            "no game files found",
            "choose romfs.bin of your unpacked 1.1.1 dump, or its .nup",
        ),
        Some(Pick::Nup(nup)) => Check::red(
            GAME,
            format!("{} is not unpacked yet", nup.display()),
            format!("just nup={} extract (about 30 GB)", nup.display()),
        ),
        Some(Pick::Dir(dir)) if !dir.is_present() => Check::red(
            GAME,
            format!(
                "no exefs/main and romfs/romfs.bin in {}",
                dir.path().display()
            ),
            "choose romfs.bin of your unpacked dump",
        ),
        Some(Pick::Dir(dir)) => match dir.validate() {
            Ok(()) => Check::green(
                GAME,
                "Ocarina of Time 1.1.1: title, build e0f3ccfa and romfs.bin size match",
            ),
            Err(err) => Check::red(
                GAME,
                err.to_string(),
                "dump the game again with the 1.1.1 update installed",
            ),
        },
    }
}

const BUILD: &str = "Game build";

fn build(plan: &anyhow::Result<Plan>) -> Check {
    let plan = match plan {
        Ok(plan) => plan,
        Err(err) => {
            return Check::red(
                BUILD,
                err.to_string(),
                "fix the run script or the justfile's run recipe",
            );
        }
    };
    let Ok(meta) = std::fs::metadata(&plan.exe) else {
        return Check::red(
            BUILD,
            format!(
                "run {} wants {}, which is missing",
                plan.name,
                plan.exe.display()
            ),
            "build it (README) or point `just run`'s default at a built run",
        );
    };
    let age = meta
        .modified()
        .ok()
        .and_then(|m| m.elapsed().ok())
        .map(|d| d.as_secs() / 3600);
    let age = age.map(|h| {
        if h < 48 {
            format!(", built {h} h ago")
        } else {
            format!(", built {} days ago", h / 24)
        }
    });
    Check::green(
        BUILD,
        format!(
            "run {} uses {}{}",
            plan.name,
            file_name(&plan.exe),
            age.unwrap_or_default()
        ),
    )
}

const UDMABUF: &str = "Guest memory";

/// PR #730 (play49 on): guest memory as dma-bufs through /dev/udmabuf instead of shadow copies; without read-write
/// access the runtime falls back to the copies (Hyrule Field f2663 standing: 52 vs 41 fps, ARCHITECTURE.md 8).
fn udmabuf(plan: &anyhow::Result<Plan>) -> Check {
    if let Ok(Plan {
        dmabuf: Some(off), ..
    }) = plan
        && off == "0"
    {
        return Check::yellow(
            UDMABUF,
            "the run sets NX2NAVI_DMABUF=0: shadow copies",
            "drop NX2NAVI_DMABUF=0",
        );
    }
    let dev = Path::new("/dev/udmabuf");
    if !dev.exists() {
        return Check::yellow(
            UDMABUF,
            "/dev/udmabuf is missing: shadow copies, about 20% slower",
            "sudo modprobe udmabuf (and add it to /etc/modules-load.d)",
        );
    }
    match std::fs::OpenOptions::new().read(true).write(true).open(dev) {
        Ok(_) => Check::green(
            UDMABUF,
            "/dev/udmabuf is read-write: dma-buf imports, no shadow copies",
        ),
        Err(_) => {
            let group = device_group(dev).unwrap_or("?".into());
            let hint = if group == "root" || group == "?" {
                "a udev rule KERNEL==\"udmabuf\", GROUP=\"kvm\", MODE=\"0660\", then join kvm"
                    .to_string()
            } else {
                format!("sudo usermod -aG {group} $USER, then log in again")
            };
            Check::yellow(
                UDMABUF,
                format!(
                    "no access to /dev/udmabuf (group {group}): shadow copies, about 20% slower"
                ),
                hint,
            )
        }
    }
}

fn device_group(dev: &Path) -> Option<String> {
    let gid = std::os::unix::fs::MetadataExt::gid(&std::fs::metadata(dev).ok()?);
    let groups = std::fs::read_to_string("/etc/group").ok()?;
    groups.lines().find_map(|l| {
        let mut f = l.split(':');
        let name = f.next()?;
        (f.nth(1)?.parse::<u32>().ok()? == gid).then(|| name.to_string())
    })
}

const GPU: &str = "GPU";

/// From sysfs only: the amdgpu card (RADV comes from the flake's Mesa), its render node and VRAM in use.
fn gpu() -> Check {
    let Ok(cards) = std::fs::read_dir("/sys/class/drm") else {
        return Check::red(GPU, "no /sys/class/drm", "no GPU driver loaded");
    };
    let mut names: Vec<_> = cards
        .flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .collect();
    names.sort();
    let mut other = None;
    for name in names
        .iter()
        .filter(|n| n.starts_with("card") && !n.contains('-'))
    {
        let dev = Path::new("/sys/class/drm").join(name).join("device");
        let driver = std::fs::read_link(dev.join("driver"))
            .ok()
            .and_then(|p| p.file_name().map(|f| f.to_string_lossy().into_owned()))
            .unwrap_or_default();
        if driver != "amdgpu" {
            other.get_or_insert(driver);
            continue;
        }
        let read = |f: &str| {
            std::fs::read_to_string(dev.join(f))
                .ok()
                .and_then(|s| s.trim().parse::<u64>().ok())
        };
        let (Some(total), Some(used)) = (read("mem_info_vram_total"), read("mem_info_vram_used"))
        else {
            return Check::yellow(
                GPU,
                format!("{name}: amdgpu without VRAM figures"),
                "check the amdgpu driver",
            );
        };
        let render = render_node(&dev);
        let gib = |b: u64| b as f64 / (1u64 << 30) as f64;
        let what = format!(
            "amdgpu, {:.0} GiB VRAM, {:.1} GiB in use",
            gib(total),
            gib(used)
        );
        return match render {
            None => Check::red(
                GPU,
                format!("{what}; no read-write render node"),
                "join the render (or video) group",
            ),
            Some(_) if total < VRAM_MIN_TOTAL => Check::yellow(
                GPU,
                what,
                "lower render scale and texture budget (NX2NAVI_TEX_RELEASED_MIB)",
            ),
            Some(_) if total - used.min(total) < VRAM_MIN_FREE => Check::yellow(
                GPU,
                what,
                "close other GPU programs (another game, NX2navi already running, video)",
            ),
            Some(node) => Check::green(GPU, format!("{what}, {node}")),
        };
    }
    match other {
        Some(driver) if driver == "nvidia" => Check::yellow(
            GPU,
            "NVIDIA GPU: not the tested setup",
            "run with NX2NAVI_GPU=nvidia (nixGL host driver)",
        ),
        Some(driver) => Check::yellow(
            GPU,
            format!("{driver} GPU: not the tested setup (amdgpu/RADV)"),
            "expect issues",
        ),
        None => Check::red(GPU, "no GPU found in /sys/class/drm", "load the GPU driver"),
    }
}

fn render_node(dev: &Path) -> Option<String> {
    let nodes = std::fs::read_dir(dev.join("drm")).ok()?;
    nodes
        .flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .find(|n| {
            n.starts_with("renderD")
                && std::fs::OpenOptions::new()
                    .read(true)
                    .write(true)
                    .open(Path::new("/dev/dri").join(n))
                    .is_ok()
        })
}

const CACHES: &str = "Shader caches";

/// Cold caches mean the first minutes of each area stutter while shaders translate and pipelines build.
fn caches(plan: &anyhow::Result<Plan>) -> Check {
    let Ok(plan) = plan else {
        return Check::yellow(
            CACHES,
            "unknown: the run could not be read",
            "see Game build",
        );
    };
    let shaders = std::fs::read_dir(&plan.shader_cache)
        .map(|d| d.take(SHADERS_WARM).count())
        .unwrap_or(0);
    let pipelines = std::fs::metadata(&plan.pipeline_cache)
        .map(|m| m.len())
        .unwrap_or(0);
    let what = format!(
        "{}{} shaders in {}, {} MB in {}",
        shaders,
        if shaders == SHADERS_WARM { "+" } else { "" },
        file_name(&plan.shader_cache),
        pipelines >> 20,
        file_name(&plan.pipeline_cache),
    );
    if shaders < SHADERS_WARM || pipelines < PIPELINES_WARM {
        return Check::yellow(
            CACHES,
            format!("cold: {what}"),
            "the first run stutters; or warm them: just shaders",
        );
    }
    Check::green(CACHES, format!("warm: {what}"))
}

const CPU: &str = "CPU power";

/// The frame is bound by the replay thread (one core: frame = replay + ~4.7 ms), so clock ramp-up shows directly.
fn cpu() -> Check {
    let Ok(policies) = std::fs::read_dir("/sys/devices/system/cpu/cpufreq") else {
        return Check::yellow(CPU, "no cpufreq in sysfs", "check the CPU frequency driver");
    };
    let mut govs = Vec::new();
    let mut epps = Vec::new();
    for policy in policies.flatten().map(|e| e.path()) {
        let read = |f: &str| {
            std::fs::read_to_string(policy.join(f))
                .ok()
                .map(|s| s.trim().to_string())
        };
        govs.extend(read("scaling_governor"));
        epps.extend(read("energy_performance_preference"));
    }
    govs.sort();
    govs.dedup();
    epps.sort();
    epps.dedup();
    let what = format!(
        "governor {}{}",
        govs.join("/"),
        if epps.is_empty() {
            String::new()
        } else {
            format!(", EPP {}", epps.join("/"))
        }
    );
    let fast = |v: &[String]| !v.is_empty() && v.iter().all(|x| x == "performance");
    if fast(&govs) || fast(&epps) {
        return Check::green(CPU, what);
    }
    Check::yellow(
        CPU,
        what,
        "powerprofilesctl set performance (or cpupower frequency-set -g performance)",
    )
}

fn file_name(path: &Path) -> String {
    path.file_name()
        .map(|f| f.to_string_lossy().into_owned())
        .unwrap_or(path.display().to_string())
}

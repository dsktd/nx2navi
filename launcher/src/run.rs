//! The default run (`just run` = `runs/<name>.sh`, the name being the justfile's default) and what it will use.
//!
//! The run scripts chain into each other and set their knobs as they go; the last one ends in
//! `exec just -f <justfile> play`. To learn the run's exe and caches without starting anything, the script is run
//! with a stand-in `just` first on PATH that prints the environment it got and exits.

use std::collections::HashMap;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;

use anyhow::anyhow;

use crate::Result;
use crate::game::GameDir;

/// Variables the launcher never passes on: HDR stays with nx2navi.ini and the in-game option (an env value locks it,
/// Cal 2026-11-12); mods are off unless asked for.
const DROPPED: &[&str] = &["NX2NAVI_HDR", "NX2NAVI_MODS", "NX2NAVI_MODS_DIR"];
/// What the launcher's own Nix wrapper (nixGL, the window's libraries) adds; the game's dev shell sets its own.
const WRAPPER: &[&str] = &[
    "LD_LIBRARY_PATH",
    "LIBGL_DRIVERS_PATH",
    "LIBVA_DRIVERS_PATH",
    "__EGL_VENDOR_LIBRARY_FILENAMES",
    "GBM_BACKENDS_PATH",
    "__GLX_VENDOR_LIBRARY_NAME",
];

/// The tooling checkout (`~/claude/nx2navi`): its justfile, runs/ and the upstream worktree in it.
#[derive(Clone, Debug)]
pub struct Root {
    pub dir: PathBuf,
    /// The upstream worktree (justfile `src`): NX2NAVI_SRC, else `<dir>/NX2navi`.
    pub src: PathBuf,
    /// The game version folder (justfile `ver`): NX2NAVI_VER, else v111.
    pub ver: String,
}
impl Root {
    /// `dir` if given, else the first folder upwards from the working folder that holds a justfile and runs/, else
    /// `~/claude/nx2navi`.
    pub fn find(dir: Option<PathBuf>) -> Result<Self> {
        let is_root = |d: &Path| d.join("justfile").is_file() && d.join("runs").is_dir();
        let dir = match dir {
            Some(dir) => dir,
            None => std::env::current_dir()
                .ok()
                .and_then(|cwd| cwd.ancestors().find(|d| is_root(d)).map(Path::to_path_buf))
                .or(dirs::home_dir().map(|h| h.join("claude/nx2navi")))
                .ok_or(anyhow!("No tooling checkout found: give --root"))?,
        };
        if !is_root(&dir) {
            return Err(anyhow!(
                "{} holds no justfile and runs/: give --root",
                dir.display()
            ));
        }
        let src = std::env::var_os("NX2NAVI_SRC")
            .map(PathBuf::from)
            .unwrap_or(dir.join("NX2navi"));
        let ver = std::env::var("NX2NAVI_VER").unwrap_or("v111".into());
        Ok(Self { dir, src, ver })
    }

    pub fn build(&self) -> PathBuf {
        self.src.join("build").join(&self.ver)
    }

    /// The justfile's default run: `run NAME="<name>" *args:`.
    pub fn default_run(&self) -> Result<String> {
        let justfile = std::fs::read_to_string(self.dir.join("justfile"))?;
        justfile
            .lines()
            .find_map(|l| {
                l.strip_prefix("run NAME=\"")?
                    .split('"')
                    .next()
                    .map(str::to_string)
            })
            .ok_or(anyhow!("The justfile has no `run NAME=\"...\"` recipe"))
    }
}

/// What a run will use, from its scripts.
#[derive(Clone, Debug)]
pub struct Plan {
    pub name: String,
    pub exe: PathBuf,
    pub shader_cache: PathBuf,
    pub pipeline_cache: PathBuf,
    /// NX2NAVI_DMABUF as the scripts set it (None: the exe's default, on).
    pub dmabuf: Option<String>,
}
impl Plan {
    pub fn probe(
        root: &Root,
        name: &str,
    ) -> Result<Self> {
        let script = root.dir.join("runs").join(format!("{name}.sh"));
        if !script.is_file() {
            return Err(anyhow!("No run script {}", script.display()));
        }
        let stub = std::env::temp_dir().join(format!("nx2navi-launcher-{}", std::process::id()));
        std::fs::create_dir_all(&stub)?;
        std::fs::write(stub.join("just"), "#!/bin/sh\nexec env -0\n")?;
        std::fs::set_permissions(
            stub.join("just"),
            std::os::unix::fs::PermissionsExt::from_mode(0o755),
        )?;
        let path = std::env::var("PATH").unwrap_or_default();
        let out = Command::new("sh")
            .arg(&script)
            .current_dir(&root.dir)
            .env("PATH", format!("{}:{path}", stub.display()))
            .env("NX2NAVI_RUN_NAME", name)
            .env_remove("NX2NAVI_MODS")
            .output();
        let _ = std::fs::remove_dir_all(&stub);
        let out = out?;
        let env: HashMap<String, String> = String::from_utf8_lossy(&out.stdout)
            .split('\0')
            .filter_map(|kv| {
                kv.split_once('=')
                    .map(|(k, v)| (k.to_string(), v.to_string()))
            })
            .collect();
        if !env.contains_key("NX2NAVI_RUN_NAME") {
            return Err(anyhow!("runs/{name}.sh did not reach `just play`"));
        }
        let build = root.build();
        let path_of = |key: &str, default: &str| {
            env.get(key)
                .map(|v| root.dir.join(v))
                .unwrap_or(build.join(default))
        };
        let exe = match env.get("NX2NAVI_EXE").filter(|e| !e.is_empty()) {
            Some(exe) => build.join(format!("nx2navi.{exe}")),
            None => build.join("nx2navi"),
        };
        Ok(Self {
            name: name.to_string(),
            exe,
            shader_cache: path_of("NX2NAVI_SHADER_CACHE", "shader-cache"),
            pipeline_cache: path_of("NX2NAVI_PIPELINE_CACHE", "pipeline-cache.bin"),
            dmabuf: env.get("NX2NAVI_DMABUF").cloned(),
        })
    }
}

/// Starts `just run <name>` with the chosen game files, mods off and HDR left to the game's settings.
pub fn play(
    root: &Root,
    name: &str,
    game: &GameDir,
) -> Result<Child> {
    let mut cmd = Command::new("just");
    cmd.arg("-f")
        .arg(root.dir.join("justfile"))
        .arg("run")
        .arg(name)
        .current_dir(&root.dir);
    cmd.env("NX2NAVI_EXEFS", game.exefs())
        .env("NX2NAVI_ROMFS", game.romfs());
    for var in DROPPED.iter().chain(WRAPPER) {
        cmd.env_remove(var);
    }
    cmd.spawn()
        .or(Err(anyhow!("Could not start `just` (is it on PATH?)")))
}

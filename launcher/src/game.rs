//! The player's game files: an unpacked dump (`exefs/` and `romfs/romfs.bin`), as `just extract` writes it into
//! `NX2navi/build/extracted/v111` and as the runtime reads it (`runtime/main.c` portable_paths: NX2NAVI_EXEFS and
//! NX2NAVI_ROMFS, else `exefs/` and `romfs/` beside the game, else the build's own path).

use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

use anyhow::anyhow;

use crate::Result;

/// Title id of Ocarina of Time (Switch 2), `tools/make_game.py` TITLE_ID.
pub const TITLE_ID: u64 = 0x0400_4860_24DE_C000;
/// NSO build id of `main` in game 1.1.1, `tools/make_game.py` MAIN_BUILD_ID.
pub const MAIN_BUILD_ID: [u8; 16] = [
    0xe0, 0xf3, 0xcc, 0xfa, 0xf5, 0x00, 0x65, 0xae, 0x4e, 0xa0, 0x1e, 0xb5, 0xae, 0xb1, 0x3b, 0x1a,
];
/// romfs.bin of 1.1.1 is 26.2 GB; anything far smaller is a cut copy.
const ROMFS_MIN_BYTES: u64 = 20_000_000_000;

/// A folder holding `exefs/` and `romfs/`.
#[derive(Clone, Debug, PartialEq)]
pub struct GameDir(PathBuf);
impl GameDir {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self(path.into())
    }

    pub fn path(&self) -> &Path {
        &self.0
    }

    pub fn exefs(&self) -> PathBuf {
        self.0.join("exefs")
    }

    pub fn romfs(&self) -> PathBuf {
        self.0.join("romfs")
    }

    /// Whether the folder looks like game files at all (cheap: no reads).
    pub fn is_present(&self) -> bool {
        self.exefs().join("main").is_file() && self.romfs().join("romfs.bin").is_file()
    }

    /// Checks the title in main.npdm, main's build id (game 1.1.1) and romfs.bin's size.
    pub fn validate(&self) -> Result<()> {
        let npdm = std::fs::read(self.exefs().join("main.npdm")).or(Err(anyhow!(
            "exefs/main.npdm is missing in {}",
            self.0.display()
        )))?;
        let title = npdm_title(&npdm).ok_or(anyhow!("exefs/main.npdm is not an NPDM file"))?;
        if title != TITLE_ID {
            return Err(anyhow!(
                "title {title:016X} is not Ocarina of Time ({TITLE_ID:016X})"
            ));
        }
        let mut head = [0u8; 0x50];
        std::fs::File::open(self.exefs().join("main"))?.read_exact(&mut head)?;
        if &head[..4] != b"NSO0" {
            return Err(anyhow!("exefs/main is not an NSO module"));
        }
        if head[0x40..0x50] != MAIN_BUILD_ID {
            let build: String = head[0x40..0x44]
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect();
            return Err(anyhow!(
                "game build {build} is not version 1.1.1 (e0f3ccfa)"
            ));
        }
        let size = std::fs::metadata(self.romfs().join("romfs.bin"))?.len();
        if size < ROMFS_MIN_BYTES {
            return Err(anyhow!(
                "romfs.bin is only {:.1} GB (1.1.1: 26.2 GB)",
                size as f64 / 1e9
            ));
        }
        Ok(())
    }
}

/// The program id in an NPDM's ACI0 block (META header, ACI0 offset at 0x70, program id at +0x10).
fn npdm_title(npdm: &[u8]) -> Option<u64> {
    if npdm.get(..4)? != b"META" {
        return None;
    }
    let aci = u32::from_le_bytes(npdm.get(0x70..0x74)?.try_into().ok()?) as usize;
    if npdm.get(aci..aci + 4)? != b"ACI0" {
        return None;
    }
    Some(u64::from_le_bytes(
        npdm.get(aci + 0x10..aci + 0x18)?.try_into().ok()?,
    ))
}

/// What the player picked or what was found.
#[derive(Clone, Debug, PartialEq)]
pub enum Pick {
    /// Unpacked game files.
    Dir(GameDir),
    /// A `.nup` dump that still has to be unpacked (`just nup=<file> extract`).
    Nup(PathBuf),
}
impl Pick {
    /// A picked file or folder: the game folder itself, a file inside it (romfs.bin, index.json, main, main.npdm)
    /// or a .nup.
    pub fn from_path(path: &Path) -> Self {
        if path
            .extension()
            .is_some_and(|e| e.eq_ignore_ascii_case("nup"))
        {
            return Self::Nup(path.to_path_buf());
        }
        if path.is_file()
            && let Some(dir) = path.parent().and_then(Path::parent)
        {
            return Self::Dir(GameDir::new(dir));
        }
        // romfs/ or exefs/ itself
        if let (Some(name), Some(parent)) = (path.file_name(), path.parent())
            && (name == "romfs" || name == "exefs")
        {
            return Self::Dir(GameDir::new(parent));
        }
        Self::Dir(GameDir::new(path))
    }

    pub fn path(&self) -> &Path {
        match self {
            Self::Dir(dir) => dir.path(),
            Self::Nup(nup) => nup,
        }
    }
}

/// Where to look when nothing was chosen, in order: beside the launcher binary, the working folder, beside the game
/// binaries (`<src>/build/<ver>`, the runtime's portable layout), the build's extraction folder.
pub fn candidates(
    src: &Path,
    ver: &str,
) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Some(dir) = std::env::args_os()
        .next()
        .map(PathBuf::from)
        .and_then(|p| p.parent().map(Path::to_path_buf))
    {
        dirs.push(dir);
    }
    if let Ok(dir) = std::env::current_dir() {
        dirs.push(dir);
    }
    dirs.push(src.join("build").join(ver));
    dirs.push(src.join("build").join("extracted").join(ver));
    dirs
}

/// The first candidate with game files in it, else a .nup lying in one of them.
pub fn detect(dirs: &[PathBuf]) -> Option<Pick> {
    for dir in dirs {
        let game = GameDir::new(dir);
        if game.is_present() {
            return Some(Pick::Dir(game));
        }
    }
    for dir in dirs {
        let Ok(entries) = std::fs::read_dir(dir) else {
            continue;
        };
        let nup = entries
            .flatten()
            .map(|e| e.path())
            .find(|p| p.extension().is_some_and(|e| e.eq_ignore_ascii_case("nup")));
        if let Some(nup) = nup {
            return Some(Pick::Nup(nup));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pick_from_file() {
        let pick = Pick::from_path(Path::new("/nonexistent/game/romfs/romfs.bin"));
        // not a file on disk: taken as a folder
        assert_eq!(
            pick,
            Pick::Dir(GameDir::new("/nonexistent/game/romfs/romfs.bin"))
        );
        let pick = Pick::from_path(Path::new("/x/Game.NUP"));
        assert_eq!(pick, Pick::Nup(PathBuf::from("/x/Game.NUP")));
        let pick = Pick::from_path(Path::new("/x/game/exefs"));
        assert_eq!(pick, Pick::Dir(GameDir::new("/x/game")));
    }

    #[test]
    fn test_npdm_title() {
        let mut npdm = vec![0u8; 0x100];
        npdm[..4].copy_from_slice(b"META");
        npdm[0x70..0x74].copy_from_slice(&0x80u32.to_le_bytes());
        npdm[0x80..0x84].copy_from_slice(b"ACI0");
        npdm[0x90..0x98].copy_from_slice(&TITLE_ID.to_le_bytes());
        assert_eq!(npdm_title(&npdm), Some(TITLE_ID));
        assert_eq!(npdm_title(b"nope"), None);
    }
}

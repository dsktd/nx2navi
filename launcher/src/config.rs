//! The remembered choice: `$XDG_CONFIG_HOME/nx2navi-launcher/config.toml`, one key `game` (the game folder or .nup).

use std::path::PathBuf;

use anyhow::anyhow;

use crate::Result;

pub fn path() -> Option<PathBuf> {
    dirs::config_dir().map(|d| d.join("nx2navi-launcher").join("config.toml"))
}

pub fn load() -> Option<PathBuf> {
    let text = std::fs::read_to_string(path()?).ok()?;
    let table: toml::Table = text.parse().ok()?;
    table.get("game")?.as_str().map(PathBuf::from)
}

pub fn save(game: &std::path::Path) -> Result<()> {
    let path = path().ok_or(anyhow!("No XDG config folder"))?;
    let mut table = toml::Table::new();
    table.insert("game".into(), game.display().to_string().into());
    std::fs::create_dir_all(path.parent().unwrap())?;
    let tmp = path.with_extension("toml.tmp");
    std::fs::write(&tmp, table.to_string())?;
    std::fs::rename(tmp, path)?;
    Ok(())
}

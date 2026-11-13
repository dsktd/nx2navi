//! A small launcher for NX2navi on Linux: finds or asks for the game files, shows a few start checks and starts the
//! default run (`just run`).

pub mod checks;
pub mod config;
pub mod game;
pub mod run;
pub mod ui;

pub type Result<T> = anyhow::Result<T>;

use std::path::PathBuf;

use crate::checks::Check;
use crate::game::Pick;
use crate::run::Plan;
use crate::run::Root;

/// Everything the checks and Play need.
pub struct State {
    pub root: Root,
    pub run: String,
    pub plan: anyhow::Result<Plan>,
    pub pick: Option<Pick>,
    pub checks: Vec<Check>,
}
impl State {
    /// `game` (command line) wins over the remembered choice, which wins over detection.
    pub fn new(
        root: Root,
        game: Option<PathBuf>,
    ) -> Result<Self> {
        let run = root.default_run()?;
        let plan = Plan::probe(&root, &run);
        let detect = || game::detect(&game::candidates(&root.src, &root.ver));
        // a remembered folder that is gone gives way to detection; shown as chosen when nothing else is found
        let pick = match (game, config::load().map(|p| Pick::from_path(&p))) {
            (Some(game), _) => Some(Pick::from_path(&game)),
            (None, Some(Pick::Dir(dir))) if !dir.is_present() => detect().or(Some(Pick::Dir(dir))),
            (None, Some(pick)) => Some(pick),
            (None, None) => detect(),
        };
        let mut state = Self {
            root,
            run,
            plan,
            pick,
            checks: Vec::new(),
        };
        state.recheck();
        Ok(state)
    }

    pub fn recheck(&mut self) {
        self.checks = checks::all(self.pick.as_ref(), &self.plan);
    }

    /// A new choice from the picker: remembered at once.
    pub fn choose(
        &mut self,
        path: PathBuf,
    ) -> Result<()> {
        let pick = Pick::from_path(&path);
        config::save(pick.path())?;
        self.pick = Some(pick);
        self.recheck();
        Ok(())
    }

    pub fn can_play(&self) -> bool {
        checks::worst(&self.checks) != checks::Status::Red
    }

    pub fn play(&self) -> Result<std::process::Child> {
        let Some(Pick::Dir(game)) = &self.pick else {
            return Err(anyhow::anyhow!("No unpacked game files chosen"));
        };
        run::play(&self.root, &self.run, game)
    }
}

use std::path::PathBuf;

use clap::Parser;
use nx2navi_launcher::State;
use nx2navi_launcher::checks::Status;
use nx2navi_launcher::game::Pick;
use nx2navi_launcher::run::Root;
use nx2navi_launcher::ui;

/// NX2navi launcher: game files, start checks, Play (the default `just run`).
#[derive(Parser)]
struct Args {
    /// Print the checks and exit: 0 when none is red, 1 otherwise
    #[arg(long)]
    check: bool,
    /// The game folder (holding exefs/ and romfs/), a file in it, or a .nup; remembered
    #[arg(long)]
    game: Option<PathBuf>,
    /// The tooling checkout (default: upwards from the working folder, else ~/claude/nx2navi)
    #[arg(long)]
    root: Option<PathBuf>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    let root = Root::find(args.root)?;
    if let Some(game) = &args.game {
        nx2navi_launcher::config::save(Pick::from_path(game).path())?;
    }
    let state = State::new(root, args.game)?;
    if args.check {
        let tty = std::io::IsTerminal::is_terminal(&std::io::stdout());
        for check in &state.checks {
            let word = format!("{:<6}", check.status.to_string());
            let word = if tty {
                paint(check.status, &word)
            } else {
                word
            };
            println!("{word}  {:<13} {}", check.name, check.reason);
            if let Some(hint) = &check.hint {
                println!("{:<8}{:<13} fix: {hint}", "", "");
            }
        }
        std::process::exit(if state.can_play() { 0 } else { 1 });
    }
    let started = ui::Started::default();
    let app = ui::App::new(state, started.clone());
    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_title("NX2navi")
            .with_app_id("nx2navi-launcher")
            .with_inner_size([640.0, 420.0]),
        ..Default::default()
    };
    eframe::run_native("NX2navi", options, Box::new(|_cc| Ok(Box::new(app))))?;
    // Play closes the window; the game keeps the terminal as `just run` would
    if let Some(mut child) = started.lock().unwrap().take() {
        let status = child.wait()?;
        std::process::exit(status.code().unwrap_or(1));
    }
    Ok(())
}

fn paint(
    status: Status,
    word: &str,
) -> String {
    let code = match status {
        Status::Green => 32,
        Status::Yellow => 33,
        Status::Red => 31,
    };
    format!("\x1b[{code}m{word}\x1b[0m")
}

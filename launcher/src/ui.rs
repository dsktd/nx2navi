//! The window: the game files row with Choose, one row per check (a coloured dot, the reason, the fix) and Play.

use std::process::Child;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::mpsc;

use eframe::egui;

use crate::State;
use crate::checks::Status;

/// The game started by Play, handed back to main to wait for once the window is closed.
pub type Started = Arc<Mutex<Option<Child>>>;

pub struct App {
    state: State,
    started: Started,
    picking: Option<mpsc::Receiver<Option<std::path::PathBuf>>>,
    error: Option<String>,
}
impl App {
    pub fn new(
        state: State,
        started: Started,
    ) -> Self {
        Self {
            state,
            started,
            picking: None,
            error: None,
        }
    }

    /// The portal dialog blocks, so it runs on its own thread.
    fn pick(&mut self) {
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            let file = rfd::FileDialog::new()
                .set_title("Choose romfs.bin of the unpacked game (or the .nup)")
                .pick_file();
            let _ = tx.send(file);
        });
        self.picking = Some(rx);
    }
}

pub fn color(status: Status) -> egui::Color32 {
    match status {
        Status::Green => egui::Color32::from_rgb(0x3f, 0xb9, 0x50),
        Status::Yellow => egui::Color32::from_rgb(0xd2, 0x99, 0x22),
        Status::Red => egui::Color32::from_rgb(0xf8, 0x51, 0x49),
    }
}

impl eframe::App for App {
    fn ui(
        &mut self,
        ui: &mut egui::Ui,
        _frame: &mut eframe::Frame,
    ) {
        if let Some(rx) = &self.picking {
            match rx.try_recv() {
                Ok(file) => {
                    self.picking = None;
                    if let Some(file) = file
                        && let Err(err) = self.state.choose(file)
                    {
                        self.error = Some(err.to_string());
                    }
                }
                Err(mpsc::TryRecvError::Empty) => ui
                    .ctx()
                    .request_repaint_after(std::time::Duration::from_millis(100)),
                Err(mpsc::TryRecvError::Disconnected) => self.picking = None,
            }
        }
        egui::Frame::central_panel(ui.style()).show(ui, |ui| {
            ui.heading("NX2navi");
            ui.label(format!("Ocarina of Time 1.1.1 · run {}", self.state.run));
            ui.add_space(8.0);
            ui.horizontal(|ui| {
                let game = self
                    .state
                    .pick
                    .as_ref()
                    .map(|p| p.path().display().to_string());
                ui.label(game.unwrap_or("no game files chosen".into()));
                let choose = ui.add_enabled(self.picking.is_none(), egui::Button::new("Choose…"));
                if choose.clicked() {
                    self.pick();
                }
            });
            ui.add_space(8.0);
            egui::Grid::new("checks")
                .num_columns(3)
                .spacing([10.0, 6.0])
                .show(ui, |ui| {
                    for check in &self.state.checks {
                        let (rect, _) =
                            ui.allocate_exact_size(egui::vec2(14.0, 14.0), egui::Sense::hover());
                        ui.painter()
                            .circle_filled(rect.center(), 6.0, color(check.status));
                        ui.strong(check.name);
                        ui.vertical(|ui| {
                            ui.label(&check.reason);
                            if let Some(hint) = &check.hint {
                                ui.weak(format!("fix: {hint}"));
                            }
                        });
                        ui.end_row();
                    }
                });
            ui.add_space(12.0);
            if let Some(err) = &self.error {
                ui.colored_label(color(Status::Red), err);
            }
            ui.horizontal(|ui| {
                let play = ui.add_enabled(self.state.can_play(), egui::Button::new("  Play  "));
                if play.clicked() {
                    match self.state.play() {
                        Ok(child) => {
                            *self.started.lock().unwrap() = Some(child);
                            ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
                        }
                        Err(err) => self.error = Some(err.to_string()),
                    }
                }
                if ui.button("Check again").clicked() {
                    self.state.recheck();
                }
            });
        });
    }
}

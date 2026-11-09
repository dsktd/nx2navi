// NX2navi first-run screen for the Flatpak kit: fullscreen, pad or keyboard, big SDL debug-font text, so it works in
// Steam Deck Game Mode (gamescope) where portal file choosers do not.
//
//   nx2navi-setup pick <data dir>     build from a .nup or import a prebuilt game: prints "nup <path>" or
//                                     "import <path>", exit 0 (1: quit). Sources: scanned places, else the portal.
//   nx2navi-setup progress <file>     show the build's progress file until it says done (exit 0) or failed (exit 1)
//
// The progress file is written by nx2navi.sh, one "key value" per line: step "<k>/<n> <name>", pct, eta (seconds),
// msg, state (running|done|failed).
#include <SDL3/SDL.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define MAXN 64
#define SCALE 2.5f   // the 8 px debug font at 20 px, 10 px rows: 64 columns, 32 rows on the Deck's 1280x800

static SDL_Renderer *ren;
static char found[MAXN][1024];
static int nfound;

static void add(const char *path) {
    for (int i = 0; i < nfound; i++)
        if (!strcmp(found[i], path)) return;
    if (nfound < MAXN) snprintf(found[nfound++], sizeof found[0], "%s", path);
}

static const char *want;   // the file suffix scan() looks for: ".nup" or ".nx2navi.tar.zst"

static int ends(const char *s, const char *suf) {
    size_t n = strlen(s), m = strlen(suf);
    return n > m && !SDL_strcasecmp(s + n - m, suf);
}

static void scan(const char *dir, int depth) {   // files ending in `want`, down to depth levels, hidden folders skipped
    DIR *d = opendir(dir);
    if (!d) return;
    struct dirent *e;
    char p[1024];
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        snprintf(p, sizeof p, "%s/%s", dir, e->d_name);
        struct stat st;
        if (stat(p, &st)) continue;
        if (S_ISREG(st.st_mode) && ends(e->d_name, want)) add(p);
        else if (S_ISDIR(st.st_mode) && depth > 0) scan(p, depth - 1);
    }
    closedir(d);
}

static void rescan(const char *data) {
    const char *home = getenv("HOME");
    char p[1024];
    nfound = 0;
    scan(data, 1);
    if (home) {
        snprintf(p, sizeof p, "%s/Downloads", home), scan(p, 2);
        snprintf(p, sizeof p, "%s/Desktop", home), scan(p, 2);
        scan(home, 0);
    }
    scan("/run/media", 3);   // SD cards and USB sticks: /run/media/<card> and /run/media/deck/<card>
}

static void text(float col, float row, SDL_Color c, const char *s) {
    SDL_SetRenderDrawColor(ren, c.r, c.g, c.b, 255);
    SDL_RenderDebugText(ren, col * 8, row * 10, s);
}

static const SDL_Color WHITE = {235, 235, 235, 255}, DIM = {140, 150, 160, 255}, HI = {120, 200, 255, 255},
                       WARN = {255, 190, 90, 255}, BAD = {255, 110, 110, 255};

static void begin(void) {
    SDL_SetRenderDrawColor(ren, 16, 24, 40, 255);
    SDL_RenderClear(ren);
    text(1, 1, HI, "NX2navi setup");
}

enum { UP = 1, DOWN, OK, BACK, QUIT };
static int input(void) {   // one input step: -1 none
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
        if (e.type == SDL_EVENT_QUIT) return QUIT;
        if (e.type == SDL_EVENT_GAMEPAD_ADDED) SDL_OpenGamepad(e.gdevice.which);
        if (e.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) switch (e.gbutton.button) {
            case SDL_GAMEPAD_BUTTON_DPAD_UP: return UP;
            case SDL_GAMEPAD_BUTTON_DPAD_DOWN: return DOWN;
            case SDL_GAMEPAD_BUTTON_SOUTH: return OK;
            case SDL_GAMEPAD_BUTTON_EAST: return BACK;
            }
        if (e.type == SDL_EVENT_KEY_DOWN) switch (e.key.key) {
            case SDLK_UP: return UP;
            case SDLK_DOWN: return DOWN;
            case SDLK_RETURN: return OK;
            case SDLK_ESCAPE: return BACK;
            }
    }
    return -1;
}

// A vertical menu of n entries; returns the chosen index, or -1 on B / quit
static int menu(const char *const *items, int n, const char *const *head, int nhead, const char *const *foot, int nfoot) {
    static int sel;
    if (sel >= n) sel = 0;
    for (;;) {
        switch (input()) {
        case UP: sel = (sel + n - 1) % n; break;
        case DOWN: sel = (sel + 1) % n; break;
        case BACK: case QUIT: return -1;
        case OK: { int s = sel; sel = 0; return s; }
        }
        begin();
        for (int i = 0; i < nhead; i++) text(1, 3 + i, i ? DIM : WHITE, head[i]);
        float row = 4 + nhead;
        for (int i = 0; i < n && row < 26; i++, row++) {
            char line[64];
            size_t len = strlen(items[i]);
            snprintf(line, sizeof line, "%s %s", i == sel ? ">" : " ", len > 50 ? items[i] + len - 50 : items[i]);
            text(1, row, i == sel ? HI : WHITE, line);
        }
        for (int i = 0; i < nfoot; i++) text(1, 27 + i, DIM, foot[i]);
        text(1, 31, DIM, "D-pad: move   A: choose   B: back");
        SDL_RenderPresent(ren);
        SDL_Delay(16);
    }
}

// The portal's file chooser (SDL3 asks xdg-desktop-portal; the document portal grants the file). It can fail to show
// in gamescope, so the scanned list stays the main route.
static char portal_path[1024];
static int portal_done;
static void portal_cb(void *u, const char *const *files, int filter) {
    (void)u, (void)filter;
    if (files && files[0]) snprintf(portal_path, sizeof portal_path, "%s", files[0]);
    portal_done = 1;
}
static SDL_Window *win;
static int portal(int folder) {
    portal_path[0] = 0, portal_done = 0;
    if (folder) SDL_ShowOpenFolderDialog(portal_cb, NULL, win, NULL, false);
    else SDL_ShowOpenFileDialog(portal_cb, NULL, win, NULL, 0, NULL, false);
    while (!portal_done) {
        if (input() == QUIT) return 0;
        begin();
        text(1, 3, WHITE, "Waiting for the file chooser...");
        SDL_RenderPresent(ren);
        SDL_Delay(33);
    }
    return portal_path[0] != 0;
}

// One source list: scanned files, then the portal chooser, Rescan, Back. 1 with the choice in *out.
static int choose(const char *data, const char *suffix, const char *what, const char *hint, int folder, char *out) {
    want = suffix;
    rescan(data);
    for (;;) {
        const char *items[MAXN + 3];
        for (int i = 0; i < nfound; i++) items[i] = found[i];
        items[nfound] = folder ? "[ Pick a folder (file chooser) ]" : "[ Pick a file (file chooser) ]";
        items[nfound + 1] = "[ Rescan ]";
        items[nfound + 2] = "[ Back ]";
        const char *head[] = {what, nfound ? "Found:" : "None found yet."};
        const char *foot[] = {hint, "Looked in: the app's data dir, Downloads, Desktop,", "home, SD cards (/run/media)."};
        int c = menu(items, nfound + 3, head, 2, foot, 3);
        if (c < 0 || c == nfound + 2) return 0;
        if (c == nfound + 1) { rescan(data); continue; }
        if (c == nfound) { if (portal(folder)) { snprintf(out, 1024, "%s", portal_path); return 1; } continue; }
        snprintf(out, 1024, "%s", found[c]);
        return 1;
    }
}

// Prints "nup <path>" or "import <path>" and exits 0; 1 on quit
static int pick(const char *data) {
    char path[1024];
    for (;;) {
        const char *items[] = {"Build from my game file (.nup)", "Import a prebuilt game (fast)", "Quit"};
        const char *head[] = {"NX2navi needs your own Ocarina of Time 1.1.1.", "Nothing of the game ships with this app."};
        const char *foot[] = {"Build: hours, on this device, plugged in.",
                              "Import: a .nx2navi.tar.zst exported by this kit",
                              "on another PC (nx2navi export)."};
        int c = menu(items, 3, head, 2, foot, 3);
        if (c < 0 || c == 2) return 1;
        if (c == 0 && choose(data, ".nup", "Pick your game dump (.nup).",
                             "Copy it to Downloads or an SD card, then Rescan.", 0, path))
            return printf("nup %s\n", path), 0;
        if (c == 1 && choose(data, ".nx2navi.tar.zst", "Pick an exported game (.nx2navi.tar.zst).",
                             "Export on the PC: flatpak run ... export", 1, path))
            return printf("import %s\n", path), 0;
    }
}

static int progress(const char *file) {
    char step[128] = "", msg[128] = "", state[32] = "running";
    int pct = 0, eta = -1, failed = 0;
    for (Uint64 next = 0;;) {
        int in = input();
        if (in == QUIT) return 1;
        if (failed && (in == OK || in == BACK)) return 1;
        if (SDL_GetTicks() >= next) {
            next = SDL_GetTicks() + 1000;
            FILE *f = fopen(file, "r");
            char line[256];
            while (f && fgets(line, sizeof line, f)) {
                line[strcspn(line, "\n")] = 0;
                char *v = strchr(line, ' ');
                if (!v) continue;
                *v++ = 0;
                if (!strcmp(line, "step")) snprintf(step, sizeof step, "%s", v);
                else if (!strcmp(line, "msg")) snprintf(msg, sizeof msg, "%.52s", v);
                else if (!strcmp(line, "state")) snprintf(state, sizeof state, "%s", v);
                else if (!strcmp(line, "pct")) pct = atoi(v);
                else if (!strcmp(line, "eta")) eta = atoi(v);
            }
            if (f) fclose(f);
            if (!strcmp(state, "done")) return 0;
            failed = !strcmp(state, "failed");
        }
        begin();
        text(1, 3, WHITE, "Building the game on this device.");
        text(1, 4, WARN, "Stay plugged in. The screen stays on.");
        text(1, 5, DIM, "Steam Deck: about 3 to 5 hours in all (estimate).");
        text(1, 6, DIM, "Quit or sleep any time: it resumes where it stopped.");
        text(1, 9, HI, step);
        float w = 1280 / SCALE - 16;
        SDL_SetRenderDrawColor(ren, 50, 60, 80, 255);
        SDL_RenderFillRect(ren, &(SDL_FRect){8, 11 * 10, w, 8});
        SDL_SetRenderDrawColor(ren, 120, 200, 255, 255);
        SDL_RenderFillRect(ren, &(SDL_FRect){8, 11 * 10, w * pct / 100, 8});
        char line[96];
        if (eta >= 0) snprintf(line, sizeof line, "%d%%   about %dh %02dm left in this step", pct, eta / 3600, eta / 60 % 60);
        else snprintf(line, sizeof line, "%d%%", pct);
        text(1, 13, WHITE, line);
        text(1, 15, DIM, msg);
        if (failed) text(1, 18, BAD, "The build stopped with an error. Log: data/nx2navi/logs. A: close");
        SDL_RenderPresent(ren);
        SDL_Delay(33);
    }
}

int main(int argc, char **argv) {
    if (argc != 3) return fprintf(stderr, "usage: nx2navi-setup pick <data dir> | progress <file>\n"), 2;
    SDL_SetHint(SDL_HINT_VIDEO_ALLOW_SCREENSAVER, "0");   // keep the screen on during the build
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) return fprintf(stderr, "nx2navi-setup: %s\n", SDL_GetError()), 3;
    win = SDL_CreateWindow("NX2navi setup", 1280, 800, SDL_WINDOW_FULLSCREEN);
    if (!win || !(ren = SDL_CreateRenderer(win, NULL))) return fprintf(stderr, "nx2navi-setup: %s\n", SDL_GetError()), 3;
    SDL_DisableScreenSaver();
    SDL_SetRenderLogicalPresentation(ren, 1280 / SCALE, 800 / SCALE, SDL_LOGICAL_PRESENTATION_LETTERBOX);
    int rc = !strcmp(argv[1], "pick") ? pick(argv[2]) : progress(argv[2]);
    SDL_Quit();
    return rc;
}

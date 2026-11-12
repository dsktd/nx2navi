// Wall-clock sampling profiler for Linux (NX2NAVI_PROFILE=<path>), the counterpart of upstream's runtime/prof_win.c,
// which perf.c's weak prof_sampler_* leave out on this OS. Compiled beside the runtime by build-linux.py; the checkout
// is not edited. perf(1) cannot open events in the lab container, so this is how a long replay frame is taken apart.
//
// A host thread wakes every period (1 ms) and sends a real-time signal to each sampled thread; the handler walks the
// thread's own stack (glibc backtrace over .eh_frame) into a ring. A thread asleep in an interruptible wait takes the
// sample at once and goes back to the wait (SA_RESTART); one inside an uninterruptible kernel call (a memory
// allocation, a page fault storm) takes it when the call returns, so each sample carries its weight: the time since
// the thread's previous sample. The weights of a thread add up to the wall time, on and off the CPU.
//
//   NX2NAVI_PROFILE=<path>          output file (text, below)
//   NX2NAVI_PROFILE_FRAMES=<lo>-<hi> sample only while presents lo..hi-1 are pending; the file is written at present hi.
//                                   Without it sampling runs from the start and the file is written at exit with the
//                                   ring's last RING samples.
//   NX2NAVI_PROFILE_MAIN=1, NX2NAVI_PROFILE_RENDER=1  also the guest main thread, the presenting thread
//   NX2NAVI_PROFILE_CHAINS=1        every thread of the process (period 2 ms)
// Default: the replay thread only. Waits of guest threads may return early on a signal, so sampling them can change
// the game's timing; the replay thread waits in pthread conditions and driver calls, which restart.
//
// File: "nx2navi-prof-linux 1", then lines
//   module <lo hex> <hi hex> <file offset hex> <path>     executable mappings (/proc/self/maps)
//   thread <tid> <name>
//   frame <present> <t ns>
//   s <tid> <t ns> <weight ns> <rip hex> <caller hex> ...
// tools/prof-window reads it with the exe (nm) and sums the weights per function for a range of presents.
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <execinfo.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <ucontext.h>
#include <unistd.h>

const char *cfg_get(const char *name);
void rt_log(const char *fmt, ...);
uint64_t kern_now_ns(void);
extern volatile uint32_t prof_render_tid, prof_main_tid, prof_replay_tid;

#define RING (1u << 18)
#define DEPTH 28
#define MAXT 256
#define MAXF 8192
typedef struct { uint64_t t, w; uint32_t tid, depth; uint64_t rip[DEPTH]; } Sample;
typedef struct { uint32_t tid; volatile uint64_t last; volatile int32_t busy; } Slot;

static Sample *ring;
static volatile uint64_t ring_n;
static Slot slots[MAXT];
static volatile int32_t nslots;
static struct { uint64_t frame, t; } frames[MAXF];
static volatile uint32_t nframes;
static const char *out_path;
static int sig, all, want_main, want_render;
static uint64_t frame_lo, frame_hi;
static volatile int32_t active, written, stop;

static Slot *slot_of(uint32_t tid, int add) {
    int n = __atomic_load_n(&nslots, __ATOMIC_ACQUIRE);
    for (int i = 0; i < n; i++)
        if (slots[i].tid == tid) return &slots[i];
    if (!add || n == MAXT) return NULL;   // only the sampler thread adds
    slots[n].tid = tid, slots[n].last = 0, slots[n].busy = 0;
    __atomic_store_n(&nslots, n + 1, __ATOMIC_RELEASE);
    return &slots[n];
}

static void handler(int s, siginfo_t *si, void *uc) {
    (void)s, (void)si;
    int e = errno;
    Slot *sl = slot_of((uint32_t)syscall(SYS_gettid), 0);
    if (sl && __atomic_load_n(&active, __ATOMIC_RELAXED)) {
        uint64_t now = kern_now_ns(), i = __atomic_fetch_add(&ring_n, 1, __ATOMIC_RELAXED);
        Sample *p = &ring[i & (RING - 1)];
        void *bt[DEPTH + 4];
        int n = backtrace(bt, DEPTH + 4), k = 0;
        uint64_t rip = (uint64_t)((ucontext_t *)uc)->uc_mcontext.gregs[REG_RIP];
        for (int j = 0; j < n && j < 4; j++)   // drop the handler's own frames: the chain starts at the interrupted Rip
            if ((uint64_t)bt[j] == rip) { k = j; break; }
        p->tid = sl->tid, p->t = now, p->w = sl->last ? now - sl->last : 0;
        p->depth = 0;
        if ((uint64_t)bt[k] != rip) p->rip[p->depth++] = rip;
        for (int j = k; j < n && p->depth < DEPTH; j++) p->rip[p->depth++] = (uint64_t)bt[j];
        sl->last = now;
    }
    if (sl) __atomic_store_n(&sl->busy, 0, __ATOMIC_RELEASE);
    errno = e;
}

static void targets(void) {
    if (all) {
        DIR *d = opendir("/proc/self/task");
        struct dirent *de;
        uint32_t self = (uint32_t)syscall(SYS_gettid);
        while (d && (de = readdir(d))) {
            uint32_t t = (uint32_t)strtoul(de->d_name, NULL, 10);
            if (t && t != self) slot_of(t, 1);
        }
        if (d) closedir(d);
        return;
    }
    if (prof_replay_tid) slot_of(prof_replay_tid, 1);
    if (want_main && prof_main_tid) slot_of(prof_main_tid, 1);
    if (want_render && prof_render_tid) slot_of(prof_render_tid, 1);
}

static void *sampler(void *arg) {
    (void)arg;
    pthread_setname_np(pthread_self(), "prof sampler");
    struct timespec ts = {0, all ? 2000000 : 1000000};
    int pid = getpid();
    for (uint64_t tick = 0; !__atomic_load_n(&stop, __ATOMIC_RELAXED); tick++) {
        nanosleep(&ts, NULL);
        if (!__atomic_load_n(&active, __ATOMIC_RELAXED)) {
            for (int i = 0; i < nslots; i++) slots[i].last = 0;   // the next window starts its weights anew
            continue;
        }
        if (!(tick & 127)) targets();
        int n = __atomic_load_n(&nslots, __ATOMIC_ACQUIRE);
        for (int i = 0; i < n; i++) {
            if (__atomic_exchange_n(&slots[i].busy, 1, __ATOMIC_ACQ_REL)) continue;   // its last signal is still pending
            if (syscall(SYS_tgkill, pid, (int)slots[i].tid, sig)) slots[i].busy = 0;   // the thread is gone
        }
    }
    return NULL;
}

int prof_sampler_start(void) {
    out_path = cfg_get("NX2NAVI_PROFILE");
    if (!out_path || !*out_path) return 0;
    const char *e;
    all = (e = cfg_get("NX2NAVI_PROFILE_CHAINS")) && *e == '1';
    want_main = (e = cfg_get("NX2NAVI_PROFILE_MAIN")) && *e == '1';
    want_render = (e = cfg_get("NX2NAVI_PROFILE_RENDER")) && *e == '1';
    if ((e = cfg_get("NX2NAVI_PROFILE_FRAMES")) && *e) {
        char *end;
        frame_lo = strtoull(e, &end, 10);
        frame_hi = *end == '-' ? strtoull(end + 1, NULL, 10) : frame_lo + 1;
    }
    ring = calloc(RING, sizeof *ring);
    if (!ring) return 0;
    void *warm[4];
    backtrace(warm, 4);   // loads the unwinder now, not inside the first signal
    sig = SIGRTMIN + 6;   // SIGRTMIN + 4 is platform/linux.c's interrupt
    struct sigaction sa = {.sa_sigaction = handler, .sa_flags = SA_SIGINFO | SA_RESTART | SA_ONSTACK};
    sigemptyset(&sa.sa_mask);
    if (sigaction(sig, &sa, NULL)) return 0;
    __atomic_store_n(&active, !frame_hi, __ATOMIC_RELEASE);
    pthread_t th;
    if (pthread_create(&th, NULL, sampler, NULL)) return 0;
    pthread_detach(th);
    rt_log("prof: sampling %s every %d ms into %s%s (runtime-linux/prof_linux.c)",
           all ? "every thread" : "the replay thread", all ? 2 : 1, out_path, frame_hi ? ", a range of presents" : "");
    return 1;
}

void prof_sampler_write(void) {
    if (!out_path || __atomic_exchange_n(&written, 1, __ATOMIC_ACQ_REL)) return;
    __atomic_store_n(&active, 0, __ATOMIC_RELEASE);
    struct timespec ts = {0, 5000000};
    nanosleep(&ts, NULL);   // handlers in flight finish their sample
    FILE *f = fopen(out_path, "w");
    if (!f) { rt_log("prof: cannot write %s", out_path); return; }
    fprintf(f, "nx2navi-prof-linux 1\n");
    FILE *m = fopen("/proc/self/maps", "r");
    char line[1024];
    while (m && fgets(line, sizeof line, m)) {
        unsigned long long lo, hi, off;
        char perm[8], path[768] = "";
        if (sscanf(line, "%llx-%llx %7s %llx %*s %*s %767[^\n]", &lo, &hi, perm, &off, path) >= 4 && perm[2] == 'x')
            fprintf(f, "module %llx %llx %llx %s\n", lo, hi, off, path[0] ? path : "-");
    }
    if (m) fclose(m);
    for (int i = 0; i < nslots; i++) {
        char p[64], name[64] = "?";
        snprintf(p, sizeof p, "/proc/self/task/%u/comm", slots[i].tid);
        FILE *c = fopen(p, "r");
        if (c) {
            if (fgets(name, sizeof name, c)) name[strcspn(name, "\n")] = 0;
            fclose(c);
        }
        fprintf(f, "thread %u %s%s\n", slots[i].tid, name,
                slots[i].tid == prof_replay_tid ? " [replay]" : slots[i].tid == prof_main_tid ? " [main]"
                : slots[i].tid == prof_render_tid ? " [render]" : "");
    }
    uint32_t nf = nframes < MAXF ? nframes : MAXF;
    for (uint32_t i = 0; i < nf; i++)
        fprintf(f, "frame %llu %llu\n", (unsigned long long)frames[i].frame, (unsigned long long)frames[i].t);
    uint64_t n = ring_n, first = n > RING ? n - RING : 0;
    for (uint64_t i = first; i < n; i++) {
        const Sample *p = &ring[i & (RING - 1)];
        fprintf(f, "s %u %llu %llu", p->tid, (unsigned long long)p->t, (unsigned long long)p->w);
        for (uint32_t j = 0; j < p->depth; j++) fprintf(f, " %llx", (unsigned long long)p->rip[j]);
        fputc('\n', f);
    }
    fclose(f);
    rt_log("prof: %llu samples of %d threads written to %s", (unsigned long long)(n - first), (int)nslots, out_path);
}

void prof_sampler_frame(uint64_t frame, uint64_t now, uint64_t d) {
    (void)d;
    if (!out_path || written) return;
    if (frame_hi) {
        if (frame >= frame_hi) { prof_sampler_write(); return; }
        if (frame + 1 >= frame_lo && !active) __atomic_store_n(&active, 1, __ATOMIC_RELEASE);
        if (!active) return;
    }
    uint32_t i = nframes;
    frames[i % MAXF].frame = frame, frames[i % MAXF].t = now;   // without a range the newest MAXF presents
    nframes = i + 1;
}

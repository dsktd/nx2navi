// cpu-sampler.so: a perf-less sampling profiler for one thread name (the container denies perf_event_open).
// LD_PRELOAD=cpu-sampler.so SAMPLER_COMM='vk replay' SAMPLER_OUT=file SAMPLER_HZ=1000 SAMPLER_DELAY=s SAMPLER_SECS=s
// A helper thread finds the threads named SAMPLER_COMM (/proc/self/task/*/comm) and arms a CPU-time timer on each
// (CLOCK_THREAD_CPUTIME of that thread, SIGEV_THREAD_ID): SIGPROF then lands on that thread every 1/HZ s of its own
// CPU, and the handler stores the interrupted RIP plus a frame-pointer walk of up to 8 return addresses. Samples are
// taken from SAMPLER_DELAY to DELAY+SECS seconds after start and written as text lines "rip ret1 ret2 ..." at the end,
// /proc/self/maps beside them as <out>.maps; tools/cpu-sampler-report.py symbolises them.
// Build: clang -O2 -shared -fPIC -o cpu-sampler.so cpu-sampler.c
#define _GNU_SOURCE
#include <dirent.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <ucontext.h>
#include <unistd.h>

#define MAXS (1 << 20)
#define DEPTH 8
static uint64_t samples[MAXS][DEPTH + 1];
static atomic_int nsamp;
static atomic_int active;

static void on_prof(int sig, siginfo_t *si, void *uc_)
{
    (void)sig; (void)si;
    if (!atomic_load(&active)) return;
    int i = atomic_fetch_add(&nsamp, 1);
    if (i >= MAXS) return;
    ucontext_t *uc = uc_;
    uint64_t *s = samples[i];
    s[0] = uc->uc_mcontext.gregs[REG_RIP];
    uint64_t *fp = (uint64_t *)uc->uc_mcontext.gregs[REG_RBP];
    uint64_t sp = uc->uc_mcontext.gregs[REG_RSP];
    for (int d = 1; d <= DEPTH; d++) {
        // only follow a plausible frame chain on this stack
        if ((uint64_t)fp < sp || (uint64_t)fp - sp > (8u << 20) || ((uint64_t)fp & 7)) { s[d] = 0; continue; }
        s[d] = fp[1];
        sp = (uint64_t)fp;
        fp = (uint64_t *)fp[0];
    }
}

static void *watch(void *arg)
{
    (void)arg;
    const char *comm = getenv("SAMPLER_COMM"), *out = getenv("SAMPLER_OUT");
    double hz = getenv("SAMPLER_HZ") ? atof(getenv("SAMPLER_HZ")) : 1000;
    int delay = getenv("SAMPLER_DELAY") ? atoi(getenv("SAMPLER_DELAY")) : 0;
    int secs = getenv("SAMPLER_SECS") ? atoi(getenv("SAMPLER_SECS")) : 60;
    int armed[256], narmed = 0;
    for (int t = 0; t < (delay + secs) * 10; t++) {
        if (t == delay * 10) atomic_store(&active, 1);
        DIR *d = opendir("/proc/self/task");
        struct dirent *e;
        while (d && (e = readdir(d))) {
            int tid = atoi(e->d_name), seen = 0;
            if (tid <= 0) continue;
            for (int k = 0; k < narmed; k++) seen |= armed[k] == tid;
            if (seen || narmed == 256) continue;
            char p[64], name[32] = {0};
            snprintf(p, sizeof p, "/proc/self/task/%d/comm", tid);
            FILE *f = fopen(p, "r");
            if (!f) continue;
            if (fgets(name, sizeof name, f)) name[strcspn(name, "\n")] = 0;
            fclose(f);
            if (strcmp(name, comm)) continue;
            struct sigevent sev = {.sigev_notify = SIGEV_THREAD_ID, .sigev_signo = SIGPROF};
            sev._sigev_un._tid = tid;
            clockid_t clk = (clockid_t)((~(unsigned)tid << 3) | 6);   // MAKE_THREAD_CPUCLOCK(tid, CPUCLOCK_SCHED)
            timer_t tm;
            if (timer_create(clk, &sev, &tm)) { perror("cpu-sampler: timer_create"); continue; }
            long ns = (long)(1e9 / hz);
            struct itimerspec its = {{0, ns}, {0, ns}};
            timer_settime(tm, 0, &its, NULL);
            armed[narmed++] = tid;
            fprintf(stderr, "cpu-sampler: sampling tid %d (%s) at %.0f Hz\n", tid, name, hz);
        }
        if (d) closedir(d);
        usleep(100000);
    }
    atomic_store(&active, 0);
    usleep(50000);
    FILE *f = fopen(out ? out : "cpu-sampler.txt", "w");
    int n = atomic_load(&nsamp) < MAXS ? atomic_load(&nsamp) : MAXS;
    for (int i = 0; f && i < n; i++) {
        for (int d = 0; d <= DEPTH; d++) fprintf(f, d ? " %lx" : "%lx", (unsigned long)samples[i][d]);
        fputc('\n', f);
    }
    if (f) fclose(f);
    // the mappings, for addresses in shared libraries: <out>.maps
    char mp[4096];
    snprintf(mp, sizeof mp, "%s.maps", out ? out : "cpu-sampler.txt");
    FILE *in = fopen("/proc/self/maps", "r"), *mo = fopen(mp, "w");
    int c;
    while (in && mo && (c = fgetc(in)) != EOF) fputc(c, mo);
    if (in) fclose(in);
    if (mo) fclose(mo);
    fprintf(stderr, "cpu-sampler: %d samples written\n", n);
    return NULL;
}

__attribute__((constructor)) static void init(void)
{
    if (!getenv("SAMPLER_COMM")) return;
    struct sigaction sa = {.sa_sigaction = on_prof, .sa_flags = SA_SIGINFO | SA_RESTART};
    sigemptyset(&sa.sa_mask);
    sigaction(SIGPROF, &sa, NULL);
    pthread_t th;
    pthread_create(&th, NULL, watch, NULL);
    pthread_detach(th);
}

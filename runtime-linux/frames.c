// Host frame capture and resume for the guest setjmp/longjmp on Linux (runtime/guest_setjmp.c).
//
// Upstream's runtime/platform/linux.c leaves plat_frame_capture a stub ("not on Linux yet"), so every setjmp the
// game makes is fatal there. This file, compiled beside the runtime by build-linux.py without touching the checkout,
// supplies the two halves:
//
//   nx_frame_capture(out, want, arg): walk the host stack with the C unwinder (.eh_frame, which clang emits for every
//     object on x86-64 Linux) up to the first frame whose code want() accepts (the lifted guest function that called
//     setjmp), and keep that frame's state as it will be when its call returns: rbx, rbp, r12-r15 as the unwinder
//     restores them to that frame, the CFA (its rsp after the return), the return address, MXCSR and the x87 control
//     word. Stored inside the jmp_buf bytes of PlatJmp (200 bytes on glibc; 80 used).
//   nx_frame_resume(buf, val): the resume. guest_setjmp.c is compiled with -Dlongjmp=nx_frame_resume, so its
//     plat_jmp_go(&frame) (longjmp((&frame)->b, 1) on Linux) lands here; the signature is <setjmp.h>'s longjmp. It
//     restores the registers above, sets rsp, puts 1 in eax (the lifted call returns a second time) and jumps.
//
// Wiring (build-linux.py): platform/linux.c gets -Dplat_frame_capture=plat_frame_capture_stub so its stub keeps out
// of the way; guest_setjmp.c gets -Dplat_frame_capture=nx_frame_capture -Dlongjmp=nx_frame_resume. Other users of
// plat_jmp_save/plat_jmp_go keep glibc's setjmp/longjmp.
#include <setjmp.h>
#include <stdint.h>
#include <string.h>
#include <unwind.h>

typedef struct {
    uint64_t rbx, rbp, r12, r13, r14, r15, rsp, rip;   // 0..56; 48 rsp; 56 rip
    uint32_t mxcsr, fpcw;                               // 64, 68
    uint64_t magic;                                     // 72: a buffer this file filled
} NxFrame;

#define NX_MAGIC 0x6e786672616d65ull   /* "nxframe" */
_Static_assert(sizeof(NxFrame) <= sizeof(jmp_buf), "NxFrame fits a jmp_buf");

typedef struct {
    int (*want)(uintptr_t rip, void *arg);
    void *arg;
    NxFrame *out;
    int found;
} Walk;

static _Unwind_Reason_Code step(struct _Unwind_Context *ctx, void *p) {
    Walk *w = p;
    int before = 0;
    uintptr_t ip = _Unwind_GetIPInfo(ctx, &before);
    if (!ip) return _URC_END_OF_STACK;
    // the return address may sit on the first byte after a call that never returns: look the call itself up
    if (!w->want(before ? ip : ip - 1, w->arg)) return _URC_NO_REASON;
    NxFrame *f = w->out;
    f->rbx = _Unwind_GetGR(ctx, 3);
    f->rbp = _Unwind_GetGR(ctx, 6);
    f->r12 = _Unwind_GetGR(ctx, 12);
    f->r13 = _Unwind_GetGR(ctx, 13);
    f->r14 = _Unwind_GetGR(ctx, 14);
    f->r15 = _Unwind_GetGR(ctx, 15);
    f->rsp = _Unwind_GetCFA(ctx);
    f->rip = ip;
    __asm__ volatile("stmxcsr %0\n\tfnstcw %1" : "=m"(f->mxcsr), "=m"(f->fpcw));
    f->magic = NX_MAGIC;
    w->found = 1;
    return _URC_END_OF_STACK;   // anything but NO_REASON stops the walk
}

int nx_frame_capture(jmp_buf *out, int (*want)(uintptr_t rip, void *arg), void *arg) {
    Walk w = {want, arg, (NxFrame *)out, 0};
    memset(out, 0, sizeof *out);
    _Unwind_Backtrace(step, &w);
    return w.found;
}

// longjmp's signature: the jmp_buf decays to struct __jmp_buf_tag *; val is ignored, the lifted call returns 1.
__attribute__((noreturn)) void nx_frame_resume(struct __jmp_buf_tag *buf, int val);
__asm__(".text\n"
        ".globl nx_frame_resume\n"
        ".type nx_frame_resume, @function\n"
        ".p2align 4\n"
        "nx_frame_resume:\n"
        "    movq 0(%rdi), %rbx\n"
        "    movq 8(%rdi), %rbp\n"
        "    movq 16(%rdi), %r12\n"
        "    movq 24(%rdi), %r13\n"
        "    movq 32(%rdi), %r14\n"
        "    movq 40(%rdi), %r15\n"
        "    ldmxcsr 64(%rdi)\n"
        "    fldcw 68(%rdi)\n"
        "    movq 48(%rdi), %rsp\n"
        "    movq 56(%rdi), %rdx\n"
        "    movl $1, %eax\n"
        "    jmp *%rdx\n"
        ".size nx_frame_resume, .-nx_frame_resume\n");

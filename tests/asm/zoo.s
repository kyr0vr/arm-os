// Every instruction form the ArmOS assembler encodes. tests/toolchain_compare.py
// assembles this with both our assembler and clang and requires identical bytes.

.text
.global _start
_start:
    // moves
    mov     x0, #0
    mov     w1, #1
    mov     x2, #0xffff
    mov     x3, #0x10000
    mov     x4, #0xffff0000
    mov     x5, #-1
    mov     w6, #-2
    mov     x7, #0x5555555555555555
    mov     w8, #0xff00ff00
    mov     x9, #(3 << 20)
    mov     x10, x11
    mov     w12, w13
    mov     sp, x14
    mov     x15, sp
    movz    x0, #0x1234, lsl #16
    movz    w0, #0xbeef
    movk    x1, #0xabcd, lsl #48
    movk    w1, #1, lsl #16
    movn    x2, #5
    movn    w2, #5, lsl #16

    // add / sub
    add     x0, x1, #4095
    add     x0, x1, #1, lsl #12
    add     w0, w1, #7
    add     sp, sp, #16
    sub     sp, sp, #32
    sub     x0, x1, x2
    add     x0, x1, x2, lsl #3
    sub     w0, w1, w2, lsr #2
    add     x0, x1, x2, asr #63
    sub     sp, sp, x16
    add     x0, sp, x1
    adds    x0, x1, x2
    subs    w0, w1, #1
    cmp     x0, #0
    cmp     w3, w4
    cmp     x2, x0, asr #63
    cmn     x0, #1
    neg     x0, x1
    add     x0, x1, #-8

    // logical
    and     x0, x1, #0xff
    and     w0, w1, #0x80000000
    orr     x0, x1, #0x0f0f0f0f0f0f0f0f
    eor     x0, x0, #1
    eor     x3, x3, #0x7fffffffffffffff
    eor     x3, x3, #0x8000000000000000
    ands    x0, x1, #0xfff0
    tst     x0, #0xffff
    tst     w3, #0x20
    and     x0, x1, x2
    orr     w0, w1, w2, lsl #4
    eor     x0, x1, x2, ror #8
    ands    x0, x1, x2
    bic     x0, x1, x2
    orn     w0, w1, w2
    mvn     x0, x1
    mvn     w0, w1
    and     sp, x1, #0xfffffffffffffff0

    // shifts and bit fields
    lsl     x0, x1, #3
    lsl     w0, w1, #31
    lsr     x0, x1, #60
    lsr     w0, w1, #1
    asr     x0, x1, #63
    asr     w0, w1, #4
    lsl     x0, x1, x2
    lsr     w0, w1, w2
    asr     x0, x1, x2
    ubfx    x0, x0, #5, #3
    ubfx    w0, w1, #0, #32
    sbfx    x0, x1, #8, #8
    bfi     x0, x5, #8, #4
    bfi     w3, w4, #0, #1
    bfxil   x0, x1, #4, #4
    sxtb    x0, w0
    sxth    x0, w1
    sxtw    x0, w2
    sxtb    w0, w1
    uxtb    w0, w0
    uxth    w0, w1

    // multiply / divide
    mul     x0, x1, x2
    mul     w0, w1, w2
    madd    x0, x1, x2, x3
    msub    x0, x2, x1, x0
    smulh   x2, x0, x1
    umulh   x2, x0, x1
    udiv    x0, x1, x2
    sdiv    w0, w1, w2

    // conditional select
    csel    x0, x1, x2, eq
    csel    w0, w1, w2, gt
    csinc   x0, x1, x2, ne
    csinv   x0, x0, xzr, cc
    csneg   x0, x1, x2, lt
    cset    x0, eq
    cset    w0, hs
    cset    x0, lo
    csetm   x0, vs

    // branches (all to local labels)
1:  b       1b
    bl      2f
    b.eq    1b
    b.ne    2f
    b.hs    1b
    b.lo    2f
    b.vs    1b
    b.gt    2f
    cbz     w0, 1b
    cbnz    x1, 2f
    tbz     x0, #63, 1b
    tbnz    w3, #5, 2f
2:  br      x3
    blr     x4
    ret
    ret     x1

    // addresses
    adrp    x0, target
    add     x0, x0, :lo12:target
    adr     x1, target
    adr     x2, 1b
    ldr     x3, literal
    ldr     w4, literal

    // loads and stores
    ldr     x0, [x1]
    ldr     x0, [x1, #8]
    ldr     x0, [x1, #32760]
    ldr     w0, [x1, #0x18]
    ldrb    w0, [x1, #4095]
    ldrh    w0, [x1, #2]
    ldrsb   x0, [x1]
    ldrsb   w0, [x1, #1]
    ldrsh   x0, [x1, #6]
    ldrsh   w0, [x1]
    ldrsw   x0, [x1, #4]
    str     x0, [x1]
    str     w0, [x2, #4]
    strb    w0, [x2, #3]
    strh    w0, [x2, #2]
    ldr     x0, [x1, #-8]
    ldur    x0, [x1, #3]
    str     x0, [sp, #-16]!
    ldr     x0, [sp], #16
    ldrb    w4, [x0], #1
    strb    wzr, [x2], #1
    str     xzr, [x0], #8
    str     w9, [x10], #4
    ldr     x5, [x6, #-256]!
    ldrb    w3, [x4, x5]
    ldr     x0, [x1, x2, lsl #3]
    ldr     w0, [x1, x2]
    stp     x29, x30, [sp, #-16]!
    ldp     x29, x30, [sp], #16
    stp     x0, x1, [x2]
    ldp     x0, x1, [x2, #16]
    ldp     x6, x7, [x0], #16
    stp     w0, w1, [sp, #8]
    ldp     x0, x1, [sp, #-512]

    // system
    mrs     x0, mpidr_el1
    mrs     x1, CurrentEL
    mrs     x2, cntpct_el0
    mrs     x3, cntfrq_el0
    mrs     x4, tpidr_el1
    mrs     x5, esr_el2
    mrs     x6, S3_0_C15_C2_0
    msr     vbar_el1, x0
    msr     vbar_el2, x0
    msr     cpacr_el1, x0
    msr     tpidr_el1, x1
    msr     sctlr_el1, x2
    msr     hcr_el2, x3
    msr     daifset, #2
    msr     daifclr, #0xf
    dsb     sy
    dsb     ish
    dmb     sy
    dmb     ishst
    isb
    nop
    yield
    wfe
    wfi
    sev
    sevl
    hlt     #0xf000
    svc     #0
    hvc     #1
    brk     #0x3e8
    ic      iallu
    eret

    // atomics, caches, TLBs
    ldxr    w0, [x1]
    ldxr    x0, [x1]
    ldaxr   w2, [x3]
    ldaxr   x2, [x3]
    stxr    w4, w5, [x6]
    stxr    w4, x5, [x6]
    stlxr   w7, w8, [x9]
    ldar    x0, [x1]
    stlr    wzr, [x2]
    stlr    x3, [x4]
    clrex
    tlbi    vmalle1
    tlbi    vmalle1is
    tlbi    alle2
    dc      civac, x0
    dc      cvac, x1
    dc      ivac, x2
    mrs     x0, vpidr_el2
    msr     vmpidr_el2, x1
    mrs     x2, isr_el1
    mrs     x3, id_aa64mmfr0_el1
    mrs     x4, ctr_el0
    msr     sp_el1, x5
    msr     elr_el2, x6
    msr     spsr_el2, x7
    msr     cnthctl_el2, x8
    msr     cntvoff_el2, xzr
    msr     cptr_el2, x9
    msr     cntv_tval_el0, x10
    msr     cntv_ctl_el0, x11
    msr     mair_el1, x12
    msr     tcr_el1, x13
    msr     ttbr0_el1, x14
    mrs     x15, esr_el1
    mrs     x16, far_el1
    mrs     x17, elr_el1
    smc     #0

    .balign 8
literal: .xword 0x1122334455667788

.section .rodata, "a"
target: .asciz "zoo\n"
        .ascii "\x01\002\t"
        .byte 1, 2, 0xff
        .hword 0x1234
        .word 0xdeadbeef
        .balign 8
        .xword target
        .zero 3

.data
        .balign 16
counter: .word 1
.rept 3
        .byte 7
.endr

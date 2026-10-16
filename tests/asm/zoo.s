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

.text
    // NEON (Advanced SIMD): the integer forms the video code uses
    add       v0.8b, v3.8b, v29.8b
    add       v0.16b, v3.16b, v29.16b
    add       v0.4h, v3.4h, v29.4h
    add       v0.8h, v3.8h, v29.8h
    add       v0.2s, v3.2s, v29.2s
    add       v0.4s, v3.4s, v29.4s
    sub       v1.8b, v4.8b, v30.8b
    sub       v1.16b, v4.16b, v30.16b
    sub       v1.4h, v4.4h, v30.4h
    sub       v1.8h, v4.8h, v30.8h
    sub       v1.2s, v4.2s, v30.2s
    sub       v1.4s, v4.4s, v30.4s
    mul       v2.8b, v5.8b, v31.8b
    mul       v2.16b, v5.16b, v31.16b
    mul       v2.4h, v5.4h, v31.4h
    mul       v2.8h, v5.8h, v31.8h
    mul       v2.2s, v5.2s, v31.2s
    mul       v2.4s, v5.4s, v31.4s
    mla       v3.8b, v6.8b, v0.8b
    mla       v3.16b, v6.16b, v0.16b
    mla       v3.4h, v6.4h, v0.4h
    mla       v3.8h, v6.8h, v0.8h
    mla       v3.2s, v6.2s, v0.2s
    mla       v3.4s, v6.4s, v0.4s
    mls       v4.8b, v7.8b, v1.8b
    mls       v4.16b, v7.16b, v1.16b
    mls       v4.4h, v7.4h, v1.4h
    mls       v4.8h, v7.8h, v1.8h
    mls       v4.2s, v7.2s, v1.2s
    mls       v4.4s, v7.4s, v1.4s
    smax      v5.8b, v8.8b, v2.8b
    smax      v5.16b, v8.16b, v2.16b
    smax      v5.4h, v8.4h, v2.4h
    smax      v5.8h, v8.8h, v2.8h
    smax      v5.2s, v8.2s, v2.2s
    smax      v5.4s, v8.4s, v2.4s
    smin      v6.8b, v9.8b, v3.8b
    smin      v6.16b, v9.16b, v3.16b
    smin      v6.4h, v9.4h, v3.4h
    smin      v6.8h, v9.8h, v3.8h
    smin      v6.2s, v9.2s, v3.2s
    smin      v6.4s, v9.4s, v3.4s
    umax      v7.8b, v10.8b, v4.8b
    umax      v7.16b, v10.16b, v4.16b
    umax      v7.4h, v10.4h, v4.4h
    umax      v7.8h, v10.8h, v4.8h
    umax      v7.2s, v10.2s, v4.2s
    umax      v7.4s, v10.4s, v4.4s
    umin      v8.8b, v11.8b, v5.8b
    umin      v8.16b, v11.16b, v5.16b
    umin      v8.4h, v11.4h, v5.4h
    umin      v8.8h, v11.8h, v5.8h
    umin      v8.2s, v11.2s, v5.2s
    umin      v8.4s, v11.4s, v5.4s
    urhadd    v9.8b, v12.8b, v6.8b
    urhadd    v9.16b, v12.16b, v6.16b
    urhadd    v9.4h, v12.4h, v6.4h
    urhadd    v9.8h, v12.8h, v6.8h
    urhadd    v9.2s, v12.2s, v6.2s
    urhadd    v9.4s, v12.4s, v6.4s
    uhadd     v10.8b, v13.8b, v7.8b
    uhadd     v10.16b, v13.16b, v7.16b
    uhadd     v10.4h, v13.4h, v7.4h
    uhadd     v10.8h, v13.8h, v7.8h
    uhadd     v10.2s, v13.2s, v7.2s
    uhadd     v10.4s, v13.4s, v7.4s
    zip1      v11.8b, v14.8b, v8.8b
    zip1      v11.16b, v14.16b, v8.16b
    zip1      v11.4h, v14.4h, v8.4h
    zip1      v11.8h, v14.8h, v8.8h
    zip1      v11.2s, v14.2s, v8.2s
    zip1      v11.4s, v14.4s, v8.4s
    zip2      v12.8b, v15.8b, v9.8b
    zip2      v12.16b, v15.16b, v9.16b
    zip2      v12.4h, v15.4h, v9.4h
    zip2      v12.8h, v15.8h, v9.8h
    zip2      v12.2s, v15.2s, v9.2s
    zip2      v12.4s, v15.4s, v9.4s
    uzp1      v13.8b, v16.8b, v10.8b
    uzp1      v13.16b, v16.16b, v10.16b
    uzp1      v13.4h, v16.4h, v10.4h
    uzp1      v13.8h, v16.8h, v10.8h
    uzp1      v13.2s, v16.2s, v10.2s
    uzp1      v13.4s, v16.4s, v10.4s
    uzp2      v14.8b, v17.8b, v11.8b
    uzp2      v14.16b, v17.16b, v11.16b
    uzp2      v14.4h, v17.4h, v11.4h
    uzp2      v14.8h, v17.8h, v11.8h
    uzp2      v14.2s, v17.2s, v11.2s
    uzp2      v14.4s, v17.4s, v11.4s
    trn1      v15.8b, v18.8b, v12.8b
    trn1      v15.16b, v18.16b, v12.16b
    trn1      v15.4h, v18.4h, v12.4h
    trn1      v15.8h, v18.8h, v12.8h
    trn1      v15.2s, v18.2s, v12.2s
    trn1      v15.4s, v18.4s, v12.4s
    trn2      v16.8b, v19.8b, v13.8b
    trn2      v16.16b, v19.16b, v13.16b
    trn2      v16.4h, v19.4h, v13.4h
    trn2      v16.8h, v19.8h, v13.8h
    trn2      v16.2s, v19.2s, v13.2s
    trn2      v16.4s, v19.4s, v13.4s
    add     v1.2d, v2.2d, v3.2d
    sub     v4.2d, v5.2d, v31.2d
    zip1    v1.2d, v2.2d, v3.2d
    and       v1.16b, v2.16b, v3.16b
    and       v30.8b, v29.8b, v28.8b
    orr       v1.16b, v2.16b, v3.16b
    orr       v30.8b, v29.8b, v28.8b
    eor       v1.16b, v2.16b, v3.16b
    eor       v30.8b, v29.8b, v28.8b
    bic       v1.16b, v2.16b, v3.16b
    bic       v30.8b, v29.8b, v28.8b
    mov     v7.16b, v8.16b
    mov     v9.8b, v10.8b
    neg       v3.8b, v4.8b
    neg       v3.16b, v4.16b
    neg       v3.4h, v4.4h
    neg       v3.8h, v4.8h
    neg       v3.2s, v4.2s
    neg       v3.4s, v4.4s
    neg       v3.2d, v4.2d
    abs       v3.8b, v4.8b
    abs       v3.16b, v4.16b
    abs       v3.4h, v4.4h
    abs       v3.8h, v4.8h
    abs       v3.2s, v4.2s
    abs       v3.4s, v4.4s
    abs       v3.2d, v4.2d
    uaddl     v1.8h, v2.8b, v3.8b
    uaddl2    v4.8h, v5.16b, v6.16b
    uaddl     v1.4s, v2.4h, v3.4h
    uaddl2    v4.4s, v5.8h, v6.8h
    uaddl     v1.2d, v2.2s, v3.2s
    uaddl2    v4.2d, v5.4s, v6.4s
    saddl     v1.8h, v2.8b, v3.8b
    saddl2    v4.8h, v5.16b, v6.16b
    saddl     v1.4s, v2.4h, v3.4h
    saddl2    v4.4s, v5.8h, v6.8h
    saddl     v1.2d, v2.2s, v3.2s
    saddl2    v4.2d, v5.4s, v6.4s
    usubl     v1.8h, v2.8b, v3.8b
    usubl2    v4.8h, v5.16b, v6.16b
    usubl     v1.4s, v2.4h, v3.4h
    usubl2    v4.4s, v5.8h, v6.8h
    usubl     v1.2d, v2.2s, v3.2s
    usubl2    v4.2d, v5.4s, v6.4s
    ssubl     v1.8h, v2.8b, v3.8b
    ssubl2    v4.8h, v5.16b, v6.16b
    ssubl     v1.4s, v2.4h, v3.4h
    ssubl2    v4.4s, v5.8h, v6.8h
    ssubl     v1.2d, v2.2s, v3.2s
    ssubl2    v4.2d, v5.4s, v6.4s
    umull     v1.8h, v2.8b, v3.8b
    umull2    v4.8h, v5.16b, v6.16b
    umull     v1.4s, v2.4h, v3.4h
    umull2    v4.4s, v5.8h, v6.8h
    umull     v1.2d, v2.2s, v3.2s
    umull2    v4.2d, v5.4s, v6.4s
    smull     v1.8h, v2.8b, v3.8b
    smull2    v4.8h, v5.16b, v6.16b
    smull     v1.4s, v2.4h, v3.4h
    smull2    v4.4s, v5.8h, v6.8h
    smull     v1.2d, v2.2s, v3.2s
    smull2    v4.2d, v5.4s, v6.4s
    umlal     v1.8h, v2.8b, v3.8b
    umlal2    v4.8h, v5.16b, v6.16b
    umlal     v1.4s, v2.4h, v3.4h
    umlal2    v4.4s, v5.8h, v6.8h
    umlal     v1.2d, v2.2s, v3.2s
    umlal2    v4.2d, v5.4s, v6.4s
    smlal     v1.8h, v2.8b, v3.8b
    smlal2    v4.8h, v5.16b, v6.16b
    smlal     v1.4s, v2.4h, v3.4h
    smlal2    v4.4s, v5.8h, v6.8h
    smlal     v1.2d, v2.2s, v3.2s
    smlal2    v4.2d, v5.4s, v6.4s
    umlsl     v1.8h, v2.8b, v3.8b
    umlsl2    v4.8h, v5.16b, v6.16b
    umlsl     v1.4s, v2.4h, v3.4h
    umlsl2    v4.4s, v5.8h, v6.8h
    umlsl     v1.2d, v2.2s, v3.2s
    umlsl2    v4.2d, v5.4s, v6.4s
    smlsl     v1.8h, v2.8b, v3.8b
    smlsl2    v4.8h, v5.16b, v6.16b
    smlsl     v1.4s, v2.4h, v3.4h
    smlsl2    v4.4s, v5.8h, v6.8h
    smlsl     v1.2d, v2.2s, v3.2s
    smlsl2    v4.2d, v5.4s, v6.4s
    uaddw     v1.8h, v2.8h, v3.8b
    uaddw2    v4.8h, v5.8h, v6.16b
    uaddw     v1.4s, v2.4s, v3.4h
    uaddw2    v4.4s, v5.4s, v6.8h
    uaddw     v1.2d, v2.2d, v3.2s
    uaddw2    v4.2d, v5.2d, v6.4s
    saddw     v1.8h, v2.8h, v3.8b
    saddw2    v4.8h, v5.8h, v6.16b
    saddw     v1.4s, v2.4s, v3.4h
    saddw2    v4.4s, v5.4s, v6.8h
    saddw     v1.2d, v2.2d, v3.2s
    saddw2    v4.2d, v5.2d, v6.4s
    usubw     v1.8h, v2.8h, v3.8b
    usubw2    v4.8h, v5.8h, v6.16b
    usubw     v1.4s, v2.4s, v3.4h
    usubw2    v4.4s, v5.4s, v6.8h
    usubw     v1.2d, v2.2d, v3.2s
    usubw2    v4.2d, v5.2d, v6.4s
    ssubw     v1.8h, v2.8h, v3.8b
    ssubw2    v4.8h, v5.8h, v6.16b
    ssubw     v1.4s, v2.4s, v3.4h
    ssubw2    v4.4s, v5.4s, v6.8h
    ssubw     v1.2d, v2.2d, v3.2s
    ssubw2    v4.2d, v5.2d, v6.4s
    ushr      v2.8b, v3.8b, #1
    ushr      v2.16b, v3.16b, #8
    ushr      v2.4h, v3.4h, #3
    ushr      v2.8h, v3.8h, #16
    ushr      v2.2s, v3.2s, #5
    ushr      v2.4s, v3.4s, #32
    ushr      v2.2d, v3.2d, #7
    ushr      v2.2d, v3.2d, #64
    sshr      v2.8b, v3.8b, #1
    sshr      v2.16b, v3.16b, #8
    sshr      v2.4h, v3.4h, #3
    sshr      v2.8h, v3.8h, #16
    sshr      v2.2s, v3.2s, #5
    sshr      v2.4s, v3.4s, #32
    sshr      v2.2d, v3.2d, #7
    sshr      v2.2d, v3.2d, #64
    urshr     v2.8b, v3.8b, #1
    urshr     v2.16b, v3.16b, #8
    urshr     v2.4h, v3.4h, #3
    urshr     v2.8h, v3.8h, #16
    urshr     v2.2s, v3.2s, #5
    urshr     v2.4s, v3.4s, #32
    urshr     v2.2d, v3.2d, #7
    urshr     v2.2d, v3.2d, #64
    srshr     v2.8b, v3.8b, #1
    srshr     v2.16b, v3.16b, #8
    srshr     v2.4h, v3.4h, #3
    srshr     v2.8h, v3.8h, #16
    srshr     v2.2s, v3.2s, #5
    srshr     v2.4s, v3.4s, #32
    srshr     v2.2d, v3.2d, #7
    srshr     v2.2d, v3.2d, #64
    usra      v2.8b, v3.8b, #1
    usra      v2.16b, v3.16b, #8
    usra      v2.4h, v3.4h, #3
    usra      v2.8h, v3.8h, #16
    usra      v2.2s, v3.2s, #5
    usra      v2.4s, v3.4s, #32
    usra      v2.2d, v3.2d, #7
    usra      v2.2d, v3.2d, #64
    ssra      v2.8b, v3.8b, #1
    ssra      v2.16b, v3.16b, #8
    ssra      v2.4h, v3.4h, #3
    ssra      v2.8h, v3.8h, #16
    ssra      v2.2s, v3.2s, #5
    ssra      v2.4s, v3.4s, #32
    ssra      v2.2d, v3.2d, #7
    ssra      v2.2d, v3.2d, #64
    shl     v2.8b, v3.8b, #0
    shl     v2.16b, v3.16b, #7
    shl     v2.4h, v3.4h, #3
    shl     v2.8h, v3.8h, #15
    shl     v2.2s, v3.2s, #1
    shl     v2.4s, v3.4s, #31
    shl     v2.2d, v3.2d, #63
    ushll     v1.8h, v2.8b, #0
    ushll2    v1.8h, v2.16b, #0
    ushll     v1.8h, v2.8b, #7
    ushll2    v1.8h, v2.16b, #7
    ushll     v1.4s, v2.4h, #0
    ushll2    v1.4s, v2.8h, #0
    ushll     v1.4s, v2.4h, #15
    ushll2    v1.4s, v2.8h, #15
    ushll     v1.2d, v2.2s, #3
    ushll2    v1.2d, v2.4s, #3
    sshll     v1.8h, v2.8b, #0
    sshll2    v1.8h, v2.16b, #0
    sshll     v1.8h, v2.8b, #7
    sshll2    v1.8h, v2.16b, #7
    sshll     v1.4s, v2.4h, #0
    sshll2    v1.4s, v2.8h, #0
    sshll     v1.4s, v2.4h, #15
    sshll2    v1.4s, v2.8h, #15
    sshll     v1.2d, v2.2s, #3
    sshll2    v1.2d, v2.4s, #3
    uxtl      v1.8h, v2.8b
    uxtl2     v1.4s, v2.8h
    sxtl      v1.8h, v2.8b
    sxtl2     v1.4s, v2.8h
    shrn      v1.8b, v2.8h, #1
    shrn2     v1.16b, v2.8h, #1
    shrn      v1.8b, v2.8h, #8
    shrn2     v1.16b, v2.8h, #8
    shrn      v1.4h, v2.4s, #6
    shrn2     v1.8h, v2.4s, #6
    shrn      v1.4h, v2.4s, #16
    shrn2     v1.8h, v2.4s, #16
    shrn      v1.2s, v2.2d, #32
    shrn2     v1.4s, v2.2d, #32
    rshrn     v1.8b, v2.8h, #1
    rshrn2    v1.16b, v2.8h, #1
    rshrn     v1.8b, v2.8h, #8
    rshrn2    v1.16b, v2.8h, #8
    rshrn     v1.4h, v2.4s, #6
    rshrn2    v1.8h, v2.4s, #6
    rshrn     v1.4h, v2.4s, #16
    rshrn2    v1.8h, v2.4s, #16
    rshrn     v1.2s, v2.2d, #32
    rshrn2    v1.4s, v2.2d, #32
    sqshrun   v1.8b, v2.8h, #1
    sqshrun2  v1.16b, v2.8h, #1
    sqshrun   v1.8b, v2.8h, #8
    sqshrun2  v1.16b, v2.8h, #8
    sqshrun   v1.4h, v2.4s, #6
    sqshrun2  v1.8h, v2.4s, #6
    sqshrun   v1.4h, v2.4s, #16
    sqshrun2  v1.8h, v2.4s, #16
    sqshrun   v1.2s, v2.2d, #32
    sqshrun2  v1.4s, v2.2d, #32
    sqrshrun  v1.8b, v2.8h, #1
    sqrshrun2 v1.16b, v2.8h, #1
    sqrshrun  v1.8b, v2.8h, #8
    sqrshrun2 v1.16b, v2.8h, #8
    sqrshrun  v1.4h, v2.4s, #6
    sqrshrun2 v1.8h, v2.4s, #6
    sqrshrun  v1.4h, v2.4s, #16
    sqrshrun2 v1.8h, v2.4s, #16
    sqrshrun  v1.2s, v2.2d, #32
    sqrshrun2 v1.4s, v2.2d, #32
    sqshrn    v1.8b, v2.8h, #1
    sqshrn2   v1.16b, v2.8h, #1
    sqshrn    v1.8b, v2.8h, #8
    sqshrn2   v1.16b, v2.8h, #8
    sqshrn    v1.4h, v2.4s, #6
    sqshrn2   v1.8h, v2.4s, #6
    sqshrn    v1.4h, v2.4s, #16
    sqshrn2   v1.8h, v2.4s, #16
    sqshrn    v1.2s, v2.2d, #32
    sqshrn2   v1.4s, v2.2d, #32
    sqrshrn   v1.8b, v2.8h, #1
    sqrshrn2  v1.16b, v2.8h, #1
    sqrshrn   v1.8b, v2.8h, #8
    sqrshrn2  v1.16b, v2.8h, #8
    sqrshrn   v1.4h, v2.4s, #6
    sqrshrn2  v1.8h, v2.4s, #6
    sqrshrn   v1.4h, v2.4s, #16
    sqrshrn2  v1.8h, v2.4s, #16
    sqrshrn   v1.2s, v2.2d, #32
    sqrshrn2  v1.4s, v2.2d, #32
    uqshrn    v1.8b, v2.8h, #1
    uqshrn2   v1.16b, v2.8h, #1
    uqshrn    v1.8b, v2.8h, #8
    uqshrn2   v1.16b, v2.8h, #8
    uqshrn    v1.4h, v2.4s, #6
    uqshrn2   v1.8h, v2.4s, #6
    uqshrn    v1.4h, v2.4s, #16
    uqshrn2   v1.8h, v2.4s, #16
    uqshrn    v1.2s, v2.2d, #32
    uqshrn2   v1.4s, v2.2d, #32
    uqrshrn   v1.8b, v2.8h, #1
    uqrshrn2  v1.16b, v2.8h, #1
    uqrshrn   v1.8b, v2.8h, #8
    uqrshrn2  v1.16b, v2.8h, #8
    uqrshrn   v1.4h, v2.4s, #6
    uqrshrn2  v1.8h, v2.4s, #6
    uqrshrn   v1.4h, v2.4s, #16
    uqrshrn2  v1.8h, v2.4s, #16
    uqrshrn   v1.2s, v2.2d, #32
    uqrshrn2  v1.4s, v2.2d, #32
    xtn       v1.8b, v2.8h
    xtn2      v1.16b, v2.8h
    xtn       v1.4h, v2.4s
    xtn2      v1.8h, v2.4s
    xtn       v1.2s, v2.2d
    xtn2      v1.4s, v2.2d
    sqxtn     v1.8b, v2.8h
    sqxtn2    v1.16b, v2.8h
    sqxtn     v1.4h, v2.4s
    sqxtn2    v1.8h, v2.4s
    sqxtn     v1.2s, v2.2d
    sqxtn2    v1.4s, v2.2d
    uqxtn     v1.8b, v2.8h
    uqxtn2    v1.16b, v2.8h
    uqxtn     v1.4h, v2.4s
    uqxtn2    v1.8h, v2.4s
    uqxtn     v1.2s, v2.2d
    uqxtn2    v1.4s, v2.2d
    sqxtun    v1.8b, v2.8h
    sqxtun2   v1.16b, v2.8h
    sqxtun    v1.4h, v2.4s
    sqxtun2   v1.8h, v2.4s
    sqxtun    v1.2s, v2.2d
    sqxtun2   v1.4s, v2.2d
    ext     v1.16b, v2.16b, v3.16b, #0
    ext     v1.16b, v2.16b, v3.16b, #15
    ext     v4.8b, v5.8b, v6.8b, #3
    dup     v5.8b, w9
    dup     v5.16b, w9
    dup     v5.4h, w9
    dup     v5.8h, w9
    dup     v5.2s, w9
    dup     v5.4s, w9
    dup     v5.2d, x9
    movi    v6.8b, #0
    movi    v6.8b, #1
    movi    v6.8b, #128
    movi    v6.8b, #255
    movi    v6.16b, #0
    movi    v6.16b, #1
    movi    v6.16b, #128
    movi    v6.16b, #255
    movi    v6.4h, #0
    movi    v6.4h, #1
    movi    v6.4h, #128
    movi    v6.4h, #255
    movi    v6.8h, #0
    movi    v6.8h, #1
    movi    v6.8h, #128
    movi    v6.8h, #255
    movi    v6.2s, #0
    movi    v6.2s, #1
    movi    v6.2s, #128
    movi    v6.2s, #255
    movi    v6.4s, #0
    movi    v6.4s, #1
    movi    v6.4s, #128
    movi    v6.4s, #255
    ld1     {v28.16b}, [x0]
    ld1     {v28.16b}, [x1], #16
    ld1     {v28.16b}, [sp], x2
    ld1     {v0.8b}, [x3], #8
    ld1     {v4.4s}, [x4], #16
    ld1     {v28.16b, v29.16b}, [x0]
    ld1     {v28.16b, v29.16b}, [x1], #32
    ld1     {v28.16b, v29.16b}, [sp], x2
    ld1     {v0.8b, v1.8b}, [x3], #16
    ld1     {v4.4s, v5.4s}, [x4], #32
    ld1     {v28.16b, v29.16b, v30.16b}, [x0]
    ld1     {v28.16b, v29.16b, v30.16b}, [x1], #48
    ld1     {v28.16b, v29.16b, v30.16b}, [sp], x2
    ld1     {v0.8b, v1.8b, v2.8b}, [x3], #24
    ld1     {v4.4s, v5.4s, v6.4s}, [x4], #48
    ld1     {v28.16b, v29.16b, v30.16b, v31.16b}, [x0]
    ld1     {v28.16b, v29.16b, v30.16b, v31.16b}, [x1], #64
    ld1     {v28.16b, v29.16b, v30.16b, v31.16b}, [sp], x2
    ld1     {v0.8b, v1.8b, v2.8b, v3.8b}, [x3], #32
    ld1     {v4.4s, v5.4s, v6.4s, v7.4s}, [x4], #64
    ld1     {v1.2d}, [x5]
    ld1     {v1.1d}, [x5]
    ld1     {v2.4h}, [x6], #8
    ld1     {v3.8h, v4.8h}, [x7], #32
    st1     {v28.16b}, [x0]
    st1     {v28.16b}, [x1], #16
    st1     {v28.16b}, [sp], x2
    st1     {v0.8b}, [x3], #8
    st1     {v4.4s}, [x4], #16
    st1     {v28.16b, v29.16b}, [x0]
    st1     {v28.16b, v29.16b}, [x1], #32
    st1     {v28.16b, v29.16b}, [sp], x2
    st1     {v0.8b, v1.8b}, [x3], #16
    st1     {v4.4s, v5.4s}, [x4], #32
    st1     {v28.16b, v29.16b, v30.16b}, [x0]
    st1     {v28.16b, v29.16b, v30.16b}, [x1], #48
    st1     {v28.16b, v29.16b, v30.16b}, [sp], x2
    st1     {v0.8b, v1.8b, v2.8b}, [x3], #24
    st1     {v4.4s, v5.4s, v6.4s}, [x4], #48
    st1     {v28.16b, v29.16b, v30.16b, v31.16b}, [x0]
    st1     {v28.16b, v29.16b, v30.16b, v31.16b}, [x1], #64
    st1     {v28.16b, v29.16b, v30.16b, v31.16b}, [sp], x2
    st1     {v0.8b, v1.8b, v2.8b, v3.8b}, [x3], #32
    st1     {v4.4s, v5.4s, v6.4s, v7.4s}, [x4], #64
    st1     {v1.2d}, [x5]
    st1     {v1.1d}, [x5]
    st1     {v2.4h}, [x6], #8
    st1     {v3.8h, v4.8h}, [x7], #32
    ld2     {v0.16b, v1.16b}, [x0]
    ld2     {v0.16b, v1.16b}, [x1], #32
    ld2     {v8.8b, v9.8b}, [x2], #16
    ld2     {v16.8h, v17.8h}, [x3], x4
    ld3     {v0.16b, v1.16b, v2.16b}, [x0]
    ld3     {v0.16b, v1.16b, v2.16b}, [x1], #48
    ld3     {v8.8b, v9.8b, v10.8b}, [x2], #24
    ld3     {v16.8h, v17.8h, v18.8h}, [x3], x4
    ld4     {v0.16b, v1.16b, v2.16b, v3.16b}, [x0]
    ld4     {v0.16b, v1.16b, v2.16b, v3.16b}, [x1], #64
    ld4     {v8.8b, v9.8b, v10.8b, v11.8b}, [x2], #32
    ld4     {v16.8h, v17.8h, v18.8h, v19.8h}, [x3], x4
    st2     {v0.16b, v1.16b}, [x0]
    st2     {v0.16b, v1.16b}, [x1], #32
    st2     {v8.8b, v9.8b}, [x2], #16
    st2     {v16.8h, v17.8h}, [x3], x4
    st3     {v0.16b, v1.16b, v2.16b}, [x0]
    st3     {v0.16b, v1.16b, v2.16b}, [x1], #48
    st3     {v8.8b, v9.8b, v10.8b}, [x2], #24
    st3     {v16.8h, v17.8h, v18.8h}, [x3], x4
    st4     {v0.16b, v1.16b, v2.16b, v3.16b}, [x0]
    st4     {v0.16b, v1.16b, v2.16b, v3.16b}, [x1], #64
    st4     {v8.8b, v9.8b, v10.8b, v11.8b}, [x2], #32
    st4     {v16.8h, v17.8h, v18.8h, v19.8h}, [x3], x4
    umov      w16, v0.b[0]
    umov      w1, v2.b[15]
    umov      w3, v4.h[7]
    umov      w5, v6.s[0]
    umov      w7, v8.s[3]
    umov      x9, v10.d[1]
    umov      x11, v31.d[0]
    uabd      v0.8b, v9.8b, v20.8b
    uabd      v0.16b, v9.16b, v20.16b
    uabd      v0.4h, v9.4h, v20.4h
    uabd      v0.8h, v9.8h, v20.8h
    uabd      v0.2s, v9.2s, v20.2s
    uabd      v0.4s, v9.4s, v20.4s
    sabd      v1.8b, v10.8b, v21.8b
    sabd      v1.16b, v10.16b, v21.16b
    sabd      v1.4h, v10.4h, v21.4h
    sabd      v1.8h, v10.8h, v21.8h
    sabd      v1.2s, v10.2s, v21.2s
    sabd      v1.4s, v10.4s, v21.4s
    cmhi      v2.8b, v11.8b, v22.8b
    cmhi      v2.16b, v11.16b, v22.16b
    cmhi      v2.4h, v11.4h, v22.4h
    cmhi      v2.8h, v11.8h, v22.8h
    cmhi      v2.2s, v11.2s, v22.2s
    cmhi      v2.4s, v11.4s, v22.4s
    cmhi      v2.2d, v11.2d, v22.2d
    cmhs      v3.8b, v12.8b, v23.8b
    cmhs      v3.16b, v12.16b, v23.16b
    cmhs      v3.4h, v12.4h, v23.4h
    cmhs      v3.8h, v12.8h, v23.8h
    cmhs      v3.2s, v12.2s, v23.2s
    cmhs      v3.4s, v12.4s, v23.4s
    cmhs      v3.2d, v12.2d, v23.2d
    cmgt      v4.8b, v13.8b, v24.8b
    cmgt      v4.16b, v13.16b, v24.16b
    cmgt      v4.4h, v13.4h, v24.4h
    cmgt      v4.8h, v13.8h, v24.8h
    cmgt      v4.2s, v13.2s, v24.2s
    cmgt      v4.4s, v13.4s, v24.4s
    cmgt      v4.2d, v13.2d, v24.2d
    cmge      v5.8b, v14.8b, v25.8b
    cmge      v5.16b, v14.16b, v25.16b
    cmge      v5.4h, v14.4h, v25.4h
    cmge      v5.8h, v14.8h, v25.8h
    cmge      v5.2s, v14.2s, v25.2s
    cmge      v5.4s, v14.4s, v25.4s
    cmge      v5.2d, v14.2d, v25.2d
    cmeq      v6.8b, v15.8b, v26.8b
    cmeq      v6.16b, v15.16b, v26.16b
    cmeq      v6.4h, v15.4h, v26.4h
    cmeq      v6.8h, v15.8h, v26.8h
    cmeq      v6.2s, v15.2s, v26.2s
    cmeq      v6.4s, v15.4s, v26.4s
    cmeq      v6.2d, v15.2d, v26.2d
    orn       v1.16b, v2.16b, v3.16b
    orn       v4.8b, v5.8b, v6.8b
    bsl       v1.16b, v2.16b, v3.16b
    bsl       v4.8b, v5.8b, v6.8b
    bit       v1.16b, v2.16b, v3.16b
    bit       v4.8b, v5.8b, v6.8b
    bif       v1.16b, v2.16b, v3.16b
    bif       v4.8b, v5.8b, v6.8b
    sshl      v1.8b, v11.8b, v21.8b
    sshl      v1.16b, v11.16b, v21.16b
    sshl      v1.4h, v11.4h, v21.4h
    sshl      v1.8h, v11.8h, v21.8h
    sshl      v1.2s, v11.2s, v21.2s
    sshl      v1.4s, v11.4s, v21.4s
    sshl      v1.2d, v11.2d, v21.2d
    srshl     v2.8b, v12.8b, v22.8b
    srshl     v2.16b, v12.16b, v22.16b
    srshl     v2.4h, v12.4h, v22.4h
    srshl     v2.8h, v12.8h, v22.8h
    srshl     v2.2s, v12.2s, v22.2s
    srshl     v2.4s, v12.4s, v22.4s
    srshl     v2.2d, v12.2d, v22.2d
    ushl      v3.8b, v13.8b, v23.8b
    ushl      v3.16b, v13.16b, v23.16b
    ushl      v3.4h, v13.4h, v23.4h
    ushl      v3.8h, v13.8h, v23.8h
    ushl      v3.2s, v13.2s, v23.2s
    ushl      v3.4s, v13.4s, v23.4s
    ushl      v3.2d, v13.2d, v23.2d
    urshl     v4.8b, v14.8b, v24.8b
    urshl     v4.16b, v14.16b, v24.16b
    urshl     v4.4h, v14.4h, v24.4h
    urshl     v4.8h, v14.8h, v24.8h
    urshl     v4.2s, v14.2s, v24.2s
    urshl     v4.4s, v14.4s, v24.4s
    urshl     v4.2d, v14.2d, v24.2d

// The small part of the ArmOS kernel that has to be assembly.
// DULL code reaches these through `elsewhere to ...` declarations; the exception
// vectors call back into DULL (`trap.handle`, `smp.secondary_main`).

.equ FRAME_SIZE, 272          // x0-x30, ELR, SPSR, SP_EL0
.equ STACK_SIZE, 0x10000      // per secondary core
.equ MAX_CORES, 4

.text

// ---------------------------------------------------------------- exception levels

// arch_drop_to_el1(): if we are at EL2, configure EL1 and return there (same stack).
.global arch_drop_to_el1
arch_drop_to_el1:
    mrs     x9, CurrentEL
    cmp     x9, #(2 << 2)
    b.ne    1f
    movz    x9, #0x8000, lsl #16          // HCR_EL2.RW: EL1 runs AArch64
    msr     hcr_el2, x9
    mrs     x9, cnthctl_el2
    orr     x9, x9, #3                    // EL1 may use the physical counter and timer
    msr     cnthctl_el2, x9
    msr     cntvoff_el2, xzr              // virtual time = physical time
    movz    x9, #0x33ff
    msr     cptr_el2, x9                  // do not trap FP/SIMD to EL2
    mrs     x9, midr_el1
    msr     vpidr_el2, x9
    mrs     x9, mpidr_el1
    msr     vmpidr_el2, x9
    movz    x9, #0x0800
    movk    x9, #0x30d0, lsl #16          // SCTLR_EL1: reserved-one bits, MMU and caches off
    msr     sctlr_el1, x9
    movz    x9, #0x30, lsl #16            // CPACR_EL1: FP/SIMD allowed at EL1
    msr     cpacr_el1, x9
    mov     x9, sp
    msr     sp_el1, x9
    msr     elr_el2, x30
    mov     x9, #0x3c5                    // EL1h with D, A, I, F masked
    msr     spsr_el2, x9
    eret
1:  movz    x9, #0x30, lsl #16
    msr     cpacr_el1, x9
    isb
    ret

// arch_current_el() gives the exception level we are running at.
.global arch_current_el
arch_current_el:
    mrs     x0, CurrentEL
    lsr     x0, x0, #2
    ret

// ---------------------------------------------------------------- exceptions

.global arch_install_vectors
arch_install_vectors:
    adrp    x0, vectors
    add     x0, x0, :lo12:vectors
    msr     vbar_el1, x0
    isb
    ret

.global arch_irq_on
arch_irq_on:
    msr     daifclr, #2
    ret

.global arch_irq_off
arch_irq_off:
    msr     daifset, #2
    ret

// One table entry per (source, kind). Sources: current EL with SP0, current EL with
// SPx, lower EL in AArch64, lower EL in AArch32. Kinds: sync, IRQ, FIQ, SError.
// Entry n saves x0/x1, puts n in x1 and joins the common path.
.balign 2048
vectors:
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #0
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #1
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #2
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #3
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #4
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #5
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #6
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #7
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #8
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #9
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #10
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #11
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #12
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #13
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #14
    b       save_and_handle
    .balign 128
    sub     sp, sp, #FRAME_SIZE
    stp     x0, x1, [sp, #0]
    mov     x1, #15
    b       save_and_handle

save_and_handle:
    stp     x2, x3, [sp, #16]
    stp     x4, x5, [sp, #32]
    stp     x6, x7, [sp, #48]
    stp     x8, x9, [sp, #64]
    stp     x10, x11, [sp, #80]
    stp     x12, x13, [sp, #96]
    stp     x14, x15, [sp, #112]
    stp     x16, x17, [sp, #128]
    stp     x18, x19, [sp, #144]
    stp     x20, x21, [sp, #160]
    stp     x22, x23, [sp, #176]
    stp     x24, x25, [sp, #192]
    stp     x26, x27, [sp, #208]
    stp     x28, x29, [sp, #224]
    mrs     x9, elr_el1
    stp     x30, x9, [sp, #240]
    mrs     x9, spsr_el1
    mrs     x10, sp_el0
    stp     x9, x10, [sp, #256]
    mov     x0, sp                        // frame: x0..x30, then ELR, SPSR, SP_EL0
    bl      trap.handle                   // (frame, kind) gives the frame to resume
    mov     sp, x0                        // maybe another process's
resume:
    ldp     x9, x10, [sp, #256]
    msr     spsr_el1, x9
    msr     sp_el0, x10
    ldp     x30, x9, [sp, #240]
    msr     elr_el1, x9
    ldp     x2, x3, [sp, #16]
    ldp     x4, x5, [sp, #32]
    ldp     x6, x7, [sp, #48]
    ldp     x8, x9, [sp, #64]
    ldp     x10, x11, [sp, #80]
    ldp     x12, x13, [sp, #96]
    ldp     x14, x15, [sp, #112]
    ldp     x16, x17, [sp, #128]
    ldp     x18, x19, [sp, #144]
    ldp     x20, x21, [sp, #160]
    ldp     x22, x23, [sp, #176]
    ldp     x24, x25, [sp, #192]
    ldp     x26, x27, [sp, #208]
    ldp     x28, x29, [sp, #224]
    ldp     x0, x1, [sp, #0]
    add     sp, sp, #FRAME_SIZE
    eret

// arch_resume(frame): run the context saved in `frame` (on top of its kernel stack).
// Never returns.
.global arch_resume
arch_resume:
    mov     sp, x0
    b       resume

// arch_enter_user(entry, arg, stack): run `entry(arg)` at EL0 on this core with
// stack `stack`, interrupts on. The exception stack is where we are now. Never returns.
.global arch_enter_user
arch_enter_user:
    msr     elr_el1, x0
    msr     sp_el0, x2
    msr     spsr_el1, xzr                 // EL0t, nothing masked
    mov     x0, x1
    mov     x1, xzr
    mov     x2, xzr
    mov     x29, xzr
    mov     x30, xzr
    eret

// arch_helper_loop(which): start over on this helper core's own stack, waiting for
// work (smp.helper_wait). Never returns.
.global arch_helper_loop
arch_helper_loop:
    adrp    x9, core_stacks
    add     x9, x9, :lo12:core_stacks
    add     x10, x0, #1
    lsl     x10, x10, #16                 // STACK_SIZE
    add     x9, x9, x10
    mov     sp, x9
    bl      smp.helper_wait
1:  wfe
    b       1b

// arch_idle_entry() gives the address of the idle loop (the context that runs when
// no process is ready).
.global arch_idle_entry
arch_idle_entry:
    adr     x0, idle_loop
    ret
idle_loop:
    wfi
    b       idle_loop

// ---------------------------------------------------------------- memory management

// arch_mmu_on(ttbr0, tcr, mair, sctlr_bits): load the translation registers and turn
// the MMU and caches on for this core. The values are also kept in boot_block so the
// other cores can do the same as soon as they start.
.global arch_mmu_on
arch_mmu_on:
    adrp    x9, boot_block
    add     x9, x9, :lo12:boot_block
    stp     x0, x1, [x9]
    stp     x2, x3, [x9, #16]
    dsb     sy
mmu_on:
    msr     mair_el1, x2
    msr     tcr_el1, x1
    msr     ttbr0_el1, x0
    isb
    tlbi    vmalle1
    dsb     sy
    isb
    mrs     x9, sctlr_el1
    orr     x9, x9, x3
    msr     sctlr_el1, x9
    isb
    ic      iallu
    dsb     sy
    isb
    ret

// arch_clean_range(address, size): write cached data in the range back to memory and
// drop it from the caches, so devices (the GPU, the firmware) see what we wrote.
.global arch_clean_range
arch_clean_range:
    add     x1, x0, x1
    and     x0, x0, #~63
1:  dc      civac, x0
    add     x0, x0, #64
    cmp     x0, x1
    b.lo    1b
    dsb     sy
    ret

// arch_tlb_flush(): forget all cached translations (after editing page tables).
.global arch_tlb_flush
arch_tlb_flush:
    dsb     sy
    tlbi    vmalle1
    dsb     sy
    isb
    ret

// arch_switch_space(ttbr0): use another set of page tables (a process's).
.global arch_switch_space
arch_switch_space:
    dsb     sy
    msr     ttbr0_el1, x0
    isb
    tlbi    vmalle1
    dsb     sy
    isb
    ret

// arch_sync_code(address, size): make code just written to memory visible to
// instruction fetch.
.global arch_sync_code
arch_sync_code:
    add     x1, x0, x1
    and     x0, x0, #~63
1:  dc      cvau, x0
    add     x0, x0, #64
    cmp     x0, x1
    b.lo    1b
    dsb     ish
    ic      iallu
    dsb     ish
    isb
    ret

// ---------------------------------------------------------------- other cores

// arch_psci(function, a, b, c, use_smc) gives the firmware's answer. PSCI is the
// standard firmware interface for starting and stopping cores.
.global arch_psci
arch_psci:
    cbz     x4, 1f
    smc     #0
    ret
1:  hvc     #0
    ret

// arch_secondary_entry() gives the address other cores should start at.
.global arch_secondary_entry
arch_secondary_entry:
    adr     x0, secondary_entry
    ret

// A newly started core arrives here with the MMU off and x0 = its core number.
secondary_entry:
    mov     x19, x0
    adrp    x9, core_stacks
    add     x9, x9, :lo12:core_stacks
    add     x10, x0, #1
    lsl     x10, x10, #16                 // STACK_SIZE
    add     x9, x9, x10
    mov     sp, x9
    bl      arch_drop_to_el1
    adrp    x9, boot_block
    add     x9, x9, :lo12:boot_block
    ldp     x0, x1, [x9]
    ldp     x2, x3, [x9, #16]
    bl      mmu_on
    bl      arch_install_vectors
    mov     x0, x19
    bl      smp.secondary_main
2:  wfe
    b       2b

.data
.balign 16
boot_block:     .zero 32                  // ttbr0, tcr, mair, sctlr bits for the other cores

.bss
.balign 16
core_stacks:    .zero 0x40000             // MAX_CORES x STACK_SIZE

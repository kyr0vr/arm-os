// Boot code for the Raspberry Pi 5 (BCM2712).
// The firmware loads kernel_2712.img (at kernel_address from config.txt) and starts
// core 0 here, at EL2 with the MMU off. If we are not running at our link address we
// copy ourselves there first. Then: stack, exception vectors, clear .bss, call the DULL
// program's `main`. `dull_trap` and CPU exceptions report over the debug UART.
// The address the firmware first started us at is left in TPIDR_EL1 for diagnostics.

.section .text.boot, "ax"
.global _start
_start:
    mrs     x0, mpidr_el1
    tst     x0, #0xffff               // core 0 only (Aff0 and Aff1 both 0)
    b.ne    park

    // Everything here is position independent, so it works wherever we were started.
    adr     x0, _start                // where we are running
    msr     tpidr_el1, x0
    ldr     x1, link_start            // where we were linked to run
    cmp     x0, x1
    b.eq    relocated
    ldr     x3, link_bss
    sub     x3, x3, x1                // image size: code + data, a multiple of 16
10: ldp     x6, x7, [x0], #16
    stp     x6, x7, [x1], #16
    subs    x3, x3, #16
    b.hi    10b
    dsb     sy
    ic      iallu
    dsb     sy
    isb
    ldr     x3, link_relocated
    br      x3                        // continue in the copy
relocated:
    adrp    x0, __stack_top
    add     x0, x0, :lo12:__stack_top
    mov     sp, x0

    adrp    x0, vectors
    add     x0, x0, :lo12:vectors
    mrs     x1, CurrentEL
    cmp     x1, #(2 << 2)
    b.ne    1f
    msr     vbar_el2, x0
    b       2f
1:  msr     vbar_el1, x0
2:  isb

    adrp    x0, __bss_start
    add     x0, x0, :lo12:__bss_start
    adrp    x1, __bss_end
    add     x1, x1, :lo12:__bss_end
3:  cmp     x0, x1
    b.hs    4f
    str     xzr, [x0], #8
    b       3b
4:
    bl      dull_main
park:
    wfe
    b       park

.balign 8                             // literal loads must be aligned: MMU off means no unaligned access
link_start:     .xword _start
link_bss:       .xword __bss_start
link_relocated: .xword relocated

// uart_puts(x0 = NUL-terminated string). Clobbers x0-x3.
uart_puts:
    movz    x1, #0x1000
    movk    x1, #0x7d00, lsl #16
    movk    x1, #0x10, lsl #32
5:  ldrb    w2, [x0], #1
    cbz     w2, 7f
6:  ldr     w3, [x1, #0x18]
    tbnz    w3, #5, 6b                // wait while TX FIFO full
    str     w2, [x1]
    b       5b
7:  ret

// dull_trap(x0 = message): print "trap: <message>" and stop.
.global dull_trap
dull_trap:
    mov     x19, x0
    adrp    x0, trap_prefix
    add     x0, x0, :lo12:trap_prefix
    bl      uart_puts
    mov     x0, x19
    bl      uart_puts
    adrp    x0, newline
    add     x0, x0, :lo12:newline
    bl      uart_puts
    b       wait_reboot

cpu_exception:
    adrp    x0, exc_msg
    add     x0, x0, :lo12:exc_msg
    bl      uart_puts
    b       wait_reboot

// After a crash: wait for "ARMR" from the PC, then reboot through the watchdog,
// so tools/build_pi5.py --send can recover the Pi without anyone touching it.
wait_reboot:
    movz    x1, #0x1000
    movk    x1, #0x7d00, lsl #16
    movk    x1, #0x10, lsl #32           // UART
    adrp    x4, reboot_word
    add     x4, x4, :lo12:reboot_word
    mov     x5, #0                       // bytes matched so far
8:  ldr     w3, [x1, #0x18]
    tbnz    w3, #4, 8b                   // wait while RX FIFO empty
    ldr     w2, [x1]
    and     w2, w2, #0xff
    ldrb    w3, [x4, x5]
    cmp     w2, w3
    b.eq    9f
    ldrb    w3, [x4]
    cmp     w2, w3
    cset    x5, eq                       // a fresh 'A' restarts the match at 1
    b       8b
9:  add     x5, x5, #1
    cmp     x5, #4
    b.ne    8b
    movz    x1, #0x0000
    movk    x1, #0x7d20, lsl #16
    movk    x1, #0x10, lsl #32           // power management (watchdog)
    movz    w6, #0x5a00, lsl #16         // password
    ldr     w2, [x1, #0x20]              // RSTS: boot partition 0
    movz    w3, #0xfaaa
    movk    w3, #0xffff, lsl #16
    and     w2, w2, w3
    orr     w2, w2, w6
    str     w2, [x1, #0x20]
    mov     w2, #10                      // WDOG: fire in 10 ticks
    orr     w2, w2, w6
    str     w2, [x1, #0x24]
    ldr     w2, [x1, #0x1c]              // RSTC: full reset
    and     w2, w2, #0xffffffcf
    orr     w2, w2, w6
    orr     w2, w2, #0x20
    str     w2, [x1, #0x1c]
    b       park

.balign 2048
vectors:
    .rept 16
    .balign 128
    b       cpu_exception
    .endr

.section .rodata, "a"
trap_prefix: .asciz "\r\ntrap: "
newline:     .asciz "\r\n"
reboot_word: .ascii "ARMR"
exc_msg:     .asciz "\r\ncpu exception - stopped\r\n"

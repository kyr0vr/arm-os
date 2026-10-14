// Boot code for the Raspberry Pi 5 (BCM2712).
// The firmware loads kernel_2712.img at 0x80000 and starts core 0 here, usually at
// EL2 with the MMU off. Sets up a stack and exception vectors, clears .bss and calls
// the DULL program's `main`. `dull_trap` and CPU exceptions report over the debug UART.

.equ UART_BASE_HI, 0x107d     // UART at 0x10_7d00_1000 (debug header between the HDMI ports)

.section .text.boot, "ax"
.global _start
_start:
    mrs     x0, mpidr_el1
    tst     x0, #0xffff               // core 0 only (Aff0 and Aff1 both 0)
    b.ne    park

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
    b       park

cpu_exception:
    adrp    x0, exc_msg
    add     x0, x0, :lo12:exc_msg
    bl      uart_puts
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
exc_msg:     .asciz "\r\ncpu exception - stopped\r\n"

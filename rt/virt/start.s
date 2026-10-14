// Test runtime for QEMU `virt` (AArch64, EL1, MMU off).
// Boots core 0, calls the DULL program's `main`, and exits QEMU with its result
// through semihosting. Provides `dull_trap`, which debug builds call on overflow,
// bad indexes and division by zero.

.section .text.boot, "ax"
.global _start
_start:
    mrs     x0, mpidr_el1
    and     x0, x0, #0xff
    cbnz    x0, park

    adrp    x0, __stack_top
    add     x0, x0, :lo12:__stack_top
    mov     sp, x0

    // Allow FP/SIMD at EL1 so stray vector instructions do not fault.
    mov     x0, #(3 << 20)
    msr     cpacr_el1, x0

    adrp    x0, vectors
    add     x0, x0, :lo12:vectors
    msr     vbar_el1, x0
    isb

    adrp    x0, __bss_start
    add     x0, x0, :lo12:__bss_start
    adrp    x1, __bss_end
    add     x1, x1, :lo12:__bss_end
1:  cmp     x0, x1
    b.hs    2f
    str     xzr, [x0], #8
    b       1b
2:
    bl      dull_main
    b       dull_exit

park:
    wfe
    b       park

// dull_exit(code x0): stop QEMU with exit status `code`.
.global dull_exit
dull_exit:
    and     x0, x0, #0xff
    sub     sp, sp, #16
    movz    x1, #0x0026
    movk    x1, #0x2, lsl #16          // ADP_Stopped_ApplicationExit
    stp     x1, x0, [sp]
    mov     x1, sp
    mov     w0, #0x18                  // SYS_EXIT
    hlt     #0xf000
    b       park

// dull_trap(msg x0): print "trap: <msg>" and exit with status 101.
.global dull_trap
dull_trap:
    mov     x19, x0
    adrp    x1, trap_prefix
    add     x1, x1, :lo12:trap_prefix
    mov     w0, #0x04                  // SYS_WRITE0
    hlt     #0xf000
    mov     x1, x19
    mov     w0, #0x04
    hlt     #0xf000
    adrp    x1, newline
    add     x1, x1, :lo12:newline
    mov     w0, #0x04
    hlt     #0xf000
    mov     x0, #101
    b       dull_exit

cpu_exception:
    mrs     x20, esr_el1
    mrs     x21, elr_el1
    mrs     x22, far_el1
    adrp    x1, exc_msg
    add     x1, x1, :lo12:exc_msg
    mov     w0, #0x04
    hlt     #0xf000
    adrp    x1, esr_msg
    add     x1, x1, :lo12:esr_msg
    mov     w0, #0x04
    hlt     #0xf000
    mov     x0, x20
    bl      print_hex
    adrp    x1, elr_msg
    add     x1, x1, :lo12:elr_msg
    mov     w0, #0x04
    hlt     #0xf000
    mov     x0, x21
    bl      print_hex
    adrp    x1, far_msg
    add     x1, x1, :lo12:far_msg
    mov     w0, #0x04
    hlt     #0xf000
    mov     x0, x22
    bl      print_hex
    adrp    x1, newline
    add     x1, x1, :lo12:newline
    mov     w0, #0x04
    hlt     #0xf000
    mov     x0, #102
    b       dull_exit

// print_hex(x0): 16 hex digits through semihosting. Clobbers x0-x5.
print_hex:
    adrp    x1, hex_buf
    add     x1, x1, :lo12:hex_buf
    mov     x2, #60
1:  lsr     x3, x0, x2
    and     x3, x3, #15
    cmp     x3, #10
    b.lo    2f
    add     x3, x3, #('a' - 10)
    b       3f
2:  add     x3, x3, #'0'
3:  strb    w3, [x1], #1
    subs    x2, x2, #4
    b.pl    1b
    strb    wzr, [x1]
    adrp    x1, hex_buf
    add     x1, x1, :lo12:hex_buf
    mov     w0, #0x04
    hlt     #0xf000
    ret

.balign 2048
vectors:
    .rept 16
    .balign 128
    b       cpu_exception
    .endr

.section .rodata, "a"
trap_prefix: .asciz "trap: "
newline:     .asciz "\n"
exc_msg:     .asciz "cpu exception"
esr_msg:     .asciz " ESR "
elr_msg:     .asciz " ELR "
far_msg:     .asciz " FAR "

.bss
hex_buf:     .zero 24

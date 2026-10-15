// The start of every ArmOS app (EL0). The kernel (kernel/proc.dull) checks the
// header, maps the image, zeroes .bss, sets up a stack and jumps to _start.

.section .text.boot, "ax"
app_header:
    .ascii  "DULX"
    .word   1                     // header version
    .quad   __end                 // where the app's memory ends (with .bss)
    .quad   _start                // entry point
    .quad   0

.global _start
_start:
    bl      dull_main
    mov     x8, #0                // exit(main's answer)
    svc     #0
1:  b       1b

// A helper core starts here (rt/app/helpers.dull) with x0 = a block holding the
// function to run and its argument; when the function returns, the core goes back
// to the kernel (helper_done).
.global helper_start
helper_start:
    ldr     x9, [x0]
    ldr     x0, [x0, #8]
    blr     x9
    mov     x8, #35               // helper_done
    svc     #0
1:  b       1b

// dull_trap(x0 = message): debug checks (overflow, bad index) end the app.
.global dull_trap
dull_trap:
    mov     x19, x0
    adr     x0, trap_text
    mov     x1, #6
    movz    x2, #0x561b
    movk    x2, #0xe0, lsl #16
    mov     x3, #0
    mov     x8, #1                // write
    svc     #0
    mov     x1, #0
2:  ldrb    w9, [x19, x1]
    cbz     w9, 3f
    add     x1, x1, #1
    b       2b
3:  mov     x0, x19
    movz    x2, #0x561b
    movk    x2, #0xe0, lsl #16
    mov     x3, #0
    mov     x8, #1
    svc     #0
    adr     x0, newline
    mov     x1, #1
    mov     x8, #1
    svc     #0
    mov     x0, #101
    mov     x8, #0
    svc     #0
4:  b       4b

trap_text:  .ascii "trap: "
newline:    .ascii "\n"

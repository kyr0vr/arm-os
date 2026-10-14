ENTRY(_start)

SECTIONS
{
    . = @BASE@;
    .text : { *(.text.boot) *(.text*) }
    .rodata : ALIGN(16) { *(.rodata*) }
    .data : ALIGN(16) { *(.data*) }
    .bss (NOLOAD) : ALIGN(16) {
        __bss_start = .;
        *(.bss*) *(COMMON)
        . = ALIGN(16);
        __bss_end = .;
    }
    __end = .;
}

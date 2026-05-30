import os
import struct
import tempfile
import pytest
from report.elf import get_instrumented_pcs


def _build_test_elf(pc_offset=0xffffffff81001234, symbol_name='__sanitizer_cov_trace_pc'):
    """Build a minimal x86_64 ELF64 with one KCOV RELA entry (or other symbol if specified)."""
    # Symbol string table: offset 0 = "", offset 1 = symbol name
    strtab = b'\x00' + symbol_name.encode() + b'\x00'

    # Section name string table
    # offsets: .strtab=1, .shstrtab=9, .symtab=19, .rela.text=27
    shstrtab = b'\x00.strtab\x00.shstrtab\x00.symtab\x00.rela.text\x00'  # 38 bytes
    shstr_idx = {'.strtab': 1, '.shstrtab': 9, '.symtab': 19, '.rela.text': 27}

    # Symbol table: NULL entry + __sanitizer_cov_trace_pc (SHN_UNDEF, GLOBAL FUNC)
    sym0 = struct.pack('<IBBHQQ', 0, 0, 0, 0, 0, 0)
    sym1 = struct.pack('<IBBHQQ', 1, (1 << 4) | 2, 0, 0, 0, 0)  # bind=GLOBAL, type=FUNC
    symtab = sym0 + sym1  # 48 bytes

    # RELA entry: offset=pc_offset, sym_idx=1, type=R_X86_64_PLT32=4, addend=-4
    r_info = (1 << 32) | 4
    rela = struct.pack('<QQq', pc_offset, r_info, -4)  # 24 bytes

    # File layout
    strtab_off   = 64                               # after ELF header
    shstrtab_off = strtab_off + len(strtab)         # 64+26 = 90
    symtab_off   = shstrtab_off + len(shstrtab)     # 90+38 = 128
    rela_off     = symtab_off + len(symtab)         # 128+48 = 176
    shdrs_off    = rela_off + len(rela)             # 176+24 = 200

    # Section headers: 0=NULL 1=.strtab 2=.shstrtab 3=.symtab 4=.rela.text
    SHT_NULL, SHT_STRTAB, SHT_SYMTAB, SHT_RELA = 0, 3, 2, 4

    def shdr(name, type_, offset, size, link, info, entsize):
        return struct.pack('<IIQQQQIIQQ',
                           name, type_, 0, 0, offset, size, link, info, 8, entsize)

    shdrs = (
        shdr(0,                        SHT_NULL,   0,           0,            0, 0,  0) +
        shdr(shstr_idx['.strtab'],     SHT_STRTAB, strtab_off,  len(strtab),  0, 0,  0) +
        shdr(shstr_idx['.shstrtab'],   SHT_STRTAB, shstrtab_off,len(shstrtab),0, 0,  0) +
        shdr(shstr_idx['.symtab'],     SHT_SYMTAB, symtab_off,  len(symtab),  1, 1, 24) +
        shdr(shstr_idx['.rela.text'],  SHT_RELA,   rela_off,    len(rela),    3, 0, 24)
    )

    # ELF64 header
    e_ident = b'\x7fELF\x02\x01\x01\x00' + b'\x00' * 8
    elf_hdr = e_ident + struct.pack('<HHIQQQIHHHHHH',
        2, 62, 1, 0, 0, shdrs_off, 0, 64, 0, 0, 64, 5, 2)

    data = bytearray(shdrs_off + len(shdrs))
    data[0:64]                                   = elf_hdr
    data[strtab_off:strtab_off+len(strtab)]      = strtab
    data[shstrtab_off:shstrtab_off+len(shstrtab)]= shstrtab
    data[symtab_off:symtab_off+len(symtab)]      = symtab
    data[rela_off:rela_off+len(rela)]            = rela
    data[shdrs_off:]                             = shdrs
    return bytes(data)


def test_finds_kcov_relocation():
    """get_instrumented_pcs returns the offset of the KCOV RELA entry."""
    pc = 0xffffffff81001234
    elf_data = _build_test_elf(pc)
    with tempfile.NamedTemporaryFile(suffix='.elf', delete=False) as f:
        f.write(elf_data)
        tmp = f.name
    try:
        result = get_instrumented_pcs(tmp)
    finally:
        os.unlink(tmp)
    assert result == [hex(pc)]


def test_no_kcov_symbol_returns_empty():
    """ELF without __sanitizer_cov_trace_pc returns empty list."""
    elf_data = _build_test_elf(symbol_name='other_function')
    with tempfile.NamedTemporaryFile(suffix='.elf', delete=False) as f:
        f.write(elf_data)
        tmp = f.name
    try:
        result = get_instrumented_pcs(tmp)
    finally:
        os.unlink(tmp)
    assert result == []


def test_missing_file_raises():
    """Missing vmlinux raises OSError."""
    with pytest.raises(OSError):
        get_instrumented_pcs('/nonexistent/vmlinux')

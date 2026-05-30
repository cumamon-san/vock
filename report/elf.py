"""Discover KCOV-instrumented PCs from vmlinux ELF relocations."""
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection
from elftools.elf.relocation import RelocationSection

_TRACE_PC_NAMES = frozenset({
    '__sanitizer_cov_trace_pc',
    # ld.lld AArch64 range thunk: "__" + name + "_veneer" → four leading underscores
    '____sanitizer_cov_trace_pc_veneer',
})


def get_instrumented_pcs(vmlinux_path: str) -> list[str]:
    """Return hex addresses of all KCOV-instrumented PCs in vmlinux.

    Scans SHT_RELA sections for relocations targeting __sanitizer_cov_trace_pc,
    matching the approach used by syzkaller's syz-cover tool.
    """
    with open(vmlinux_path, 'rb') as f:
        elf = ELFFile(f)

        symtab = elf.get_section_by_name('.symtab')
        if symtab is None or not isinstance(symtab, SymbolTableSection):
            return []

        trace_indices = {
            i for i, sym in enumerate(symtab.iter_symbols())
            if sym.name in _TRACE_PC_NAMES
        }
        if not trace_indices:
            return []

        pcs = []
        for section in elf.iter_sections():
            if isinstance(section, RelocationSection) and section.is_RELA():
                for rel in section.iter_relocations():
                    if rel['r_info_sym'] in trace_indices:
                        pcs.append(hex(rel['r_offset']))
        return pcs

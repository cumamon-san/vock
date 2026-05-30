"""Discover KCOV-instrumented lines from vmlinux (ELF RELA or DWARF fallback)."""
import subprocess
from os import path as osp
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


def get_instrumented_lines_dwarf(vmlinux_path: str, kernel_src: str) -> dict[str, set[int]]:
    """Parse DWARF .debug_line via readelf to find all is_stmt source lines.

    Fallback for kernels built without CONFIG_RELOCATABLE (no RELA sections).
    Uses statement-start entries from the DWARF line number program, which
    correspond to the lines KCOV instruments.
    """
    try:
        proc = subprocess.run(
            ['readelf', '--debug-dump=decodedline', vmlinux_path],
            capture_output=True, text=True, errors='replace'
        )
    except FileNotFoundError:
        return {}

    result: dict[str, set[int]] = {}
    current_file: str | None = None
    abs_src = osp.abspath(kernel_src)

    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # File context header: a path ending with ':'
        if stripped.endswith(':') and not stripped.startswith('0x'):
            raw = stripped[:-1]
            if osp.isabs(raw):
                try:
                    rel = osp.relpath(raw, abs_src)
                except ValueError:
                    rel = None
            else:
                rel = raw.lstrip('./')
            current_file = rel if (rel and not rel.startswith('..')) else None
            continue

        if current_file is None or 'Line number' in stripped:
            continue

        # Entry line: is_stmt entries end with 'x'
        if not stripped.endswith('x'):
            continue

        parts = stripped.split()
        # Format: filename  line_no  0xaddr  [view]  x
        if len(parts) < 3:
            continue
        try:
            line_no = int(parts[1])
        except ValueError:
            continue
        if line_no <= 0:
            continue

        result.setdefault(current_file, set()).add(line_no)

    return result

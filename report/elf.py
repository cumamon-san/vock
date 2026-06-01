"""Discover KCOV-instrumented lines from vmlinux via DWARF .debug_line."""
import subprocess
from os import path as osp


def get_instrumented_lines_dwarf(vmlinux_path: str, kernel_src: str) -> dict[str, set[int]]:
    """Parse DWARF .debug_line via readelf to find all is_stmt source lines.

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

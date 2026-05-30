#!/usr/bin/env python3
"""vock output — coverage report generator.

Reads kerncov.log, resolves to source via addr2line, outputs coverage.html + terminal.
"""
import argparse
import time
from pathlib import Path
from os import path

from report.kaslr import detect_kaslr_offset, dekaslr_addresses
from report.resolve import run_addr2line, aggregate
from report.html import generate as generate_html
from report.terminal import print_report

DEFAULT_KERNEL_SRC = str(Path.home() / "stable")
DEFAULT_VMLINUX = str(Path.home() / "stable" / "vmlinux")

# Auto-detect kernel source
for _p in [Path.home() / "linux", Path.home() / "stable", Path.home() / "net"]:
    if (_p / "vmlinux").is_file():
        DEFAULT_KERNEL_SRC = str(_p)
        DEFAULT_VMLINUX = str(_p / "vmlinux")
        break


def read_addresses(log_path: Path) -> set[str]:
    if not log_path.is_file():
        return set()
    with log_path.open() as f:
        addrs = set()
        for line in f:
            a = line.strip()
            if a:
                addrs.add(a if a.startswith("0x") else "0x" + a)
        return addrs


def parse_args():
    p = argparse.ArgumentParser(description="VOCK Coverage Reporter")
    p.add_argument("--kernel-src", default=DEFAULT_KERNEL_SRC)
    p.add_argument("--vmlinux", default=DEFAULT_VMLINUX)
    p.add_argument("--log", default="kerncov.log", help="coverage log file")
    p.add_argument("--filter", help="only show files containing keyword")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-A", type=int, default=4, help="context lines after")
    p.add_argument("-B", type=int, default=4, help="context lines before")
    p.add_argument("-o", "--output", default="coverage.html")
    p.add_argument("--btf", action="store_true",
                   help="resolve PCs via /proc/kallsyms (no vmlinux needed)")
    return p.parse_args()


def main():
    args = parse_args()

    if args.kernel_src != DEFAULT_KERNEL_SRC and args.vmlinux == DEFAULT_VMLINUX:
        args.vmlinux = str(Path(args.kernel_src) / "vmlinux")

    if not args.quiet:
        print(" VOCK Coverage Reporter ".center(80, "="))

    addrs = sorted(read_addresses(Path(args.log)))
    if not addrs:
        if not args.quiet:
            print("\033[93mno coverage data found\033[0m")
        return

    # BTF mode: resolve via /proc/kallsyms, no vmlinux needed
    if args.btf:
        from report.btf import generate_btf_report, generate_btf_html
        ranked = generate_btf_report(addrs)
        if not args.quiet:
            print(f"\n\033[93m📊 [VOCK] BTF report ({len(addrs)} PCs → {len(ranked)} functions)\033[0m\n")
            print(f"  {'Function':<50} {'Hits':>6}")
            print(f"  {'─'*50} {'─'*6}")
            for name, hits in ranked[:50]:
                print(f"  {name:<50} {hits:>6}")
            if len(ranked) > 50:
                print(f"  ... and {len(ranked)-50} more functions")
            print(f"\n\033[92m✓ {len(ranked)} kernel functions covered\033[0m")

        # Generate HTML with highlighted source lines if kernel-src available
        kernel_src = args.kernel_src if args.kernel_src != DEFAULT_KERNEL_SRC else None
        if kernel_src and os.path.isdir(kernel_src):
            generate_btf_html(ranked, kernel_src, args.output)
            if not args.quiet:
                print(f"\033[92m✓ Written: {args.output} (source-highlighted)\033[0m")
        else:
            # Fallback: text-only report
            txt_path = args.output.replace(".html", ".txt")
            with open(txt_path, "w") as f:
                for name, hits in ranked:
                    f.write(f"{name}\t{hits}\n")
            if not args.quiet:
                print(f"\033[92m✓ Written: {txt_path}\033[0m")
        return

    q = args.quiet

    def step(n, total, msg):
        if not q:
            print(f"  [{n}/{total}] {msg}", end="", flush=True)
        return time.monotonic()

    def done(t0, detail=""):
        if not q:
            elapsed = time.monotonic() - t0
            suffix = f"  {detail}" if detail else ""
            print(f"\033[90m  ({elapsed:.1f}s){suffix}\033[0m")

    if not q:
        print(f"\n\033[93m📊 [VOCK] Generating coverage report...\033[0m\n")

    # KASLR detection
    offset = detect_kaslr_offset(args.vmlinux, addrs)
    if offset and not q:
        print(f"  KASLR detected: offset 0x{offset:x}")
    addrs = dekaslr_addresses(addrs, offset)

    # Resolve covered addresses
    t = step(1, 4, f"Resolving {len(addrs):,} covered PCs via addr2line... ")
    lines = run_addr2line(args.vmlinux, addrs)
    cov = aggregate(lines, args.kernel_src)
    if not cov:
        if not q:
            print("\033[93mno source lines resolved\033[0m")
        return
    done(t, f"→ {sum(len(v) for v in cov.values()):,} lines in {len(cov):,} files")

    # Scan vmlinux ELF for instrumented PCs
    instrumented_cov = None
    try:
        from report.elf import get_instrumented_pcs
        t = step(2, 4, "Scanning vmlinux ELF for instrumented PCs... ")
        inst_addrs = get_instrumented_pcs(args.vmlinux)
        done(t, f"→ {len(inst_addrs):,} instrumented PCs")

        t = step(3, 4, f"Resolving {len(inst_addrs):,} instrumented PCs via addr2line... ")
        inst_lines = run_addr2line(args.vmlinux, inst_addrs)
        instrumented_cov = aggregate(inst_lines, args.kernel_src)
        done(t, f"→ {sum(len(v) for v in instrumented_cov.values()):,} lines in {len(instrumented_cov):,} files")
    except ImportError:
        if not q:
            print(f"  [2/4] \033[93mpyelftools not installed; miss highlighting disabled\033[0m")
    except Exception as e:
        if not q:
            print(f"  [2/4] \033[93mELF scan failed ({e}); miss highlighting disabled\033[0m")

    t = step(4, 4, f"Writing {args.output}... ")
    generate_html(cov, args.kernel_src, args.B, args.A, args.output, args.filter,
                  instrumented_cov)
    done(t)
    if not q:
        print(f"\n\033[92m✓ Written: {args.output}\033[0m")


if __name__ == "__main__":
    main()

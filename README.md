# vock

Kernel code coverage via KCOV — in one tool.

Map any userspace program to the exact kernel code it exercises, with a
source-annotated HTML report.

```bash
make && sudo ./vock /bin/ip addr show
```

No dependencies beyond a C compiler and Python 3. Just `make` and run.

## What It Does

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────────┐
│  Your App   │────▶│  vock (KCOV) │────▶│  Kernel PCs  │────▶│ coverage.html  │
│  /bin/ip    │     │  LD_PRELOAD  │     │  kerncov.log │     │ (addr2line)    │
└─────────────┘     └──────────────┘     └──────────────┘     └────────────────┘
```

`vock` forks the target with `LD_PRELOAD=mode/kcov.so`, which enables KCOV
(local + remote) inside the target process and writes the covered kernel PCs
to `kerncov.log`. It then resolves those PCs to source `file:line` via
`addr2line` and emits `coverage.html`.

## Install

```bash
git clone https://github.com/yskzalloc/vock && cd vock
make
```

Requires a kernel built with `CONFIG_KCOV` (and `CONFIG_KCOV_INSTRUMENT_ALL`
for whole-kernel coverage), plus `vmlinux` with debug info for source-level
reports.

## Usage

```bash
# Collect coverage and generate a report (needs root for /sys/kernel/debug/kcov)
sudo ./vock /bin/ip addr show
# → kerncov.log + coverage.html

# Point at the matching kernel source / vmlinux for source-annotated output
sudo ./vock --kernel-src ~/linux --vmlinux ~/linux/vmlinux /bin/ip addr show

# Restrict the report to matching paths
sudo ./vock --filter net /bin/ip addr show
```

### Options

| Option | Description |
|--------|-------------|
| `--kernel-src PATH` | kernel source tree for the coverage report |
| `--vmlinux FILE` | vmlinux with debug info (for addr2line) |
| `--filter KW` | only show files whose path contains the keyword |
| `-A N`, `-B N` | context lines after / before covered lines in the report |

## Selftest

```bash
./vock selftest --on vng-kvm --kernel-src ~/linux   # build a KCOV kernel in a VM, collect coverage
./vock selftest --on vng-tcg --kernel-src ~/linux   # same without KVM (CI)
./vock selftest --help                              # all options
```

Unit tests for the report generator:

```bash
python3 -m pytest tests/
```

See [SELFTEST.md](SELFTEST.md) for kernel configuration and VM testing details.

## Files

| Output | Description |
|--------|-------------|
| `kerncov.log` | Merged kernel coverage (local + remote) |
| `local.log` | KCOV local coverage (direct syscall paths) |
| `remote.log` | KCOV remote coverage (softirqs, workqueues) |
| `coverage.html` | Source-annotated coverage report |

## Build Options

```bash
make                    # default (clang)
make CC=clang           # use clang
make CC=gcc             # use gcc
```

## License

See [LICENSE](LICENSE).

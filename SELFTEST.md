# vock selftest

Automated test framework. Configures a KCOV kernel, builds it, boots a VM, and
verifies coverage collection plus HTML report generation end-to-end.

## Quick Start

```bash
# VM test (needs kernel source + vng)
vock selftest --on vng-kvm --kernel-src ~/linux

# CI (no KVM available)
vock selftest --on vng-tcg --kernel-src ~/linux

# Run directly on a host that already boots a KCOV kernel
sudo vock selftest --on host --kernel-src ~/linux
```

## Options

```
vock selftest [-h] [--on {host,vng-kvm,vng-tcg}] [--kernel-src PATH] [--llvm SUFFIX] [-v]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--on` | `vng-kvm` | Execution target |
| `--kernel-src` | `$HOME/stable` | Kernel source tree |
| `--llvm` | auto-detect | LLVM suffix (e.g. `-21`) or path. Also reads `LLVM` env |
| `-v`, `--verbose` | off | Show command output for debugging |

## What It Does

1. Builds `vock` with the selected toolchain.
2. Configures and builds the kernel at `--kernel-src` with `CONFIG_KCOV`,
   `CONFIG_KCOV_INSTRUMENT_ALL`, `CONFIG_DEBUG_INFO`, and the crypto configs
   used by the test target.
3. Runs an `xts(aes)` decrypt under `vock` (with `--vmlinux` + `--kernel-src`).
4. Asserts that `kerncov.log` has PCs > 0 and that `coverage.html` is generated.

The test target exercises the kernel crypto subsystem (skcipher, aes, xts).

## Kernel Configuration

```bash
cd ~/linux
scripts/config \
    --enable CONFIG_DEBUG_KERNEL \
    --enable CONFIG_KCOV \
    --enable CONFIG_KCOV_INSTRUMENT_ALL \
    --enable CONFIG_DEBUG_INFO \
    --enable CONFIG_DEBUG_INFO_DWARF5 \
    --enable CONFIG_CRYPTO_XTS \
    --enable CONFIG_CRYPTO_USER \
    --enable CONFIG_CRYPTO_USER_API_SKCIPHER \
    --disable CONFIG_DEBUG_INFO_NONE
make olddefconfig
vng LLVM=-21 --build
```

| Need | Required configs |
|------|-----------------|
| KCOV coverage | `KCOV`, `KCOV_INSTRUMENT_ALL`, `DEBUG_INFO` |
| Source-level report | `DEBUG_INFO`, `DEBUG_INFO_DWARF5` (vmlinux with debug info) |
| crypto test target | `CRYPTO_XTS`, `CRYPTO_USER`, `CRYPTO_USER_API_SKCIPHER` |

## LLVM Toolchain

Priority: `--llvm` flag > `LLVM` env > auto-detect.

```bash
# Suffix style (system-installed)
vock selftest --llvm -21 --kernel-src ~/linux

# Path style (custom build)
vock selftest --llvm /path/to/llvm-project/build/bin/ --kernel-src ~/linux
```

## GitHub CI

```yaml
- name: Test
  run: |
    if [ -w /dev/kvm ]; then ON=vng-kvm; else ON=vng-tcg; fi
    ./vock selftest --on $ON --kernel-src $PWD/staging
```

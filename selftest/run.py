#!/usr/bin/env python3
"""vock selftest — configure, build, and test KCOV coverage end-to-end."""

import argparse
import os
import platform
import subprocess
import sys

PASS = 0
FAIL = 0
SKIP = 0
LLVM_SUFFIX = ""
RUN_TARGET = "host"
VERBOSE = False


def log(status, msg):
    global PASS, FAIL, SKIP
    colors = {"PASS": "32", "FAIL": "31", "SKIP": "33"}
    print(f"  \033[{colors.get(status, '0')}m{status}\033[0m: {msg}")
    if status == "PASS": PASS += 1
    elif status == "FAIL": FAIL += 1
    elif status == "SKIP": SKIP += 1


def run(cmd, **kwargs):
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("timeout", 300)
    kwargs["shell"] = False  # Explicitly prevent shell injection
    return subprocess.run(cmd, **kwargs)


def vlog(r):
    """Print command output if --verbose."""
    if not VERBOSE:
        return
    out = r.stdout.decode() if r.stdout else ""
    err = r.stderr.decode() if r.stderr else ""
    if out:
        for line in out.strip().split('\n')[-20:]:
            print(f"    | {line}")
    if err:
        for line in err.strip().split('\n')[-10:]:
            print(f"    ! {line}")


def kvm_available():
    return os.access("/dev/kvm", os.W_OK)


def detect_llvm_suffix():
    for cmd in ["clang", "clang-21", "clang-20", "clang-19", "clang-18",
                "clang-17", "clang-16", "clang-15"]:
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True)
        except FileNotFoundError:
            continue
        if r.returncode == 0:
            out = (r.stdout or b"").decode()
            for line in out.splitlines():
                if "clang version" in line.lower():
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "version" and i + 1 < len(parts):
                            major = parts[i + 1].split(".")[0]
                            suffix = f"-{major}"
                            try:
                                if subprocess.run([f"clang{suffix}", "--version"],
                                                  capture_output=True).returncode == 0:
                                    return suffix
                            except FileNotFoundError:
                                pass
                            return ""
    return ""


def find_vock_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def kernel_configure_and_build(kernel_src, configs):
    """Configure + build using vng --configitem + --build."""
    if RUN_TARGET == "host":
        # On host, don't build — assume kernel is already built
        return True

    print("  Configuring + building kernel...")
    cmd = ["vng"]
    for key, enable in configs.items():
        cmd += ["--configitem", f"{key}={'y' if enable else 'n'}"]
    cmd += ["--build", f"LLVM={LLVM_SUFFIX}"]
    r = run(cmd, cwd=kernel_src, timeout=1800)
    if r.returncode != 0:
        vlog(r)
    return r.returncode == 0


def vng_run(kernel_src, cmd):
    """Run command on target. If --on host, run directly. Otherwise use vng."""
    if RUN_TARGET == "host":
        return run(cmd, cwd=kernel_src, timeout=600)
    vng_cmd = ["vng", "--rw"]
    if RUN_TARGET == "vng-tcg":
        vng_cmd.append("--disable-kvm")
    vng_cmd += ["--"] + cmd
    return run(vng_cmd, cwd=kernel_src, timeout=600)


def crypto_prepare():
    """Shell commands to create test block + key + encrypt (setup, not traced)."""
    cipher = "xts(aes)"
    key = "ThisIsA64ByteSecretKeyForAES256XTSModeWhichRequires512BitsOfData"
    iv = "00000000000000000000000000000000"
    return (
        f"dd if=/dev/urandom of=/tmp/block.img bs=64K count=64 2>/dev/null; "
        f"printf '{key}' > /tmp/key.bin; "
        f"kcapi-enc -c '{cipher}' -e -i /tmp/block.img -o /tmp/block.enc "
        f"--iv {iv} --keyfd 3 3</tmp/key.bin 2>/dev/null; "
        f"printf '#!/bin/sh\\nkcapi-enc -d -c \"{cipher}\" -i /tmp/block.enc -o /tmp/block.dec "
        f"--iv {iv} --keyfd 3 3</tmp/key.bin\\n' > /tmp/dec.sh; "
        f"chmod +x /tmp/dec.sh; true"
    )


# Target command: exercise the kernel crypto subsystem via an xts(aes) decrypt
CRYPTO_TARGET = "/bin/sh /tmp/dec.sh"


def test_kcov(vock_dir, kernel_src):
    """Build a KCOV kernel, run a target under vock, assert PCs + HTML report."""
    print("\n" + "=" * 60)
    print("  TEST: KCOV coverage + HTML report")
    print("=" * 60)

    configs = {
        "CONFIG_DEBUG_KERNEL": True,
        "CONFIG_KCOV": True,
        "CONFIG_KCOV_INSTRUMENT_ALL": True,
        "CONFIG_DEBUG_INFO": True,
        "CONFIG_DEBUG_INFO_DWARF5": True,
        "CONFIG_DEBUG_INFO_NONE": False,
        "CONFIG_CRYPTO_XTS": True,
        "CONFIG_CRYPTO_USER": True,
        "CONFIG_CRYPTO_USER_API_SKCIPHER": True,
    }

    if not kernel_configure_and_build(kernel_src, configs):
        log("FAIL", "kernel configure+build failed")
        return False
    log("PASS", "kernel configured + built")

    vmlinux = os.path.join(kernel_src, "vmlinux")

    print("\n[Test: vock --vmlinux --kernel-src (xts(aes) decrypt)]")
    r = vng_run(kernel_src, [
        "bash", "-c",
        f"rm -f kerncov.log coverage.html && "
        f"{crypto_prepare()} && "
        f"{vock_dir}/vock --vmlinux {vmlinux} --kernel-src {kernel_src} {CRYPTO_TARGET} 2>&1; "
        f"echo KCOV_PCS=$(wc -l < kerncov.log 2>/dev/null || echo 0) && "
        f"[ -f coverage.html ] && echo HTML_OK"
    ])
    vlog(r)
    out = r.stdout.decode() if r.stdout else ""

    if "KCOV_PCS=" in out:
        pcs = out.split("KCOV_PCS=")[1].split()[0]
        if int(pcs) > 0:
            log("PASS", f"kcov: {pcs} kernel PCs collected")
        else:
            log("FAIL", "kcov: no coverage")
    else:
        log("FAIL", "kcov: command failed")
        if out:
            print(f"    {out[:300]}")

    if "HTML_OK" in out:
        log("PASS", "coverage.html generated")
    else:
        log("FAIL", "coverage.html missing")

    return True


def main():
    parser = argparse.ArgumentParser(
        prog="vock selftest",
        description="Configure, build, and test KCOV coverage end-to-end.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""--on target:
  vng-kvm   VM tests use KVM acceleration (default)
  vng-tcg   VM tests use QEMU TCG (CI, no KVM)
  host      run directly on host (assumes a KCOV kernel is booted)

defaults:
  --kernel-src   $HOME/stable
  --on           vng-kvm

examples:
  vock selftest                          run the KCOV test (KVM)
  vock selftest --on vng-tcg             run the KCOV test (TCG, CI)
  vock selftest --kernel-src ~/linux     custom kernel source
""")
    parser.add_argument("test", nargs="?", choices=["1"], default=None,
                        help="test number (only 1 exists; default: run it)")
    parser.add_argument("--on", choices=["host", "vng-kvm", "vng-tcg"], default="vng-kvm",
                        help="execution target (default: vng-kvm)")
    parser.add_argument("--kernel-src", default=None,
                        help="kernel source tree (default: $HOME/stable)")
    parser.add_argument("--llvm", default=None,
                        help="LLVM suffix (e.g. -21, -20). Overrides auto-detect. Env: LLVM=")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show command output for debugging")
    args = parser.parse_args()

    kernel_src = args.kernel_src or os.path.join(os.path.expanduser("~"), "stable")
    vock_dir = find_vock_dir()

    global LLVM_SUFFIX, RUN_TARGET, VERBOSE
    VERBOSE = args.verbose
    if args.llvm is not None:
        LLVM_SUFFIX = args.llvm
    elif os.environ.get("LLVM"):
        LLVM_SUFFIX = os.environ["LLVM"]
    else:
        LLVM_SUFFIX = detect_llvm_suffix()

    RUN_TARGET = args.on

    print("=" * 60)
    print("  vock selftest")
    print("=" * 60)
    print(f"  Kernel src: {kernel_src}")
    print(f"  vock dir:   {vock_dir}")
    print(f"  Arch:       {platform.machine()}")
    print(f"  KVM:        {'available' if kvm_available() else 'unavailable'}")
    print(f"  Run on:     {RUN_TARGET}")
    print(f"  LLVM:       clang{LLVM_SUFFIX} (LLVM={LLVM_SUFFIX})")

    # Build vock
    print("\n[Build vock]")
    if "/" in LLVM_SUFFIX:
        cc = os.path.join(os.path.expanduser(LLVM_SUFFIX), "clang")
    else:
        cc = f"clang{LLVM_SUFFIX}"
    run(["make", "clean"], cwd=vock_dir, timeout=30)
    r = run(["make", f"CC={cc}", "-j4"], cwd=vock_dir, timeout=120)
    if r.returncode != 0:
        print("  FATAL: cannot build vock")
        vlog(r)
        sys.exit(1)
    print("  vock built")

    if not os.path.isdir(kernel_src):
        print(f"\n  FATAL: kernel source not found at {kernel_src}")
        print(f"  Use: vock selftest --kernel-src /path/to/linux")
        sys.exit(1)

    if not os.path.isfile(os.path.join(kernel_src, "Makefile")):
        print(f"\n  FATAL: {kernel_src} is not a kernel source tree")
        sys.exit(1)

    test_kcov(vock_dir, kernel_src)

    # Summary
    print("\n" + "=" * 60)
    total = PASS + FAIL + SKIP
    print(f"  Results: {PASS} passed, {FAIL} failed, {SKIP} skipped ({total} total)")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

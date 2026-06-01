"""Unit tests for the KCOV report pipeline: log parsing, addr2line
aggregation, and KASLR de-randomization."""
import os
import tempfile
from pathlib import Path

from output import read_addresses
from report.resolve import aggregate
from report.kaslr import dekaslr_addresses


# ─── read_addresses (output.py) ──────────────────────────────────────────────

def test_read_addresses_normalizes_and_dedups():
    """Lines get a 0x prefix when missing; duplicates collapse into a set."""
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "kerncov.log"
        log.write_text("ffffffff81001234\n0x81002000\nffffffff81001234\n")
        assert read_addresses(log) == {"0xffffffff81001234", "0x81002000"}


def test_read_addresses_skips_blank_lines():
    """Blank/whitespace-only lines are ignored."""
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "kerncov.log"
        log.write_text("0x1\n\n   \n0x2\n")
        assert read_addresses(log) == {"0x1", "0x2"}


def test_read_addresses_missing_file_returns_empty():
    """A non-existent log yields an empty set, not an error."""
    assert read_addresses(Path("/nonexistent/kerncov.log")) == set()


# ─── aggregate (report/resolve.py) ───────────────────────────────────────────

def test_aggregate_relpath_under_kernel_src():
    """Paths inside kernel_src become relative; line numbers group per file."""
    src = "/home/u/linux"
    lines = [
        f"{src}/kernel/sched/core.c:42",
        f"{src}/kernel/sched/core.c:43",
        f"{src}/net/socket.c:10",
    ]
    cov = aggregate(lines, src)
    assert cov["kernel/sched/core.c"] == {42, 43}
    assert cov["net/socket.c"] == {10}


def test_aggregate_skips_unresolved():
    """'??' lines and non-file:line lines are dropped."""
    cov = aggregate(["??:0", "garbage", "/x/kernel/foo.c:5"], "/x")
    assert cov == {"kernel/foo.c": {5}}


def test_aggregate_recovers_kernel_dir_outside_src():
    """A path outside kernel_src is rebased onto a known kernel subdir."""
    # Build directory differs from kernel_src → relpath starts with ".."
    lines = ["/build/abc/net/ipv4/tcp.c:99"]
    cov = aggregate(lines, "/home/u/linux")
    assert cov == {"net/ipv4/tcp.c": {99}}


def test_aggregate_unknown_path_falls_back_to_basename():
    """A path with no recognizable kernel dir falls back to the file name."""
    lines = ["/opt/vendor/blob.c:7"]
    cov = aggregate(lines, "/home/u/linux")
    assert cov == {"blob.c": {7}}


# ─── dekaslr_addresses (report/kaslr.py) ─────────────────────────────────────

def test_dekaslr_zero_offset_is_identity():
    """offset == 0 returns the input unchanged."""
    addrs = ["0xffffffff81001234", "0xffffffff81002000"]
    assert dekaslr_addresses(addrs, 0) is addrs


def test_dekaslr_subtracts_offset():
    """Each address has the offset subtracted and is re-hex-formatted."""
    out = dekaslr_addresses(["0xffffffff82001234"], 0x1000000)
    assert out == ["0xffffffff81001234"]


def test_dekaslr_accepts_unprefixed_input():
    """Addresses without a 0x prefix are still parsed as hex."""
    out = dekaslr_addresses(["ffffffff82000000"], 0x1000000)
    assert out == ["0xffffffff81000000"]

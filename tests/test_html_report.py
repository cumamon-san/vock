import json
import os
import tempfile
import pytest
from report.html import generate


def _parse_data(html: str) -> dict:
    """Extract and parse the DATA JSON object from generated HTML."""
    marker = "const DATA="
    start = html.index(marker) + len(marker)
    end = html.index(";\n", start)
    return json.loads(html[start:end])


def test_data_json_structure():
    """generate() embeds JSON with files, covered, lines keys."""
    with tempfile.TemporaryDirectory() as src:
        fpath = "kernel/sched/core.c"
        os.makedirs(os.path.join(src, "kernel/sched"))
        with open(os.path.join(src, fpath), "w") as f:
            f.write("line one\nline two\nline three\n")

        output = os.path.join(src, "out.html")
        generate({"kernel/sched/core.c": {2}}, src, 4, 4, output)

        data = _parse_data(open(output).read())
        assert data["files"] == ["kernel/sched/core.c"]
        assert data["covered"]["kernel/sched/core.c"] == [2]
        assert data["lines"]["kernel/sched/core.c"] == ["line one", "line two", "line three"]


def test_missing_file_produces_null():
    """Files not found on disk are represented as null in JSON."""
    with tempfile.TemporaryDirectory() as src:
        output = os.path.join(src, "out.html")
        generate({"kernel/missing.c": {5}}, src, 4, 4, output)

        data = _parse_data(open(output).read())
        assert data["lines"]["kernel/missing.c"] is None


def test_filter_kw_excludes_files():
    """filter_kw is applied in Python; excluded files absent from DATA."""
    with tempfile.TemporaryDirectory() as src:
        os.makedirs(os.path.join(src, "kernel/sched"))
        os.makedirs(os.path.join(src, "net"))
        open(os.path.join(src, "kernel/sched/core.c"), "w").write("a\n")
        open(os.path.join(src, "net/socket.c"), "w").write("b\n")

        output = os.path.join(src, "out.html")
        generate(
            {"kernel/sched/core.c": {1}, "net/socket.c": {1}},
            src, 4, 4, output, filter_kw="sched"
        )

        data = _parse_data(open(output).read())
        assert data["files"] == ["kernel/sched/core.c"]
        assert "net/socket.c" not in data["files"]


def test_empty_cov_shows_message():
    """Empty coverage dict produces 'No files covered' message in HTML."""
    with tempfile.TemporaryDirectory() as src:
        output = os.path.join(src, "out.html")
        generate({}, src, 4, 4, output)

        content = open(output).read()
        assert "No files covered" in content


def test_html_contains_sidebar_and_js():
    """Output contains sidebar elements and renderFile JS function."""
    with tempfile.TemporaryDirectory() as src:
        output = os.path.join(src, "out.html")
        generate({}, src, 4, 4, output)

        content = open(output).read()
        assert "file-list" in content
        assert "renderFile" in content
        assert 'id="filter"' in content


def test_files_sorted_alphabetically():
    """DATA.files list is sorted alphabetically regardless of input order."""
    with tempfile.TemporaryDirectory() as src:
        os.makedirs(os.path.join(src, "z"))
        os.makedirs(os.path.join(src, "a"))
        open(os.path.join(src, "z/last.c"), "w").write("x\n")
        open(os.path.join(src, "a/first.c"), "w").write("y\n")

        output = os.path.join(src, "out.html")
        generate({"z/last.c": {1}, "a/first.c": {1}}, src, 4, 4, output)

        data = _parse_data(open(output).read())
        assert data["files"] == ["a/first.c", "z/last.c"]

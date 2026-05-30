import json
import os
import tempfile
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


def test_script_tag_not_broken_by_source_content():
    """Source lines containing </script> must not break the <script> block."""
    with tempfile.TemporaryDirectory() as src:
        os.makedirs(os.path.join(src, "kernel"))
        with open(os.path.join(src, "kernel/foo.c"), "w") as f:
            f.write('/* see </script> in docs */\n')

        output = os.path.join(src, "out.html")
        generate({"kernel/foo.c": {1}}, src, 4, 4, output)

        content = open(output).read()
        data = _parse_data(content)
        assert data["lines"]["kernel/foo.c"] == ['/* see </script> in docs */']
        assert "</script>" not in content.split("</script>")[0].split("const DATA=")[1]


def test_instrumented_key_in_data_json():
    """DATA.instrumented contains sorted instrumented line numbers when provided."""
    with tempfile.TemporaryDirectory() as src:
        fpath = "kernel/sched/core.c"
        os.makedirs(os.path.join(src, "kernel/sched"))
        with open(os.path.join(src, fpath), "w") as f:
            f.write("line one\nline two\nline three\nline four\n")

        output = os.path.join(src, "out.html")
        generate({"kernel/sched/core.c": {2}}, src, 4, 4, output,
                 instrumented={"kernel/sched/core.c": {2, 3}})

        data = _parse_data(open(output).read())
        assert data["instrumented"]["kernel/sched/core.c"] == [2, 3]


def test_no_instrumented_gives_empty_dict():
    """DATA.instrumented is {} when instrumented=None (non-empty cov)."""
    with tempfile.TemporaryDirectory() as src:
        fpath = "kernel/sched/core.c"
        os.makedirs(os.path.join(src, "kernel/sched"))
        open(os.path.join(src, fpath), "w").write("a\n")

        output = os.path.join(src, "out.html")
        generate({"kernel/sched/core.c": {1}}, src, 4, 4, output)

        data = _parse_data(open(output).read())
        assert data["instrumented"] == {}


def test_miss_css_class_present():
    """.miss CSS class present; miss line appears in DATA when instrumented but not covered."""
    with tempfile.TemporaryDirectory() as src:
        fpath = "kernel/sched/core.c"
        os.makedirs(os.path.join(src, "kernel/sched"))
        with open(os.path.join(src, fpath), "w") as f:
            f.write("covered\nnot_hit\ncontext\n")

        output = os.path.join(src, "out.html")
        generate({"kernel/sched/core.c": {1}}, src, 4, 4, output,
                 instrumented={"kernel/sched/core.c": {1, 2}})

        content = open(output).read()
        assert ".miss" in content
        data = _parse_data(content)
        assert 2 in data["instrumented"]["kernel/sched/core.c"]
        assert 2 not in data["covered"]["kernel/sched/core.c"]


def test_filter_kw_applied_to_instrumented():
    """filter_kw excludes files from DATA.instrumented as well as DATA.covered."""
    with tempfile.TemporaryDirectory() as src:
        os.makedirs(os.path.join(src, "kernel/sched"))
        os.makedirs(os.path.join(src, "net"))
        open(os.path.join(src, "kernel/sched/core.c"), "w").write("a\n")
        open(os.path.join(src, "net/socket.c"), "w").write("b\n")

        output = os.path.join(src, "out.html")
        generate(
            {"kernel/sched/core.c": {1}, "net/socket.c": {1}},
            src, 4, 4, output,
            filter_kw="sched",
            instrumented={"kernel/sched/core.c": {1, 2}, "net/socket.c": {1, 2}},
        )

        data = _parse_data(open(output).read())
        assert "net/socket.c" not in data["instrumented"]
        assert "kernel/sched/core.c" in data["instrumented"]


def test_instrumented_only_file_appears_in_files():
    """Files with instrumented lines but zero coverage appear in DATA.files."""
    with tempfile.TemporaryDirectory() as src:
        os.makedirs(os.path.join(src, "kernel"))
        open(os.path.join(src, "kernel/covered.c"), "w").write("a\nb\n")
        open(os.path.join(src, "kernel/uncovered.c"), "w").write("x\ny\n")

        output = os.path.join(src, "out.html")
        generate(
            {"kernel/covered.c": {1}},
            src, 4, 4, output,
            instrumented={
                "kernel/covered.c": {1, 2},
                "kernel/uncovered.c": {1, 2},
            },
        )

        data = _parse_data(open(output).read())
        assert "kernel/uncovered.c" in data["files"]
        assert data["covered"]["kernel/uncovered.c"] == []
        assert data["instrumented"]["kernel/uncovered.c"] == [1, 2]

"""
The docstring convention of the package, outside the vendored `numpy`,
`modeling` and `optimization` packages.
"""

import ast
import re
from pathlib import Path

import pytest

import architeuthis

ROOT = Path(architeuthis.__file__).parent
VENDORED = {"numpy", "modeling", "optimization"}
WIDTH = 72
FILES = [
    path
    for path in sorted(ROOT.rglob("*.py"))
    if path.relative_to(ROOT).parts[0] not in VENDORED
]


def docstrings(path):
    """
    Each docstring of a file: its first line number and its source lines.
    """
    source = path.read_text(encoding="utf-8")
    lines = source.split("\n")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                yield first.lineno, lines[first.lineno - 1:first.end_lineno]


@pytest.mark.parametrize("path", FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_docstrings_follow_the_convention(path):
    for line_number, block in docstrings(path):
        where = f"{path.name}:{line_number}"
        assert block[0].strip() in ('"""', 'r"""'), f"{where}: text on the opening line"
        assert block[-1].strip() == '"""', f"{where}: text on the closing line"
        assert block[1].strip(), f"{where}: blank first line"
        for line in block:
            # A URL cannot be wrapped.
            assert len(line) <= WIDTH or "https://" in line, f"{where}: over {WIDTH} columns: {line.strip()}"
            assert line == line.rstrip(), f"{where}: trailing space"
        text = "\n".join(block)
        assert not re.search(
            r"^\s*-{3,}\s*$|:param |:return|^\s*(Args|Returns): \S",
            text,
            flags=re.MULTILINE,
        ), f"{where}: not Google style"


@pytest.mark.parametrize("path", FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_each_summary_fits_on_one_line(path):
    for line_number, block in docstrings(path):
        inner = block[1:-1]
        assert len(inner) == 1 or not inner[1].strip(), (
            f"{path.name}:{line_number}: summary over one line: {inner[0].strip()}"
        )


def has_docstring(node):
    return ast.get_docstring(node, clean=False) is not None


def undocumented(node, documented_class=False):
    """
    The public items without a docstring below a node.

    `__init__` is exempt when its class has a docstring, which holds
    `Args:`. Nested functions and private items are not public.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            private = child.name.startswith("_") and not child.name.endswith("__")
            exempt = child.name == "__init__" and documented_class
            if not private and not exempt and not has_docstring(child):
                yield child.name
        elif isinstance(child, ast.ClassDef):
            if child.name.startswith("_"):
                continue
            if not has_docstring(child):
                yield child.name
            yield from undocumented(child, has_docstring(child))
        else:
            yield from undocumented(child, documented_class)


@pytest.mark.parametrize("path", FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_public_items_have_a_docstring(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert has_docstring(tree), f"{path.name}: no module docstring"
    assert list(undocumented(tree)) == []


def test_modules_are_described_before_their_header():
    for path in FILES:
        summary = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))).split("\n")[0]
        assert not summary.startswith(("Created on", "@author")), path.name


def test_the_convention_is_really_checked_on_the_package():
    assert sum(len(list(docstrings(path))) for path in FILES) > 150
    assert not any("numpy" in path.relative_to(ROOT).parts for path in FILES)

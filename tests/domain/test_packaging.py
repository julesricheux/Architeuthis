"""The version is written once, in `architeuthis/__init__.py`."""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import architeuthis

ROOT = Path(architeuthis.__file__).parent.parent


def pyproject():
    with open(ROOT / "pyproject.toml", "rb") as stream:
        return tomllib.load(stream)


def test_pyproject_takes_the_version_of_the_package():
    configuration = pyproject()

    assert "version" not in configuration["project"]
    assert "version" in configuration["project"]["dynamic"]
    assert configuration["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "architeuthis.__version__"}


def test_version_is_a_literal_that_setuptools_reads_without_importing():
    # setuptools then reads it with ast, without the dependencies of the package.
    source = (ROOT / "architeuthis" / "__init__.py").read_text(encoding="utf-8")

    assert re.search(r'^__version__ = "\d+\.\d+\.\d+"', source, flags=re.MULTILINE)


def test_release_check_reads_the_same_version():
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    command = re.search(r'PKG_VERSION=\$\(python -c "(.+)"\)', workflow).group(1)

    done = subprocess.run([sys.executable, "-I", "-c", command], cwd=ROOT, capture_output=True, text=True, check=True)

    assert done.stdout.strip() == architeuthis.__version__


def test_keyring_is_a_dependency():
    assert "keyring" in pyproject()["project"]["dependencies"]


DUX_DEPENDENCIES = ("dash", "flask", "dash-extensions", "dash-leaflet", "dash-mantine-components", "dash-iconify")


def names(requirements):
    return {re.split(r"[<>=!\[; ]", requirement, maxsplit=1)[0].lower() for requirement in requirements}


def test_the_display_tools_are_an_extra():
    # pip install architeuthis gives the routing without Dash, architeuthis[dux] adds the pages.
    project = pyproject()["project"]
    extras = project["optional-dependencies"]

    assert not names(project["dependencies"]) & set(DUX_DEPENDENCIES)
    assert set(DUX_DEPENDENCIES) <= names(extras["dux"])
    assert "app" not in extras
    assert "architeuthis[dux]" in extras["test"]

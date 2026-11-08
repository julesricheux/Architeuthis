"""The README: what it must keep saying, and links that lead somewhere."""

import re
import tomllib
from pathlib import Path

import pytest

import architeuthis

ROOT = Path(architeuthis.__file__).parent.parent
LOGO = "media/logo-architeuthis-color.png"
DESCRIPTION = (
    "An open-source marine weather and decision-making framework for hybrid sailing ships. "
    "It couples mesh-free, fully differentiable methods in a unified optimization environment "
    "to compute optimal routes under real-world constraints."
)


@pytest.fixture(scope="module")
def readme():
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_file_starts_with_the_full_width_logo(readme):
    image = re.search(r"<img [^>]*>", readme).group(0)

    assert readme.index(image) < readme.index("# Architeuthis")
    assert f'src="{LOGO}"' in image
    assert 'width="100%"' in image


def test_description_is_kept_word_for_word(readme):
    assert DESCRIPTION in readme


@pytest.mark.parametrize("document", ["README.md", "docs/user_guide.md", "examples/README.md"])
def test_relative_links_lead_to_a_file(document):
    path = ROOT / document
    targets = re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", path.read_text(encoding="utf-8"))
    relative = [target for target in targets if not target.startswith("http")]

    assert relative
    for target in relative:
        assert (path.parent / target).exists(), target


def test_license_of_the_readme_is_the_license_file(readme):
    assert "GNU GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text(encoding="utf-8")[:200]
    assert "GNU General Public License v3" in readme
    assert (ROOT / "architeuthis" / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    with open(ROOT / "pyproject.toml", "rb") as stream:
        assert tomllib.load(stream)["project"]["license"] == "GPL-3.0-only"


def test_adapted_code_keeps_its_credit_and_license_notice(readme):
    assert "Copyright (c) 2019-2023 Peter Sharpe" in readme
    assert "shall be included in all" in readme
    for package in ("numpy", "optimization", "modeling"):
        assert f"`{package}`" in readme


def test_data_sources_of_the_readme_exist():
    from architeuthis import presets

    for name in ("atmosphere", "wave", "ensemble_atmosphere", "ensemble_wave", "hrdps_atmosphere", "current_mercator", "topography"):
        assert callable(getattr(presets, name))

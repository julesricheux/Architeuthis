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
    assert "https://github.com/peterdsharpe/AeroSandbox/blob/master/LICENSE.txt" in readme
    for package in ("numpy", "optimization", "modeling"):
        assert f"`{package}`" in readme


def slug(heading):
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")


def test_links_inside_the_readme_lead_to_a_heading(readme):
    headings = {slug(heading) for heading in re.findall(r"^#+ (.+)$", readme, flags=re.MULTILINE)}

    for anchor in re.findall(r"\]\(#([^)]+)\)", readme):
        assert anchor in headings, anchor


def test_tutorials_cover_every_credential_that_is_read():
    common = (ROOT / "architeuthis" / "common.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    names = re.findall(r'_get_env_var\("(\w+)"\)', common)

    assert set(names) == {"CDS_API_KEY", "CMEMS_USER", "CMEMS_PWD", "EUMDAC_USER", "EUMDAC_PWD"}
    section = readme[readme.index("## 🔑 Credentials"):readme.index("The Routing Problem")]
    for name in names:
        assert f"`{name}`" in section


def test_eumetsat_tutorial_asks_for_what_the_client_expects(readme):
    import inspect

    import eumdac

    assert "consumer_key, consumer_secret" in inspect.getdoc(eumdac.AccessToken.__init__)
    assert "`EUMDAC_USER` to your **Consumer Key**" in readme
    assert "`EUMDAC_PWD` to your **Consumer Secret**" in readme


def test_cds_tutorial_gives_the_url_that_is_written(readme):
    from architeuthis.common import _CDS_URL

    assert f"url: {_CDS_URL}" in readme


def test_data_sources_of_the_readme_exist():
    import architeuthis.forecast as forecast

    for name in ("DeterministicHerbieForecast", "EnsembleHerbieForecast", "HRDPSForecast", "CopernicusForecast", "CDSForecast", "Topography"):
        assert callable(getattr(forecast, name))


def test_package_has_no_presets():
    import importlib.util

    assert importlib.util.find_spec("architeuthis.presets") is None

"""
The real architeuthis.icebergs module, loaded with the network cut off.

tests/conftest.py replaces architeuthis.icebergs with a stub for every other test, so this
file loads the source under another name, with requests.get raising a timeout.
"""

import importlib.util
import os

import pytest
import requests

import architeuthis

ICEBERGS_SOURCE = os.path.join(os.path.dirname(architeuthis.__file__), "icebergs.py")

BULLETIN = """
ICEBERG LIMIT ALONG TRACKLINE JOINING 47-00N 052-00W 45-30N 048-15W 44-00N 045-00W
TO THE COAST.
"""


def unreachable(*args, **kwargs):
    raise requests.exceptions.ConnectTimeout("navcen.uscg.gov timed out")


@pytest.fixture
def load_icebergs(monkeypatch, tmp_path):
    from architeuthis import common

    monkeypatch.setattr(common, "_HOME", str(tmp_path))
    monkeypatch.setattr(requests, "get", unreachable)

    def _load():
        spec = importlib.util.spec_from_file_location("icebergs_offline", ICEBERGS_SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


def test_import_survives_an_unreachable_server(load_icebergs, capsys):
    icebergs = load_icebergs()

    assert icebergs.berg_zone == []
    assert icebergs.berg_geojson == {"type": "FeatureCollection", "features": []}
    assert "No iceberg exclusion zone" in capsys.readouterr().out


def test_last_downloaded_bulletin_is_used_offline(load_icebergs, tmp_path, capsys):
    (tmp_path / "iip").mkdir()
    (tmp_path / "iip" / "IcebergBulletin.txt").write_text(BULLETIN, encoding="utf-8")

    zone = load_icebergs().berg_zone

    assert zone[:3] == [[47.0, -52.0], [45.5, -48.25], [44.0, -45.0]]
    assert zone[0] == zone[-1]
    assert "Using the bulletin downloaded on" in capsys.readouterr().out


def test_bulletin_parsing():
    from types import ModuleType

    source = open(ICEBERGS_SOURCE, encoding="utf-8").read()
    parser = ModuleType("parser")
    exec(source[: source.index("# CONFIG")], parser.__dict__)

    assert parser.get_iip_zone_from_bulletin(BULLETIN)[0] == [47.0, -52.0]

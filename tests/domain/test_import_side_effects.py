"""
Importing the package must not touch anything: a GUI or a library needs to import it freely.

Each check runs in a new interpreter, with an empty home and the network cut off, because the
test session has already imported these modules and replaced architeuthis.icebergs.
"""

import json
import os
import subprocess
import sys

import pytest

import architeuthis

REPOSITORY = os.path.dirname(os.path.dirname(architeuthis.__file__))

PRELUDE = """
import json
import logging
import socket
import sys


def no_network(*args, **kwargs):
    raise AssertionError("network access during import")


socket.socket.connect = no_network
socket.create_connection = no_network
socket.getaddrinfo = no_network

root_handlers = list(logging.getLogger().handlers)
"""


def run(code, tmp_path, **environment):
    home = tmp_path / "home"
    (home / "data").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()

    env = {key: value for key, value in os.environ.items() if key not in ("CDS_API_KEY", "CMEMS_USER", "CMEMS_PWD")}
    env |= {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PYTHONPATH": REPOSITORY,
        "PYTHONUTF8": "1",
        "MPLBACKEND": "Agg",
    } | environment

    done = subprocess.run(
        [sys.executable, "-c", PRELUDE + code],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert done.returncode == 0, done.stderr
    return home, work, json.loads(done.stdout.strip().splitlines()[-1])


CORE = """
import architeuthis.core

print(json.dumps({
    "icebergs_imported": "architeuthis.icebergs" in sys.modules,
    "handlers_added": len(logging.getLogger().handlers) - len(root_handlers),
    "dash_imported": "dash" in sys.modules,
}))
"""


def test_importing_core_needs_no_network_and_writes_nothing(tmp_path):
    home, work, result = run(CORE, tmp_path)

    assert result["icebergs_imported"] is False
    assert result["handlers_added"] == 0
    assert result["dash_imported"] is False
    assert not (home / ".cdsapirc").exists()
    assert not (home / "data" / "iip").exists()
    assert list(work.iterdir()) == []


def test_importing_icebergs_needs_no_network_and_writes_nothing(tmp_path):
    home, _, result = run(
        """
import architeuthis.icebergs

print(json.dumps({"cache": len(architeuthis.icebergs._cache)}))
""",
        tmp_path,
    )

    assert result["cache"] == 0
    assert not (home / "data" / "iip").exists()


def test_importing_plots_leaves_the_global_style_alone(tmp_path):
    _, _, result = run(
        """
import matplotlib as mpl

before = {key: str(value) for key, value in mpl.rcParams.items()}

import architeuthis.toolbox.plot_utils

after = {key: str(value) for key, value in mpl.rcParams.items()}
print(json.dumps({"changed": sorted(key for key in before if before[key] != after[key])}))
""",
        tmp_path,
    )

    assert result["changed"] == []


def test_reports_need_neither_dash_nor_the_figures(tmp_path):
    _, _, result = run(
        """
import architeuthis.report

print(json.dumps({"loaded": sorted(set(sys.modules) & {"dash", "dash_leaflet", "matplotlib.pyplot"})}))
""",
        tmp_path,
    )

    assert "dash" not in result["loaded"]
    assert "dash_leaflet" not in result["loaded"]


def test_reading_the_scripts_zones_downloads_the_iceberg_limit_only_then(tmp_path):
    home, _, result = run(
        """
import architeuthis.core
import requests


class Bulletin:
    text = "ICEBERG LIMIT ALONG TRACKLINE JOINING 47-00N 052-00W 45-30N 048-15W 44-00N 045-00W TO THE COAST."

    def raise_for_status(self):
        pass


calls = []


def get(url, **kwargs):
    calls.append(url)
    return Bulletin()


requests.get = get
before = len(calls)
from architeuthis.exclusion import iceberg_zone
zone = iceberg_zone()
again = iceberg_zone()
print(json.dumps({"before": before, "after": len(calls), "points": len(zone), "name": zone.name}))
""",
        tmp_path,
    )

    assert result["before"] == 0
    assert result["after"] == 1
    assert result["points"] > 0
    assert result["name"] == "iceberg_limit"
    assert (home / "data" / "iip" / "IcebergBulletin.txt").exists()


@pytest.mark.parametrize("key, written", [("my-key", True), (None, False)])
def test_cdsapirc_is_written_only_before_a_download_and_only_with_a_key(tmp_path, key, written):
    environment = {} if key is None else {"CDS_API_KEY": key}

    home, _, result = run(
        """
from architeuthis import common

import os

before = os.path.exists(common.file_path)
common.ensure_cdsapirc()
print(json.dumps({"before": before, "after": os.path.exists(common.file_path)}))
""",
        tmp_path,
        **environment,
    )

    assert result["before"] is False
    assert result["after"] is written
    if written:
        assert "my-key" in (home / ".cdsapirc").read_text()

"""
The real ui.py, run without starting its server: the latest routes and the exclusion zones must
reach the page, and each layer must be hideable.

Everything that ui.py downloads is replaced: forecasts, the NOAA chart and the coastline file
that it reads from its working directory, which is a temporary folder here because ui.py writes
into assets/.
"""

import io
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from PIL import Image

import architeuthis
from architeuthis.common import _HOME
from architeuthis.exclusion import ExclusionZone, ExclusionZoneLibrary
from architeuthis.forecast import DeterministicHerbieForecast
from architeuthis.report import ROUTES_DIRECTORY, ReportCollection

UI_SOURCE = os.path.join(os.path.dirname(architeuthis.__file__), "ui.py")

START = pd.Timestamp("now").floor("1d")
TIME = (pd.date_range(START, periods=9, freq="6h") - pd.Timestamp("1970-01-01")).total_seconds().to_numpy()
LATITUDE = np.arange(30.0, 61.0, 2.0)
LONGITUDE = np.arange(-70.0, 6.0, 2.0)

VARIABLES = {
    ("ifs", "oper"): {"u10": 5.0, "v10": 2.0, "msl": 101000.0},
    ("gfs", "pgrb2.0p25"): {"u10": 4.0, "v10": 3.0, "prmsl": 101500.0},
    ("ifs", "wave"): {"swh": 2.0, "mwd": 250.0},
    ("gfs_wave", "global.0p25"): {"swh": 3.0, "dirpw": 240.0},
}


def load_forecast(self):
    # Fields vary with latitude: ui.py cannot draw contours of a constant field.
    variation = np.broadcast_to(
        (LATITUDE - LATITUDE.mean())[None, :, None] / np.ptp(LATITUDE),
        (TIME.size, LATITUDE.size, LONGITUDE.size),
    )
    self.data = xr.Dataset(
        {
            key: (("valid_time", "latitude", "longitude"), value * (1.0 + 0.01 * variation))
            for key, value in VARIABLES[(self.model, self.product)].items()
        },
        coords={
            "valid_time": TIME,
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "time": np.datetime64(START),
        },
    )


class Chart:
    """The NOAA chart that ui.py downloads at each start."""

    def __init__(self):
        buffer = io.BytesIO()
        Image.new("RGB", (4, 4), "white").save(buffer, format="GIF")
        self.content = buffer.getvalue()

    def raise_for_status(self):
        pass


def walk(component):
    """Every component of a serialized Dash layout."""
    if isinstance(component, list):
        for item in component:
            yield from walk(item)
    elif isinstance(component, dict) and "props" in component:
        yield component
        yield from walk(component["props"].get("children"))


@pytest.fixture(scope="module")
def tagged_reports(routing, baseline_report, optimized_report):
    return ReportCollection([baseline_report, optimized_report])


@pytest.fixture(scope="module")
def user_zone():
    return ExclusionZone(
        "safety",
        [[45.0, -30.0], [45.0, -25.0], [40.0, -25.0]],
        label="Safety margin",
        color="#00ff00",
        visible=False,
        verbose=False,
    )


@pytest.fixture(scope="module")
def ui(tmp_path_factory, tagged_reports, user_zone):
    work = tmp_path_factory.mktemp("ui")
    (work / "assets").mkdir()
    (work / "assets" / "countries-coastline-1km.geo.json").write_text(
        json.dumps({"type": "FeatureCollection", "features": []})
    )

    routes = Path(ROUTES_DIRECTORY)
    library = ExclusionZoneLibrary(verbose=False)
    older = ReportCollection([tagged_reports[0]]).save(str(routes / "z_older.json"))
    os.utime(older, (1000, 1000))
    latest = tagged_reports.save(str(routes / "a_latest.json"))
    zone_path = library.save(user_zone)

    previous = os.getcwd()
    os.chdir(work)
    # Another backend than the Agg of the test session, to see which one ui.py selects.
    plt.switch_backend("svg")
    try:
        with patch.object(DeterministicHerbieForecast, "load_data", load_forecast), patch(
            "requests.get", lambda *args, **kwargs: Chart()
        ):
            namespace = runpy.run_path(UI_SOURCE, run_name="ui_under_test")
        yield namespace
    finally:
        plt.switch_backend("agg")
        os.chdir(previous)
        for path in (older, latest, zone_path):
            os.remove(path)


@pytest.fixture(scope="module")
def client(ui):
    return ui["server"].test_client()


@pytest.fixture(scope="module")
def layout(client):
    response = client.get("/_dash-layout")
    assert response.status_code == 200
    return response.get_json()


@pytest.fixture(scope="module")
def overlays(layout):
    found = [component for component in walk(layout) if component["type"] == "Overlay"]
    return {component["props"].get("name"): component["props"] for component in found}


def test_ui_can_be_launched_as_a_script(tmp_path):
    # Python then puts architeuthis/ first on the path, where architeuthis/numpy hides numpy.
    # The refused proxy stops the script at its first download, after all its imports.
    environment = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "NO_PROXY", "no_proxy")}
    environment |= {
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "PYTHONUTF8": "1",
        "MPLBACKEND": "Agg",
    }

    done = subprocess.run(
        [sys.executable, UI_SOURCE],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )

    assert "No module named" not in done.stderr
    assert "remove_white_pixels" in done.stderr


def test_ui_draws_without_a_gui_backend(ui):
    # A GUI backend, the default in a terminal, kills the process at the first raster or contour.
    assert ui["matplotlib"].get_backend().lower() == "agg"


def test_ui_stores_routes_under_the_data_folder(ui):
    assert ui["ROUTES_DIR"] == Path(_HOME, "routes")


def test_ui_reads_the_most_recently_modified_file(ui):
    assert ui["latest_file"].name == "a_latest.json"
    assert len(ui["reports"]) == 2


def test_latest_routes_are_on_the_page(overlays, tagged_reports):
    for report in tagged_reports:
        name = f"{report['model']} {report['init_fac']} {report['vessel'][3:]} {report['fuel']:.1f} m{report['member']}"
        assert name in overlays


def test_only_optimized_routes_are_shown_at_first(overlays, tagged_reports):
    baseline, optimized = tagged_reports
    assert overlays[f"ifs 0.0 45 {baseline['fuel']:.1f} m0"]["checked"] is False
    assert overlays[f"gfs 0.0 60 {optimized['fuel']:.1f} m0"]["checked"] is True


def test_routes_are_drawn_where_the_report_says(overlays, tagged_reports):
    optimized = tagged_reports[1]
    overlay = overlays[f"gfs 0.0 60 {optimized['fuel']:.1f} m0"]

    features = overlay["children"]["props"]["data"]["features"]
    line = next(feature for feature in features if feature["properties"].get("kind") == "route")
    assert line["geometry"]["coordinates"][0] == pytest.approx([optimized["lon"][0], optimized["lat"][0]])


@pytest.mark.parametrize("label", ["North America", "Brittany", "Iceberg limit"])
def test_default_zones_can_be_hidden_under_their_label(overlays, label):
    assert overlays[label]["checked"] is True


def test_zones_of_the_library_are_on_the_page(overlays):
    assert overlays["Safety margin"]["checked"] is False


def test_zone_labels_are_written_on_the_map(layout):
    labels = {
        component["props"]["children"]
        for component in walk(layout)
        if component["type"] == "Tooltip" and component["props"].get("className") == "exclusion-zone-label"
    }

    assert labels == {"North America", "Brittany", "Iceberg limit", "Safety margin"}


def test_zone_lines_follow_their_outline(ui, layout):
    lines = {component["props"]["id"]: component["props"] for component in walk(layout) if component["type"] == "Polyline"}

    assert lines["exclusion-zone-brittany"]["positions"] == next(
        zone.outline for zone in ui["exclusion_zones"] if zone.name == "brittany"
    )
    assert lines["exclusion-zone-safety"]["color"] == "#00ff00"


def test_every_layer_is_in_the_layers_control(layout):
    control = next(component for component in walk(layout) if component["type"] == "LayersControl")
    names = {child["props"].get("name") for child in control["props"]["children"]}

    assert {"North America", "Brittany", "Iceberg limit", "Safety margin"} <= names


def test_page_and_callbacks_are_served(client, ui):
    assert client.get("/").status_code == 200
    response = client.get("/_dash-dependencies")
    assert response.status_code == 200
    assert len(response.get_json()) > 0


@pytest.mark.parametrize("model", ["ifs", "gfs"])
def test_forecast_routes_answer_for_each_model(client, model):
    raster = client.get(f"/raster.png?var=si10&time=0&member=1&model={model}")
    arrows = client.get(f"/wind_arrows.geojson?time=0&qvar=wdir10&density=2&member=1&model={model}")
    contours = client.get(f"/contour_field.geojson?var=msl&time=0&member=1&model={model}")

    assert raster.status_code == 200
    assert raster.data.startswith(b"\x89PNG")
    assert arrows.get_json()["type"] == "FeatureCollection"
    assert contours.get_json()["type"] == "FeatureCollection"


def test_style_of_the_labels_is_in_the_assets():
    style = os.path.join(os.path.dirname(architeuthis.__file__), "assets", "style.css")

    with open(style, encoding="utf-8") as file:
        assert ".exclusion-zone-label" in file.read()

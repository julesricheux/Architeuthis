"""
The real ui.py, run without starting its server: the latest routes, the forecasts and the
exclusion zones must reach the preview, and the download must hold the analyst's choices.

Everything that ui.py downloads is replaced: forecasts, the NOAA chart and MapLibre, cached in a
temporary folder. ui.py runs from a temporary folder too, so that nothing it might write lands
in the checkout.
"""

import io
import json
import os
import re
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
from dash import no_update
from PIL import Image

import architeuthis
from architeuthis.dux import share
from architeuthis.common import _HOME
from architeuthis.exclusion import ExclusionZone, ExclusionZoneLibrary
from architeuthis.forecast import DeterministicHerbieForecast
from architeuthis.report import ROUTES_DIRECTORY, ReportCollection

UI_SOURCE = os.path.join(os.path.dirname(architeuthis.__file__), "dux", "ui.py")

START = pd.Timestamp("now").floor("1d")
TIME = (pd.date_range(START, periods=9, freq="6h") - pd.Timestamp("1970-01-01")).total_seconds().to_numpy()
LATITUDE = np.arange(30.0, 61.0, 2.0)
LONGITUDE = np.arange(-70.0, 6.0, 2.0)

VARIABLES = {
    ("ifs", "oper"): {"u10": 5.0, "v10": 2.0, "msl": 101000.0, "fg10": 9.0, "mucape": 300.0, "ptype": 1.0},
    ("gfs", "pgrb2.0p25"): {"u10": 4.0, "v10": 3.0, "prmsl": 101500.0, "gust": 8.0, "cape": 250.0},
    ("ifs", "wave"): {"swh": 2.0, "mwd": 250.0, "mwp": 8.0},
    ("gfs_wave", "global.0p25"): {"swh": 3.0, "dirpw": 240.0, "perpw": 9.0},
}
IFS_LAYERS = ["wind", "gust", "waves", "pressure", "cape", "ptype", "period", "slope"]
GFS_LAYERS = ["wind", "gust", "waves", "pressure", "cape", "period", "slope"]


def load_forecast(self):
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


CHART_WRITTEN = "Fri, 20 Nov 2026 08:15:49 GMT"


class Answer:
    """What the servers send: the NOAA chart, or MapLibre."""

    def __init__(self, url):
        self.headers = {}
        if url.endswith(".js"):
            self.content = b"window.maplibregl = {}; // fake maplibregl"
        elif url.endswith(".css"):
            self.content = b".maplibregl-map { color: red; }"
        else:
            buffer = io.BytesIO()
            Image.new("RGB", (4, 4), "white").save(buffer, format="GIF")
            self.content = buffer.getvalue()
            self.headers = {"Last-Modified": CHART_WRITTEN}

    def raise_for_status(self):
        pass


def walk(component):
    """Every component of a serialized Dash layout."""
    if isinstance(component, list):
        for item in component:
            yield from walk(item)
    elif isinstance(component, dict) and "props" in component:
        yield component
        for value in component["props"].values():
            yield from walk(value)


def scene_of(page):
    """The scene embedded in a viewer page."""
    match = re.search(r'<script type="application/json" id="architeuthis-scene">(.*?)</script>', page, flags=re.DOTALL)
    return json.loads(match.group(1))


@pytest.fixture(scope="module")
def tagged_reports(routing, baseline_report, optimized_report):
    return ReportCollection([baseline_report, optimized_report])


@pytest.fixture(scope="module")
def user_zone():
    # Shown at first in the library, hidden at first by ui.py.
    return ExclusionZone(
        "safety",
        [[45.0, -30.0], [45.0, -25.0], [40.0, -25.0]],
        label="Safety margin",
        color="#00ff00",
        visible=True,
        verbose=False,
    )


@pytest.fixture(scope="module")
def ui(tmp_path_factory, tagged_reports, user_zone):
    work = tmp_path_factory.mktemp("ui")

    routes = Path(ROUTES_DIRECTORY)
    library = ExclusionZoneLibrary(verbose=False)
    older = ReportCollection([tagged_reports[0]]).save(str(routes / "z_older.json"), verbose=False)
    os.utime(older, (1000, 1000))
    latest = tagged_reports.save(str(routes / "a_latest.json"), verbose=False)
    zone_path = library.save(user_zone)

    previous = os.getcwd()
    os.chdir(work)
    # Another backend than the Agg of the test session, to see which one ui.py selects.
    plt.switch_backend("svg")
    try:
        with patch.object(DeterministicHerbieForecast, "load_data", load_forecast), patch(
            "requests.get", lambda url, *args, **kwargs: Answer(url)
        ), patch.object(share, "VIEWER_DIRECTORY", str(work / "viewer")):
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
    # Components with a pattern-matching identifier, a dict, are found through their parents.
    return {
        component["props"]["id"]: component["props"]
        for component in walk(response.get_json())
        if isinstance(component["props"].get("id"), str)
    }


@pytest.fixture(scope="module")
def scene(client):
    response = client.get("/viewer?file=a_latest.json&member=1")
    assert response.status_code == 200
    return scene_of(response.get_data(as_text=True))


def test_ui_can_be_launched_as_a_script(tmp_path):
    # Python then puts architeuthis/dux/ first on the path, and ui.py must import from the
    # repository root, never from architeuthis/, where architeuthis/numpy hides numpy.
    # The refused proxy stops the script at its first forecast, after all its imports.
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
    assert "NOAA surface analysis unavailable" in done.stdout
    assert "load_data" in done.stderr


def test_ui_draws_without_a_gui_backend(ui):
    # A GUI backend, the default in a terminal, kills the process from a server thread.
    assert ui["matplotlib"].get_backend().lower() == "agg"


def test_ui_stores_routes_under_the_data_folder(ui):
    assert ui["ROUTES_DIR"] == Path(_HOME, "routes")


def test_ui_reads_the_most_recently_modified_file(ui):
    assert ui["latest_file"].name == "a_latest.json"
    assert len(ui["reports"]) == 2


def test_ui_writes_nothing_where_it_runs(ui):
    assert sorted(path.name for path in Path.cwd().iterdir()) == ["viewer"]


def test_maplibre_is_put_in_the_pages_once_downloaded(ui, client):
    page = client.get("/viewer?file=a_latest.json").get_data(as_text=True)

    assert ui["LIBRARY"] == "inline"
    assert "fake maplibregl" in page
    assert "unpkg.com" not in page


# ----------------------------------------------------------------------
# Choices of the analyst
# ----------------------------------------------------------------------


def test_report_files_are_listed_the_latest_first(layout):
    select = layout["file-select"]

    assert select["value"] == "a_latest.json"
    assert [option["value"] for option in select["data"]] == ["a_latest.json", "z_older.json"]


def test_only_optimized_routes_are_chosen_at_first(layout):
    checkboxes = [component for component in walk(layout["routes-options"]["children"]) if component["type"] == "Checkbox"]

    assert layout["routes-select"]["value"] == ["r1"]
    assert [checkbox["props"]["value"] for checkbox in checkboxes] == ["r0", "r1"]


def test_each_route_takes_a_description(layout):
    boxes = [component["props"] for component in walk(layout["routes-options"]["children"]) if component["type"] == "Textarea"]

    assert [box["id"] for box in boxes] == [{"type": "route-description", "index": index} for index in (0, 1)]
    assert [box["value"] for box in boxes] == ["", ""]


def test_each_route_takes_a_name_its_label_at_first(layout, tagged_reports):
    boxes = [component["props"] for component in walk(layout["routes-options"]["children"]) if component["type"] == "TextInput"]

    assert [box["id"] for box in boxes] == [{"type": "route-name", "index": index} for index in (0, 1)]
    assert [box["value"] for box in boxes] == share.route_labels(tagged_reports)


def test_the_map_opens_dark_with_no_comment(layout):
    assert layout["theme-switch"]["checked"] is False
    assert layout["provider"]["forceColorScheme"] == "dark"
    assert layout["route-comments"]["data"] == {}


def test_the_page_follows_the_theme_of_the_map(ui):
    assert ui["color_scheme"](True) == "light"
    assert ui["color_scheme"](False) == "dark"


def test_routes_are_offered_under_their_label(layout, tagged_reports):
    labels = [
        component["props"]["children"]
        for component in walk(layout["routes-options"]["children"])
        if component["type"] == "Text"
    ]

    assert labels == share.route_labels(tagged_reports)


def test_tooltips_offer_every_variable_and_show_the_defaults(layout, tagged_reports):
    hover = layout["hover-select"]
    offered = [option["value"] for option in hover["data"]]

    assert hover["value"] == share.default_variables(tagged_reports)
    assert offered[: len(hover["value"])] == hover["value"]
    assert set(offered) == set(share.segment_variables(tagged_reports[0])) | set(share.segment_variables(tagged_reports[1]))


def test_every_model_is_offered(layout):
    assert layout["sources-select"]["value"] == ["ifs", "gfs"]


def test_members_are_hidden_for_deterministic_forecasts(ui, layout):
    assert ui["PRODUCT"] == "oper"
    assert layout["member-select"]["value"] == ui["DEFAULT_MEMBER"]


def test_another_file_comes_with_its_own_defaults(ui):
    options, routes, data, hover, title, comments = ui["select_file"]("z_older.json")

    # Its only route is a baseline: with no optimized route, all are chosen.
    assert routes == ["r0"]
    assert len(options) == 1
    assert hover == share.default_variables(ui["load_reports"]("z_older.json"))
    assert title.startswith("Routes departing ")
    # The comments were on the routes of the other file.
    assert comments == {}


def test_the_preview_follows_the_file_and_member(ui):
    assert ui["show_file"]("z_older.json", 3) == "/viewer?file=z_older.json&member=3"
    assert ui["show_file"]("a b.json", None) == f"/viewer?file=a%20b.json&member={ui['DEFAULT_MEMBER']}"


def test_files_outside_the_routes_folder_are_refused(ui):
    with pytest.raises(FileNotFoundError):
        ui["load_reports"]("../exclusion_zones/safety.json")


# ----------------------------------------------------------------------
# Preview
# ----------------------------------------------------------------------


def test_the_preview_shows_every_route_with_the_defaults_chosen(scene, tagged_reports):
    assert [route["id"] for route in scene["routes"]] == ["r0", "r1"]
    assert scene["settings"]["routes"] == ["r1"]
    assert scene["settings"]["hover"] == share.default_variables(tagged_reports)
    assert scene["settings"]["overlays"] is None
    assert scene["title"].startswith("Routes departing ")


def test_the_preview_holds_both_models(scene):
    assert [source["id"] for source in scene["sources"]] == ["ifs", "gfs"]
    assert [source["layers"] for source in scene["sources"]] == [IFS_LAYERS, GFS_LAYERS]
    for source in scene["sources"]:
        assert len(source["times"]) == len(TIME)


def test_every_field_of_the_forecasts_is_offered_and_ticked(layout):
    offered = [component["props"] for component in walk(layout["fields-select"]["children"]) if component["type"] == "Checkbox"]

    assert [box["value"] for box in offered] == ["wind", "gust", "waves", "pressure", "cape", "ptype", "period", "slope"]
    assert [box["label"] for box in offered][-2:] == ["Wave period", "Wave slope"]
    assert layout["fields-select"]["value"] == [box["value"] for box in offered]


def test_iceberg_limit_and_library_zones_are_on_the_globe(scene, user_zone):
    zones = {zone["label"]: zone for zone in scene["zones"]}

    assert zones["Safety margin"]["color"] == "#00ff00"
    assert zones["Safety margin"]["outline"] == [[lon, lat] for lat, lon in user_zone.outline]


def test_only_the_iceberg_limit_is_shown_at_first(ui, scene, user_zone):
    zones = {zone["label"]: zone for zone in scene["zones"]}

    assert zones["Iceberg limit"]["visible"] is True
    assert zones["Safety margin"]["visible"] is False
    # The zone of the library is left as it is.
    assert user_zone.visible is True


def test_the_downloaded_fields_are_options_translated_for_each_model(ui):
    regex = ui["grib_regex"]

    assert ui["ATMOS"]["ifs"].regex == regex("ifs", ui["ATMOSPHERE_FIELDS"])
    assert ui["WAVE"]["gfs"].regex == regex("gfs_wave", ui["WAVE_FIELDS"])
    assert regex("ifs", ["wind", "gust"]) == ":10[uv]:|:10fg:"
    assert re.search(regex("gfs", ["wind"]), ":UGRD:10 m above ground:6 hour fcst")
    assert not re.search(regex("gfs", ["wind"]), ":UGRD:10 mb:6 hour fcst")

    # GFS has no precipitation type: it is left out with a warning.
    printed = []
    with patch.dict(ui["grib_regex"].__globals__, status=printed.append):
        assert regex("gfs", ["wind", "precipitation_type"]) == regex("gfs", ["wind"])
    assert printed[0].startswith("⚠️ gfs has no precipitation_type")


def test_the_noaa_chart_can_be_drawn_over_the_globe(scene, layout):
    (overlay,) = scene["overlays"]

    assert overlay["visible"] is False
    assert layout["noaa-check"]["checked"] is False
    assert overlay["label"] == "NOAA surface analysis"
    assert overlay["url"].startswith("data:image/png;base64,")
    assert (overlay["north"], overlay["west"], overlay["south"], overlay["east"]) == (65.15, -100.0, 14.4, 10.0)


def test_the_noaa_chart_is_shown_at_its_valid_time(ui, scene):
    (overlay,) = scene["overlays"]

    # Written at 08:15 UTC: the analysis of 06 UTC.
    assert overlay["time"] == pd.Timestamp("2026-11-20 06:00", tz="UTC").timestamp()
    assert ui["noaa_label"]() == "NOAA surface analysis, Fri 20 06 UTC"


@pytest.mark.parametrize(
    "written, valid",
    [
        ("Fri, 20 Nov 2026 08:15:49 GMT", "2026-11-20 06:00"),
        ("Fri, 20 Nov 2026 07:29:00 GMT", "2026-11-20 00:00"),
        ("Fri, 20 Nov 2026 01:00:00 GMT", "2026-11-19 18:00"),
        ("Fri, 20 Nov 2026 09:15:49 +0100", "2026-11-20 06:00"),
    ],
)
def test_the_analysis_time_is_the_synoptic_hour_before_the_file(ui, written, valid):
    assert ui["analysis_time"](written) == pd.Timestamp(valid, tz="UTC")


@pytest.mark.parametrize("written", [None, "", "yesterday"])
def test_an_unknown_file_date_gives_no_analysis_time(ui, written):
    assert ui["analysis_time"](written) is None


@pytest.mark.parametrize(
    "query",
    ["file=nothing.json", "file=../exclusion_zones/safety.json", "file=a_latest.json&member=first"],
)
def test_unknown_files_are_not_found(client, query):
    assert client.get(f"/viewer?{query}").status_code == 404


def test_page_and_callbacks_are_served(client):
    page = client.get("/")
    response = client.get("/_dash-dependencies")

    assert page.status_code == 200
    assert response.status_code == 200
    assert len(response.get_json()) > 0
    # The bridge that sends the choices to the preview.
    assert "architeuthis:settings" in page.get_data(as_text=True)


def test_the_viewer_answers_the_bridge():
    with open(share._TEMPLATES / "viewer.js", encoding="utf-8") as file:
        script = file.read()

    assert '"architeuthis:ready"' in script
    assert '"architeuthis:settings"' in script
    # And takes the names of the routes, and sends back the comments and the theme, which the
    # bridge receives.
    assert "settings.labels" in script
    assert '"architeuthis:comments"' in script
    assert '"architeuthis:theme"' in script
    assert '"architeuthis:overlays"' in script


# ----------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------


def test_nothing_is_downloaded_before_a_click(ui):
    assert ui["download"](None, "a_latest.json", ["r1"], [], ["ifs"], "", "", 1, False) == (no_update, no_update)


def test_the_download_holds_the_choices(ui, tagged_reports):
    data, info = ui["download"](1, "a_latest.json", ["r0"], ["twa", "sog"], ["gfs"], "Crossing 12", "Keep north", 1, True)
    scene = scene_of(data["content"])

    assert data["filename"] == "Crossing_12.html"
    assert data["type"] == "text/html"
    assert [route["id"] for route in scene["routes"]] == ["r0"]
    assert scene["routes"][0]["label"] == share.route_labels(tagged_reports)[0]
    assert list(scene["variables"]) == ["twa", "sog"]
    assert [source["label"] for source in scene["sources"]] == ["GFS"]
    assert [(overlay["label"], overlay["visible"]) for overlay in scene["overlays"]] == [("NOAA surface analysis", True)]
    assert {zone["label"] for zone in scene["zones"]} == {"Iceberg limit", "Safety margin"}
    assert (scene["title"], scene["note"]) == ("Crossing 12", "Keep north")
    assert scene["settings"] == {"routes": None, "sources": None, "overlays": None, "hover": None, "fields": None, "theme": "dark"}
    assert "fake maplibregl" in data["content"]
    assert info.startswith("Crossing_12.html: 1 routes, ")


def test_the_download_holds_the_descriptions_comments_and_theme(ui):
    data, _ = ui["download"](
        1,
        "a_latest.json",
        ["r0", "r1"],
        [],
        [],
        "Crossing",
        "",
        1,
        False,
        ["South of the low", ""],
        [{"type": "route-description", "index": 0}, {"type": "route-description", "index": 1}],
        {"r1": {"2": "Gybe here", "5": ""}},
        True,
    )
    first, second = scene_of(data["content"])["routes"]

    assert (first["description"], first["comments"]) == ("South of the low", [])
    assert (second["description"], second["comments"]) == ("", [{"k": 2, "text": "Gybe here"}])
    assert scene_of(data["content"])["settings"]["theme"] == "light"


def test_the_download_holds_the_chosen_fields(ui):
    args = (1, "a_latest.json", ["r0"], [], ["ifs", "gfs"], "Crossing", "", 1, False, None, None, None, False, None, None)
    data, _ = ui["download"](*args, ["period", "ptype"])
    ifs, gfs = scene_of(data["content"])["sources"]

    assert ifs["layers"] == ["ptype", "period"]
    assert gfs["layers"] == ["period"]
    # The wave arrows come with the period.
    assert set(gfs["quantities"]) == {"swh", "wave_x", "wave_y", "period"}
    assert [source["layers"] for source in scene_of(ui["download"](*args)[0]["content"])["sources"]] == [IFS_LAYERS, GFS_LAYERS]


def test_the_download_holds_the_names_of_the_routes(ui, tagged_reports):
    ids = [{"type": "route-name", "index": index} for index in (0, 1)]
    data, _ = ui["download"](1, "a_latest.json", ["r0", "r1"], [], [], "Crossing", "", 1, False, None, None, None, False, ["  ", "North option"], ids)
    first, second = scene_of(data["content"])["routes"]

    assert first["label"] == share.route_labels(tagged_reports)[0]
    assert second["label"] == "North option"


def test_route_names_keep_the_label_of_unnamed_routes(ui, tagged_reports):
    labels = share.route_labels(tagged_reports)

    assert ui["route_names"](tagged_reports) == labels
    assert ui["route_names"](tagged_reports, ["South", "", "Lost"], [{"index": 1}, {"index": 0}, {"index": 9}]) == [labels[0], "South"]


def test_route_notes_gather_descriptions_and_comments_by_report(ui):
    notes = ui["route_notes"](
        ["A", "B"],
        [{"type": "route-description", "index": 3}, {"type": "route-description", "index": 0}],
        {"r3": {"1": "x"}, "r7": {}},
    )

    assert notes == {3: {"description": "A", "points": {1: "x"}}, 0: {"description": "B"}, 7: {"points": {}}}
    assert ui["route_notes"]() == {}


def test_a_download_without_title_is_named_after_the_departure(ui):
    data, _ = ui["download"](1, "a_latest.json", [], [], [], None, None, None, False)
    scene = scene_of(data["content"])

    assert scene["routes"] == [] and scene["sources"] == []
    # The chart is always shared, hidden when the box is not ticked.
    assert [(overlay["label"], overlay["visible"]) for overlay in scene["overlays"]] == [("NOAA surface analysis", False)]
    assert scene["title"].startswith("Routes departing ")
    assert data["filename"].startswith("Routes_departing_")


def test_quick_selection_of_routes(client):
    dependencies = client.get("/_dash-dependencies").get_json()
    callback = next(
        dependency
        for dependency in dependencies
        if dependency["output"].startswith("routes-select.value@")
    )

    def press(button):
        response = client.post(
            "/_dash-update-component",
            json={
                "output": callback["output"],
                "outputs": {"id": "routes-select", "property": callback["output"].split(".", 1)[1]},
                "inputs": [
                    {"id": name, "property": "n_clicks", "value": 1 if name == button else None}
                    for name in ("routes-optimized", "routes-all", "routes-none")
                ],
                "changedPropIds": [f"{button}.n_clicks"],
                "state": [{"id": "file-select", "property": "value", "value": "a_latest.json"}],
            },
        )
        assert response.status_code == 200
        return next(iter(response.get_json()["response"].values()))["value"]

    assert press("routes-all") == ["r0", "r1"]
    assert press("routes-none") == []
    assert press("routes-optimized") == ["r1"]


def test_style_of_the_labels_is_in_the_assets():
    style = os.path.join(os.path.dirname(architeuthis.__file__), "dux", "assets", "style.css")

    with open(style, encoding="utf-8") as file:
        assert ".exclusion-zone-label" in file.read()

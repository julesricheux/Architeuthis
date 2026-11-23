"""
The share file: the scene of routes, forecasts and zones, and the HTML page holding it.

Everything stays offline: MapLibre is either a fake file in a temporary cache or
loaded from its CDN address, never downloaded.
"""

import base64
import copy
import io
import json
import re

import numpy as np
import pandas as pd
import pytest
import requests
import xarray as xr
from PIL import Image

from architeuthis.dux import share
from architeuthis.common import set_status_sink
from architeuthis.exclusion import ExclusionZone
from architeuthis.report import ReportCollection

HOUR = 3600.0
KNOTS = 1.0 / 0.514444

# The routes of the fixtures go from 48N 35W to 50N 15W in 60 h.
TIME = np.arange(-12.0, 85.0, 3.0) * HOUR
LATITUDE = np.arange(20.0, 75.01, 0.25)
LONGITUDE = np.arange(-60.0, 10.01, 0.25)


def padded(times):
    """Times with the two fake final steps of Herbie and Copernicus forecasts."""
    return np.append(times, [times[-1] + 1e6, times[-1] + 1e7])


def forecast_dataset(**overrides):
    """A forecast whose wind and pressure vary in time and space, with waves missing on a box."""
    time, lat, lon = np.meshgrid(TIME / HOUR, LATITUDE, LONGITUDE, indexing="ij")
    fields = {
        "u10": 5.0 + 0.05 * time + 0.1 * (lat - 45.0),
        "v10": -3.0 + 0.02 * (lon + 30.0),
        "msl": 101000.0 + 50.0 * (lat - 45.0) + 5.0 * time,
        "swh": 1.0 + 0.02 * time + 0.0 * lat,
        "mwd": 250.0 + 0.0 * time,
    }
    fields["swh"][:, (LATITUDE > 60.0), :] = np.nan
    fields["mwd"][:, (LATITUDE > 60.0), :] = np.nan
    fields.update(overrides)
    zeros = np.zeros((2, LATITUDE.size, LONGITUDE.size))
    return xr.Dataset(
        {name: (("valid_time", "latitude", "longitude"), np.concatenate([value, zeros])) for name, value in fields.items()},
        coords={"valid_time": padded(TIME), "latitude": LATITUDE, "longitude": LONGITUDE},
    )


def frame_values(source, quantity, step):
    """A quantity of a frame read back from its PNG, NaN where missing."""
    pack = next(pack for pack in source["packs"] if quantity in pack["quantities"])
    channel = pack["quantities"].index(quantity)
    png = base64.b64decode(pack["frames"][step].split(",", 1)[1])
    pixels = np.asarray(Image.open(io.BytesIO(png)))[..., channel].astype(float)
    info = source["quantities"][quantity]
    values = info["offset"] + info["scale"] * pixels
    values[pixels == share.NO_DATA] = np.nan
    return values


def grid_coordinates(source):
    grid = source["grid"]
    latitude = grid["lat0"] + grid["dlat"] * np.arange(grid["nlat"])
    longitude = grid["lon0"] + grid["dlon"] * np.arange(grid["nlon"])
    return latitude, longitude


def scene_of(page):
    """The scene embedded in a viewer page."""
    match = re.search(r'<script type="application/json" id="architeuthis-scene">(.*?)</script>', page, flags=re.DOTALL)
    return json.loads(match.group(1))


@pytest.fixture(scope="module")
def reports(baseline_report, optimized_report):
    return ReportCollection([baseline_report, optimized_report])


@pytest.fixture(scope="module")
def dataset():
    return forecast_dataset()


@pytest.fixture(scope="module")
def scene(reports, dataset):
    return share.build_scene(reports, forecasts={"IFS": dataset}, title="Test", note="Keep north")


@pytest.fixture
def messages():
    received = []
    set_status_sink(received.append)
    yield received
    set_status_sink(None)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """An empty MapLibre cache that the tests may fill."""
    folder = tmp_path / "viewer"
    monkeypatch.setattr(share, "VIEWER_DIRECTORY", str(folder))
    return folder


def fill(cache):
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"maplibre-gl-{share.MAPLIBRE_VERSION}.js").write_text("window.maplibregl = {}; // fake maplibregl", encoding="utf-8")
    (cache / f"maplibre-gl-{share.MAPLIBRE_VERSION}.css").write_text(".maplibregl-map { color: red; }", encoding="utf-8")


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


def test_routes_are_named_after_their_tags(reports):
    assert share.route_labels(reports) == ["IFS eff45 (baseline)", "GFS eff60"]
    assert share.route_label({"model": "ifs", "vessel": "eff60", "member": 3, "init_fac": -0.5, "solve": 1}) == "IFS eff60 m3 init -0.5"
    assert share.route_label({}) == "route"


def test_repeated_labels_are_numbered(baseline_report):
    assert share.route_labels([baseline_report, baseline_report]) == ["IFS eff45 (baseline) #1", "IFS eff45 (baseline) #2"]


def test_a_route_keeps_its_index_colour_and_label_when_chosen(reports, dataset):
    scene = share.build_scene(reports, forecasts=None, routes=[1])

    (route,) = scene["routes"]
    assert route["id"] == "r1"
    assert route["color"] == share.ROUTE_COLORS[1]
    assert route["label"] == "GFS eff60"


def test_routes_hold_their_positions_and_schedule(scene, reports):
    route = scene["routes"][1]
    report = reports[1]

    assert route["lat"] == pytest.approx(np.ravel(report["lat"]), abs=1e-4)
    assert route["lon"] == pytest.approx(np.ravel(report["lon"]), abs=1e-4)
    assert route["tim"] == pytest.approx(np.ravel(report["tim"]), abs=1)
    assert len(route["ctim"]) == len(route["cog"]) == len(route["clat"])
    assert route["summary"]["fuel"] == pytest.approx(report["fuel"], abs=0.01)
    assert route["summary"]["solve"] == 1


def test_segment_variables_are_every_array_along_the_route(baseline_report):
    names = share.segment_variables(baseline_report)

    assert {"sog", "cog", "tws", "twa", "swh", "bhp", "max_bhp", "sails_contribution", "z"} <= set(names)
    assert not {"tim", "lat", "lon", "ctim", "clat", "clon", "pos", "cpos", "fuel", "model"} & set(names)


def test_the_topography_shows_its_worst_point_of_each_segment(baseline_report):
    # z is sampled at the interior nodes and 3 points between each two of them.
    count = np.ravel(baseline_report["ctim"]).size
    z = np.ravel(baseline_report["z"])
    values = share.segment_values(baseline_report, "z")

    assert z.size == 4 * (count - 2) + 1
    assert values.shape == (count,)
    assert values[0] == z[0] and values[-1] == z[-1]
    assert values[1] == z[0:5].max()
    assert values[count - 2] == z[-5:].max()


def test_node_and_resampled_entries_are_averaged_on_segments():
    report = {"ctim": [0.0, 1.0, 2.0], "nodes": [0.0, 2.0, 4.0, 10.0], "fine": np.arange(7.0), "odd": [1.0, 2.0]}

    assert share.segment_values(report, "nodes").tolist() == [1.0, 3.0, 7.0]
    assert share.segment_values(report, "fine").tolist() == [1.0, 3.0, 5.0]
    assert share.segment_values(report, "odd") is None
    assert share.segment_variables(report) == ["nodes", "fine"]


def test_unknown_variables_are_written_out():
    assert share.variable_info("air_temperature")["label"] == "Air temperature"
    assert share.variable_info("tws100") == {"label": "tws100", "unit": "", "digits": 2, "description": "tws100"}


def test_tooltips_show_the_default_variables_the_reports_have(scene, reports):
    expected = [name for name in share.DEFAULT_VARIABLES if name in share.segment_variables(reports[0])]

    assert list(scene["variables"]) == expected
    assert scene["variables"]["sog"] == {"label": "SOG", "unit": "kt", "digits": 1, "description": "Speed over ground"}


def test_only_the_chosen_variables_are_stored_in_their_order(reports):
    scene = share.build_scene(reports, variables=["twa", "sog"])

    assert list(scene["variables"]) == ["twa", "sog"]
    assert set(scene["routes"][0]["values"]) == {"twa", "sog"}
    assert scene["routes"][0]["values"]["sog"] == pytest.approx(np.ravel(reports[0]["sog"]), abs=0.01)


def test_a_variable_no_route_has_is_left_out_with_a_warning(reports, messages):
    scene = share.build_scene(reports, variables=["sog", "nothing"])

    assert list(scene["variables"]) == ["sog"]
    assert any("⚠️" in message and "nothing" in message for message in messages)


def test_missing_values_become_null_so_the_scene_is_strict_json(reports):
    report = copy.deepcopy(dict(reports[0]))
    report["sog"] = np.array(report["sog"], dtype=float)
    report["sog"][0] = np.nan

    scene = share.build_scene([report], variables=["sog"])

    assert scene["routes"][0]["values"]["sog"][0] is None
    json.dumps(scene, allow_nan=False)


def test_settings_default_to_showing_everything(scene):
    assert scene["settings"] == {"routes": None, "sources": None, "overlays": None, "hover": None, "fields": None}


def test_settings_of_the_analyst_are_kept(reports):
    scene = share.build_scene(reports, settings={"routes": ["r1"], "hover": ["sog"]})

    assert scene["settings"]["routes"] == ["r1"]
    assert scene["settings"]["hover"] == ["sog"]
    assert scene["settings"]["sources"] is None


# ----------------------------------------------------------------------
# Forecasts
# ----------------------------------------------------------------------


def test_forecast_layers_come_from_the_fields(scene):
    (source,) = scene["sources"]

    assert source["id"] == "ifs"
    assert source["label"] == "IFS"
    assert source["layers"] == ["wind", "waves", "pressure"]
    assert set(source["quantities"]) == {"wind_u", "wind_v", "pressure", "swh", "wave_x", "wave_y"}
    assert all(len(pack["frames"]) == len(source["times"]) for pack in source["packs"])
    assert all(len(pack["quantities"]) <= 3 for pack in source["packs"])


def test_fake_final_steps_are_dropped(dataset):
    scene = share.build_scene([], forecasts={"IFS": dataset})

    assert scene["sources"][0]["times"] == pytest.approx(TIME)


def test_frames_cover_the_routes_with_one_more_step_each_side(scene, reports):
    # The routes sail from 0 to 60 h, so 12 h of margin keeps -12 to 72 h,
    # and one more step 75 h (the forecast starts at -12 h).
    assert [float(np.min(report["tim"])) for report in reports] == [0.0, 0.0]
    assert [float(np.max(report["tim"])) for report in reports] == [60 * HOUR, 60 * HOUR]

    assert scene["sources"][0]["times"] == pytest.approx(np.arange(-12.0, 75.1, 3.0) * HOUR)


def test_frames_are_cropped_around_the_routes_and_thinned(scene, reports):
    latitude, longitude = grid_coordinates(scene["sources"][0])
    lat = np.concatenate([np.ravel(report["lat"]) for report in reports])
    lon = np.concatenate([np.ravel(report["lon"]) for report in reports])

    assert scene["sources"][0]["grid"]["dlat"] == pytest.approx(share.DEFAULT_RESOLUTION)
    assert latitude[0] >= lat.min() - share.DEFAULT_MARGIN - 1e-9
    assert latitude[-1] <= lat.max() + share.DEFAULT_MARGIN + 1e-9
    assert longitude[0] >= lon.min() - share.DEFAULT_MARGIN - 1e-9
    assert longitude[-1] <= lon.max() + share.DEFAULT_MARGIN + 1e-9


def test_frames_read_back_to_the_fields_in_their_units(scene):
    source = scene["sources"][0]
    latitude, longitude = grid_coordinates(source)
    step = 5
    hours = source["times"][step] / HOUR
    lat = latitude[:, None]

    wind = (5.0 + 0.05 * hours + 0.1 * (lat - 45.0)) * KNOTS + 0.0 * longitude
    pressure = (101000.0 + 50.0 * (lat - 45.0) + 5.0 * hours) / 100.0 + 0.0 * longitude

    assert frame_values(source, "wind_u", step) == pytest.approx(wind, abs=source["quantities"]["wind_u"]["scale"])
    assert frame_values(source, "pressure", step) == pytest.approx(pressure, abs=source["quantities"]["pressure"]["scale"])


def test_missing_wave_values_stay_missing(scene):
    source = scene["sources"][0]
    latitude, _ = grid_coordinates(source)
    swh = frame_values(source, "swh", 0)

    assert np.isnan(swh[latitude > 60.0]).all()
    assert np.isfinite(swh[latitude <= 60.0]).all()


def test_wave_directions_are_unit_vectors_to_where_waves_come_from(scene):
    source = scene["sources"][0]
    latitude, _ = grid_coordinates(source)
    sea = latitude <= 60.0
    x = frame_values(source, "wave_x", 0)[sea]
    y = frame_values(source, "wave_y", 0)[sea]

    assert np.degrees(np.arctan2(x, y)) % 360.0 == pytest.approx(250.0, abs=1.0)


def test_gfs_and_herbie_names_are_read(reports):
    data = forecast_dataset()
    speed = np.hypot(data["u10"], data["v10"])
    data["si10"] = speed
    data["wdir10"] = (np.degrees(np.arctan2(-data["u10"], -data["v10"])) + 360.0) % 360.0
    data = data.drop_vars(["u10", "v10"]).rename({"msl": "prmsl", "mwd": "dirpw"})

    source = share.build_scene(reports, forecasts={"GFS": data})["sources"][0]
    reference = share.build_scene(reports, forecasts={"IFS": forecast_dataset()})["sources"][0]

    assert source["layers"] == ["wind", "waves", "pressure"]
    assert frame_values(source, "wind_v", 3) == pytest.approx(frame_values(reference, "wind_v", 3), abs=0.2)


def test_a_list_of_forecasts_is_merged_on_the_first_grid(reports):
    full = forecast_dataset()
    atmosphere = full[["u10", "v10", "msl"]]
    wave = full[["swh", "mwd"]].isel(latitude=slice(None, None, 2), longitude=slice(None, None, 2))

    source = share.build_scene(reports, forecasts={"IFS": [atmosphere, wave]})["sources"][0]

    assert source["layers"] == ["wind", "waves", "pressure"]


def test_the_chosen_ensemble_member_is_shown(reports):
    members = xr.concat([forecast_dataset(), forecast_dataset() * 2.0], dim=xr.DataArray([0, 1], dims="number", name="number"))

    first = share.build_scene(reports, forecasts={"ENS": members})["sources"][0]
    second = share.build_scene(reports, forecasts={"ENS": members}, member=1)["sources"][0]

    assert frame_values(second, "wind_u", 2) == pytest.approx(2.0 * frame_values(first, "wind_u", 2), rel=0.02, abs=0.3)


def test_datetimes_and_lat_lon_names_are_accepted(reports):
    data = forecast_dataset().isel(valid_time=slice(0, -2))
    data = data.assign_coords(valid_time=np.datetime64("1970-01-01") + (data["valid_time"].to_numpy() * 1e9).astype("timedelta64[ns]"))
    data = data.rename({"latitude": "lat", "longitude": "lon"})

    source = share.build_scene(reports, forecasts={"IFS": data})["sources"][0]

    assert source["times"][0] == pytest.approx(TIME[0])


def test_a_forecast_without_fields_of_time_and_position_is_left_out(reports, messages):
    data = xr.Dataset(
        {"lsm": (("latitude", "longitude"), np.zeros((LATITUDE.size, LONGITUDE.size))), "step": (("valid_time",), TIME)},
        coords={"valid_time": TIME, "latitude": LATITUDE, "longitude": LONGITUDE},
    )

    scene = share.build_scene(reports, forecasts={"X": data})

    assert scene["sources"] == []
    assert any("⚠️" in message and "X" in message for message in messages)


def test_other_fields_are_layers_on_a_scale_of_their_values(reports):
    data = forecast_dataset().rename({"u10": "visibility_m"})
    data["visibility_m"].attrs.update(GRIB_name="Visibility", GRIB_units="m")

    scene = share.build_scene(reports, forecasts={"X": data})
    (source,) = scene["sources"]
    layer = scene["layers"]["visibility_m"]

    assert source["layers"] == ["waves", "pressure", "visibility_m", "v10"]
    assert (layer["label"], layer["unit"], layer["quantity"], layer["arrows"]) == ("Visibility", "m", "visibility_m", None)
    assert scene["layers"]["v10"]["label"] == "v10"
    values = frame_values(source, "visibility_m", 0)
    assert layer["colormap"]["min"] >= np.nanmin(values) - 0.1
    assert layer["colormap"]["max"] <= np.nanmax(frame_values(source, "visibility_m", len(source["times"]) - 1)) + 0.1
    assert layer["colormap"]["min"] <= min(layer["ticks"]) <= max(layer["ticks"]) <= layer["colormap"]["max"]


def wave_period_dataset():
    period = np.full((TIME.size, LATITUDE.size, LONGITUDE.size), 8.0)
    ptype = np.zeros_like(period)
    ptype[:, LATITUDE < 40.0, :] = 1.0
    ptype[:, LATITUDE < 30.0, :] = 5.0
    return forecast_dataset(mwp=period, t2m=period + 280.0, ptype=ptype)


def test_known_fields_have_their_units_scale_and_arrows(reports):
    scene = share.build_scene(reports, forecasts={"IFS": wave_period_dataset()})
    (source,) = scene["sources"]

    assert source["layers"] == ["wind", "waves", "pressure", "period", "slope", "temperature", "ptype"]
    assert (scene["layers"]["period"]["unit"], scene["layers"]["period"]["arrows"]) == ("s", "waves")
    assert scene["layers"]["slope"]["arrows"] == "waves"
    assert np.nanmax(frame_values(source, "temperature", 0)) == pytest.approx(14.85, abs=0.01)
    # Wave steepness: 2 pi Hs / (g T2), in %.
    height = frame_values(source, "swh", 0)
    assert frame_values(source, "slope", 0) == pytest.approx(200 * np.pi * height / (share.GRAVITY * 64.0), abs=0.02, nan_ok=True)


def test_categories_are_kept_exactly_and_drawn_in_their_colours(reports):
    scene = share.build_scene(reports, forecasts={"IFS": wave_period_dataset()})
    (source,) = scene["sources"]
    layer = scene["layers"]["ptype"]

    assert source["quantities"]["ptype"] == {"offset": 0.0, "scale": 1.0, "categorical": True}
    assert set(np.unique(frame_values(source, "ptype", 0))) <= {0.0, 1.0, 5.0}
    assert {"value": 1, "label": "Rain", "color": "#3a86ff"} in layer["categories"]
    assert {"value": 0, "label": "None", "color": None} in layer["categories"]


def test_only_the_chosen_fields_are_stored_with_their_arrows(reports):
    scene = share.build_scene(reports, forecasts={"IFS": wave_period_dataset()}, fields=["period", "pressure"])
    (source,) = scene["sources"]

    assert source["layers"] == ["pressure", "period"]
    assert set(source["quantities"]) == {"pressure", "swh", "wave_x", "wave_y", "period"}
    assert set(scene["layers"]) == set(share.LAYER_QUANTITIES) | {"period"}


def test_a_source_without_any_chosen_field_is_left_out(reports, dataset):
    assert share.build_scene(reports, forecasts={"IFS": dataset}, fields=["period"])["sources"] == []


def test_functions_of_a_forecast_are_layers(reports, dataset):
    from architeuthis.forecast import Forecast

    forecast = Forecast("waves", date=0.0, fxx=None, verbose=False)
    forecast.data = dataset
    forecast.add_function("double_swh", lambda x: 2.0 + 0.0 * x["latitude"], inputs=["valid_time", "latitude", "longitude"])
    forecast.add_function("broken", lambda x: x["missing"], inputs=["latitude"])

    scene = share.build_scene(reports, forecasts={"IFS": forecast})
    (source,) = scene["sources"]

    assert "double_swh" in source["layers"]
    assert scene["layers"]["double_swh"]["label"] == "Double swh"
    assert np.nanmax(frame_values(source, "double_swh", 0)) == pytest.approx(2.0)
    assert "broken" not in source["layers"]


def test_forecast_fields_lists_the_layers_of_every_forecast(dataset):
    fields = share.forecast_fields({"IFS": dataset, "WAVES": wave_period_dataset()[["swh", "mwd", "mwp"]]})

    assert fields == {"wind": "Wind", "waves": "Waves", "pressure": "Pressure", "period": "Wave period", "slope": "Wave slope"}


def test_forecasts_outside_the_routes_are_kept_whole(reports):
    data = forecast_dataset().assign_coords(valid_time=padded(TIME + 1e9))

    source = share.build_scene(reports, forecasts={"IFS": data})["sources"][0]

    assert len(source["times"]) == TIME.size


def test_sources_with_the_same_label_get_distinct_identifiers(reports, dataset):
    scene = share.build_scene(reports, forecasts={"IFS": dataset, "ifs": dataset})

    assert [source["id"] for source in scene["sources"]] == ["ifs", "ifs-2"]


def test_layers_have_a_colour_scale_and_a_legend(scene):
    for layer, info in scene["layers"].items():
        assert {"label", "unit", "colormap", "ticks"} <= set(info)
        assert len(info["colormap"]["colors"]) > 10
        assert all(re.fullmatch(r"#[0-9a-f]{6}", color) for color in info["colormap"]["colors"])
        assert info["colormap"]["min"] <= min(info["ticks"]) <= max(info["ticks"]) <= info["colormap"]["max"]


# ----------------------------------------------------------------------
# Zones, overlays and land
# ----------------------------------------------------------------------


def test_zones_are_drawn_with_their_label_colour_and_visibility(reports):
    zone = ExclusionZone("safety", [[45.0, -30.0], [45.0, -25.0], [40.0, -25.0]], label="Safety", color="#00ff00", visible=False, verbose=False)

    scene = share.build_scene(reports, zones=[zone, [[50.0, -40.0], [51.0, -41.0]]])

    first, second = scene["zones"]
    assert first == {
        "id": "z0",
        "label": "Safety",
        "color": "#00ff00",
        "visible": False,
        "outline": [[-30.0, 45.0], [-25.0, 45.0], [-25.0, 40.0]],
    }
    assert second["outline"] == [[-40.0, 50.0], [-41.0, 51.0]]
    assert second["visible"] is True


def test_an_empty_zone_is_still_listed(reports):
    scene = share.build_scene(reports, zones=[ExclusionZone("iceberg_limit", [], label="Iceberg limit", verbose=False)])

    assert scene["zones"][0]["outline"] == []


def test_overlays_are_placed_between_their_corners(reports):
    url = share.png_data_uri(b"\x89PNG")
    scene = share.build_scene(reports, overlays=[{"label": "Chart", "url": url, "bounds": [[65.0, -100.0], [14.0, 10.0]]}])

    assert scene["overlays"][0] == {
        "id": "o0",
        "label": "Chart",
        "url": url,
        "north": 65.0,
        "south": 14.0,
        "west": -100.0,
        "east": 10.0,
        "visible": False,
        "opacity": 0.9,
        "time": None,
    }


@pytest.mark.parametrize(
    "time",
    [
        pd.Timestamp("2026-11-20 06:00", tz="UTC"),
        pd.Timestamp("2026-11-20 07:00", tz="Europe/Paris"),
        pd.Timestamp("2026-11-20 06:00"),
        "2026-11-20T06:00Z",
        1795154400,
    ],
)
def test_an_overlay_keeps_its_valid_time_in_utc_seconds(reports, time):
    url = share.png_data_uri(b"\x89PNG")
    scene = share.build_scene(reports, overlays=[{"label": "Chart", "url": url, "bounds": [[65.0, -100.0], [14.0, 10.0]], "time": time}])

    assert scene["overlays"][0]["time"] == pd.Timestamp("2026-11-20 06:00", tz="UTC").timestamp()


# ----------------------------------------------------------------------
# Descriptions and comments of the analyst
# ----------------------------------------------------------------------


def test_routes_have_no_description_or_comment_by_default(scene):
    for route in scene["routes"]:
        assert route["description"] == ""
        assert route["comments"] == []


def test_routes_carry_the_analyst_description_and_comments(reports):
    scene = share.build_scene(
        reports,
        comments={
            0: {"description": "  Southern option ", "points": {"3": "Gybe here", 1: "Reef", 2: "  "}},
            "r1": "Northern option",
        },
    )
    first, second = scene["routes"]

    assert first["description"] == "Southern option"
    # In segment order, without the empty comment.
    assert first["comments"] == [{"k": 1, "text": "Reef"}, {"k": 3, "text": "Gybe here"}]
    assert second["description"] == "Northern option"
    assert second["comments"] == []


def test_comments_off_the_route_are_left_out(reports):
    segments = len(np.ravel(reports[0]["ctim"]))

    scene = share.build_scene(reports, comments={0: {"points": {segments: "After arrival", -1: "Before"}}})

    assert scene["routes"][0]["comments"] == []


def test_a_report_description_is_used_unless_the_analyst_gives_one(reports):
    report = dict(reports[0])
    report["description"] = "From the report"

    assert share.build_scene([report])["routes"][0]["description"] == "From the report"
    assert share.build_scene([report], comments={0: {"description": ""}})["routes"][0]["description"] == ""


def test_the_theme_is_a_setting_of_the_page(reports):
    scene = share.build_scene(reports, settings={"theme": "light"})

    assert scene["settings"]["theme"] == "light"


def test_land_rings_decode_to_positions_on_earth():
    land = share.land()

    assert len(land["polygons"]) > 500
    for rings in land["polygons"][:50]:
        for ring in rings:
            points = np.cumsum(np.reshape(ring, (-1, 2)), axis=0) * land["quantum"]
            assert (np.abs(points[:, 0]) <= 180.0).all() and (np.abs(points[:, 1]) <= 90.0).all()
            assert points[0] == pytest.approx(points[-1])


def test_the_land_comes_with_a_finer_level_for_close_ups():
    land = share.land()
    detail = land["detail"]
    points = lambda level: sum(len(ring) // 2 for rings in level["polygons"] for ring in rings)

    assert detail["quantum"] < land["quantum"]
    assert points(detail) > 3 * points(land)
    for rings in detail["polygons"][:50]:
        for ring in rings:
            positions = np.cumsum(np.reshape(ring, (-1, 2)), axis=0) * detail["quantum"]
            assert (np.abs(positions[:, 0]) <= 180.0).all() and (np.abs(positions[:, 1]) <= 90.0).all()
            assert positions[0] == pytest.approx(positions[-1])


# ----------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------


def test_the_page_holds_the_scene_and_maplibre_from_the_cache(scene, cache):
    fill(cache)

    page = share.viewer_html(scene)

    assert scene_of(page) == json.loads(json.dumps(scene))
    assert "fake maplibregl" in page
    assert "unpkg.com" not in page
    assert "<!--@" not in page
    assert "<title>Test</title>" in page


def test_text_cannot_close_the_scene_element(reports, cache):
    scene = share.build_scene(reports, title="<b>Route</b>", note="</script><script>alert(1)</script>")

    page = share.viewer_html(scene, library="cdn")

    assert scene_of(page)["note"] == "</script><script>alert(1)</script>"
    assert "<title>&lt;b&gt;Route&lt;/b&gt;</title>" in page


def test_cdn_pages_load_maplibre_from_its_address(scene, cache):
    page = share.viewer_html(scene, library="cdn")

    assert f"https://unpkg.com/maplibre-gl@{share.MAPLIBRE_VERSION}/dist/maplibre-gl.js" in page
    assert not cache.exists()


def test_unknown_library_mode_is_refused(scene):
    with pytest.raises(ValueError):
        share.viewer_html(scene, library="local")


def test_maplibre_is_downloaded_once(cache, monkeypatch):
    calls = []

    class Answer:
        def __init__(self, url):
            self.content = (
                b"/* maplibregl */" if url.endswith(".js") else b".maplibregl-map {}"
            )

        def raise_for_status(self):
            pass

    def get(url, **kwargs):
        calls.append(url)
        return Answer(url)

    monkeypatch.setattr(share.requests, "get", get)

    first = share.maplibre_files()
    second = share.maplibre_files()

    assert first == second == {"js": "/* maplibregl */", "css": ".maplibregl-map {}"}
    assert len(calls) == 2


def test_offline_pages_fall_back_to_the_cdn(scene, cache, monkeypatch, messages):
    def get(url, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(share.requests, "get", get)

    page = share.viewer_html(scene)

    assert "https://unpkg.com/maplibre-gl@" in page
    assert any("⚠️" in message for message in messages)
    assert not list(cache.glob("*"))


def test_an_unexpected_answer_is_not_cached(cache, monkeypatch):
    class Page:
        content = b"<html>Captive portal</html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(share.requests, "get", lambda url, **kwargs: Page())

    assert share.maplibre_files() is None
    assert not list(cache.glob("*"))


def test_share_routes_writes_one_file(reports, dataset, tmp_path, cache, messages):
    path = share.share_routes(reports, str(tmp_path / "out" / "share.html"), library="cdn", forecasts={"GFS": dataset}, note="Hello")

    page = (tmp_path / "out" / "share.html").read_text(encoding="utf-8")
    assert path == str(tmp_path / "out" / "share.html")
    assert scene_of(page)["note"] == "Hello"
    assert [source["label"] for source in scene_of(page)["sources"]] == ["GFS"]
    assert any("➕" in message and "share.html" in message for message in messages)


def test_share_files_go_to_the_shared_folder_by_default(reports, tmp_path, cache, monkeypatch):
    monkeypatch.setattr(share, "SHARED_DIRECTORY", str(tmp_path / "shared"))

    path = share.share_routes(reports, library="cdn", title="North Atlantic", verbose=False)

    assert path.startswith(str(tmp_path / "shared"))
    assert "north-atlantic_" in path


def test_report_collections_can_be_shared(reports, tmp_path, cache):
    path = reports.share(str(tmp_path / "share.html"), library="cdn", routes=[1], verbose=False)

    assert [route["id"] for route in scene_of(open(path, encoding="utf-8").read())["routes"]] == ["r1"]


def test_viewer_files_are_in_the_package():
    for name in ("viewer.html", "viewer.css", "viewer.js"):
        assert (share._TEMPLATES / name).read_text(encoding="utf-8").strip()
    template = (share._TEMPLATES / "viewer.html").read_text(encoding="utf-8")
    assert set(re.findall(r"<!--@(\w+)@-->", template)) == {"TITLE", "MAPLIBRE_CSS", "VIEWER_CSS", "SCENE", "MAPLIBRE_JS", "VIEWER_JS"}


def test_the_field_scales_come_from_windy_colormaps():
    from architeuthis.toolbox import windy_colormaps

    cmap, norm = windy_colormaps.get_field_cmap("cape")

    assert share.FIELDS["cape"]["colormap"] == windy_colormaps.FIELD_COLORMAPS["cape"]
    assert share.FIELDS["ptype"]["categories"] is windy_colormaps.PRECIPITATION_TYPES
    assert (norm.vmin, norm.vmax) == (0.0, 3000.0)
    assert cmap.name == "inferno"
    assert windy_colormaps.get_field_cmap("other", 1.0, 2.0)[0].name == windy_colormaps.DEFAULT_FIELD_COLORMAP
    with pytest.raises(ValueError, match="give low and high"):
        windy_colormaps.get_field_cmap("other")

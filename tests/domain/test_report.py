"""Reports of a routing: tables, GPX, storage and the file format that the UI reads."""

import importlib
import json
import os
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import pytest

from architeuthis.report import (
    DEFAULT_TABLE_VARIABLES,
    ROUTES_DIRECTORY,
    ReportCollection,
    RoutingReport,
    latest_report_file,
    routes_to_table,
)
from architeuthis.toolbox.json_utils import CustomEncoder, custom_decoder
from architeuthis.toolbox.os_utils import save_gpx

GPX = "{http://www.topografix.com/GPX/1/1}"


def collection(*reports):
    return ReportCollection(reports)


def assert_same_report(first, second):
    assert set(first) == set(second)
    for key, value in first.items():
        if isinstance(value, str):
            assert second[key] == value
        else:
            np.testing.assert_allclose(np.asarray(second[key], dtype=float), np.asarray(value, dtype=float), err_msg=key)


# ------------------------------------------------------------------------------
# RoutingReport
# ------------------------------------------------------------------------------


def test_routing_returns_a_report_that_is_still_a_dict(baseline_report):
    assert isinstance(baseline_report, RoutingReport)
    assert isinstance(baseline_report, dict)
    assert baseline_report["fuel"] == pd.DataFrame([baseline_report])["fuel"][0]


def test_report_times_are_utc_dates(baseline_report):
    assert baseline_report.etd_time == pd.Timestamp("1970-01-01 00:00")
    assert baseline_report.eta_time == pd.Timestamp("1970-01-03 12:00")


def test_report_table_has_one_row_per_segment(baseline_report):
    table = baseline_report.table()

    assert list(table.columns) == ["timestamp", *DEFAULT_TABLE_VARIABLES]
    assert len(table) == len(baseline_report["ctim"])
    assert table["timestamp"][0] == baseline_report.etd_time
    np.testing.assert_allclose(table["sog"], baseline_report["sog"])


def test_report_table_takes_its_variables(baseline_report):
    assert list(baseline_report.table(variables=["swh"]).columns) == ["timestamp", "swh"]


def test_report_steps_hold_each_value_over_its_segment(baseline_report):
    times, values = baseline_report.steps("sog")

    assert len(times) == len(values) == 2 * len(baseline_report["ctim"])
    assert values[0] == values[1] == baseline_report["sog"][0]
    assert times[0] == baseline_report.etd_time
    assert times[-1] == baseline_report.eta_time


# ------------------------------------------------------------------------------
# GPX
# ------------------------------------------------------------------------------


def track_points(path):
    root = ET.parse(path).getroot()
    return root, root.findall(f".//{GPX}trkpt")


def test_gpx_follows_the_route_with_the_right_dates(baseline_report, tmp_path):
    path = baseline_report.to_gpx(str(tmp_path / "track.gpx"), track_name="crossing")

    root, points = track_points(path)
    assert root.find(f".//{GPX}name").text == "crossing"
    assert len(points) == len(baseline_report["lat"])
    assert float(points[0].get("lat")) == pytest.approx(baseline_report["lat"][0])
    assert float(points[-1].get("lon")) == pytest.approx(baseline_report["lon"][-1])
    assert points[-1].find(f"{GPX}time").text.startswith("1970-01-03T12:00:00")


def test_gpx_default_names_come_from_the_tags(baseline_report, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    path = baseline_report.to_gpx()

    assert path == "track_IFS_eff45_19700101.gpx"
    assert track_points(path)[0].find(f".//{GPX}name").text == "track_IFS"


def test_collection_writes_one_gpx_per_report(baseline_report, optimized_report, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    paths = collection(baseline_report, optimized_report).to_gpx()

    assert paths == ["track_IFS_eff45_19700101.gpx", "track_GFS_eff60_19700101.gpx"]
    assert all(os.path.exists(path) for path in paths)


@pytest.mark.parametrize(
    "times",
    [
        [1.7e9, 1.7e9 + 3600.0],
        np.array([1.7e9, 1.7e9 + 3600.0]),
    ],
)
def test_gpx_reads_epoch_seconds_as_dates(times, tmp_path):
    # Numbers used to be read as nanoseconds, and every point was dated 1970.
    path = tmp_path / "track.gpx"

    save_gpx([48.0, 49.0], [-5.0, -6.0], times, str(path))

    assert track_points(path)[1][0].find(f"{GPX}time").text.startswith("2023-11-14T22:13:20")


def test_gpx_keeps_accepting_dates(tmp_path):
    path = tmp_path / "track.gpx"

    save_gpx([48.0], [-5.0], pd.to_datetime(["2026-01-02 03:00"]), str(path))

    assert track_points(path)[1][0].find(f"{GPX}time").text.startswith("2026-01-02T03:00:00")


# ------------------------------------------------------------------------------
# ReportCollection
# ------------------------------------------------------------------------------


def test_collection_converts_plain_dicts():
    reports = ReportCollection([{"fuel": 1.0}])
    reports.append({"fuel": 2.0})

    assert all(isinstance(report, RoutingReport) for report in reports)
    assert isinstance(reports, list)


@pytest.fixture
def several():
    return ReportCollection(
        [
            {"vessel": "eff45", "model": "ifs", "fuel": 90.0, "solve": 1},
            {"vessel": "eff45", "model": "gfs", "fuel": 80.0, "solve": 0},
            {"vessel": "eff60", "model": "ifs", "fuel": 70.0, "solve": 1},
        ]
    )


def test_select_by_entries(several):
    assert [r["fuel"] for r in several.select(vessel="eff45")] == [90.0, 80.0]
    assert [r["fuel"] for r in several.select(vessel="eff45", model="ifs")] == [90.0]
    assert several.select(vessel="unknown") == []


def test_select_by_function_and_entries(several):
    selected = several.select(lambda report: report["fuel"] < 85.0, solve=1)

    assert isinstance(selected, ReportCollection)
    assert [r["fuel"] for r in selected] == [70.0]


def test_frame_has_one_row_per_report(several):
    frame = several.frame()

    assert len(frame) == 3
    assert list(frame["model"]) == ["ifs", "gfs", "ifs"]


def test_table_merges_routes_on_time(baseline_report, optimized_report):
    table = collection(baseline_report, optimized_report).table()

    assert set(table.columns) == {"timestamp"} | {f"{v}_{i}" for v in DEFAULT_TABLE_VARIABLES for i in (0, 1)}
    assert table["timestamp"].is_monotonic_increasing
    np.testing.assert_allclose(table["sog_0"], baseline_report["sog"])
    np.testing.assert_allclose(table["sog_1"], optimized_report["sog"])


def test_table_mask_selects_the_routes(baseline_report, optimized_report):
    table = collection(baseline_report, optimized_report).table(mask=[1])

    assert "sog_1" in table and "sog_0" not in table


def test_routes_to_table_leaves_missing_times_empty():
    first = {"tim": [0.0, 3600.0, 7200.0], "sog": [1.0, 2.0]}
    second = {"tim": [3600.0, 7200.0, 10800.0], "sog": [3.0, 4.0]}

    table = routes_to_table(pd.DataFrame([first, second]), variables=["sog"])

    assert len(table) == 3
    assert np.isnan(table["sog_1"].iloc[0])
    assert np.isnan(table["sog_0"].iloc[-1])


def test_routes_to_table_refuses_an_empty_selection(several):
    with pytest.raises(ValueError, match="no report"):
        routes_to_table(several.frame(), mask=[False, False, False])


def test_quantiles_are_computed_at_each_segment():
    reports = ReportCollection({"tws": [float(i), 10.0 * i]} for i in range(101))

    quantiles = reports.quantiles("tws", quantiles=(0.25, 0.5))

    np.testing.assert_allclose(quantiles[0.25], [25.0, 250.0])
    np.testing.assert_allclose(quantiles[0.5], [50.0, 500.0])


def test_quantiles_refuse_an_empty_collection():
    with pytest.raises(ValueError, match="no report"):
        ReportCollection().quantiles("tws")


# ------------------------------------------------------------------------------
# Storage: the file format is the one the UI and the former scripts read
# ------------------------------------------------------------------------------


def test_save_and_load_keep_every_entry(baseline_report, optimized_report, tmp_path):
    reports = collection(baseline_report, optimized_report)

    path = reports.save(str(tmp_path / "folder" / "reports.json"))
    loaded = ReportCollection.load(path)

    assert isinstance(loaded, ReportCollection)
    assert all(isinstance(report, RoutingReport) for report in loaded)
    for before, after in zip(reports, loaded):
        assert_same_report(before, after)


def test_loaded_arrays_are_arrays(baseline_report, tmp_path):
    loaded = ReportCollection.load(collection(baseline_report).save(str(tmp_path / "reports.json")))[0]

    assert isinstance(loaded["lat"], np.ndarray)
    assert isinstance(loaded["fuel"], float)


def test_default_path_is_in_the_folder_the_ui_reads(several, monkeypatch, tmp_path):
    monkeypatch.setattr("architeuthis.report.ROUTES_DIRECTORY", str(tmp_path))

    path = several.save()

    assert os.path.dirname(path) == str(tmp_path)
    assert os.path.basename(path) == f"output_{pd.Timestamp('now'):%Y-%m-%d}.json"


def test_routes_directory_is_under_the_data_folder():
    from architeuthis.common import _HOME

    assert ROUTES_DIRECTORY == os.path.join(_HOME, "routes")


def test_files_written_by_the_former_scripts_can_be_loaded(baseline_report, tmp_path):
    path = tmp_path / "former.json"
    with open(path, "w") as file:
        json.dump([dict(baseline_report)], file, cls=CustomEncoder, indent=2)

    assert_same_report(baseline_report, ReportCollection.load(path)[0])


def test_files_can_be_read_without_the_collection(baseline_report, tmp_path):
    path = collection(baseline_report).save(str(tmp_path / "reports.json"))

    with open(path) as file:
        reports = json.load(file, object_hook=custom_decoder)

    assert_same_report(baseline_report, reports[0])


def test_latest_file_is_the_most_recently_modified(tmp_path, several):
    older = several[:1]
    newer = several[1:]
    older_path = ReportCollection(older).save(str(tmp_path / "z_older.json"))
    newer_path = ReportCollection(newer).save(str(tmp_path / "a_newer.json"))
    os.utime(older_path, (1000, 1000))
    os.utime(newer_path, (2000, 2000))

    assert latest_report_file(tmp_path).name == "a_newer.json"
    assert len(ReportCollection.latest(tmp_path)) == len(newer)


def test_latest_file_is_required(tmp_path):
    with pytest.raises(FileNotFoundError, match="No JSON files"):
        latest_report_file(tmp_path)


# ------------------------------------------------------------------------------
# Codec and UI format
# ------------------------------------------------------------------------------


def test_json_codec_round_trip():
    data = {
        "array": np.array([1.0, 2.0]),
        "integer": np.int64(3),
        "float": np.float64(0.5),
        "text": "text",
        "list": [1, 2],
    }

    loaded = json.loads(json.dumps(data, cls=CustomEncoder), object_hook=custom_decoder)

    np.testing.assert_array_equal(loaded["array"], data["array"])
    assert loaded["integer"] == 3
    assert loaded["float"] == 0.5
    assert loaded["text"] == "text"


@pytest.fixture
def json_wrapper(tmp_path, monkeypatch):
    # Importing this module makes dash_extensions write assets/dashExtensions_default.js
    # in the working directory, which must not be the repository.
    monkeypatch.chdir(tmp_path)
    return importlib.import_module("architeuthis.wrappers.json_wrapper")


def test_json_wrapper_keeps_giving_the_codec(json_wrapper):
    assert json_wrapper.CustomEncoder is CustomEncoder
    assert json_wrapper.custom_decoder is custom_decoder


def test_a_saved_report_can_be_displayed(json_wrapper, optimized_report, tmp_path):
    path = collection(optimized_report).save(str(tmp_path / "reports.json"))

    geojson = json_wrapper.route_to_geojson(ReportCollection.load(path)[0], valid_time=0, color="#ff0000")

    kinds = [feature["properties"].get("kind") for feature in geojson["features"]]
    assert "route" in kinds
    route = next(f for f in geojson["features"] if f["properties"].get("kind") == "route")
    assert route["geometry"]["coordinates"][0] == pytest.approx([optimized_report["lon"][0], optimized_report["lat"][0]])


def test_reports_carry_what_the_ui_needs_by_default(routing):
    report = routing(solve=False)

    assert report["solve"] == 0
    for key in ("model", "vessel", "member", "fuel", "init_fac"):
        assert key in report, key


@pytest.mark.parametrize("label", ["eff45", "custom"])
def test_vessel_label_with_or_without_efficiency_prefix(json_wrapper, baseline_report, label):
    report = dict(baseline_report) | {"vessel": label}

    json_wrapper.route_to_geojson(report, valid_time=0)

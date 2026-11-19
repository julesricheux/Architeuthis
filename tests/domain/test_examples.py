"""
The real example scripts, run from start to finish on synthetic data: they use most of the public
API, and nothing else fails when a signature changes under them.

Data sources are replaced where they load their data, and each run stops after a few iterations:
this checks that the scripts run and what they produce, not the quality of their routes.
"""

import os
import re
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
import xarray as xr

import architeuthis
from architeuthis.common import _HOME, ArchiteuthisData
from architeuthis.core import RoutingAnalysis
from architeuthis.exclusion import ExclusionZoneLibrary
from architeuthis.forecast import (
    CopernicusForecast,
    DeterministicHerbieForecast,
    EnsembleHerbieForecast,
    HRDPSForecast,
    Topography,
)
from architeuthis.report import ReportCollection
from architeuthis.route import RouteLibrary
from architeuthis.satellite import CopernicusASCATData, EUMETSATASCATData, GIBSData, WMSImageryData
from architeuthis.vessel import Vessel
from architeuthis.voyage import PassagePlanLibrary

from .conftest import polar_dataset

pytestmark = pytest.mark.integration

ROOT = Path(architeuthis.__file__).parent.parent
EXAMPLES = ROOT / "examples"
TODAY = pd.Timestamp("now").floor("1d")
SOON = (TODAY - pd.Timedelta(days=2), TODAY + pd.Timedelta(days=16))

# First and last time of the forecasts, around the schedule of each script.
WINDOWS = {
    "simple_routing.py": SOON,
    "long_term_routing.py": SOON,
    "ensemble_routing.py": SOON,
    "post_leg_rewind.py": ("2025-12-16", "2025-12-24"),
    "short_term_routing.py": SOON,
    "passage_planning.py": SOON,
    "ifs_route_tested_with_gfs.py": SOON,
    "comparison_ascat_models.py": (TODAY - pd.Timedelta(days=4), TODAY + pd.Timedelta(days=2)),
    "ascat_sources.py": (TODAY - pd.Timedelta(days=2), TODAY),
    "cloud_imagery.py": SOON,
    "function_polar_routing.py": SOON,
    "sky_along_route.py": SOON,
    "vessel_definitions.py": SOON,
    "wind_only_routing.py": SOON,
}
QUICK_START = "readme_quick_start.py"

LATITUDE = np.arange(5.0, 72.0, 3.0)
LONGITUDE = np.arange(-100.0, 12.0, 3.0)

# Typical value of each field.
FIELDS = {
    "u10": 4.0, "v10": 1.0, "fg10": 11.0, "gust": 10.0, "msl": 101000.0, "prmsl": 101000.0,
    "swh": 2.5, "mwd": 250.0, "dirpw": 240.0, "uo": 0.1, "vo": 0.05,
    "t2m": 285.0, "u100": 5.0, "v100": 1.5, "mwp": 8.0,
    "tcc": 0.6, "lcc": 0.4, "mcc": 0.3, "hcc": 0.2, "mucape": 150.0, "tprate": 1e-4,
    "d2m": 281.0, "t": 270.0,
}


def field_dataset(names, start, end, freq="6h"):
    time = (pd.date_range(start, end, freq=freq) - pd.Timestamp("1970-01-01")).total_seconds().to_numpy()
    # The two time steps past the horizon that providers add, which `check_valid_time` expects.
    time = np.append(time, [time[-1] + 1e6, time[-1] + 1e7])
    time, latitude, longitude = np.meshgrid(time, LATITUDE, LONGITUDE, indexing="ij")
    variation = np.sin(time / 86400.0 + latitude / 7.0) * np.cos(longitude / 11.0)
    return xr.Dataset(
        {name: (("valid_time", "latitude", "longitude"), FIELDS[name] * (1.0 + 0.3 * variation)) for name in names},
        coords={"valid_time": time[:, 0, 0], "latitude": LATITUDE, "longitude": LONGITUDE},
    )


def deterministic_names(forecast):
    """The fields that the `regex` of a forecast asks of its provider."""
    regex = forecast.regex or ""
    if forecast.model == "ifs":
        # As Herbie searches the IFS inventory: parameter, then level and level type.
        surface = {"u10": "10u", "v10": "10v", "fg10": "10fg", "msl": "msl", "u100": "100u", "v100": "100v", "t2m": "2t", "swh": "swh", "mwd": "mwd", "mwp": "mwp",
                   "tcc": "tcc", "lcc": "lcc", "mcc": "mcc", "hcc": "hcc", "mucape": "mucape", "tprate": "tprate", "d2m": "2d"}
        tokens = {name: f":{param}:sfc:" for name, param in surface.items()} | {"t": ":t:700:pl:"}
        return [name for name, token in tokens.items() if re.search(regex, token)]
    if forecast.model == "gfs":
        return ["u10", "v10"] + (["gust"] if "GUST" in regex else [])
    return ["swh", "dirpw"]


def topography_dataset():
    latitude = np.arange(5.0, 72.0, 1.0)
    longitude = np.arange(-100.0, 12.0, 1.0)
    grid_longitude, grid_latitude = np.meshgrid(longitude, latitude)
    distance = -500.0 - np.hypot(grid_latitude - 40.0, grid_longitude + 30.0)
    return xr.Dataset(
        {"distance_to_iso0": (("lat", "lon"), distance)},
        coords={"lat": latitude, "lon": longitude},
    )


def ascat_dataset():
    count = 200
    rng = np.random.default_rng(0)
    return xr.Dataset({
        "valid_time": ("obs", pd.Timestamp("now").timestamp() - rng.uniform(0.0, 40.0, count) * 3600.0),
        "lat": ("obs", rng.uniform(32.0, 58.0, count)),
        "lon": ("obs", rng.uniform(-78.0, -2.0, count)),
        "wind_speed": ("obs", rng.uniform(1.0, 20.0, count)),
        "wind_dir": ("obs", rng.uniform(0.0, 360.0, count)),
    })


def imagery_dataset(imagery):
    """
    Images every 10 min over the period and the grid of an imagery
    source: clouds moving east over a warm sea, GOES-East 1.5 K warmer
    than Meteosat in the infrared and darker in the visible.
    """
    latitude, longitude = imagery.grid()
    times = pd.date_range(pd.Timestamp(imagery.start).ceil("10min"), pd.Timestamp(imagery.end), freq="10min")
    hours = (times - times[0]).total_seconds().values / 3600.0
    goes = isinstance(imagery, GIBSData)
    clouds = np.cos(np.radians(longitude[None, None, :] * 6.0 - hours[:, None, None] * 30.0)) * np.cos(np.radians(latitude[None, :, None] * 8.0))
    values = {
        "brightness": (0.4 + 0.3 * clouds) * (0.8 if goes else 1.0),
        "bt": 255.0 + 30.0 * clouds + (1.5 if goes else 0.0),
    }
    return xr.Dataset(
        {variable: (("valid_time", "latitude", "longitude"), values[variable].astype(np.float32)) for variable in imagery.variables},
        coords={"valid_time": times.asi8 / 1e9, "latitude": latitude, "longitude": longitude},
    )


def with_wind(data):
    return data.assign(
        si10=np.hypot(data.u10, data.v10),
        wdir10=(np.degrees(np.arctan2(data.u10, data.v10)) + 360.0) % 360.0,
    )


def with_variable(data, var_dim, coord_dims):
    """
    The data with `var_dim` added if it lacks it, so that a script may ask
    for any variable of its real sources.

    The new variable copies the dimensions of one already there, with the
    typical value of FIELDS or else 0, the value of a missing field once
    NaN becomes 0.
    """
    if var_dim in data:
        return data
    template = next(variable for variable in data.data_vars.values() if set(coord_dims) <= set(variable.dims))
    return data.assign({var_dim: xr.full_like(template, FIELDS.get(var_dim, 0.0), dtype=float)})


def quick_start_of_readme():
    """The first Python block of the README."""
    return re.search(r"```python\n(.*?)```", (ROOT / "README.md").read_text(encoding="utf-8"), flags=re.DOTALL).group(1)


def run_script(script, folder):
    """Run a script from a temporary folder and return its variables."""
    start, end = SOON if script == QUICK_START else WINDOWS[script]

    def load_deterministic(forecast):
        forecast.data = field_dataset(deterministic_names(forecast), start, end)

    def load_hrdps(forecast):
        forecast.data = field_dataset(["u10", "v10"], start, end, freq="1h")

    def load_ensemble(forecast):
        members = xr.DataArray([1, 2], dims="number", name="number")
        data = field_dataset(["u10", "v10", "swh", "mwd"], start, end)
        forecast.data = xr.concat([data, data * 1.1], dim=members).transpose("valid_time", "number", "latitude", "longitude")

    def load_current(forecast):
        forecast.data = field_dataset(["uo", "vo"], start, end)

    def load_topography(topography):
        topography.data = topography_dataset()

    def load_vessel(vessel):
        vessel.data = polar_dataset().assign(sails_contribution=lambda polar: xr.full_like(polar["bhp"], 20.0))

    def load_ascat(ascat):
        ascat.data = ascat_dataset()

    def load_imagery(imagery):
        imagery.data = imagery_dataset(imagery)

    add_interpolator = ArchiteuthisData.add_interpolator

    def add_any_interpolator(data, var_dim, coord_dims, *args, **kwargs):
        # The synthetic data holds the usual variables, the scripts may ask for others.
        data.data = with_variable(data.data, var_dim, coord_dims)
        return add_interpolator(data, var_dim, coord_dims, *args, **kwargs)

    run = RoutingAnalysis.run

    def few_iterations(analysis, *args, solver_options=None, **kwargs):
        # mumps, because of the spral crash described in CLAUDE.md.
        ipopt = (solver_options or {}).get("ipopt", {}) | {"linear_solver": "mumps"}
        options = (solver_options or {}) | {"ipopt": ipopt}
        return run(analysis, *args, solver_options=options, **(kwargs | {"max_iter": 3}))

    # Two members rather than the 50 of the real ensemble, as in the synthetic forecast.
    if script == QUICK_START:
        source = quick_start_of_readme()
    else:
        source = (EXAMPLES / script).read_text(encoding="utf-8").replace("members = list(range(1,51,1))", "members = [1, 2]")
        # Pixels of 1 deg rather than 0.05: the same script, 400 times fewer pixels
        source = source.replace("resolution = 0.05", "resolution = 1.0")
    run_file = folder / script
    run_file.write_text(source, encoding="utf-8")

    previous = os.getcwd()
    os.chdir(folder)
    try:
        with (
            patch.object(DeterministicHerbieForecast, "load_data", load_deterministic),
            patch.object(HRDPSForecast, "load_data", load_hrdps),
            patch.object(EnsembleHerbieForecast, "load_data", load_ensemble),
            patch.object(CopernicusForecast, "load_data", load_current),
            patch.object(Topography, "load_data", load_topography),
            patch.object(Vessel, "load_data", load_vessel),
            patch.object(EUMETSATASCATData, "load_data", load_ascat),
            patch.object(CopernicusASCATData, "load_data", load_ascat),
            patch.object(WMSImageryData, "load_data", load_imagery),
            patch.object(ArchiteuthisData, "add_interpolator", add_any_interpolator),
            patch.object(type(xr.Dataset().herbie), "with_wind", lambda accessor: with_wind(accessor._obj), create=True),
            patch.object(RoutingAnalysis, "run", few_iterations),
            patch("architeuthis.forecast.HerbieLatest", lambda **kwargs: SimpleNamespace(valid_date=TODAY)),
            patch.object(pd.DataFrame, "to_clipboard", lambda *args, **kwargs: None),
            patch.object(plt, "show", lambda *args, **kwargs: None),
            # Drawing a map would download Natural Earth
            patch.object(plt.Figure, "savefig", lambda *args, **kwargs: None),
        ):
            return runpy.run_path(str(run_file), run_name="__main__")
    finally:
        os.chdir(previous)
        plt.close("all")


@pytest.fixture(scope="module")
def example(tmp_path_factory):
    """Runs a script once for this module; what the scripts store does not outlive the module."""

    def stored():
        return {path for path in Path(_HOME).rglob("*") if path.is_file()}

    before = stored()
    runs = {}

    def get(script):
        if script not in runs:
            folder = tmp_path_factory.mktemp(script.removesuffix(".py"))
            variables = run_script(script, folder)
            latest = ReportCollection.latest() if script == "simple_routing.py" else None
            runs[script] = SimpleNamespace(variables=variables, folder=folder, latest=latest)
        return runs[script]

    yield get

    for path in stored() - before:
        path.unlink()


@pytest.mark.parametrize("script", sorted(WINDOWS))
def test_example_runs_from_start_to_finish(script, example):
    example(script)


def test_quick_start_of_readme_runs_and_gives_its_results(example):
    run = example(QUICK_START)

    assert len(run.variables["reports"]) == 1
    assert run.variables["report"]["solve"] == 1
    assert len(list(run.folder.glob("*.gpx"))) == 1


def test_every_example_is_run_by_these_tests():
    scripts = {path.name for path in EXAMPLES.glob("*.py")}

    assert scripts == set(WINDOWS)


# The tests of simple_routing.py hold whatever its settings: models, vessels, facs, members and
# timeframes change as they are tried, and so do the number and the kind of its runs.


def test_simple_routing_gives_what_ui_displays(example):
    run = example("simple_routing.py")
    variables = run.variables
    reports = variables["reports"]

    assert len(reports) > 0
    assert {report["solve"] for report in reports} <= {0, 1}
    assert {report["model"] for report in reports} <= set(variables["models"])
    assert {report["vessel"] for report in reports} <= {vessel.label for vessel in variables["vessels"]}

    assert len(run.latest) == len(reports)
    assert all("init_fac" in report and "member" in report for report in run.latest)


def test_simple_routing_stores_its_routes_and_plans(example):
    variables = example("simple_routing.py").variables

    for route in (variables["routeSbd"], variables["routeO"], variables["routePrt"]):
        assert RouteLibrary().load(route.name).name == route.name
    for plan in variables["plans"]:
        assert PassagePlanLibrary().load(plan.name).name == plan.name

    # One plan per run, and the evaluations are of the optimized ones.
    solved = {plan.name for plan in variables["plans"] if plan.metadata["solve"]}
    assert len(variables["plans"]) == len(variables["reports"])
    assert len(solved) == sum(report["solve"] for report in variables["reports"])
    assert {evaluation["plan"] for evaluation in variables["evaluations"]} <= solved


def test_simple_routing_writes_gpx_tracks(example):
    run = example("simple_routing.py")
    solved = sum(report["solve"] for report in run.variables["reports"])
    tracks = list(run.folder.glob("track_*.gpx"))

    # Runs of the same model, vessel and day share a file name.
    assert (len(tracks) > 0) == (solved > 0)
    assert len(tracks) <= solved


def test_simple_routing_stores_its_zones_for_the_ui(example):
    example("simple_routing.py")

    assert {"north_america", "brittany"} <= {zone.name for zone in ExclusionZoneLibrary()}


def test_examples_define_their_own_zones_and_their_own_sources():
    for script in WINDOWS:
        source = (EXAMPLES / script).read_text(encoding="utf-8")
        assert "presets" not in source
        assert "reference_data" not in source


def test_ascat_sources_uses_both_sources_and_matches_them(example):
    variables = example("ascat_sources.py").variables

    assert variables["default"].source == "eumetsat"
    assert variables["cmems_only"].source == "cmems"
    # The same synthetic measurements from both: every one matches, identical
    assert len(variables["pairs"]) > 0
    assert (variables["pairs"]["wind_speed_cmems"] == variables["pairs"]["wind_speed_eumetsat"]).all()


def test_cloud_imagery_joins_both_satellites_into_one_layer(example):
    run = example("cloud_imagery.py")
    variables = run.variables
    clouds = variables["clouds"]

    assert list(clouds.data["source"].values) == ["clouds_eumetview", "clouds_gibs"]
    assert np.isfinite(clouds.data["bt"].values).all()
    # The overlap check finds the 1.5 K of the synthetic sources
    assert np.median(variables["difference"]) == pytest.approx(1.5, abs=1e-3)
    assert len(variables["frames"]) == len(clouds.times()) > 1
    # The visible of GOES, 20 % darker, put on the levels of Meteosat
    np.testing.assert_allclose(variables["daylight"].data["gain"].sel(channel="visible").isel(source=1), 1.25, rtol=1e-3)
    assert len(variables["daylight"].times()) > 1
    assert variables["frames"][0].shape == (25, 80, 4)
    assert (run.folder / "cloud_imagery.gif").exists()


def test_function_polar_routing_reads_the_air_temperature(example):
    variables = example("function_polar_routing.py").variables
    reports = variables["reports"]

    assert [report["solve"] for report in reports] == [0, 1]
    assert {report["vessel"] for report in reports} == {"dummy_vessel"}
    assert variables["vessel"].path is None
    assert "air_temperature" in variables["atmosphere"].models

    # Variables that the polar does not use are computed and reported all the same.
    for report in reports:
        assert np.all(np.asarray(report["slope"]) > 0.0)
        assert report["gust_excess"] == pytest.approx(np.asarray(report["tws_gust"]) - np.asarray(report["tws"]))
        assert {"aws_gust", "tws100", "air_temperature"} <= set(report)

    # Colder air, more sail power, less brake power.
    query = {"stw": 11.0, "tws": 20.0, "twa": 90.0, "tws100": 25.0, "twa100": 85.0, "swh": 2.0, "mwa": 30.0}
    vessel = variables["vessel"]
    cold = float(vessel("bhp", query | {"air_temperature": 0.0}))
    warm = float(vessel("bhp", query | {"air_temperature": 30.0}))
    assert cold < warm

    # The sails take the wind averaged between 10 m and 100 m.
    stronger_aloft = float(vessel("bhp", query | {"tws100": 35.0, "air_temperature": 15.0}))
    assert stronger_aloft < float(vessel("bhp", query | {"air_temperature": 15.0}))
    assert {"u100", "v100"} <= set(variables["atmosphere"].models)


def test_ensemble_routing_evaluates_each_plan_in_each_member(example):
    evaluations = example("ensemble_routing.py").variables["evaluations"]

    assert len(evaluations) == 2 * 2
    assert {report["plan_member"] for report in evaluations} == {1, 2}
    assert {report["member"] for report in evaluations} == {1, 2}


def test_sky_along_route_describes_each_point_with_both_models(example):
    variables = example("sky_along_route.py").variables
    table = variables["table"]

    assert len(table) == variables["points"]
    assert {"sky IFS", "sky GFS"} <= set(table.columns)
    assert all(isinstance(line, str) and line for line in table["sky IFS"])
    assert {"cloud_low", "cloud_middle", "cloud_high"} <= set(variables["skies"]["gfs"])


def test_vessel_definitions_of_the_same_vessel_burn_the_same_fuel(example):
    reports = example("vessel_definitions.py").variables["reports"]
    reference = {report["vessel"]: report for report in reports.select(solve=0)}

    assert set(reference) == {"bhp_function", "bhp_table", "sfoc_curve", "total_power", "hourly_consumption"}
    for name in ("total_power", "hourly_consumption"):
        assert reference[name]["fuel"] == pytest.approx(reference["bhp_function"]["fuel"], rel=1e-9)
    assert reference["bhp_table"]["fuel"] == pytest.approx(reference["bhp_function"]["fuel"], rel=5e-2)
    assert reference["sfoc_curve"]["fuel"] > reference["bhp_function"]["fuel"]
    assert "bhp" not in reference["hourly_consumption"]


def test_wind_only_routing_has_a_calm_sea_and_no_current(example):
    reports = example("wind_only_routing.py").variables["reports"]

    assert [report["solve"] for report in reports] == [0, 1]
    for report in reports:
        for key in ("swh", "cs"):
            assert np.ravel(report[key]) == pytest.approx(0.0)
        assert np.max(np.ravel(report["tws"])) > 0.0

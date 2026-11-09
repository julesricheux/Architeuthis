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
from architeuthis.common import _HOME
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
from architeuthis.satellite import ASCATData
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
}
QUICK_START = "readme_quick_start.py"

LATITUDE = np.arange(5.0, 72.0, 3.0)
LONGITUDE = np.arange(-100.0, 12.0, 3.0)

# Typical value of each field.
FIELDS = {
    "u10": 4.0, "v10": 1.0, "fg10": 11.0, "gust": 10.0, "msl": 101000.0, "prmsl": 101000.0,
    "swh": 2.5, "mwd": 250.0, "dirpw": 240.0, "uo": 0.1, "vo": 0.05,
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
        tokens = {"u10": ":10u:", "v10": ":10v:", "fg10": ":10fg:", "msl": ":msl:", "swh": ":swh:", "mwd": ":mwd:"}
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


def with_wind(data):
    return data.assign(
        si10=np.hypot(data.u10, data.v10),
        wdir10=(np.degrees(np.arctan2(data.u10, data.v10)) + 360.0) % 360.0,
    )


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
            patch.object(ASCATData, "load_data", load_ascat),
            patch.object(type(xr.Dataset().herbie), "with_wind", lambda accessor: with_wind(accessor._obj), create=True),
            patch.object(RoutingAnalysis, "run", few_iterations),
            patch("architeuthis.forecast.HerbieLatest", lambda **kwargs: SimpleNamespace(valid_date=TODAY)),
            patch.object(pd.DataFrame, "to_clipboard", lambda *args, **kwargs: None),
            patch.object(plt, "show", lambda *args, **kwargs: None),
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


def test_simple_routing_gives_what_ui_displays(example):
    run = example("simple_routing.py")
    reports = run.variables["reports"]

    # A reference, then two models with two sail efficiencies.
    assert [report["solve"] for report in reports] == [0, 1, 1, 1, 1]
    assert {report["model"] for report in reports} == {"ifs", "gfs"}
    assert {report["vessel"] for report in reports} == {"eff1", "eff45", "eff60"}

    assert len(run.latest) == 5
    assert all("init_fac" in report and "member" in report for report in run.latest)


def test_simple_routing_stores_its_routes_and_plans(example):
    variables = example("simple_routing.py").variables

    for route in (variables["routeSbd"], variables["routeO"], variables["routePrt"]):
        assert RouteLibrary().load(route.name).name == route.name
    for plan in variables["plans"]:
        assert PassagePlanLibrary().load(plan.name).name == plan.name

    # Every optimized plan is tested with each model and vessel.
    assert sum(1 for plan in variables["plans"] if plan.metadata["solve"]) == 4
    assert len(variables["evaluations"]) == 4 * 2 * 3


def test_simple_routing_writes_gpx_tracks(example):
    assert len(list(example("simple_routing.py").folder.glob("track_*.gpx"))) == 4


def test_simple_routing_stores_its_zones_for_the_ui(example):
    example("simple_routing.py")

    assert {"north_america", "brittany"} <= {zone.name for zone in ExclusionZoneLibrary()}


def test_examples_define_their_own_zones_and_their_own_sources():
    for script in WINDOWS:
        source = (EXAMPLES / script).read_text(encoding="utf-8")
        assert "presets" not in source
        assert "reference_data" not in source


def test_ensemble_routing_evaluates_each_plan_in_each_member(example):
    evaluations = example("ensemble_routing.py").variables["evaluations"]

    assert len(evaluations) == 2 * 2
    assert {report["plan_member"] for report in evaluations} == {1, 2}
    assert {report["member"] for report in evaluations} == {1, 2}

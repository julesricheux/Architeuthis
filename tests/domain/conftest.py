"""Synthetic weather, vessel and topography objects, so no test needs a data provider."""

import contextlib
import io

import numpy as np
import pytest
import xarray as xr

# With a fresh home, Herbie's first import writes its config and prints a non-ASCII
# banner, which raises UnicodeEncodeError on consoles using a legacy Windows code page.
with contextlib.redirect_stdout(io.StringIO()):
    import herbie  # noqa: F401

from architeuthis.core import RoutingAnalysis
from architeuthis.forecast import Forecast, Topography
from architeuthis.vessel import Vessel
from architeuthis.voyage import Voyage

HOUR = 3600.0

ISLAND_LATITUDE = 49.5
ISLAND_LONGITUDE = -25.0
POLAR_DIMS = ("stw", "tws", "twa", "hs", "wa")
POLAR_POWER_COEFFICIENT = 1.2  # bhp = coefficient * stw**3, in kW


def uniform_forecast(name, **uniform_fields):
    """Build a forecast with constant fields over a 72 h, North Atlantic domain."""
    valid_time = np.arange(0.0, 73.0, 3.0) * HOUR
    latitude = np.arange(40.0, 56.0, 0.5)
    longitude = np.arange(-40.0, -9.0, 0.5)
    shape = (valid_time.size, latitude.size, longitude.size)

    forecast = Forecast(name, date=0.0, fxx=None, verbose=False)
    forecast.data = xr.Dataset(
        {
            key: (("valid_time", "latitude", "longitude"), np.full(shape, value))
            for key, value in uniform_fields.items()
        },
        coords={"valid_time": valid_time, "latitude": latitude, "longitude": longitude},
    )
    for key in uniform_fields:
        forecast.add_interpolator(key, "valid_time", "latitude", "longitude")
    return forecast


def island_topography(island_radius_nm):
    """Build a signed-distance field that is positive inside a disc (negative radius: open sea)."""
    latitude = np.arange(38.0, 58.0, 0.1)
    longitude = np.arange(-42.0, -7.0, 0.1)
    longitude_grid, latitude_grid = np.meshgrid(longitude, latitude)
    distance_nm = np.hypot(
        (latitude_grid - ISLAND_LATITUDE) * 60.0,
        (longitude_grid - ISLAND_LONGITUDE) * 60.0 * np.cos(np.radians(ISLAND_LATITUDE)),
    )

    topography = Topography("topography", verbose=False)
    topography.data = xr.Dataset(
        {"distance_to_iso0": (("lat", "lon"), island_radius_nm - distance_nm)},
        coords={"lat": latitude, "lon": longitude},
    )
    topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")
    return topography


def polar_dataset():
    """Build a polar table whose power follows a cubic law in speed through water."""
    coords = {
        "stw": np.linspace(0.0, 25.0, 26),
        "tws": np.array([0.0, 60.0]),
        "twa": np.array([0.0, 180.0]),
        "hs": np.array([0.0, 15.0]),
        "wa": np.array([0.0, 180.0]),
    }
    shape = tuple(coords[dim].size for dim in POLAR_DIMS)
    power = np.broadcast_to(
        (POLAR_POWER_COEFFICIENT * coords["stw"] ** 3)[:, None, None, None, None],
        shape,
    )
    return xr.Dataset(
        {
            "bhp": (POLAR_DIMS, power),
            "max_bhp": (POLAR_DIMS, power),
            "sails_contribution": (POLAR_DIMS, np.zeros(shape)),
        },
        coords=coords,
    )


@pytest.fixture
def polar():
    return polar_dataset()


@pytest.fixture(scope="session")
def atmosphere():
    return uniform_forecast("atmosphere", u10=5.0, v10=2.0)


@pytest.fixture(scope="session")
def wave():
    return uniform_forecast("wave", swh=1.5, mwd=270.0)


@pytest.fixture(scope="session")
def current():
    return uniform_forecast("current", uo=0.1, vo=0.0)


@pytest.fixture(scope="session")
def open_sea():
    return island_topography(island_radius_nm=-1e4)


@pytest.fixture(scope="session")
def island():
    return island_topography(island_radius_nm=90.0)


@pytest.fixture(scope="session")
def vessel():
    ship = Vessel(
        "ship",
        filepath="unused.nc",
        sfc=224.0,
        hotel_load=200.0,
        max_power=1e6,
        verbose=False,
    )
    ship.data = polar_dataset()
    for key in ("bhp", "max_bhp", "sails_contribution"):
        ship.add_interpolator(key, *POLAR_DIMS)
    return ship


@pytest.fixture(scope="session")
def routing(vessel, atmosphere, wave, current, open_sea):
    """Compute a real report on the synthetic data. Reports are shared: copy them to change them."""

    def _routing(analysis_options=None, **run_options):
        analysis = RoutingAnalysis(
            "analysis",
            vessel,
            Voyage(
                name="voyage",
                etd=0.0,
                eta=60.0 * HOUR,
                departure=np.array([48.0, -35.0]),
                arrival=np.array([50.0, -15.0]),
                verbose=False,
            ),
            atmosphere,
            wave,
            current,
            open_sea,
            verbose=False,
            **(analysis_options or {}),
        )
        return analysis.run(
            max_iter=30,
            solver_options={
                "ipopt": {
                    "acceptable_tol": 1e9,
                    "linear_solver": "mumps",
                    "hessian_approximation": "limited-memory",
                },
            },
            **run_options,
        )

    return _routing


@pytest.fixture(scope="session")
def baseline_report(routing):
    return routing(solve=False, tags={"model": "ifs", "vessel": "eff45", "member": 0, "init_fac": 0.0})


@pytest.fixture(scope="session")
def optimized_report(routing):
    return routing(tags={"model": "gfs", "vessel": "eff60", "member": 0, "init_fac": 0.0})

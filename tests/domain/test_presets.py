"""Ready-made data sources, built on synthetic datasets instead of the providers."""

import datetime as dt
from unittest.mock import patch

import numpy as np
import pytest
import xarray as xr

from architeuthis import presets
from architeuthis.common import GUST_DEFAULT_RATIO, Domain
from architeuthis.exclusion import ExclusionZone
from architeuthis.forecast import (
    CopernicusForecast,
    DeterministicHerbieForecast,
    EnsembleHerbieForecast,
    Topography,
)

DATE = dt.datetime(2025, 1, 15)
DOMAIN = Domain(min_lon=-5.0, max_lon=5.0, min_lat=40.0, max_lat=50.0)
LATITUDE = np.arange(40.0, 51.0, 1.0)
LONGITUDE = np.arange(-5.0, 6.0, 1.0)
TIME = np.array([0.0, 3600.0, 7200.0])
QUERY = [[3600.0, 45.0, 0.0]]


def fields(names, dims=("valid_time", "latitude", "longitude"), **coords):
    """A dataset of constant fields, `names` giving the value of each variable."""
    coords = {"valid_time": TIME, "latitude": LATITUDE, "longitude": LONGITUDE} | coords
    shape = tuple(len(coords[dim]) for dim in dims)
    return xr.Dataset(
        {name: (dims, np.full(shape, value, dtype=float)) for name, value in names.items()},
        coords=coords,
    )


def patched_load(cls, data):
    def load_data(self):
        self.loaded_settings = dict(vars(self))
        self.data = data

    return patch.object(cls, "load_data", load_data)


def value(forecast, key, query=QUERY):
    return float(forecast(key, np.array(query))[0])


# ------------------------------------------------------------------------------
# Domain
# ------------------------------------------------------------------------------


def test_domain_unpacks_as_keyword_arguments():
    assert dict(**DOMAIN) == {"min_lon": -5.0, "max_lon": 5.0, "min_lat": 40.0, "max_lat": 50.0}


def test_domain_defaults_to_the_whole_globe():
    assert dict(**Domain()) == {"min_lon": -180.0, "max_lon": 180.0, "min_lat": -90.0, "max_lat": 90.0}


def test_domain_refuses_unknown_keys():
    with pytest.raises(KeyError):
        DOMAIN["unknown"]


def test_domain_cannot_be_changed_by_accident():
    with pytest.raises(AttributeError):
        DOMAIN.min_lon = 0.0


def test_domain_gives_the_limits_to_a_topography():
    topography = Topography("topo", verbose=False, **DOMAIN)

    assert topography.min_lon == -5.0
    assert topography.max_lat == 50.0


# ------------------------------------------------------------------------------
# Atmosphere
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model, product, gust_name",
    [
        ("ifs", "oper", "fg10"),
        ("gfs", "pgrb2.0p25", "gust"),
    ],
)
def test_atmosphere_has_what_routing_requires(model, product, gust_name):
    data = fields({"u10": 3.0, "v10": 4.0, gust_name: 7.0})

    with patched_load(DeterministicHerbieForecast, data):
        forecast = presets.atmosphere(model, DOMAIN, date=DATE, fxx=[0, 3], verbose=False)

    assert forecast.name == f"wind_{model}"
    assert forecast.product == product
    assert forecast.fxx == [0, 3]
    assert forecast.min_lon == -5.0
    assert value(forecast, "u10") == pytest.approx(3.0)
    assert value(forecast, "v10") == pytest.approx(4.0)
    assert value(forecast, "gust") == pytest.approx(7.0)


def test_atmosphere_wind_factor_applies_to_the_wind_and_the_gust():
    data = fields({"u10": 3.0, "v10": 4.0, "fg10": 7.0})

    with patched_load(DeterministicHerbieForecast, data):
        forecast = presets.atmosphere("ifs", DOMAIN, date=DATE, wind_factor=2.0, verbose=False)

    assert value(forecast, "u10") == pytest.approx(6.0)
    assert value(forecast, "gust") == pytest.approx(14.0)


def test_gust_below_the_mean_wind_is_corrected():
    data = fields({"u10": 3.0, "v10": 4.0, "fg10": 1.0})

    with patched_load(DeterministicHerbieForecast, data):
        default = presets.atmosphere("ifs", DOMAIN, date=DATE, verbose=False)
    with patched_load(DeterministicHerbieForecast, fields({"u10": 3.0, "v10": 4.0, "fg10": 1.0})):
        custom = presets.atmosphere("ifs", DOMAIN, date=DATE, gust_factor=1.5, verbose=False)

    assert value(default, "gust") == pytest.approx(5.0 * GUST_DEFAULT_RATIO)
    assert value(custom, "gust") == pytest.approx(7.5)


def test_atmosphere_without_gust_leaves_it_to_the_standard_ratio(capsys):
    data = fields({"u10": 3.0, "v10": 4.0})

    with patched_load(DeterministicHerbieForecast, data):
        forecast = presets.atmosphere("ifs", DOMAIN, date=DATE, regex=r":10[uv]:", verbose=False)

    assert forecast.regex == r":10[uv]:"
    assert "gust" not in forecast.interpolators
    assert "standard ratio" in capsys.readouterr().out


def test_atmosphere_can_be_named():
    data = fields({"u10": 3.0, "v10": 4.0, "fg10": 7.0})

    with patched_load(DeterministicHerbieForecast, data):
        assert presets.atmosphere("ifs", DOMAIN, date=DATE, name="wind", verbose=False).name == "wind"


@pytest.mark.parametrize(
    "function",
    [
        presets.atmosphere,
        presets.wave,
        presets.ensemble_atmosphere,
        presets.ensemble_wave,
    ],
)
def test_unknown_model_is_refused_with_the_available_ones(function):
    with pytest.raises(ValueError, match="'ifs'"):
        function("unknown", DOMAIN, date=DATE)


# ------------------------------------------------------------------------------
# Waves
# ------------------------------------------------------------------------------


def test_ifs_wave_has_what_routing_requires():
    with patched_load(DeterministicHerbieForecast, fields({"swh": 2.0, "mwd": 270.0})):
        forecast = presets.wave("ifs", DOMAIN, date=DATE, verbose=False)

    assert forecast.name == "wave_ifs"
    assert forecast.product == "wave"
    assert value(forecast, "swh") == pytest.approx(2.0)
    assert value(forecast, "mwd") == pytest.approx(270.0)


def test_gfs_wave_direction_becomes_mwd():
    with patched_load(DeterministicHerbieForecast, fields({"swh": 2.0, "dirpw": 200.0})):
        forecast = presets.wave("gfs", DOMAIN, date=DATE, verbose=False)

    assert forecast.model == "gfs_wave"
    assert value(forecast, "mwd") == pytest.approx(200.0)


# ------------------------------------------------------------------------------
# Ensembles
# ------------------------------------------------------------------------------


def ensemble(names):
    """Each member holds `value * member`, to check that members can be told apart."""
    data = fields(names)
    return xr.concat(
        [data * member for member in (1.0, 2.0)],
        dim=xr.DataArray([1, 2], dims="number", name="number"),
    ).transpose("valid_time", "number", "latitude", "longitude")


def test_ensemble_atmosphere_has_one_value_per_member():
    with patched_load(EnsembleHerbieForecast, ensemble({"u10": 3.0, "v10": 4.0})):
        forecast = presets.ensemble_atmosphere(domain=DOMAIN, date=DATE, wind_factor=10.0, verbose=False)

    assert forecast.product == "enfo"
    assert value(forecast, "u10", [[3600.0, 1, 45.0, 0.0]]) == pytest.approx(30.0)
    assert value(forecast, "v10", [[3600.0, 2, 45.0, 0.0]]) == pytest.approx(80.0)


def test_ensemble_wave_has_one_value_per_member():
    with patched_load(EnsembleHerbieForecast, ensemble({"swh": 2.0, "mwd": 90.0})):
        forecast = presets.ensemble_wave(domain=DOMAIN, date=DATE, verbose=False)

    assert forecast.product == "waef"
    assert value(forecast, "swh", [[3600.0, 2, 45.0, 0.0]]) == pytest.approx(4.0)


def test_ensemble_stride_thins_the_grid():
    with patched_load(EnsembleHerbieForecast, ensemble({"u10": 3.0, "v10": 4.0})):
        with patch.object(EnsembleHerbieForecast, "add_interpolator") as add_interpolator:
            presets.ensemble_atmosphere(domain=DOMAIN, date=DATE, stride=4, verbose=False)

    keywords = add_interpolator.call_args.kwargs
    assert keywords["latitude_slice"] == slice(None, None, 4)
    assert keywords["longitude_slice"] == slice(None, None, 4)
    assert add_interpolator.call_args.args == ("v10", "valid_time", "number", "latitude", "longitude")


def test_ensemble_interpolator_arguments_can_be_named():
    # They used to be named lat, lon, time and member in the wrong places.
    forecast = EnsembleHerbieForecast("ensemble", model="ifs", product="enfo", date=DATE, verbose=False)
    forecast.data = ensemble({"u10": 3.0})

    forecast.add_interpolator(
        "u10",
        time_dim="valid_time",
        member_dim="number",
        latitude_dim="latitude",
        longitude_dim="longitude",
        var_key="wind",
    )

    assert value(forecast, "wind", [[3600.0, 2, 45.0, 0.0]]) == pytest.approx(6.0)


# ------------------------------------------------------------------------------
# Currents and topography
# ------------------------------------------------------------------------------


def test_mercator_current_has_what_routing_requires():
    data = fields({"uo": 0.5, "vo": 0.25})

    with patched_load(CopernicusForecast, data):
        forecast = presets.current_mercator(DOMAIN, date=DATE, end=DATE + dt.timedelta(days=1), time_stride=1, verbose=False)

    assert forecast.name == "current"
    assert forecast.dataset == presets.MERCATOR_CURRENT_DATASET
    assert forecast.variables == ["uo", "vo"]
    assert value(forecast, "uo") == pytest.approx(0.5)
    assert value(forecast, "vo") == pytest.approx(0.25)


def test_mercator_current_thins_the_grid():
    with patched_load(CopernicusForecast, fields({"uo": 0.5, "vo": 0.25})):
        with patch.object(CopernicusForecast, "add_interpolator") as add_interpolator:
            presets.current_mercator(DOMAIN, date=DATE, stride=5, time_stride=2, verbose=False)

    keywords = add_interpolator.call_args.kwargs
    assert keywords["latitude_slice"] == slice(None, None, 5)
    assert keywords["time_slice"] == slice(None, None, 2)


def topography_data():
    return xr.Dataset(
        {"distance_to_iso0": (("lat", "lon"), np.full((LATITUDE.size, LONGITUDE.size), -7.0))},
        coords={"lat": LATITUDE, "lon": LONGITUDE},
    )


def test_topography_exposes_the_distance_as_z():
    with patched_load(Topography, topography_data()):
        topography = presets.topography(DOMAIN, exclusion_zones=[], depth_offset=10.0, z_margin=5.0, verbose=False)

    assert topography.exclusion_zones == []
    assert topography.depth_offset == 10.0
    assert topography.z_margin == 5.0
    assert value(topography, "z", [[45.0, 0.0]]) == pytest.approx(-7.0)


def test_topography_uses_the_default_zones_when_none_are_given():
    with patched_load(Topography, topography_data()):
        topography = presets.topography(DOMAIN, verbose=False)

    assert [zone.name for zone in topography.exclusion_zones] == ["north_america", "brittany", "iceberg_limit"]


def test_topography_keeps_the_given_zones():
    zone = ExclusionZone("zone", [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0]])

    with patched_load(Topography, topography_data()):
        topography = presets.topography(DOMAIN, exclusion_zones=[zone], verbose=False)

    assert topography.exclusion_zones == [zone]


def test_presets_can_be_routed_with(routing_inputs):
    atmosphere, wave, current, topography = routing_inputs
    assert set(atmosphere.interpolators) == {"u10", "v10", "gust"}
    assert set(wave.interpolators) == {"swh", "mwd"}
    assert set(current.interpolators) == {"uo", "vo"}
    assert set(topography.interpolators) == {"z"}


@pytest.fixture
def routing_inputs():
    with patched_load(DeterministicHerbieForecast, fields({"u10": 3.0, "v10": 4.0, "fg10": 7.0})):
        atmosphere = presets.atmosphere("ifs", DOMAIN, date=DATE, verbose=False)
    with patched_load(DeterministicHerbieForecast, fields({"swh": 2.0, "mwd": 270.0})):
        wave = presets.wave("ifs", DOMAIN, date=DATE, verbose=False)
    with patched_load(CopernicusForecast, fields({"uo": 0.5, "vo": 0.25})):
        current = presets.current_mercator(DOMAIN, date=DATE, stride=1, time_stride=1, verbose=False)
    with patched_load(Topography, topography_data()):
        topography = presets.topography(DOMAIN, exclusion_zones=[], verbose=False)
    return atmosphere, wave, current, topography

# -*- coding: utf-8 -*-
"""
Ready-made data sources for the routing scripts.

Each function builds, loads and prepares an ordinary forecast or
topography object: the same as writing
`DeterministicHerbieForecast(...)`, `load_data()` and
`add_interpolator(...)` by hand, which remains valid and is needed for
anything these functions do not offer.

Import this module with its name, as `wave` is a usual variable name in
scripts:

    >>> from architeuthis import presets
    >>> from architeuthis.common import Domain
    >>> domain = Domain(
    ...     min_lon=-70., max_lon=5., min_lat=30., max_lat=60.
    ... )
    >>> atmosphere = presets.atmosphere(
    ...     "ifs", domain, date=recent, fxx=steps, wind_factor=1.20
    ... )
    >>> wave = presets.wave("gfs", domain, date=recent, fxx=steps)
    >>> current = presets.current_mercator(domain, date=recent)
    >>> topography = presets.topography(domain)
    >>> vessel = presets.vessel(
    ...     "polar_eff60.nc", sfc=220., hotel_load=194., max_power=4100.
    ... )
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Union

import numpy as onp
import xarray as xr

from architeuthis.common import Domain, GUST_DEFAULT_RATIO, status
from architeuthis.exclusion import default_exclusion_zones
from architeuthis.forecast import (
    CopernicusForecast,
    DeterministicHerbieForecast,
    EnsembleHerbieForecast,
    Forecast,
    HRDPSForecast,
    Topography,
)
from architeuthis.vessel import Vessel


# gust: name of the gust variable once read, renamed to the `gust` interpolator.
ATMOSPHERE_MODELS = {
    "ifs": {
        "model": "ifs",
        "product": "oper",
        "regex": r":(?:10[uv]|10fg|msl):",
        "gust": "fg10",
    },
    "gfs": {
        "model": "gfs",
        "product": "pgrb2.0p25",
        "regex": r"(?:(?:U|V)GRD:10 m above ground|GUST:surface|PRES:surface)",
        "gust": "gust",
    },
}

# variables: variable once read -> interpolator required by RoutingAnalysis.
WAVE_MODELS = {
    "ifs": {
        "model": "ifs",
        "product": "wave",
        "regex": r":swh:|:mwd:",
        "variables": {"swh": "swh", "mwd": "mwd"},
    },
    "gfs": {
        "model": "gfs_wave",
        "product": "global.0p25",
        "regex": r":HTSGW:|:DIRPW:",
        "variables": {"swh": "swh", "dirpw": "mwd"},
    },
}

ENSEMBLE_ATMOSPHERE_MODELS = {
    "ifs": {"model": "ifs", "product": "enfo", "regex": r":10[u|v]:"},
}

ENSEMBLE_WAVE_MODELS = {
    "ifs": {"model": "ifs", "product": "waef", "regex": r":swh:|:mwd:"},
}

MERCATOR_CURRENT_DATASET = "cmems_mod_glo_phy_anfc_0.083deg_PT1H-m"

_TIME_LAT_LON = ("valid_time", "latitude", "longitude")
_TIME_MEMBER_LAT_LON = ("valid_time", "number", "latitude", "longitude")


def _settings(models: dict, model: str, kind: str) -> dict:
    if model not in models:
        raise ValueError(f"No {kind} preset for model {model!r}. Available: {sorted(models)}.")
    return models[model]


def atmosphere(
    model: str,
    domain: Domain = Domain(),
    date=None,
    fxx: Sequence[int] = (0,),
    wind_factor: float = 1.0,
    gust_factor: float = GUST_DEFAULT_RATIO,
    regex: Optional[str] = None,
    name: Optional[str] = None,
    verbose: bool = True,
) -> DeterministicHerbieForecast:
    """
    Wind forecast with the `u10`, `v10` and `gust` interpolators.

    These are the interpolators that routing requires.

    Where a gust is lower than the mean wind speed, which is not
    physical, it is replaced by the mean wind speed times `gust_factor`.

    Args:
        model: `"ifs"` or `"gfs"`.
        domain: Area to keep.
        date: Forecast base time. The latest run by default.
        fxx: Lead times, in hours.
        wind_factor: Correction applied to the wind and the gust, for
            example 1.20 at 10 m for global models.
        gust_factor: Ratio of gust to mean wind speed used to correct
            unphysical gusts.
        regex: Fields to download, replacing those of the preset. If the
            gust is not among them, no `gust` interpolator is added:
            `RoutingAnalysis` then uses the standard ratio.
        name: Name of the forecast. `wind_<model>` by default.
        verbose: Whether the forecast reports its progress.
    """
    settings = _settings(ATMOSPHERE_MODELS, model, "atmosphere")

    forecast = DeterministicHerbieForecast(
        name if name is not None else f"wind_{model}",
        model=settings["model"],
        product=settings["product"],
        regex=regex if regex is not None else settings["regex"],
        fxx=list(fxx),
        date=date,
        verbose=verbose,
        **domain,
    )
    forecast.load_data()

    gust_var = settings["gust"]
    if gust_var in forecast.data:
        # Sanity correction: gust can't be lower than the mean 10 m wind speed
        ds = forecast.data
        speed = onp.hypot(ds.u10, ds.v10)
        ds[gust_var] = ds[gust_var].where(ds[gust_var] >= speed, speed * gust_factor)
    else:
        status(f"🟦 No {gust_var} in {forecast.name}: gust left to the standard ratio.")

    forecast.add_interpolator("u10", *_TIME_LAT_LON, fac=wind_factor)
    forecast.add_interpolator("v10", *_TIME_LAT_LON, fac=wind_factor)
    if gust_var in forecast.data:
        forecast.add_interpolator(gust_var, *_TIME_LAT_LON, var_key="gust", fac=wind_factor)

    return forecast


def hrdps_atmosphere(
    domain: Domain = Domain(),
    date=None,
    fxx: Sequence[int] = tuple(range(0, 49)),
    wind_factor: float = 1.0,
    resolution: float = 0.0225,
    name: str = "wind_hrdps",
    verbose: bool = True,
) -> HRDPSForecast:
    """
    HRDPS continental wind with `u10` and `v10` interpolators.

    The wind is on a regular grid. Its domain must stay inside the area
    of the model, which covers Canada and its approaches.

    Args:
        domain: Area to keep.
        date: Forecast base time. The latest run by default.
        fxx: Lead times, in hours.
        wind_factor: Correction applied to the wind.
        resolution: Step of the regular grid, in degrees. About 2.5 km
            by default.
        name: Name of the forecast.
        verbose: Whether the forecast reports its progress.
    """
    forecast = HRDPSForecast(
        name,
        date=date,
        fxx=list(fxx),
        resolution=resolution,
        verbose=verbose,
        **domain,
    )
    forecast.load_data()

    forecast.add_interpolator("u10", *_TIME_LAT_LON, fac=wind_factor)
    forecast.add_interpolator("v10", *_TIME_LAT_LON, fac=wind_factor)

    return forecast


def wave(
    model: str,
    domain: Domain = Domain(),
    date=None,
    fxx: Sequence[int] = (0,),
    name: Optional[str] = None,
    verbose: bool = True,
) -> DeterministicHerbieForecast:
    """
    Wave forecast with the `swh` and `mwd` interpolators.

    These are the interpolators that routing requires.

    Args:
        model: `"ifs"` or `"gfs"`.
        domain: Area to keep.
        date: Forecast base time. The latest run by default.
        fxx: Lead times, in hours.
        name: Name of the forecast. `wave_<model>` by default.
        verbose: Whether the forecast reports its progress.
    """
    settings = _settings(WAVE_MODELS, model, "wave")

    forecast = DeterministicHerbieForecast(
        name if name is not None else f"wave_{model}",
        model=settings["model"],
        product=settings["product"],
        regex=settings["regex"],
        fxx=list(fxx),
        date=date,
        verbose=verbose,
        **domain,
    )
    forecast.load_data()

    for variable, key in settings["variables"].items():
        forecast.add_interpolator(variable, *_TIME_LAT_LON, var_key=key)

    return forecast


def _ensemble_interpolator(forecast, variable, stride, fac=1.0):
    forecast.add_interpolator(
        variable,
        *_TIME_MEMBER_LAT_LON,
        latitude_slice=slice(None, None, stride),
        longitude_slice=slice(None, None, stride),
        fac=fac,
    )


def ensemble_atmosphere(
    model: str = "ifs",
    domain: Domain = Domain(),
    date=None,
    fxx: Sequence[int] = (0,),
    wind_factor: float = 1.0,
    stride: int = 2,
    name: str = "wind_ens",
    verbose: bool = True,
) -> EnsembleHerbieForecast:
    """
    Ensemble wind forecast with the `u10` and `v10` interpolators.

    Select a member with `RoutingAnalysis(..., atmosphere_member=m)`.

    Args:
        model: `"ifs"`.
        domain: Area to keep.
        date: Forecast base time. The latest run by default.
        fxx: Lead times, in hours.
        wind_factor: Correction applied to the wind.
        stride: Keeps one latitude and longitude out of `stride`, as
            ensembles are memory heavy.
        name: Name of the forecast.
        verbose: Whether the forecast reports its progress.
    """
    forecast = EnsembleHerbieForecast(
        name,
        fxx=list(fxx),
        date=date,
        verbose=verbose,
        **_settings(ENSEMBLE_ATMOSPHERE_MODELS, model, "ensemble atmosphere"),
        **domain,
    )
    forecast.load_data()

    for variable in ("u10", "v10"):
        _ensemble_interpolator(forecast, variable, stride, fac=wind_factor)

    return forecast


def ensemble_wave(
    model: str = "ifs",
    domain: Domain = Domain(),
    date=None,
    fxx: Sequence[int] = (0,),
    stride: int = 2,
    name: str = "wave_ens",
    verbose: bool = True,
) -> EnsembleHerbieForecast:
    """
    Ensemble wave forecast with the `swh` and `mwd` interpolators.

    Select a member with `RoutingAnalysis(..., wave_member=m)`.

    Args:
        model: `"ifs"`.
        domain: Area to keep.
        date: Forecast base time. The latest run by default.
        fxx: Lead times, in hours.
        stride: Keeps one latitude and longitude out of `stride`, as
            ensembles are memory heavy.
        name: Name of the forecast.
        verbose: Whether the forecast reports its progress.
    """
    forecast = EnsembleHerbieForecast(
        name,
        fxx=list(fxx),
        date=date,
        verbose=verbose,
        **_settings(ENSEMBLE_WAVE_MODELS, model, "ensemble wave"),
        **domain,
    )
    forecast.load_data()

    for variable in ("swh", "mwd"):
        _ensemble_interpolator(forecast, variable, stride)

    return forecast


def current_mercator(
    domain: Domain = Domain(),
    date=None,
    end=None,
    stride: int = 3,
    time_stride: int = 3,
    name: str = "current",
    verbose: bool = True,
) -> CopernicusForecast:
    """
    Mercator SMOC currents with the `uo` and `vo` interpolators.

    Needs CMEMS credentials.

    Args:
        domain: Area to keep.
        date: First time. Today by default.
        end: Last time. The end of the product by default.
        stride: Keeps one latitude and longitude out of `stride`.
        time_stride: Keeps one time step out of `time_stride`.
        name: Name of the forecast.
        verbose: Whether the forecast reports its progress.
    """
    forecast = CopernicusForecast(
        name,
        dataset=MERCATOR_CURRENT_DATASET,
        variables=["uo", "vo"],
        date=date,
        end=end,
        verbose=verbose,
        **domain,
    )
    forecast.load_data()

    for variable in ("uo", "vo"):
        forecast.add_interpolator(
            variable,
            *_TIME_LAT_LON,
            latitude_slice=slice(None, None, stride),
            longitude_slice=slice(None, None, stride),
            time_slice=slice(None, None, time_stride),
        )

    return forecast


def calm_current(like: Forecast, name: str = "calm_current", verbose: bool = True) -> Forecast:
    """
    No current, with the `uo` and `vo` interpolators.

    It is on the grid of another forecast, to route without CMEMS
    credentials.

    Args:
        like: A deterministic forecast, whose `u10` gives the grid.
        name: Name of the forecast.
        verbose: Whether the forecast reports its progress.
    """
    calm = xr.zeros_like(like.data["u10"])

    forecast = Forecast(name, date=None, fxx=None, verbose=verbose)
    forecast.data = xr.Dataset({"uo": calm, "vo": calm})

    for variable in ("uo", "vo"):
        forecast.add_interpolator(variable, *_TIME_LAT_LON)

    return forecast


def vessel(
    filepath: str,
    sfc: Union[Callable, float] = 0.,
    hotel_load: Union[Callable, float] = 0.,
    max_power: float = 1e12,
    name: str = "vessel",
    label: Optional[str] = None,
    verbose: bool = True,
) -> Vessel:
    """
    A vessel from its polar file.

    It has the `bhp`, `max_bhp` and `sails_contribution` interpolators.

    Args:
        filepath: Polar NetCDF file.
        sfc: Specific fuel consumption, in g/kWh, or a function of the
            power. It must be given for a routing: the objective is zero
            without it.
        hotel_load: Hotel load, in kW, or a function of the power.
        max_power: Maximum brake power, in kW.
        name: Name of the vessel.
        label: Short identifier in reports and in the UI. By default,
            from the file name: `eff45` for `..._eff45.nc`.
        verbose: Whether the vessel reports its progress.
    """
    boat = Vessel(
        name,
        filepath=filepath,
        sfc=sfc,
        hotel_load=hotel_load,
        max_power=max_power,
        label=label,
        verbose=verbose,
    )
    boat.load_data()

    boat.add_interpolators()

    return boat


def topography(
    domain: Domain = Domain(),
    exclusion_zones: Optional[Sequence] = None,
    depth_offset: float = 0.,
    z_margin: float = 0.,
    name: str = "topo",
    verbose: bool = True,
) -> Topography:
    """
    ETOPO topography with the `z` interpolator.

    `z` is the signed distance to the navigable boundary.

    Args:
        domain: Area to keep.
        exclusion_zones: `ExclusionZone` objects or lists of `[lat,
            lon]` points. By default, `default_exclusion_zones()`, which
            fetches the iceberg limit. Pass `[]` for none.
        depth_offset: Treats water shallower than this as land, in m.
        z_margin: Clearance added to the distance, in nm.
        name: Name of the topography.
        verbose: Whether the topography reports its progress.
    """
    topo = Topography(
        name,
        depth_offset=depth_offset,
        z_margin=z_margin,
        exclusion_zones=default_exclusion_zones() if exclusion_zones is None else exclusion_zones,
        verbose=verbose,
        **domain,
    )
    topo.load_data()

    topo.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

    return topo

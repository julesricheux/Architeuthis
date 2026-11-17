# -*- coding: utf-8 -*-
"""
Route a voyage with a vessel whose polar is a function, not a NetCDF table.

A minimal version of simple_routing.py: one IFS run, calm water and a dummy
semi-empirical polar with fitted parameters. The polar depends on stw, swh, mwa,
the true wind averaged between 10 m and 100 m, and slightly on the air temperature.
The routing computes stw, swh and mwa, and the wind at both heights relative to the
vessel: tws and twa from u10 and v10, tws100 and twa100 from u100 and v100, which the
atmospheric forecast provides. The air temperature is not a routing quantity, so it
is read from that forecast too, which has a model of that name.

The routing also computes variables that the polar does not use, for constraints
and reports: the IFS gusts and a wave slope, swh / mwp, which the wave forecast
computes as a function of its own fields.

Needs no polar file and no credentials: IFS comes through Herbie, and the current
is calm. Run from the repository root, cell by cell (#%%) or as a script.

Created on Tue Nov 17 2026

@author: jrich
"""

import pandas as pd
import xarray as xr
import architeuthis.numpy as np

from architeuthis.core import DEFAULT_SOLVER_OPTIONS, RoutingAnalysis, Voyage
from architeuthis.forecast import DeterministicHerbieForecast, Forecast, Topography
from architeuthis.icebergs import berg_zone
from architeuthis.report import ReportCollection
from architeuthis.route import Route
from architeuthis.vessel import Vessel

domain = {"min_lon": -70.0, "max_lon": 5.0, "min_lat": 30.0, "max_lat": 60.0}
steps = list(range(0, 145, 3)) + list(range(150, 361, 6))
recent = pd.Timestamp("now").floor("1d8h").floor("1d")  # latest 00 UTC run

#%% DUMMY FUNCTION-BASED POLAR

# Fitted parameters of the dummy model, passed to it as fixed arguments.
parameters = {
    "c_calm": 1.2,  # kW/kt³: calm water power
    "c_wave": 3.0,  # kW/(m² kt): added power in head seas
    "c_sail": 0.11,  # kW/(kt² kt): sail power on a beam reach
    "k_air": 0.004,  # 1/°C: denser cold air, more sail power
    "t_ref": 15.0,  # °C: temperature of the fit
}


def dummy_polar(x, p):
    """
    Brake power of a dummy sailing vessel, and its components.

    Written with architeuthis.numpy and without branching on values, so
    that the routing differentiates through it.

    Args:
        x: Dict with stw, tws, twa, tws100, twa100, swh, mwa and
            air_temperature.
        p: Fitted parameters.

    Returns:
        The brake power in kW, and a dict of its components.
    """
    calm = p["c_calm"] * x["stw"] ** 3
    # Head seas (mwa = 0) cost the most, following seas nothing
    waves = p["c_wave"] * x["swh"] ** 2 * x["stw"] * (1. + np.cosd(x["mwa"])) / 2.
    # The sails see the wind between 10 m and 100 m: average of both heights.
    # The angles are absolute, in [0, 180], so their plain mean has no wrap
    tws = (x["tws"] + x["tws100"]) / 2.
    twa = (x["twa"] + x["twa100"]) / 2.
    # Sails pull most on a beam reach, a little more in cold air
    air_density = 1. - p["k_air"] * (x["air_temperature"] - p["t_ref"])
    sails = p["c_sail"] * air_density * tws ** 2 * x["stw"] * np.sind(twa) ** 2

    # The engine cannot absorb power: smooth floor at 10 % of the calm water power
    bhp = np.softmax(calm + waves - sails, 0.1 * calm, softness=10.)

    return bhp, {"calm": calm, "waves": waves, "sails": sails}


# tws100 and twa100: the routing computes them from u100 and v100, as tws and twa from u10 and v10
polar_inputs = ["stw", "tws", "twa", "tws100", "twa100", "swh", "mwa", "air_temperature"]

vessel = Vessel("dummy_vessel", sfc=196., hotel_load=172., max_power=4100.)  # no file, no load_data
vessel.add_function("bhp", dummy_polar, polar_inputs, args={"p": parameters})
vessel.add_function("max_bhp", dummy_polar, polar_inputs, args={"p": parameters})
vessel.add_function("sails_contribution", dummy_polar, polar_inputs, args={"p": parameters}, output="sails")

print(vessel("bhp", {
    "stw": 11., "tws": 20., "twa": 90., "tws100": 25., "twa100": 85.,
    "swh": 2., "mwa": 30., "air_temperature": 10.,
}))

#%% FORECASTS AND TOPOGRAPHY

# IFS 10 m and 100 m wind, 10 m gust and 2 m air temperature
atmosphere = DeterministicHerbieForecast(
    "wind_ifs", model="ifs", product="oper", regex=r":(?:10[uv]|10fg|100[uv]|2t):",
    fxx=steps, date=recent, **domain,
)
atmosphere.load_data()
for key in ("u10", "v10", "u100", "v100", "t2m"):
    atmosphere.add_interpolator(key, "valid_time", "latitude", "longitude", method="bspline")
# The gust, in m/s, under the key the routing reads for tws_gust and aws_gust
atmosphere.add_interpolator("fg10", "valid_time", "latitude", "longitude", var_key="gust", method="bspline")

# The routing reads the inputs of the polar from the atmosphere, wave and current
# forecasts: the atmosphere gets an air_temperature model, in °C as the polar takes it
atmosphere.add_function(
    "air_temperature",
    lambda x: atmosphere("t2m", x) - 273.15,
    inputs=["valid_time", "latitude", "longitude"],
)

wave = DeterministicHerbieForecast(
    "wave_ifs", model="ifs", product="wave", regex=r":swh:|:mwd:|:mwp:",
    fxx=steps, date=recent, **domain,
)
wave.load_data()
wave.add_wave_components()
for key in ("swh", "uw", "vw", "mwp"):
    wave.add_interpolator(key, "valid_time", "latitude", "longitude", method="bspline")

# Wave slope (m/s), a comfort criterion that the polar does not use. The period is 0
# on land and past the horizon, so it is smoothly kept above 1 s.
wave.add_function(
    "slope",
    lambda x: wave("swh", x) / np.softmax(wave("mwp", x), 1., softness=0.1),
    inputs=["valid_time", "latitude", "longitude"],
)

# Calm water on the IFS grid, so that no credentials are needed
calm = xr.zeros_like(atmosphere.data["u10"])
current = Forecast("calm_current", date=None, fxx=None, **domain)
current.data = xr.Dataset({"uo": calm, "vo": calm})
for key in ("uo", "vo"):
    current.add_interpolator(key, "valid_time", "latitude", "longitude")

topography = Topography("topography", exclusion_zones=[berg_zone], **domain)  # berg_zone: the latest IIP iceberg limit
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

#%% ROUTING

departure = np.array([50.489, -0.037])
arrival = np.array([46.781, -56.091])  # SPM pilot
route = Route(
    "channel_spm",
    [departure, [49.665, -6.241], [46.551, -53.321], arrival],  # Scilly, Cape Race
    divergences=[0., 0., 0.],
)

voyage = Voyage(
    "crossing",
    etd=recent + pd.Timedelta(hours=9),
    eta=recent + pd.Timedelta(days=8, hours=20),
    route=route,
)

def constraints(ctx):
    return [
        ctx["max_bhp"] < ctx["vessel"].max_power,
        ctx["z"] < 0.,
        # ctx["tws_gust"] < 45.,  # no gust over 45 kt
        # ctx["gust_excess"] < 15.,  # nor gusts 15 kt above the mean wind
        # ctx["slope"] < 0.5,  # nor steep seas
    ]


analysis = RoutingAnalysis(
    "ifs", vessel, voyage, atmosphere, wave, current, topography,
    constraints=constraints,
    # Computed along the route, in ctx for the constraints and in the reports:
    # gusts in kt (from the forecast "gust", else tws * GUST_DEFAULT_RATIO), any model
    # of the forecasts or vessel by its key ("wave.slope" to name the source), the
    # wind at 100 m, and functions of the variables before them.
    variables=[
        "tws_gust",
        "aws_gust",
        "slope",
        "tws100",
        "air_temperature",
        {"gust_excess": lambda ctx: ctx["tws_gust"] - ctx["tws"]},
    ],
)
solver_options = {"ipopt": DEFAULT_SOLVER_OPTIONS["ipopt"] | {"linear_solver": "mumps"}}

reports = ReportCollection()
reports.append(analysis.run(solve=False, solver_options=solver_options))  # reference route
reports.append(analysis.run(max_iter=1000, solver_options=solver_options))

print(reports.summary())
print(reports[-1].table(["tws", "tws_gust", "gust_excess", "swh", "slope"]))

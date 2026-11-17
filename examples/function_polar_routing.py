# -*- coding: utf-8 -*-
"""
Route a voyage with a vessel whose polar is a function, not a NetCDF table.

A minimal version of simple_routing.py: one IFS run, calm water and a dummy
semi-empirical polar with fitted parameters. The polar depends on stw, tws, twa,
swh and mwa, and slightly on the air temperature. The routing computes the first
five; the air temperature is not a routing quantity, so it is read from the
atmospheric forecast, which has a model of that name.

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
        x: Dict with stw, tws, twa, swh, mwa and air_temperature.
        p: Fitted parameters.

    Returns:
        The brake power in kW, and a dict of its components.
    """
    calm = p["c_calm"] * x["stw"] ** 3
    # Head seas (mwa = 0) cost the most, following seas nothing
    waves = p["c_wave"] * x["swh"] ** 2 * x["stw"] * (1. + np.cosd(x["mwa"])) / 2.
    # Sails pull most on a beam reach, a little more in cold air
    air_density = 1. - p["k_air"] * (x["air_temperature"] - p["t_ref"])
    sails = p["c_sail"] * air_density * x["tws"] ** 2 * x["stw"] * np.sind(x["twa"]) ** 2

    # The engine cannot absorb power: smooth floor at 10 % of the calm water power
    bhp = np.softmax(calm + waves - sails, 0.1 * calm, softness=10.)

    return bhp, {"calm": calm, "waves": waves, "sails": sails}


polar_inputs = ["stw", "tws", "twa", "swh", "mwa", "air_temperature"]

vessel = Vessel("dummy_vessel", sfc=196., hotel_load=172., max_power=4100.)  # no file, no load_data
vessel.add_function("bhp", dummy_polar, polar_inputs, args={"p": parameters})
vessel.add_function("max_bhp", dummy_polar, polar_inputs, args={"p": parameters})
vessel.add_function("sails_contribution", dummy_polar, polar_inputs, args={"p": parameters}, output="sails")

print(vessel("bhp", {"stw": 11., "tws": 20., "twa": 90., "swh": 2., "mwa": 30., "air_temperature": 10.}))

#%% FORECASTS AND TOPOGRAPHY

# IFS 10 m wind and 2 m air temperature
atmosphere = DeterministicHerbieForecast(
    "wind_ifs", model="ifs", product="oper", regex=r":(?:10[uv]|2t):",
    fxx=steps, date=recent, **domain,
)
atmosphere.load_data()
atmosphere.add_interpolator("u10", "valid_time", "latitude", "longitude", method="bspline")
atmosphere.add_interpolator("v10", "valid_time", "latitude", "longitude", method="bspline")
atmosphere.add_interpolator("t2m", "valid_time", "latitude", "longitude", method="bspline")

# The routing reads the inputs of the polar from the atmosphere, wave and current
# forecasts: the atmosphere gets an air_temperature model, in °C as the polar takes it
atmosphere.add_function(
    "air_temperature",
    lambda x: atmosphere("t2m", x) - 273.15,
    inputs=["valid_time", "latitude", "longitude"],
)

wave = DeterministicHerbieForecast(
    "wave_ifs", model="ifs", product="wave", regex=r":swh:|:mwd:",
    fxx=steps, date=recent, **domain,
)
wave.load_data()
wave.add_wave_components()
for key in ("swh", "uw", "vw"):
    wave.add_interpolator(key, "valid_time", "latitude", "longitude", method="bspline")

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

analysis = RoutingAnalysis("ifs", vessel, voyage, atmosphere, wave, current, topography)
solver_options = {"ipopt": DEFAULT_SOLVER_OPTIONS["ipopt"] | {"linear_solver": "mumps"}}

reports = ReportCollection()
reports.append(analysis.run(solve=False, solver_options=solver_options))  # reference route
reports.append(analysis.run(max_iter=1000, solver_options=solver_options))

print(reports.summary())

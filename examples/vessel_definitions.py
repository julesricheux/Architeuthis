# -*- coding: utf-8 -*-
"""
Compare ways of defining the consumption of a vessel, on a short-sea leg.

The routing only needs the consumption of the vessel, its objective. The
vessel gives it through the first of these models that it has:
hourly_consumption (L/h), total_power (kW) burnt at the sfoc, or bhp plus the
hotel load burnt at the sfoc. Each model can be a function, a table or a
constant, and the hotel load and sfoc can be numbers or models too.

Five vessels share one dummy brake power polar, defined five ways, on a
crossing of the Bay of Biscay from Montoir to Bilbao: IFS wind, no waves and
no current. Three definitions are the same vessel and burn the same fuel, the
table is close to them, and the sfoc curve burns more.

Needs no polar file and no credentials: IFS comes through Herbie, and the
waves and the current are left out, so the routing takes them as zero. Run from the repository root, cell by cell (#%%) or
as a script.

Created on Thu Nov 19 2026

@author: jrich
"""

import pandas as pd
import xarray as xr
import architeuthis.numpy as np

from architeuthis.core import RoutingAnalysis, Voyage
from architeuthis.forecast import DeterministicHerbieForecast, Topography
from architeuthis.report import ReportCollection
from architeuthis.fuels import FUELS
from architeuthis.vessel import Vessel

domain = {"min_lon": -8.0, "max_lon": 0.0, "min_lat": 42.0, "max_lat": 49.0}
steps = list(range(0, 73, 3))
recent = (pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta("9h")).floor("1d")  # latest 00 UTC run

HOTEL_LOAD = 172.  # kW
SFOC = 196.  # g/kWh
MAX_POWER = 4100.  # kW

#%% ONE DUMMY POLAR


def dummy_bhp(x):
    """
    Brake power of a dummy sailing vessel, in kW.

    Calm water power, minus the sails on a beam reach, with a smooth floor
    at 10 % of the calm water power. Written with architeuthis.numpy, so it
    works on numbers, arrays and CasADi symbols alike.

    Args:
        x: Dict with stw, tws and twa (kt, kt, deg).

    Returns:
        The brake power, in kW.
    """
    calm = 1.2 * x["stw"] ** 3
    sails = 0.11 * x["tws"] ** 2 * x["stw"] * np.sind(x["twa"]) ** 2
    return np.softmax(calm - sails, 0.1 * calm, softness=10.)


def sfoc_curve(x):
    """
    Specific fuel oil consumption of the engine, in g/kWh.

    Dummy curve, lowest at 600 kW and rising on both sides. The fuel,
    power times sfoc, then grows faster than the power, which the
    optimizer handles well. A curve that falls with the power makes the
    fuel concave in the power, harder to optimize.

    Args:
        x: Dict with total_power, in kW.

    Returns:
        The sfoc, in g/kWh.
    """
    return SFOC + 2e-5 * (x["total_power"] - 600.) ** 2


polar_inputs = ["stw", "tws", "twa"]

#%% FIVE VESSEL DEFINITIONS

# 1. The brake power as a function, with a constant hotel load and sfoc
bhp_function = Vessel("bhp_function", hotel_load=HOTEL_LOAD, sfoc=SFOC, max_power=MAX_POWER)
bhp_function.add_function("bhp", dummy_bhp, polar_inputs)

# 2. The same brake power as a table, as read from a polar file: here the
# function on a grid, with the five axes of a table, the waves being calm.
# A B-spline is smooth, which the optimizer prefers to the kinks of "linear".
axes = {
    "stw": np.arange(4., 17., 1.),
    "tws": np.arange(0., 45., 5.),
    "twa": np.arange(0., 181., 15.),
    "hs": np.array([0., 4.]),
    "wa": np.array([0., 180.]),
}
grid = dict(zip(axes, np.meshgrid(*axes.values(), indexing="ij")))
bhp_table = Vessel("bhp_table", hotel_load=HOTEL_LOAD, sfoc=SFOC, max_power=MAX_POWER)
bhp_table.data = xr.Dataset({"bhp": (tuple(axes), dummy_bhp(grid))}, coords=axes)
bhp_table.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa", method="bspline")

# 3. The brake power as a function, the hotel load as a constant model and
# the sfoc as a curve of the total power (bhp + hotel load)
sfoc_model = Vessel("sfoc_curve", max_power=MAX_POWER)
sfoc_model.add_function("bhp", dummy_bhp, polar_inputs)
sfoc_model.add_constant("hotel_load", HOTEL_LOAD)
sfoc_model.add_function("sfoc", sfoc_curve, ["total_power"])

# 4. The total power (propulsion and hotel) as a function, burnt at the sfoc
total_power = Vessel("total_power", sfoc=SFOC, max_power=MAX_POWER)
total_power.add_function("total_power", lambda x: dummy_bhp(x) + HOTEL_LOAD, polar_inputs)

# 5. The fuel consumption itself, in L/h (kg/h over the fuel density, that of
# marine diesel oil, the default fuel_type): no power, so no power limit
FUEL_DENSITY = FUELS["mdo"].density # kg/L
hourly = Vessel("hourly_consumption", max_power=None)
hourly.add_function("hourly_consumption", lambda x: SFOC / 1e3 * (dummy_bhp(x) + HOTEL_LOAD) / FUEL_DENSITY, polar_inputs)

vessels = [bhp_function, bhp_table, sfoc_model, total_power, hourly]

for vessel in vessels:
    print(f"{vessel.name}: {vessel.consumption_model}, computes {vessel.consumption_quantities()}")

#%% WIND AND TOPOGRAPHY

atmosphere = DeterministicHerbieForecast(
    "wind_ifs", model="ifs", product="oper", regex=r":10[uv]:",
    fxx=steps, date=recent, **domain,
)
atmosphere.load_data()
for key in ("u10", "v10"):
    atmosphere.add_interpolator(key, "valid_time", "latitude", "longitude")

topography = Topography("topography", **domain)
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

#%% ROUTING

voyage = Voyage(
    "biscay",
    etd=recent + pd.Timedelta(hours=9),
    eta=recent + pd.Timedelta(hours=31),
    departure=np.array([47.112, -2.405]),  # Montoir pilot
    arrival=np.array([43.420, -3.100]),  # Bilbao
)
# A short leg has few variables: the exact Hessian (IPOPT's default) is cheap,
# and the same vessel defined in different ways then reaches the same optimum
solver_options = {"ipopt": {"linear_solver": "mumps"}}

reports = ReportCollection()
for vessel in vessels:
    # No wave nor current given: a flat sea and no current, their fields being zero
    analysis = RoutingAnalysis("biscay", vessel, voyage, atmosphere, topography=topography, verbose=False)
    reports.append(analysis.run(solve=False, solver_options=solver_options))  # the same reference route
    reports.append(analysis.run(max_iter=300, solver_options=solver_options))

summary = reports.summary()
print(summary[["vessel", "solve", "status", "fuel", "sog", "max_z"]])

# Each report holds the consumption quantities of its definition only
print(reports.select(vessel="sfoc_curve", solve=1)[0].table(["sog", "bhp", "total_power", "sfoc", "hourly_consumption"]))

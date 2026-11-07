# -*- coding: utf-8 -*-
"""
Passage planning with stored routes and passage plans.

1. Define the FRMTX - PMFSP route (Montoir to Saint-Pierre via Penmarc'h and Cape Race)
   once, store it with its reverse, and reload it.
2. Restart the voyage from a position at sea, keeping the same ETA.
3. Optimize the passage with IFS forecasts and store the resulting passage plan.
4. Evaluate that plan, positions fixed, with GFS forecasts and another vessel, to
   measure how sensitive its consumption is to the conditions it was optimized for.

Cell 1 needs neither network nor data. The other cells download IFS and GFS forecasts
through Herbie (no credentials) and need a vessel polar NetCDF: set POLAR below.
Run from the repository root, cell by cell (#%%) or as a script.
"""

import os

import pandas as pd

from architeuthis.route import Route, RouteLibrary, Waypoint
from architeuthis.voyage import PassagePlan, PassagePlanLibrary, Voyage

POLAR = os.path.expanduser("~/data/polars/vessel_polar.nc")

#%% 1. ROUTES: DEFINE ONCE, STORE, REVERSE, RELOAD

routes = RouteLibrary()  # ~/data/route_library/

if "FRMTX-PMFSP" not in routes:
    crossing = Route(
        "FRMTX-PMFSP",
        [
            Waypoint(47.112116788143474, -2.4051169026612866, "FRMTX"),  # Montoir pilot
            Waypoint(47.72529611513597, -4.379839003826363, "Penmarch"),
            Waypoint(46.551, -53.321, "Cape Race"),
            Waypoint(46.781, -56.091, "PMFSP"),  # Saint-Pierre pilot
        ],
        # Great circles between waypoints. The ocean segment may bend by +/- 0.4 when
        # the deviation factor varies (route_minus and route_plus).
        divergences=[0.0, 0.0, 0.0],
        spread=[0.0, 0.4, 0.0],
    )
    routes.save(crossing)
    routes.save(crossing.reversed())  # PMFSP-FRMTX, same path the other way

crossing = routes.load("FRMTX-PMFSP")
print(crossing)
print(routes.load("PMFSP-FRMTX"))

#%% 2. VOYAGE, AND THE SAME VOYAGE RESTARTED FROM A POSITION AT SEA

etd = pd.Timestamp("now", tz="UTC").floor("1d")
eta = etd + pd.Timedelta(days=11)

voyage = Voyage("crossing", etd=etd, eta=eta, route=crossing)

# Two days later the vessel reports its position: route the rest of the leg, same ETA.
# Penmarc'h is behind, so the restarted route heads for Cape Race.
position_time = etd + pd.Timedelta(days=2)
rest_of_voyage = voyage.from_position([48.2, -12.6], time=position_time)
print(rest_of_voyage.route)
print(f"Remaining {rest_of_voyage.distance:.0f} nm at {rest_of_voyage.transit_sog:.1f} kt.")

#%% 3. OPTIMIZE WITH IFS AND STORE THE PASSAGE PLAN

import xarray as xr

from architeuthis.core import DEFAULT_SOLVER_OPTIONS, RoutingAnalysis, exclusion_zones
from architeuthis.forecast import DeterministicHerbieForecast, Forecast, Topography
from architeuthis.vessel import Vessel

domain = {"min_lon": -60.0, "max_lon": 0.0, "min_lat": 38.0, "max_lat": 56.0}
steps = list(range(0, 145, 3)) + list(range(150, 361, 6))
forecast_date = position_time.tz_localize(None).floor("12h") - pd.Timedelta(hours=12)


def herbie_fields(name, keys, **herbie):
    forecast = DeterministicHerbieForecast(name, fxx=steps, date=forecast_date, **domain, **herbie)
    forecast.load_data()
    for variable, key in keys.items():
        forecast.add_interpolator(variable, "valid_time", "latitude", "longitude", var_key=key)
    return forecast


def build_vessel(name, polar=POLAR, **performance):
    vessel = Vessel(name, filepath=polar, **performance)
    vessel.load_data()
    for key in ("bhp", "max_bhp", "sails_contribution"):
        vessel.add_interpolator(key, "stw", "tws", "twa", "hs", "wa", method="linear")
    return vessel


ifs_wind = herbie_fields("wind_ifs", {"u10": "u10", "v10": "v10"}, model="ifs", product="oper", regex=r":10[u|v]:")
ifs_wave = herbie_fields("wave_ifs", {"swh": "swh", "mwd": "mwd"}, model="ifs", product="wave", regex=r":swh:|:mwd:")
# Calm water on the IFS grid, so that no credentials are needed. For real currents use
# CopernicusForecast (Mercator SMOC, CMEMS credentials) as in post_leg_rewind.py.
calm = xr.zeros_like(ifs_wind.data["u10"])
current = Forecast("calm_current", date=None, fxx=None, **domain)
current.data = xr.Dataset({"uo": calm, "vo": calm})
for key in ("uo", "vo"):
    current.add_interpolator(key, "valid_time", "latitude", "longitude")

topography = Topography("topography", exclusion_zones=exclusion_zones, **domain)
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

vessel = build_vessel("vessel", sfc=196.0, hotel_load=172.0, max_power=3e3)

analysis = RoutingAnalysis("ifs", vessel, rest_of_voyage, ifs_wind, ifs_wave, current, topography)
report = analysis.run(
    max_iter=1000,
    solver_options={"ipopt": DEFAULT_SOLVER_OPTIONS["ipopt"] | {"linear_solver": "mumps"}},
)
print(f"IFS optimum: {report['fuel']:.2f} t, status {report['status']}, max z {max(report['z']):.2f} nm.")

plans = PassagePlanLibrary()  # ~/data/passage_plans/
plan = analysis.passage_plan  # also built from any report: PassagePlan.from_report(report, route, name)
plans.save(plan, overwrite=True)

#%% 4. OPEN-LOOP SENSITIVITY: SAME POSITIONS, OTHER CONDITIONS

plan = PassagePlan.load(plans.path(plan.name))

gfs_wind = herbie_fields("wind_gfs", {"u10": "u10", "v10": "v10"}, model="gfs", product="pgrb2.0p25", regex=r"(?:U|V)GRD:10 m")
gfs_wave = herbie_fields("wave_gfs", {"swh": "swh", "dirpw": "mwd"}, model="gfs_wave", product="global.0p25", regex=r":HTSGW:|:DIRPW:")

heavier_hotel_load = build_vessel("vessel_hotel_250", sfc=196.0, hotel_load=250.0, max_power=3e3)

scenarios = {
    "IFS (as optimized)": (vessel, ifs_wind, ifs_wave),
    "GFS wind and waves": (vessel, gfs_wind, gfs_wave),
    "IFS, hotel load 250 kW": (heavier_hotel_load, ifs_wind, ifs_wave),
}

for label, (scenario_vessel, wind, wave) in scenarios.items():
    evaluation = RoutingAnalysis(label, scenario_vessel, plan.voyage(), wind, wave, current, topography, verbose=False).evaluate(plan)
    print(
        f"{label:<24} {evaluation['fuel']:7.2f} t"
        f"  ({evaluation['fuel'] / report['fuel'] - 1:+.1%})"
        f"  max constraint violation {evaluation['max_constraint_violation']:.2f}"
    )

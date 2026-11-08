# -*- coding: utf-8 -*-
"""
Passage planning with stored routes and passage plans.

1. Define the FRMTX - PMFSP route (Montoir to Saint-Pierre via Penmarc'h and Cape Race)
   once, store it with its reverse, and reload it.
2. Restart the voyage from a position at sea, keeping the same ETA.
3. Optimize the passage with IFS forecasts and store the resulting passage plan.
4. Evaluate that plan, positions fixed, with GFS forecasts and another vessel, to
   measure how sensitive its consumption is to the conditions it was optimized for.

Cells 1 and 2 need neither network nor data. The other cells download IFS and GFS forecasts
through Herbie (no credentials) and need a vessel polar NetCDF: set POLAR_FILE below.
Run from the repository root, cell by cell (#%%) or as a script.
"""

import os

import pandas as pd

from architeuthis.route import Route, RouteLibrary, Waypoint
from architeuthis.voyage import PassagePlanLibrary, Voyage

POLAR_FILE = os.path.expanduser("~/data/polars/vessel_polar.nc")

#%% 1. ROUTES: DEFINE ONCE, STORE, REVERSE, RELOAD

routes = RouteLibrary() # ~/data/route_library/

if "FRMTX-PMFSP" not in routes:
    crossing = Route(
        "FRMTX-PMFSP",
        [
            Waypoint(47.112116788143474, -2.4051169026612866, "FRMTX"), # Montoir pilot
            Waypoint(47.72529611513597, -4.379839003826363, "Penmarch"),
            Waypoint(46.551, -53.321, "Cape Race"),
            Waypoint(46.781, -56.091, "PMFSP"), # Saint-Pierre pilot
        ],
        # Great circles between waypoints. The ocean segment may bend by +/- 0.4 when
        # the deviation factor varies (route_minus and route_plus).
        divergences=[0., 0., 0.],
        spread=[0., 0.4, 0.],
    )
    routes.save(crossing)
    routes.save(crossing.reversed()) # PMFSP-FRMTX, same path the other way

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

from architeuthis import presets
from architeuthis.common import Domain
from architeuthis.core import DEFAULT_SOLVER_OPTIONS, RoutingAnalysis

domain = Domain(min_lon=-60., max_lon=0., min_lat=38., max_lat=56.)
steps = list(range(0, 145, 3)) + list(range(150, 361, 6)) # lead times, in hours
forecast_date = position_time.tz_localize(None).floor("12h") - pd.Timedelta(hours=12)

ifs_wind = presets.atmosphere("ifs", domain, date=forecast_date, fxx=steps)
ifs_wave = presets.wave("ifs", domain, date=forecast_date, fxx=steps)

# No current, so that no credentials are needed. For real currents, use
# presets.current_mercator, with CMEMS credentials, as in simple_routing.py.
current = presets.calm_current(ifs_wind)

topography = presets.topography(domain)
vessel = presets.vessel(POLAR_FILE, sfc=196., hotel_load=172., max_power=3e3)

analysis = RoutingAnalysis("ifs", vessel, rest_of_voyage, ifs_wind, ifs_wave, current, topography)
report = analysis.run(
    max_iter=1000,
    solver_options={"ipopt": DEFAULT_SOLVER_OPTIONS["ipopt"] | {"linear_solver": "mumps"}},
)
print(f"IFS optimum: {report['fuel']:.2f} t, status {report['status']}, max z {max(report['z']):.2f} nm.")

plans = PassagePlanLibrary() # ~/data/passage_plans/
plan = analysis.passage_plan # also built from any report: PassagePlan.from_report(report, route, name)
plans.save(plan, overwrite=True)

#%% 4. OPEN-LOOP SENSITIVITY: SAME POSITIONS, OTHER CONDITIONS

plan = plans.load(plan.name)

gfs_wind = presets.atmosphere("gfs", domain, date=forecast_date, fxx=steps)
gfs_wave = presets.wave("gfs", domain, date=forecast_date, fxx=steps)

heavier_hotel_load = presets.vessel(POLAR_FILE, sfc=196., hotel_load=250., max_power=3e3)

scenarios = {
    "IFS (as optimized)": (vessel, ifs_wind, ifs_wave),
    "GFS wind and waves": (vessel, gfs_wind, gfs_wave),
    "IFS, hotel load 250 kW": (heavier_hotel_load, ifs_wind, ifs_wave),
}

for label, (scenario_vessel, wind, wave) in scenarios.items():
    # No voyage: the plan gives the positions and times.
    evaluation = RoutingAnalysis(label, scenario_vessel, None, wind, wave, current, topography, verbose=False).evaluate(plan)
    print(
        f"{label:<24} {evaluation['fuel']:7.2f} t"
        f"  ({evaluation['fuel'] / report['fuel'] - 1:+.1%})"
        f"  max constraint violation {evaluation['max_constraint_violation']:.2f}"
    )

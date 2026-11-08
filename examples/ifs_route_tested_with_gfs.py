# -*- coding: utf-8 -*-
"""
Optimize FRMTX - PMFSP with IFS, then test the same passage plan with GFS.

1. Load the FRMTX - PMFSP route (via Penmarc'h and Cape Race) from the route library,
   or define and store it on the first run.
2. Optimize the passage with the IFS wind and wave forecasts.
3. Store the resulting passage plan (timed positions).
4. Evaluate that plan with the GFS forecasts, without moving any point: same positions,
   same times, only the weather changes. No optimization is run for this step.

Data: IFS and GFS through Herbie (no credentials), Mercator currents through
Copernicus Marine (CMEMS_USER, CMEMS_PWD) and a vessel polar NetCDF (POLAR_FILE).
Run from the repository root, cell by cell (#%%) or as a script.
"""

import os

import numpy as np
import pandas as pd

from architeuthis import presets
from architeuthis.common import Domain
from architeuthis.core import RoutingAnalysis
from architeuthis.route import Route, RouteLibrary, Waypoint
from architeuthis.toolbox.plot_utils import draw
from architeuthis.voyage import PassagePlanLibrary, Voyage

POLAR_FILE = os.path.expanduser("~/data/polars/neoliner_origin_v2-2-0_mc0_sc0_28up_28down_7buff_5m_eff60.nc")

DOMAIN = Domain(min_lon=-70., max_lon=5., min_lat=30., max_lat=60.)
FORECAST_DATE = pd.Timestamp("now").floor("1d") # base time of the forecasts: today, 00 UTC
STEPS = list(range(0, 145, 3)) + list(range(150, 361, 6)) # lead times, in hours
WIND_FACTOR = 1.20 # speed correction of global models at 10 m

SOLVER_OPTIONS = {
    "ipopt": {
        "acceptable_tol": 1e2,
        "linear_solver": "mumps",
        "hessian_approximation": "limited-memory",
    },
}

#%% ROUTE AND VOYAGE

routes = RouteLibrary() # ~/data/route_library/

if "FRMTX-PMFSP" not in routes:
    route = Route(
        "FRMTX-PMFSP",
        [
            Waypoint(47.112116788143474, -2.4051169026612866, "FRMTX"), # Montoir pilot
            Waypoint(47.72529611513597, -4.379839003826363, "Penmarch"),
            Waypoint(46.551, -53.321, "Cape Race"),
            Waypoint(46.781, -56.091, "PMFSP"), # SPM pilot
        ],
    )
    routes.save(route)
    routes.save(route.reversed()) # PMFSP-FRMTX, for the return passage

route = routes.load("FRMTX-PMFSP")
print(route)

# Departure 12 h after the forecast base time, arrival 10 days later.
etd = FORECAST_DATE + pd.Timedelta(hours=12)
eta = etd + pd.Timedelta(days=10)

voyage = Voyage("FRMTX-PMFSP", etd=etd, eta=eta, route=route)
print(f"{voyage.distance:.0f} nm at {voyage.transit_sog:.1f} kt on average.")

#%% VESSEL, FORECASTS AND TOPOGRAPHY

vessel = presets.vessel(POLAR_FILE, sfc=220., hotel_load=194., max_power=4100.)

ATMOS = {
    model: presets.atmosphere(model, DOMAIN, date=FORECAST_DATE, fxx=STEPS, wind_factor=WIND_FACTOR)
    for model in ("ifs", "gfs")
}
WAVE = {model: presets.wave(model, DOMAIN, date=FORECAST_DATE, fxx=STEPS) for model in ("ifs", "gfs")}

# The same currents are used for both models, so only the wind and waves differ.
current = presets.current_mercator(DOMAIN, date=FORECAST_DATE)
topography = presets.topography(DOMAIN)

#%% 1. OPTIMIZE WITH IFS

ifs_analysis = RoutingAnalysis("ifs", vessel, voyage, ATMOS["ifs"], WAVE["ifs"], current, topography)
ifs_report = ifs_analysis.run(max_iter=1000, solver_options=SOLVER_OPTIONS)

if ifs_report["status"] != 1 or np.max(ifs_report["z"]) > 0.:
    print(f"⚠️ Warning: status {ifs_report['status']}, max z {np.max(ifs_report['z']):.2f} nm. Check the IFS optimum.")

# The optimal passage plan: timed positions, route, schedule and how they were obtained.
plan = ifs_analysis.passage_plan
plan.name = f"{plan.name}_ifs"
plans = PassagePlanLibrary() # ~/data/passage_plans/
plans.save(plan, overwrite=True)

#%% 2. TEST THE IFS PLAN WITH GFS, POINTS UNCHANGED

# Reload the plan from storage, as any later session would.
plan = plans.load(plan.name)

# No voyage: the plan gives the positions and times, and nothing is optimized.
gfs_analysis = RoutingAnalysis("gfs", vessel, None, ATMOS["gfs"], WAVE["gfs"], current, topography)
gfs_report = gfs_analysis.evaluate(plan)

assert np.allclose(gfs_report["lat"], ifs_report["lat"]) and np.allclose(gfs_report["lon"], ifs_report["lon"])

#%% 3. COMPARE

reports = [ifs_report, gfs_report]

summary = pd.DataFrame(
    [
        {
            "fuel [t]": report["fuel"],
            "mean TWS [kt]": np.mean(report["tws"]),
            "max Hs [m]": np.max(report["swh"]),
            "mean STW [kt]": np.mean(report["stw"]),
            "max BHP [kW]": np.max(report["max_bhp"]),
        }
        for report in reports
    ],
    index=["IFS (optimized)", "GFS (same points)"],
)
print(summary.round(2))
print()
print(f"Same plan, GFS instead of IFS: {gfs_report['fuel'] - ifs_report['fuel']:+.2f} t "
      f"({gfs_report['fuel'] / ifs_report['fuel'] - 1:+.1%}).")
print(f"Largest constraint violation with GFS: {gfs_report['max_constraint_violation']:.2f} "
      f"(positive means the plan breaks a constraint, e.g. max_bhp above max_power).")

#%% 4. PLOT BOTH (same track, wind from each model)

draw(reports, barbs=False)

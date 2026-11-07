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
Copernicus Marine (CMEMS_USER, CMEMS_PWD) and a vessel polar NetCDF (VESSEL_FILE).
Run from the repository root, cell by cell (#%%) or as a script.
"""

import pandas as pd
import architeuthis.numpy as np

from architeuthis.vessel import Vessel
from architeuthis.route import Route, RouteLibrary, Waypoint
from architeuthis.voyage import Voyage, PassagePlanLibrary
from architeuthis.core import RoutingAnalysis, exclusion_zones
from architeuthis.forecast import DeterministicHerbieForecast, CopernicusForecast, Topography

VESSEL_FILE = r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_28up_28down_7buff_5m_eff60.nc"

minimum_longitude = -70.
maximum_longitude = 5.
minimum_latitude = 30.
maximum_latitude = 60.

steps = list(range(0, 145, 3)) + list(range(150, 361, 6)) # fxx
recent = pd.Timestamp("now").floor("1d") # latest 00 UTC run

global_corr_fac = 1.20 # global models speed correction (120% @ 10m, 105% @ 100m)

solver_options = {
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
etd = recent + pd.Timedelta(hours=12)
eta = etd + pd.Timedelta(days=10)

voyage = Voyage("FRMTX-PMFSP", etd=etd, eta=eta, route=route)
print(f"{voyage.distance:.0f} nm at {voyage.transit_sog:.1f} kt on average.")

#%% VESSEL

vessel = Vessel(
    "vessel",
    filepath=VESSEL_FILE,
    sfc=220.,
    hotel_load=194.,
    max_power=4100.,
)
vessel.load_data()
for key in ("bhp", "max_bhp", "sails_contribution"):
    vessel.add_interpolator(key, "stw", "tws", "twa", "hs", "wa", method="linear")

#%% FORECASTS: IFS AND GFS WIND AND WAVES, MERCATOR CURRENTS, TOPOGRAPHY

domain = dict(
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
)

ATMOS = {
    "ifs": DeterministicHerbieForecast(
        "wind_ifs", model="ifs", product="oper", regex=r":10[uv]:",
        fxx=steps, date=recent, **domain,
    ),
    "gfs": DeterministicHerbieForecast(
        "wind_gfs", model="gfs", product="pgrb2.0p25", regex=r"(?:U|V)GRD:10 m above ground",
        fxx=steps, date=recent, **domain,
    ),
}
for atmos in ATMOS.values():
    atmos.load_data()
    atmos.add_interpolator("u10", "valid_time", "latitude", "longitude", fac=global_corr_fac)
    atmos.add_interpolator("v10", "valid_time", "latitude", "longitude", fac=global_corr_fac)

WAVE = {
    "ifs": DeterministicHerbieForecast(
        "wave_ifs", model="ifs", product="wave", regex=r":swh:|:mwd:",
        fxx=steps, date=recent, **domain,
    ),
    "gfs": DeterministicHerbieForecast(
        "wave_gfs", model="gfs_wave", product="global.0p25", regex=r":HTSGW:|:DIRPW:",
        fxx=steps, date=recent, **domain,
    ),
}
WAVE["ifs"].load_data()
WAVE["ifs"].add_interpolator("swh", "valid_time", "latitude", "longitude")
WAVE["ifs"].add_interpolator("mwd", "valid_time", "latitude", "longitude")
WAVE["gfs"].load_data()
WAVE["gfs"].add_interpolator("swh", "valid_time", "latitude", "longitude", var_key="swh")
WAVE["gfs"].add_interpolator("dirpw", "valid_time", "latitude", "longitude", var_key="mwd")

# The same currents are used for both models, so only the wind and waves differ.
current = CopernicusForecast(
    "current", dataset="cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", variables=["uo", "vo"],
    date=recent, **domain,
)
current.load_data()
for key in ("uo", "vo"):
    current.add_interpolator(
        key, "valid_time", "latitude", "longitude",
        latitude_slice=slice(None, None, 3),
        longitude_slice=slice(None, None, 3),
        time_slice=slice(None, None, 3),
    )

topo = Topography(
    "topo", depth_offset=0., z_margin=0.,
    exclusion_zones=exclusion_zones,
    **domain,
)
topo.load_data()
topo.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

#%% 1. OPTIMIZE WITH IFS

ifs_analysis = RoutingAnalysis(
    "ifs",
    vessel,
    voyage,
    ATMOS["ifs"],
    WAVE["ifs"],
    current,
    topo,
)
ifs_report = ifs_analysis.run(max_iter=1000, solver_options=solver_options)

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

gfs_analysis = RoutingAnalysis(
    "gfs",
    vessel,
    plan.voyage(),
    ATMOS["gfs"],
    WAVE["gfs"],
    current,
    topo,
)
gfs_report = gfs_analysis.evaluate(plan) # no optimization: positions and times are kept

assert np.allclose(gfs_report["lat"], ifs_report["lat"]) and np.allclose(gfs_report["lon"], ifs_report["lon"])

#%% 3. COMPARE

summary = pd.DataFrame(
    [
        {
            "fuel [t]": report["fuel"],
            "mean TWS [kt]": np.mean(report["tws"]),
            "max Hs [m]": np.max(report["swh"]),
            "mean STW [kt]": np.mean(report["stw"]),
            "max BHP [kW]": np.max(report["max_bhp"]),
        }
        for report in (ifs_report, gfs_report)
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

from architeuthis.toolbox.plot_utils import plot_route

reports = [ifs_report, gfs_report]
plot_route(
    [r["lon"] for r in reports],
    [r["lat"] for r in reports],
    [r["clon"] for r in reports],
    [r["clat"] for r in reports],
    [r["tws"] for r in reports],
    [r["twd"] for r in reports],
    False,
)

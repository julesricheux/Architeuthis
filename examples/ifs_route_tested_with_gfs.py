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
from architeuthis.core import RoutingAnalysis
from architeuthis.icebergs import berg_zone
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

# Your exclusion zones: lists of [lat, lon] points (or ExclusionZone objects, see architeuthis.exclusion).
north_america = [
    [46.6475507, -53.0879974], [47.1448975, -52.6904297],
    [47.8057761, -52.6574707], [48.7272088, -53.0310059],
    [52.2547088, -55.5688477], [57.0646303, -61.6992188],
    [59.1759282, -64.0283203], [60.5221575, -64.8193359],
    [62.0833149, -66.2255859], [63.5485522, -70.3125],
    [64.434892, -73.6083984], [64.8862654, -77.3876953],
    [66.0715465, -86.4404297], [64.1681069, -92.109375],
    [59.4450751, -96.6796875], [56.2677611, -95.9765625],
    [46.1950421, -92.7246094], [41.0793511, -87.6708984],
    [35.3532161, -75.9814453], [37.7620299, -77.0141602],
    [38.3761154, -76.9454956], [38.9935721, -76.8273926],
    [39.2577782, -76.3659668], [38.3416562, -75.9594727],
    [37.2980904, -75.9979248], [37.1121458, -75.9539795],
    [37.6164071, -75.5804443], [38.0351124, -75.2563477],
    [38.4084061, -75.0723267], [38.7883454, -75.0860596],
    [39.2705372, -74.6026611], [39.7747695, -74.1137695],
    [40.3904888, -73.9984131], [41.2881262, -70.7794189],
    [41.2365112, -69.9746704], [41.2943173, -69.9362183],
    [41.8347815, -69.9307251], [42.0615286, -70.0708008],
    [42.6440611, -70.5844116], [43.4130287, -70.4553223],
    [43.8345268, -68.8623047], [44.6881828, -67.1539307],
    [44.2412638, -66.395874], [43.3930737, -66.0305786],
    [43.3850899, -65.6268311], [43.5007524, -65.2807617],
    [44.4631908, -63.5641479], [45.2555553, -60.9851074],
    [46.0045933, -59.666748], [47.025206, -60.3918457],
    [47.5394554, -59.2053223], [47.2549999, -55.9616089],
    [46.9146271, -55.9780884], [46.8414071, -55.8050537],
    [46.8733358, -55.3738403], [46.8188578, -54.1873169],
    [46.6098279, -53.5720825], [46.6263348, -53.1614685],
    [46.6484934, -53.0879974], [46.6475507, -53.0879974],
]
brittany = [
    [47.234906794905456, -2.298894594711654], [47.25856998567288, -2.4325583888579034],
    [47.29283375261824, -2.547348407391687], [47.472965041672204, -3.132757632163045],
    [47.643448179530274, -3.2076668170178877], [47.700395091200015, -3.368297468536256],
    [47.69636166917016, -3.4548323100507234], [47.79791598030666, -3.8522262539473218],
    [47.85365939763104, -3.980613066215874], [47.84328834623138, -4.041571653262067],
    [47.79730758529769, -4.187810231946969], [47.7951034723181, -4.380102394509618],
    [48.04251441805747, -4.732749036488459], [48.271675251256646, -4.616214170859991],
    [48.33235206326594, -4.766668801789211], [48.51970337432375, -4.781458461018697],
    [48.67589361128423, -4.353382869976883], [48.75347516979233, -4.009457823390732],
    [48.84141631708758, -3.5046081884123716], [48.89654815888168, -3.0605321526173523],
    [48.560105723588045, -2.671292321902763], [48.685993556279584, -2.318443857961514],
    [47.234906794905456, -2.298894594711654],
]
exclusion_zones = [north_america, brittany, berg_zone] # berg_zone: the latest IIP iceberg limit

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

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

# POLAR = os.path.expanduser("~/data/polars/vessel_polar.nc")
POLAR = os.path.expanduser("~/data/polars/neoliner_origin_v2-2-0_mc0_sc0_28up_28down_7buff_5m_eff60.nc")

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

from architeuthis.core import DEFAULT_SOLVER_OPTIONS, RoutingAnalysis
from architeuthis.icebergs import berg_zone
from architeuthis.forecast import DeterministicHerbieForecast, Forecast, Topography
from architeuthis.vessel import Vessel

domain = {"min_lon": -60.0, "max_lon": 0.0, "min_lat": 38.0, "max_lat": 56.0}
steps = list(range(0, 145, 3)) + list(range(150, 361, 6))
# forecast_date = position_time.tz_localize(None).floor("12h") - pd.Timedelta(hours=12)
forecast_date = etd.tz_localize(None) # latest 00 UTC run


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

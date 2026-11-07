# -*- coding: utf-8 -*-
"""
Created on Tue Feb  3 14:35:10 2026

@author: jrich
"""

import os
import json

import pandas as pd
import seaborn as sns
import cartopy.crs as ccrs
import architeuthis.numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import cartopy.feature as cfeature

from itertools import product
from architeuthis.common import _HOME
from architeuthis.vessel import Vessel
from architeuthis.toolbox.geo_utils import poly_deviated_route
from architeuthis.wrappers.json_wrapper import CustomEncoder, custom_decoder
from architeuthis.core import RoutingAnalysis, Voyage, DEFAULT_SOLVER_OPTIONS, exclusion_zones
from architeuthis.route import Route, RouteLibrary
from architeuthis.voyage import PassagePlan, PassagePlanLibrary
from architeuthis.forecast import DeterministicHerbieForecast, EnsembleHerbieForecast, CopernicusForecast, Topography

def tall(array):
    return np.reshape(array, (-1, 1))


def wide(array):
    return np.reshape(array, (1, -1))


def draw(reports, barbs=True, sails_threshold=None):
        
    from architeuthis.toolbox.plot_utils import plot_route

    # cvtim = pd.to_datetime(self.report["ctim"], unit="s")
    # vtim = pd.to_datetime(self.report["tim"], unit="s")
    
    lons = [r["lon"] for r in reports]
    lats = [r["lat"] for r in reports]
    clons = [r["clon"] for r in reports]
    clats = [r["clat"] for r in reports]
    tws = [r["tws"] for r in reports]
    twd = [r["twd"] for r in reports]
    
    sc = [r['sails_contribution'] for r in reports]
    
    if sails_threshold is not None:
        plot_route(lons, lats, clons, clats, tws, twd, barbs, sails_contribution=sc, sails_threshold=sails_threshold)
    else:
        plot_route(lons, lats, clons, clats, tws, twd, barbs)
    
def get_steps(report, quantity):
    
    tim = pd.to_datetime(report["tim"], unit="s")
    
    X = []
    Y = []
    for i in range(len(report["ctim"])):
        X.append(tim[i])
        X.append(tim[i+1])
        Y.append(report[quantity][i])
        Y.append(report[quantity][i])
        
    return np.asarray(X), np.asarray(Y)
        
minimum_longitude=-60.
maximum_longitude=0.
minimum_latitude=30.
maximum_latitude=60.

# minimum_longitude=-80.
# maximum_longitude=-50.
# minimum_latitude=35.
# maximum_latitude=50.

steps = list(range(0, 145, 3)) + list(range(150, 361, 6))
    
#%% BUILD VESSEL INTERPOLATORS

def cubic_model(x, p):
    return p["d"] * x**3 + p["c"] * x**2 + p["b"] * x + p["a"]

def quadratic_model(x, p):
    return p["c"] * x**2 + p["b"] * x + p["a"]

def sfc_func(x):
    p_sfc = {
        'a': 325.7684374001559,
        'b': -0.13133435575556507,
        'c': 5.216985806784128e-05,
        'd': -6.660802866517442e-09
    }
    return np.fmax(cubic_model(x, p_sfc), 200.)

def hotel_load_func(x):
    p_hl = {
        'a': 177.84810351574922,
        'b': -0.011382017491188723,
        'c': 1.0915372379294297e-05
    }
    return quadratic_model(x, p_hl)

vessel_files = [    
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff15.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff30.nc",
    r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff45.nc",
    r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff60.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff75.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff90.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff100.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff60.nc",
]

columns = ["bhp", "max_bhp", "leeway"]

vessels = []

maxBHP = 4100.
# maxBHP = 3100.

for i, vessel_data in enumerate(vessel_files):
    vessel = Vessel(
        f"vessel_{i}",
        filepath=vessel_data,
        sfc=220.,
        hotel_load=194.,
        # sfc=sfc_func,
        # hotel_load=hotel_load_func,
        max_power=maxBHP
    )
    # vessel = Vessel(f"vessel_{i}", filepath=vessel_data, sfc=196., hotel_load=172., max_power=maxBHP)
    vessel.load_data()
    
    vessel.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("max_bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    # vessel.add_interpolator("leeway", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("sails_contribution", "stw", "tws", "twa", "hs", "wa", method="linear")
    
    vessels.append(vessel)

#%% BUILD WIND INTERPOLATORS

# global_corr_fac = 1.10 # global models speed correction (115% @ 10m, 105% @ 100m)
global_corr_fac = 1.0 # global models speed correction (115% @ 10m, 105% @ 100m)

recent = pd.Timestamp("now").floor("1d")
# mirror_end = pd.Timestamp('2025-12-21 12:00')

ATMOS = {}

# IFS atmospheric data
ATMOS["ifs"] = DeterministicHerbieForecast(
    "wind_ifs", model="ifs", product="oper", regex=r":10[u|v]:|:msl:", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent
)

# GFS atmospheric data
ATMOS["gfs"] = DeterministicHerbieForecast(
    "wind_gfs", model="gfs", product="pgrb2.0p25", regex=r"(?:U|V)GRD:10 m", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent
)

for model, atmos in ATMOS.items():
    atmos.load_data()

    atmos.add_interpolator("u10", "valid_time", "latitude", "longitude", fac=global_corr_fac)
    atmos.add_interpolator("v10", "valid_time", "latitude", "longitude", fac=global_corr_fac)

# atmos = DeterministicHerbieForecast(
#     "wind", model="ifs", product="scda", regex=r":10[u|v]:", fxx=steps,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     # date=mirror_date
# )

atmos_ens = EnsembleHerbieForecast(
    "wind_ens", model="ifs", product="enfo", regex=r":10[u|v]:", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent
)
atmos_ens.load_data()

atmos_ens.add_interpolator(
    "u10", "valid_time", "number", "latitude", "longitude",
    member_slice=slice(None, None,1),
    time_slice=slice(None, None,1),
    latitude_slice=slice(None, None,2),
    longitude_slice=slice(None, None,2),
    fac=global_corr_fac
)
atmos_ens.add_interpolator(
    "v10", "valid_time", "number", "latitude", "longitude",
    member_slice=slice(None, None,1),
    time_slice=slice(None, None,1),
    latitude_slice=slice(None, None,2),
    longitude_slice=slice(None, None,2),
    fac=global_corr_fac
)


#%% BUILD WAVE INTERPOLATORS

WAVE = {}

# IFS wave data
WAVE["ifs"] = DeterministicHerbieForecast(
    "wave_ifs", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent
)
WAVE["ifs"].load_data()

WAVE["ifs"].add_interpolator("swh", "valid_time", "latitude", "longitude")
WAVE["ifs"].add_interpolator("mwd", "valid_time", "latitude", "longitude")

# GFS wave data
WAVE["gfs"] = DeterministicHerbieForecast(
    "wave_gfs", model="gfs_wave", product="global.0p25", regex=r":HTSGW:|:DIRPW:", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent
)
WAVE["gfs"].load_data()

WAVE["gfs"].add_interpolator("swh", "valid_time", "latitude", "longitude", var_key="swh")
WAVE["gfs"].add_interpolator("dirpw", "valid_time", "latitude", "longitude", var_key="mwd")

wave_ens = EnsembleHerbieForecast(
    "wave_ens", model="ifs", product="waef", regex=r":swh:|:mwd:", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent
)
wave_ens.load_data()

wave_ens.add_interpolator(
    "swh", "valid_time", "number", "latitude", "longitude",
    member_slice=slice(None, None,1),
    time_slice=slice(None, None,1),
    latitude_slice=slice(None, None,2),
    longitude_slice=slice(None, None,2),
)
wave_ens.add_interpolator(
    "mwd", "valid_time", "number", "latitude", "longitude",
    member_slice=slice(None, None,1),
    time_slice=slice(None, None,1),
    latitude_slice=slice(None, None,2),
    longitude_slice=slice(None, None,2),
)


#%% BUILD CURRENT INTERPOLATORS

# Mercator SMOC data
current = CopernicusForecast(
    "current", dataset="cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", variables=["uo", "vo"],
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent,
    # date=mirror_date, end=mirror_end
)
current.load_data()

current.add_interpolator(
    "uo", "valid_time", "latitude", "longitude",
    latitude_slice=slice(None, None, 3),
    longitude_slice=slice(None, None, 3),
    time_slice=slice(None, None, 3),
)
current.add_interpolator(
    "vo", "valid_time", "latitude", "longitude",
    latitude_slice=slice(None, None, 3),
    longitude_slice=slice(None, None, 3),
    time_slice=slice(None, None, 3),
)


#%% BUILD TOPOGRAPHY

# topo0 = Topography(
#     "topo0", depth_offset=0., z_margin=0.,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     exclusion_zones=exclusion_zones[:-1],
# )
# topo0.load_data()

# topo0.add_interpolator(
#     "distance_to_iso0",
#     "latitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
#     "longitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
#     var_key="z"
# )

topo = Topography(
    "topo", depth_offset=-30., z_margin=0.,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    exclusion_zones=exclusion_zones,
)
topo.load_data()

topo.add_interpolator(
    "distance_to_iso0",
    "latitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
    "longitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
    var_key="z"
)

#%%

# departure = np.array([47.01483765543116, -2.63720447676916]) # Montoir pilot
# departure = np.array([43.612500, -11.603333]) # pos 01/06/2026 06h30 UTC
# departure = np.array([42.216111, -15.564167]) # pos 01/06/2026 06h30 UTC
# departure = np.array([47.823964087925354, -4.772235284069338]) # pos 06/02/2026 10h00 UTC
# departure = np.array([53.418611, -22.285278]) # pos 09/02/2026 10h00 UTC
# departure = np.array([53.130556, -38.120833]) # pos 11/02/2026 12h15 UTC
# departure = np.array([50.453056, -42.795278]) # pos 12/02/2026 10h00 UTC
# departure = np.array([47.595000, -47.963333]) # pos 13/02/2026 10h50 UTC
# departure = np.array([44.117702, -60.907898]) # pos 16/02/2026 00h00 UTC


# departure = np.array([47.68366513909249, -3.5247528817988893]) # Lorient
# arrival = np.array([47.68366513909249, -3.5247528817988893]) # Lorient

# departure = np.array([45.3868773482704, -54.57870483398438]) # 15/05 00h01 UTC
departure = np.array([46.781, -56.091]) # SPM pilot
# arrival = np.array([46.781, -56.091]) # SPM pilot
# departure = np.array([45.831667, -51.700000]) # pos 27/02/2026 14h00 UTC
# departure = np.array([44.993333, -39.533333]) # pos 01/03/2026 14h00 UTC
# departure = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# departure = np.array([37.38330548509701, -74.4866180419922]) # pos 20/02/2026 17h00 UTC
# departure = np.array([43.248056, -62.397778]) # pos 23/02/2026 09h20 UTC
arrival = np.array([47.112116788143474, -2.4051169026612866]) # Montoir pilot
# departure = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# arrival = np.array([46.50781973122021, -53.33670295591693]) # Cape Race

# arrival = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# wp = np.array([46.551, -53.321]) # cape race
# wp = np.array([46.166667, -46.916667]) # iip 23/02/2026
wp = np.array([
    [46.551, -53.321], # cape race
    # [47.79657767419367, -4.876263748342499], # Penmarc'h
    
    # [45.750000, -46.750000], # iip 25/02/2026
    # [45.250000, -46.750000], # iip 25/02/2026 0.50 deg margin
    # [45.250000, -48.500000], # iip 27/02/2026
    # [45.166667, -45.916667], # iip 27/02/2026
    # [44.916667, -46.916667], # iip 27/02/2026 0.25 deg margin
    # [45.916667 - 0.50, -44.166667], # iip 09/03/2026 0.50 deg margin
    # [45.333333 - 0.50, -49.500000], # iip 09/03/2026 0.50 deg margin
    # [46.333333 - 0.50, -46.416667], # iip 31/03/2026 0.50 deg margin
    
    # [45.166667, -45.583333], # iip 16/03/2026
    # [44.916667, -51.583333], # iip 16/03/2026
    
    # [41.416667, -50.750000], # iip 13/05/2026
    # [41.583333, -46.750000], # iip 13/05/2026
    
    # [44.66666 - 1.0, -43.75000], # iip 28/05/2026
    # [44.66666 - 1.0, -50.33333], # iip 28/05/2026
    
    # [41.666667, -50.583333], # iip 15/05/2026
    # [41.916667, -47.833333], # iip 15/05/2026

    # [46.551, -53.321], # cape race
    [47.72529611513597, -4.379839003826363], # Penmarc'h
    
    # [47.79657767419367, -4.876263748342499], # Penmarc'h
])
# arrival = np.array([46.781, -56.091]) # SPM pilot

# departure = np.array([11.3196, -74.2835])
# wp = np.array([
#     [15.4358, -82.9951],
#     [16.0791, -84.9973],
#     [16.0810, -85.9931],
# ])
# arrival = np.array([15.9927, -87.7219])

# Reference routes as Route objects (architeuthis.route), with the same waypoints and
# divergences as before. A Route is called like the former poly_deviated_route
# functions: route(s) -> (lat, lon) for s in [0, 1].
routeSbd = Route(
    "long_term_starboard",
    [departure, arrival],
    divergences=[-0.5],
)

routeO = Route(
    "long_term_ortho",
    [departure, *wp[:-1], arrival],
    divergences=list(np.zeros(len(wp[:-1]) + 1)),
)

routePrt = Route(
    "long_term_port",
    [departure, *wp, arrival],
    divergences=[0., 0.4, 0.],
)

# Store the routes: RouteLibrary().load(name) gives them back in any script
# (~/data/route_library/), and route.reversed() gives the return passage.
routes = RouteLibrary()
for route in (routeSbd, routeO, routePrt):
    routes.save(route, overwrite=True)


ax = plt.axes(projection=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND, facecolor="khaki")
# ax.add_feature(cfeature.LAND, facecolor="sandybrown")
ax.add_feature(cfeature.OCEAN, facecolor="lavender")
# ax.add_feature(cfeature.OCEAN, facecolor="lightsteelblue")
ax.add_feature(cfeature.COASTLINE, linewidth=0.3)
# ax.add_feature(cfeature.BORDERS, linestyle=":")
gl = ax.gridlines(draw_labels=False, dms=True, x_inline=False, y_inline=False, linewidth=0.5)

ax.plot(*routeSbd(np.linspace(0,1,50))[::-1])
ax.plot(*routeO(np.linspace(0,1,50))[::-1])
ax.plot(*routePrt(np.linspace(0,1,50))[::-1])

plt.show()

# s = np.linspace(0, 1, 100)
# latN, lonN = routeSbd(s)
# latS, lonS = routePrt(s)
# latO, lonO = routeO(s)


# etd = pd.to_datetime("2026-02-05T20:00").timestamp() # LT 21h ATD
# etd = pd.to_datetime("2026-02-06T10:00").timestamp() # 06/02/2026 10h00 UTC
# etd = pd.to_datetime("2026-02-09T10:00").timestamp() # 09/02/2026 01h30 UTC
# etd = pd.to_datetime("2026-02-11T12:15").timestamp() # 11/02/2026 12h15 UTC
# etd = pd.to_datetime("2026-02-12T10:00").timestamp() # 12/02/2026 10h00 UTC
# etd = pd.to_datetime("2026-02-13T10:50").timestamp() # 13/02/2026 10h50 UTC
# etd = pd.to_datetime("2026-02-20T10:30").timestamp()
# etd = pd.to_datetime("2026-02-20T17h00").timestamp() 
# etd = pd.to_datetime("2026-02-23T09h20").timestamp()
# etd = pd.to_datetime("2026-02-26T20h00").timestamp() # ATD
# etd = pd.to_datetime("2026-02-27T14h00").timestamp() 
# etd = pd.to_datetime("2026-03-12T17h00").timestamp()
# etd = pd.to_datetime("2026-03-13T14h00").timestamp()
# etd = pd.to_datetime("2026-02-16T00:00").timestamp() # 16/02/2026 00h00 UTC
# eta = pd.to_datetime("2026-02-25T11:00").timestamp()
# eta = pd.to_datetime("2026-02-18T22:00").timestamp() # LT 17h

# Routing after the start of the leg: the voyage restarts from this position, reached at
# this time, and keeps its ETA (Voyage.from_position). None routes the whole leg.
rewind = None
# rewind = ([43.612500, -11.603333], "2026-06-01T06:30") # pos 01/06/2026 06h30 UTC

solver_options = DEFAULT_SOLVER_OPTIONS

reports = []
plans = [] # PassagePlan of each routing (timed positions)

zero_fac = 0.

models = ["ifs", "gfs"]
# models = ["ifs",]
# facs = np.asarray([0., 1.]) + zero_fac
facs = np.asarray([-0.9, -0.2, 0.2, 0.9]) + zero_fac
# facs = np.asarray([-0.3, 0., 0.3]) + zero_fac
# facs = np.asarray([-1., 0., 1.]) + zero_fac
# facs = [zero_fac]
# topos = [topo]
topos = [topo]

# members = None
members = [0]
# members = list(range(1,51,1))

def to_time(s):
    return pd.to_datetime(s).timestamp()

timeframes = [
    # (to_time("2026-08-07T07h00"), to_time("2026-08-12T11:00")),
    # (to_time("2026-08-07T17h00"), to_time("2026-08-12T11:00")),
    # (to_time("2026-08-13T07h00"), to_time("2026-08-22T11:00")),
    (to_time("2026-09-04T15h00"), to_time("2026-09-14T02:00")),
]

def custom_constraints(ctx):
    return [
        ctx["max_bhp"] < ctx["vessel"].max_power,
        (wide(ctx["z"]) @ tall(ctx["z"])) == 0.,
        # ctx["aws"] < 35.0,
        # ctx["aws"] > 10.0,
        # ctx["stw"] <= 20.0, # STW cap
    ]

# for m, fac in product(list(range(1,51,1)), facs):
# for m, fac in product(list(range(1,51,51)), facs):
for solve, tf, model, vessel, fac, m, tpg in (
        list(
            product([0], timeframes, models, vessels, [zero_fac], [1], [topo]) # NOT SOLVED ortho cst speed refs
            # product([0], timeframes, models[:1], vessels[:1], [zero_fac], [1]) # NOT SOLVED ortho cst speed refs
        ) + list(
            product([1], timeframes, models, vessels, facs, members, topos) # SOLVED
        )
    ):
                
    etd, eta = tf
    
    voyage = Voyage(
        name="voyage",
        etd = etd,
        eta = eta,
        departure = departure,
        arrival = arrival,
        route=routeO,
        route_minus=routePrt,
        route_ortho=routeO,
        route_plus=routeSbd,
    )
    if rewind is not None:
        voyage = voyage.from_position(*rewind)

    analysis = RoutingAnalysis(
        "analysis",
        vessel,
        voyage,
        ATMOS[model],
        # ATMOS["gfs"],
        # atmos_ens,
        WAVE[model],
        # WAVE["gfs"],
        # WAVE["ifs"],
        # wave_ens,
        current,
        tpg,
        # atmosphere_member=m,
        # wave_member=m,
        constraints=custom_constraints,
    )
    
    report = analysis.run(
        max_iter=1000,
        skip_tim=0,
        init_fac=fac,
        # init_fac=-1.,
        # init_fac=-0.5,
        # init_fac=0,
        # init_fac=0.5,
        # init_fac=1.,
        # init_fac=1.5,
        # init_fac=2.,
        # vary_fac=0,
        vary_fac=1,
        solver_options = {
            "ipopt":{
                "acceptable_tol": 1e2,
                # 'linear_solver': 'spral',
                'linear_solver': 'mumps',
                "hessian_approximation": "limited-memory",
            },
        },
        # solve=0,
        solve=solve,
    ) # TODO report should probably be a class of its own
    
    report["solve"] = solve
    report["model"] = model
    report["vessel"] = vessel.path[79:-3]
    report["member"] = m

    # Passage plan of this routing, stored after the loop and evaluated in a later cell.
    plan = analysis.passage_plan
    plan.name = f"{plan.name}_{model}{vessel.path[79:-3]}_fac{fac:+.2f}_m{m}_{'solved' if solve else 'ref'}"
    plan.metadata |= {"model": model, "member": m, "solve": solve, "vessel_tag": vessel.path[79:-3]}
    plans.append(plan)
    
    ctime = pd.to_datetime(report["ctim"], unit="s")
        
    # plt.clf()
    # # plt.scatter(ctime, unit="s"), report["avg_bhp"])
    # plt.plot(*get_steps(report, "avg_bhp"))
    # plt.plot(*get_steps(report, "max_bhp"))
    # plt.plot(*get_steps(report, "swh"))
    # # plt.plot(ctime, report["sails_contribution"])
    # # plt.plot(ctime, report["sails_contribution"])
    # plt.xticks(rotation=45)
    # plt.tight_layout()
    # plt.show()
    
    # print(f"{pd.to_datetime(report['etd'], unit='s').strftime('%d/%m %Hh%M UTC')} - {pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}")
    # print(f"fuel = {report['fuel']:.1f} t i.e. {report['fuel']/report['transit_time']*24.:.1f} t/day")
    
    # if report["status"] == 1:
    reports.append(report)

for report in reports:
    # print(f"{pd.to_datetime(report['etd'], unit='s').strftime('%d/%m %Hh%M UTC')} - {pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}")
    print(f"{pd.to_datetime(report['etd'], unit='s').strftime('%d/%m %Hh%M UTC')} - {pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}")
    print(f"{report['init_fac']}, {report['model']}")
    print(f"{report['dist']:.1f}, {report['dist_rel'] * 100 - 100:.1f}")
    print(f"{np.mean(report['sog']):.1f} {np.mean(report['sog']) / report['transit_sog'] * 100 - 100:.1f} ")
    print(f"fuel = {report['fuel']:.1f} t i.e. {report['fuel']/report['transit_time']*24.:.1f} t/day")
    print()

df = pd.DataFrame(reports)

# cv_reports = [r for r in reports if (r["status"]==1)] # TODO rather name raw_reports and reports
cv_reports = reports # TODO rather name raw_reports and reports

draw(cv_reports, barbs=0, sails_threshold=10.)
# draw(cv_reports, barbs=0, sails_threshold=None)
# draw(reports[0:8]+reports[8+1:], barbs=0)
# draw([r for r in reports if (r["vessel"] == "_eff60")][2:10], barbs=1)
# draw([r for r in reports if (r["vessel"] == "_eff90")], barbs=0)
# draw([r for r in reports if (r["vessel"] == "_eff60")], barbs=0)

# for r in [r for r in reports if (r["vessel"] == "_eff60")]:
# for r in [r for r in reports if (r["vessel"] == "_eff90")]:
#     draw([r], barbs=1)

from datetime import datetime

now = datetime.now()

json_file = f"output_{now.strftime(r'%Y-%m-%d')}.json"
# json_file = "output2.json"
# json_file = "output_caperace.json"
# json_file = "output_caperace.json"
# json_file = "trash.json"


# WRITE
with open(os.path.join(_HOME, "routes", json_file), "w") as f:
    json.dump(cv_reports, f, cls=CustomEncoder, indent=2)

# Passage plans, reloadable with PassagePlanLibrary().load(name) (~/data/passage_plans/)
plan_library = PassagePlanLibrary()
for plan in plans:
    plan_library.save(plan, overwrite=True)
#%% OPEN-LOOP EVALUATION OF THE PASSAGE PLANS

# Each optimized plan is evaluated with every model and vessel, its positions and times
# fixed (no optimization): the sensitivity of its consumption to the conditions it was
# optimized with. Constraints are the defaults, reported in max_constraint_violation.
# A stored plan can be evaluated the same way: PassagePlanLibrary().load(name).
evaluations = []
for plan, (model, vessel) in product(
        [p for p in plans if p.metadata["solve"]],
        list(product(models, vessels)),
    ):
    evaluation = RoutingAnalysis(
        "evaluation",
        vessel,
        plan.voyage(),
        ATMOS[model],
        WAVE[model],
        current,
        topos[0],
        verbose=False,
    ).evaluate(plan)
    evaluation["plan"] = plan.name
    evaluation["model"] = model
    evaluation["vessel"] = vessel.path[79:-3]
    evaluations.append(evaluation)

eval_table = pd.DataFrame(evaluations).pivot_table(
    index="plan",
    columns=["model", "vessel"],
    values="fuel",
)
print(eval_table)

#%%

import pandas as pd

# 1. Convert your list of dictionaries into a Pandas DataFrame
cv_df = pd.DataFrame(cv_reports)

# 2. Convert the ETA timestamp to a human-readable date format
cv_df['eta_date'] = pd.to_datetime(cv_df['eta'], unit='s')

# 3. Group by the requested columns and calculate the mean (or sum) of fuel
# We use 'vessel' as it maps to your efficiency tracking field
grouped_df = cv_df.groupby(['eta_date', 'vessel', 'init_fac', 'model'])['fuel'].mean().reset_index()

grouped_df["fuel"] = grouped_df["fuel"].round(1)

# 4. Rename the columns to match your preferred formatting
grouped_df.columns = ['ETA', 'Init Fac', 'Model', 'Efficiency', 'Total Fuel Consumption']

# Display the resulting table
print(grouped_df)

#%% FUEL VS ETA

fuel_reports = (
    pd.DataFrame(reports)
    .groupby(["solve", "vessel", "model"], as_index=False)[["etd", "fuel"]]
    .agg(list)
)

minFuel = (df["fuel"].min() // 10) * 10.
maxFuel = (df["fuel"].max() // 10 + 1) * 10.

effs = fuel_reports["vessel"].unique()
models = fuel_reports["model"].unique()

markers = {0 : "x", 1: "o"}
names  = {0 : "ortho cst speed", 1: "optimised"}
colors = {model : color for model, color in zip(models, sns.color_palette("viridis", len(models)))}


for eff in effs:
    
    plt.clf()
    plt.figure(figsize=(10, 3.5))

    sub_fuel_reports = fuel_reports[fuel_reports["vessel"] == eff]
    
    for i in range(len(sub_fuel_reports)):
        fr = sub_fuel_reports.iloc[i]
        plt.plot(
            pd.to_datetime(fr["etd"], unit="s"), fr["fuel"],
            marker=markers[fr["solve"]],
            color = colors[fr["model"]],
            label=f"{fr['model'].upper()} / {names[fr['solve']]}"
        )
    
    plt.xticks(rotation=45.)
    plt.xlabel("ETA (UTC)")
    plt.ylabel("Total fuel consumption / tons")
    plt.title(f"Sails efficiency {eff[4:]} %")
    # plt.ylim((minFuel, maxFuel))
    plt.legend()
    plt.show()

#%%

import seaborn as sns

def slicing(r):
    return (
        (reports.index(r) in [4, 9]) &
        # (r["init_fac"] != 0.) &
        # (r["init_fac"] == 0.) &
        # (r["vessel"] == "eff45") &
        # (r["eta"] >= 1772049600.0) &
        # (r["eta"] < 1772049600.0) &
        True
    )

plots = [r for r in reports if slicing(r)]

# options = {-0.5: "North coast", 0.:"Ortho cst speed", 0.75: "North offshore", 3.: "South"}
options = {-1.: "North", 0.:"Ortho cst speed", 1.: "South"}

colors = sns.color_palette(palette="viridis", n_colors=len(plots))

variable = "sog"
unit = "kts"

# variable = "swh"
# unit = "m"

# variable = "sails_contribution"
# unit = "%"

# variable = "mwa"
# unit = "deg"

# variable = "avg_bhp"
# variable = "max_bhp"
# unit = "kW"

plt.clf()
plt.figure(figsize=(8, 4))
for i, r in enumerate(plots):
    x, y = get_steps(r, variable)
    plt.plot(x, y, color=colors[i])
    plt.xlim((x.min(), x.max()))
# plt.legend()
plt.xticks(rotation=45)
plt.xlabel("Time (UTC)")
plt.ylabel(f"{variable.upper()} / {unit}")
plt.tight_layout()
plt.show()

#%%

# fuel plot
# plt.clf()
# plt.violinplot([r["fuel"] for r in reports])
# plt.boxplot([r["fuel"] for r in reports])
# plt.show()

data = [
    # [r["fuel"] for r in reports if (r["vessel"] == "_eff90")],
    # [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
    # [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
    # [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
    [r["fuel"] for r in reports if ((r["init_fac"] < 0.))],
    [r["fuel"] for r in reports if (r["init_fac"] == 0.)],
    # [r["fuel"] for r in reports if (r["init_fac"] > 0.)],
    # [r["fuel"] for r in cv_reports],
]

# fig, ax = plt.subplots(figsize=(3, 4))  # width=8, height=3
fig, ax = plt.subplots(figsize=(8, 3))  # width=8, height=3

vp = plt.violinplot(data, showextrema=False)
bp = ax.boxplot(data, patch_artist=True)

# colors = ["tab:blue", "tab:orange", "tab:green"]

for box, color in zip(bp["boxes"], colors):
    box.set(facecolor="limegreen")

ax.set_xticks(list(range(1, len(data)+1)))
ax.set_xticklabels(["Eff. 90%", "Eff. 60%"])
# ax.set_xticklabels(["Ortho routes", "North routes"])
# ax.set_xticklabels(["North routes", "Ortho routes", "South routes"])
# ax.set_xticks([1])
# ax.set_xticklabels(["All routes"])
ax.set_ylabel("Fuel / tons")

#%%

def slicing(r):
    return (
        (r["init_fac"] != 0.) &
        # (r["init_fac"] == 0.) &
        # (r["init_fac"] == -1.) &
        # (r["vessel"] == "eff45") &
        # (r["eta"] >= 1772049600.0) &
        # (r["eta"] < 1772049600.0) &
        True
    )

variable = "swh"
# variable = "tws"
# variable = "avg_bhp"
# variable = "sails_contribution"

tim = pd.to_datetime(report["tim"], unit="s")
ctim = pd.to_datetime(report["ctim"], unit="s")

meteogram = np.array([r[variable] for r in reports if slicing(r)])

q00 = np.quantile(meteogram, 0.01, axis=0)
q05 = np.quantile(meteogram, 0.05, axis=0)
q25 = np.quantile(meteogram, 0.25, axis=0)
q50 = np.quantile(meteogram, 0.50, axis=0)
q75 = np.quantile(meteogram, 0.75, axis=0)
q95 = np.quantile(meteogram, 0.95, axis=0)
q100 = np.quantile(meteogram, 0.99, axis=0)

plt.fill_between(ctim, q00, q100, alpha=0.1, label="IFS ensemble 1–99%", color="limegreen")
plt.fill_between(ctim, q05, q95, alpha=0.25, label="IFS ensemble 05–95%", color="limegreen")
plt.fill_between(ctim, q25, q75, alpha=0.4, label="IFS ensemble 25–75%", color="limegreen")
plt.plot(ctim, q50, label="Median")
plt.ylim((0,9))
plt.legend()
plt.xticks(rotation=45)
plt.xlabel("Time (UTC)")
plt.ylabel(f"{variable.upper()} / {unit}")
plt.tight_layout()
plt.show()

#%%

variable = "sog"
unit = "kts"
vmin = 4.
vmax=14.

# variable = "swh"
# unit = "m"


# variable = "sails_contribution"
# unit = "%"
# vmin = -1
# vmax=101.

# variable = "mwa"
# unit = "deg"

# variable = "avg_bhp"
# variable = "max_bhp"
# unit = "kW"
# vmin = 0.
# vmax = maxBHP * 1.1



def slicing(r):
    return (
        (reports.index(r) in [4, 9]) &
        # (r["init_fac"] != 0.) &
        # (r["init_fac"] == 0.) &
        # (r["vessel"] == "eff45") &
        # (r["eta"] >= 1772049600.0) &
        # (r["eta"] < 1772049600.0) &
        True
    )

for r in [r for r in reports if slicing(r)]:
    plt.figure(figsize=(10,3))
    
    # environment_query = np.concatenate([
    #     r["ctim"], r["clat"], r["clon"],
    # ], axis=1)
    
    n = r["ctim"].shape[0]
    
    # vmin = (r[variable].min() // 1 - 1)
    # vmax = (r[variable].max() // 1 + 2)
    
    tim = pd.to_datetime(r["tim"], unit="s")
    ctim = pd.to_datetime(r["ctim"], unit="s")
    
    # plt.fill_between(ctim, q00, q100, alpha=0.1, label="01–99%", color="limegreen")
    # plt.fill_between(ctim, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
    # plt.fill_between(ctim, q25, q75, alpha=0.4, label="25–75%", color="limegreen")
    plt.plot(*get_steps(r, variable))
    plt.legend()
    plt.xticks(rotation=45)
    plt.xlabel("Time (UTC)")
    plt.ylabel(f"{variable.upper()} / {unit}")
    # plt.title(f"{variable.upper()} distribution")
    plt.tight_layout()
    # plt.ylim((-180, 180))
    plt.ylim((vmin, vmax))
    plt.xlim((tim[0], tim[-1]))
    plt.show()

#%%

def slicing(r):
    return (
        (reports.index(r) in [4, 9]) &
        # (r["init_fac"] != 0.) &
        # (r["init_fac"] == 0.) &
        # (r["vessel"] == "eff45") &
        # (r["eta"] >= 1772049600.0) &
        # (r["eta"] < 1772049600.0) &
        True
    )

for r in [r for r in reports if slicing(r)]:
    # --- [Keep your existing data extraction and calculations here] ---
    n = r["ctim"].shape[0]
    
    tim = pd.to_datetime(r["tim"], unit="s")
    ctim = pd.to_datetime(r["ctim"], unit="s")

    environment_query = np.column_stack([
        np.repeat(r["ctim"].reshape(-1), 50),
        np.tile(np.arange(1, 51), n),
        np.repeat(r["clat"].reshape(-1), 50),
        np.repeat(r["clon"].reshape(-1), 50),
    ])
    
    u10 = np.asarray(atmos_ens("u10", environment_query).reshape((50, n))) 
    v10 = np.asarray(atmos_ens("v10", environment_query).reshape((50, n))) 
    swh = np.asarray(wave_ens("swh", environment_query).reshape((50, n))) 
    mwd = np.asarray(wave_ens("mwd", environment_query).reshape((50, n))) 
    
    tws = np.sqrt(u10**2. + v10**2.) * 3600./1852. # wind speed in kts
    twd = np.mod(np.arctan2d(u10, v10)+180., 360.) # wind direction from 0 to 360 deg
    
    cog = r["cog"][np.newaxis, ...]
    
    twa = np.mod(twd-cog + 180., 360.) - 180
    mwa = np.mod(mwd-cog + 180., 360.) - 180
    
    sog = r["sog"]
    duog = sog * np.sind(cog) 
    dvog = sog * np.cosd(cog) 
    
    stw = r["stw"]
    
    # ==========================================
    # --- NEW PLOTTING LOGIC STARTS HERE ---
    # ==========================================
    
    # Create a figure with 3 stacked subplots that share the same x-axis
    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=(10, 8), sharex=True)
    
    # 1. Plot BHP on the top subplot (axes[0])
    osc = r["max_bhp"] - r["avg_bhp"]
    
    axes[0].plot(ctim, r["avg_bhp"], label="Average BHP")
    axes[0].plot(ctim, r["max_bhp"], label="Load fluctuations", ls="--")
    axes[0].plot(ctim, r["max_bhp"] - 2*osc, ls="--")
    axes[0].fill_between(ctim, r["avg_bhp"] - osc, r["avg_bhp"] + osc, alpha=0.1)
    
    axes[0].legend(loc="upper right")
    axes[0].set_ylabel("BHP / kW")
    axes[0].set_ylim((0., 2700.))
    axes[0].set_xlim((tim[0], tim[-1]))
    
    # 2. Setup the environmental variables and map them to the remaining subplots
    env_var = [
        (swh, "swh", "m", 0., 7., axes[1]),  # Map SWH to the middle plot
        (tws, "tws", "kts", 0., 40., axes[2]) # Map TWS to the bottom plot
    ]
    
    # 3. Loop through environmental data to plot quantiles
    for meteogram, variable, unit, vmin, vmax, ax in env_var:
        q00 = np.quantile(meteogram, 0.01, axis=0)
        q05 = np.quantile(meteogram, 0.05, axis=0)
        q25 = np.quantile(meteogram, 0.25, axis=0)
        q50 = np.quantile(meteogram, 0.50, axis=0)
        q75 = np.quantile(meteogram, 0.75, axis=0)
        q95 = np.quantile(meteogram, 0.95, axis=0)
        q100 = np.quantile(meteogram, 0.99, axis=0)
        
        ax.fill_between(ctim, q00, q100, alpha=0.1, label="01–99%", color="limegreen")
        ax.fill_between(ctim, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
        ax.fill_between(ctim, q25, q75, alpha=0.4, label="25–75%", color="limegreen")
        ax.plot(ctim, q50, label="Median")
        
        ax.legend(loc="upper right")
        ax.set_ylabel(f"{variable.upper()} / {unit}")
        ax.set_ylim((vmin, vmax))

    # 4. Format the shared x-axis (only needs to be applied to the bottom-most plot)
    axes[2].set_xlabel("Time (UTC)")
    plt.setp(axes[2].xaxis.get_majorticklabels(), rotation=45)
    
    plt.tight_layout()
    plt.show()

#%%

# variable = "sog"
# unit = "kts"

# variable = "tws"
# unit = "kts"

# variable = "swh"
# unit = "m"

# variable = "mwa"
# unit = "deg"

# variable = "sails_contribution"
# unit = "%"

# variable = "mwa"
# unit = "deg"

variable = "avg_bhp"
# variable = "max_bhp"
unit = "kW"

    # [r["fuel"] for r in reports if (r["vessel"] == "_eff90")],
    # [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],

# meteogram = np.array([r[variable] for r in reports if (r["vessel"] == "_eff90")])
# meteogram = np.array([r[variable] for r in reports if (r["vessel"] == "_eff60")])
meteogram = np.array([r[variable] for r in reports if (r["solve"] == 1)])
    
q00 = np.quantile(meteogram, 0.01, axis=0)
q05 = np.quantile(meteogram, 0.05, axis=0)
q25 = np.quantile(meteogram, 0.25, axis=0)
q50 = np.quantile(meteogram, 0.50, axis=0)
q75 = np.quantile(meteogram, 0.75, axis=0)
q95 = np.quantile(meteogram, 0.95, axis=0)
q100 = np.quantile(meteogram, 0.99, axis=0)

plt.fill_between(ctim, q00, q100, alpha=0.1, label="01–99%", color="limegreen")
plt.fill_between(ctim, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
plt.fill_between(ctim, q25, q75, alpha=0.4, label="25–75%", color="limegreen")
plt.plot(ctim, q50, label="Median")
plt.legend()
plt.xticks(rotation=45)
plt.xlabel("Time (UTC)")
plt.ylabel(f"{variable.upper()} / {unit}")
plt.title(f"{variable.upper()} distribution along optimised routes for all scenarios")
plt.tight_layout()
# plt.ylim((-180, 180))
# plt.ylim((0, None))
plt.xlim((tim[0], tim[-1]))
plt.show()



#%%

etas = np.sort(np.unique([r["eta"] for r in reports]))

for eta in etas:
    def slicing(r):
        return (
            # (r["init_fac"] != 0.) &
            # (r["init_fac"] == -1.) &
            # (r["vessel"] == "eff45") &
            (r["eta"] >= 1772049600.0) &
            # (r["status"] == 1) &
            # (r["solve"] == 1) &
            # (r["eta"] == eta) &
            True
        )
    # slicing = (df["status"] == 1) & (df["eta"] == eta) & (df["solve"] == 1)

    # # optional slicing
    # subDf = df[slicing]
    
    variable = "swh"
    unit = "m"
    vmax = 10.
    # variable = "tws"
    # unit = "kts"
    # vmax=50.
    # variable = "avg_bhp"
    # variable = "max_bhp"
    # unit = "kW"
    # vmax = maxBHP *1.066
    # variable = "sog"
    # unit = "kts"
    # vmax = 13.
    # variable = "sails_contribution"
    # unit = "%"
    # vmax=45.
    
    subr = [r for r in reports if slicing(r)]
    
    etd = pd.to_datetime(subr[0]["etd"], unit="s")
    tim = pd.to_datetime(subr[0]["tim"], unit="s")
    ctim = pd.to_datetime(subr[0]["ctim"], unit="s")
    
    plt.figure(figsize=(10, 4))
    
    meteogram = np.array([r[variable] for r in reports if slicing(r)])
    
    q00 = np.quantile(meteogram, 0.01, axis=0)
    q05 = np.quantile(meteogram, 0.05, axis=0)
    q25 = np.quantile(meteogram, 0.25, axis=0)
    q50 = np.quantile(meteogram, 0.50, axis=0)
    q75 = np.quantile(meteogram, 0.75, axis=0)
    q95 = np.quantile(meteogram, 0.95, axis=0)
    q100 = np.quantile(meteogram, .99, axis=0)
    
    
    plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=1))   # every 24 h
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    
    plt.fill_between(ctim, q00, q100, alpha=0.1, label="IFS ensemble 1–99%", color="limegreen")
    plt.fill_between(ctim, q05, q95, alpha=0.25, label="IFS ensemble 05–95%", color="limegreen")
    plt.fill_between(ctim, q25, q75, alpha=0.4, label="IFS ensemble 25–75%", color="limegreen")
    plt.plot(ctim, q50, label="Median", marker="o", ms=3.)
    plt.legend()
    plt.ylim((0,vmax))
    plt.xticks(rotation=45)
    # plt.xlabel("Time (UTC)")
    plt.ylabel(f"{variable.upper()} / {unit}")
    plt.title(f"ETD {pd.to_datetime(etd, unit='s')} UTC - ETA {pd.to_datetime(eta, unit='s')} UTC")
    plt.tight_layout()
    plt.show()


#%% FUEL CONSUMPTION

plt.figure(figsize=(8, 4))

slicing = (df["status"] == 1)

df["daily_fuel"] = df["fuel"] / df["transit_time"] * 24.

# optional slicing
subDf = df[slicing]

# subDf = df

quantiles = subDf.groupby("eta")["fuel"].quantile(
    [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
).unstack()

x = pd.to_datetime(quantiles.index.values, unit="s")

q00 = quantiles[0.01].values
q05 = quantiles[0.05].values
q25 = quantiles[0.25].values
q50 = quantiles[0.50].values
q75 = quantiles[0.75].values
q95 = quantiles[0.95].values
q100 = quantiles[0.99].values

plt.fill_between(x, q00, q100, alpha=0.1, label="1–99%", color="limegreen")
plt.fill_between(x, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
plt.fill_between(x, q25, q75, alpha=0.4, label="25–75%", color="limegreen")

plt.plot(x, q50, label="Median", marker="o")

plt.legend()
plt.xticks(rotation=45)
plt.xlabel("ETA")
plt.ylabel("TOTAL FUEL CONS. / tons")
plt.tight_layout()
plt.show()


# FUEL CONSUMPTION DAILY

plt.figure(figsize=(8, 4))

slicing = (df["status"] == 1)

df["daily_fuel"] = df["fuel"] / df["transit_time"] * 24.

# optional slicing
subDf = df[slicing]

# subDf = df

quantiles = subDf.groupby("eta")["daily_fuel"].quantile(
    [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
).unstack()

x = pd.to_datetime(quantiles.index.values, unit="s")

q00 = quantiles[0.01].values
q05 = quantiles[0.05].values
q25 = quantiles[0.25].values
q50 = quantiles[0.50].values
q75 = quantiles[0.75].values
q95 = quantiles[0.95].values
q100 = quantiles[0.99].values

plt.fill_between(x, q00, q100, alpha=0.1, label="1–99%", color="limegreen")
plt.fill_between(x, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
plt.fill_between(x, q25, q75, alpha=0.4, label="25–75%", color="limegreen")

plt.plot(x, q50, label="Median", marker="o")

plt.legend()
plt.xticks(rotation=45)
plt.xlabel("ETA")
plt.ylabel("DAILY FUEL CONS. / tons/day")
plt.tight_layout()
plt.show()


# CONVERGED RATIO

# Compute ratio of status == 1 per eta
ratio = df.groupby("eta")["status"].apply(lambda s: (s == 1).mean())

# Arrays for plotting if needed
x = pd.to_datetime(ratio.index.values, unit="s")
prob = ratio.values

plt.figure(figsize=(8, 4))

# Plot
plt.plot(x, prob*100, marker="o")
plt.xlabel("ETA")
plt.ylabel("Probability of possible ETA / %")
# plt.ylim(0, 102)
plt.xticks(rotation=45)
# plt.legend()
plt.tight_layout()
plt.show()

#%%    
# json_file = "output_ensemble.json"
    
with open(os.path.join(_HOME, "routes", json_file), "r") as f:
    reports = json.load(f, object_hook=custom_decoder)
    
#%%

def routes_to_table(
    DF,
    mask,
    variables = ("sog", "cog", "avg_bhp", "twa")
):

    rows = DF.loc[mask]

    tables = []

    for I, row in rows.iterrows():

        data = {
            "timestamp": pd.to_datetime(row["tim"][:-1], unit="s")
        }

        for VAR in variables:
            data[f"{VAR}_{I}"] = np.asarray(row[VAR])

        tables.append(pd.DataFrame(data))

    table = tables[0]

    for t in tables[1:]:
        table = table.merge(t, on="timestamp", how="outer")

    table = table.sort_values("timestamp")

    return table


mask = (df["status"] == 1) & (df.index.isin([1, 2]))

table = routes_to_table(df, mask)

table_fmt = table.copy()

for col in table_fmt.columns:

    if col.startswith("sog"):
        table_fmt[col] = table_fmt[col].map(lambda x: f"{x:.1f}" if pd.notna(x) else "")

    elif col.startswith(("cog", "avg_bhp", "twa")):
        table_fmt[col] = table_fmt[col].map(lambda x: f"{x:.0f}" if pd.notna(x) else "")

table_fmt.to_clipboard(index=False, excel=True)

print("Table copied to clipboard. Paste directly into Word.")
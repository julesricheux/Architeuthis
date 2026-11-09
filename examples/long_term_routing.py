# -*- coding: utf-8 -*-
"""
Several starting routes and two weather models, with the spread of an ensemble along a route.

The optimizer may also move each route between its port and starboard references (vary_fac). Run from
the repository root, cell by cell (#%%) or as a script.

Needs the polar files of vessel_files and CMEMS credentials for the currents (CMEMS_USER, CMEMS_PWD).

Created on Tue Feb  3 14:35:10 2026

@author: jrich
"""

import os

import pandas as pd
import cartopy.crs as ccrs
import architeuthis.numpy as np
import matplotlib.pyplot as plt
import cartopy.feature as cfeature

from itertools import product
from architeuthis.common import _HOME, wide, tall
from architeuthis.vessel import Vessel
from architeuthis.core import RoutingAnalysis, Voyage, DEFAULT_SOLVER_OPTIONS
from architeuthis.icebergs import berg_zone
from architeuthis.report import ReportCollection
from architeuthis.route import Route, RouteLibrary
from architeuthis.voyage import PassagePlan, PassagePlanLibrary
from architeuthis.forecast import DeterministicHerbieForecast, EnsembleHerbieForecast, CopernicusForecast, Topography
from architeuthis.toolbox.plot_utils import (
    draw,
    plot_convergence,
    plot_ensemble_along_route,
    plot_fuel_distribution,
    plot_fuel_quantiles,
    plot_fuel_vs_etd,
    plot_quantiles,
    plot_variable,
)

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
    "lat",
    "lon",
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

reports = ReportCollection()
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
    # (to_time("2026-09-04T15h00"), to_time("2026-09-14T02:00")),
    (to_time(recent + pd.Timedelta(hours=15)), to_time(recent + pd.Timedelta(days=9, hours=26))),
]

def custom_constraints(ctx):
    return [
        ctx["max_bhp"] < ctx["vessel"].max_power,
        # (wide(ctx["z"]) @ tall(ctx["z"])) == 0.,
        ctx["z"] < 0.,
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
    report["member"] = m

    # Passage plan of this routing, stored after the loop and evaluated in a later cell.
    plan = analysis.passage_plan
    plan.name = f"{plan.name}_{model}{vessel.label}_fac{fac:+.2f}_m{m}_{'solved' if solve else 'ref'}"
    plan.metadata |= {"model": model, "member": m, "solve": solve, "vessel_tag": vessel.label}
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


# WRITE (ui.py displays the latest file of this folder)
ReportCollection(cv_reports).save(os.path.join(_HOME, "routes", json_file))

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
    evaluation["vessel"] = vessel.label
    evaluations.append(evaluation)

eval_table = pd.DataFrame(evaluations).pivot_table(
    index="plan",
    columns=["model", "vessel"],
    values="fuel",
)
print(eval_table)

#%% FUEL PER ETA, VESSEL, STARTING ROUTE AND MODEL

# 1. Convert your list of dictionaries into a Pandas DataFrame
cv_df = pd.DataFrame(cv_reports)

# 2. Convert the ETA timestamp to a human-readable date format
cv_df['eta_date'] = pd.to_datetime(cv_df['eta'], unit='s')

# 3. Group by the requested columns and calculate the mean (or sum) of fuel
# We use 'vessel' as it maps to your efficiency tracking field
grouped_df = cv_df.groupby(['eta_date', 'vessel', 'init_fac', 'model'])['fuel'].mean().reset_index()

grouped_df["fuel"] = grouped_df["fuel"].round(1)

# 4. Rename the columns to match your preferred formatting
grouped_df.columns = ['ETA', 'Efficiency', 'Init Fac', 'Model', 'Total Fuel Consumption']

# Display the resulting table
print(grouped_df)

#%% FIGURES: ALL THE RUNS

solved = reports.select(solve=1)

plot_fuel_vs_etd(reports)
plot_fuel_distribution({
    "Started to port": reports.select(lambda report: report["init_fac"] < 0.),
    "Ortho references": reports.select(init_fac=0.),
})
plot_quantiles(reports.select(lambda report: report["init_fac"] != 0.), "swh", unit="m", ylim=(0., 9.))
plot_quantiles(solved, "avg_bhp", unit="kW", title="AVG_BHP distribution along optimised routes for all scenarios")
plot_fuel_quantiles(reports)
plot_fuel_quantiles(reports, daily=True)
plot_convergence(reports)

#%% FIGURES: A FEW ROUTES

compared = reports[4:10:5]

plot_variable(compared, "sog", unit="kts", figsize=(8, 4), dpi=100)

for report in compared:
    plot_variable([report], "sog", unit="kts", ylim=(4., 14.), figsize=(10, 3), dpi=100)
    plot_ensemble_along_route(
        report,
        atmos_ens,
        wave_ens,
        ylim={"bhp": (0., 2700.), "swh": (0., 7.), "tws": (0., 40.)},
    )

#%% BACK LATER: RELOAD THE REPORTS

reports = ReportCollection.latest()

# json_file = "output_ensemble.json"
# reports = ReportCollection.load(os.path.join(_HOME, "routes", json_file))

#%% TABLE TO PASTE IN A DOCUMENT

table = reports.select(solve=1)[:2].table()

for column in table.columns:
    if column.startswith("sog"):
        table[column] = table[column].map(lambda value: f"{value:.1f}" if pd.notna(value) else "")
    elif column.startswith(("cog", "avg_bhp", "twa")):
        table[column] = table[column].map(lambda value: f"{value:.0f}" if pd.notna(value) else "")

table.to_clipboard(index=False, excel=True)
print("Table copied to clipboard. Paste directly into Word.")

#%% FIGURE AND TABLE SETTINGS OF EARLIER STUDIES

# What the former figures had as comments, in their order: other variables, units, limits, and
# conditions that selected the reports. Pass them to reports.select and to the helpers of plot_utils,
# for example plot_variable(reports.select(init_fac=0.), "swh", unit="m", ylim=(0., 10.)).

# plt.ylim((minFuel, maxFuel))

# (r["init_fac"] != 0.) &
# (r["init_fac"] == 0.) &
# (r["vessel"] == "eff45") &
# (r["eta"] >= 1772049600.0) &
# (r["eta"] < 1772049600.0) &

# options = {-0.5: "North coast", 0.:"Ortho cst speed", 0.75: "North offshore", 3.: "South"}

# variable = "swh"
# unit = "m"
# variable = "sails_contribution"
# unit = "%"
# variable = "mwa"
# unit = "deg"
# variable = "avg_bhp"
# variable = "max_bhp"
# unit = "kW"

# plt.legend()

# plt.violinplot([r["fuel"] for r in reports])
# plt.boxplot([r["fuel"] for r in reports])

# [r["fuel"] for r in reports if (r["vessel"] == "_eff90")],
# [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
# [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
# [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],

# [r["fuel"] for r in reports if (r["init_fac"] > 0.)],
# [r["fuel"] for r in cv_reports],

# fig, ax = plt.subplots(figsize=(3, 4))  # width=8, height=3

# colors = ["tab:blue", "tab:orange", "tab:green"]

# ax.set_xticklabels(["Ortho routes", "North routes"])
# ax.set_xticklabels(["North routes", "Ortho routes", "South routes"])
# ax.set_xticks([1])
# ax.set_xticklabels(["All routes"])

# (r["init_fac"] == 0.) &
# (r["init_fac"] == -1.) &
# (r["vessel"] == "eff45") &
# (r["eta"] >= 1772049600.0) &
# (r["eta"] < 1772049600.0) &

# variable = "tws"
# variable = "avg_bhp"
# variable = "sails_contribution"

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

# environment_query = np.concatenate([
#     r["ctim"], r["clat"], r["clon"],
# ], axis=1)

# vmin = (r[variable].min() // 1 - 1)
# vmax = (r[variable].max() // 1 + 2)

# plt.fill_between(ctim, q00, q100, alpha=0.1, label="01–99%", color="limegreen")
# plt.fill_between(ctim, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
# plt.fill_between(ctim, q25, q75, alpha=0.4, label="25–75%", color="limegreen")

# plt.title(f"{variable.upper()} distribution")
# plt.ylim((-180, 180))

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

# variable = "max_bhp"

# [r["fuel"] for r in reports if (r["vessel"] == "_eff90")],
# [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
# meteogram = np.array([r[variable] for r in reports if (r["vessel"] == "_eff90")])
# meteogram = np.array([r[variable] for r in reports if (r["vessel"] == "_eff60")])

# plt.ylim((-180, 180))
# plt.ylim((0, None))

# (r["init_fac"] != 0.) &
# (r["init_fac"] == -1.) &
# (r["vessel"] == "eff45") &
# (r["status"] == 1) &
# (r["solve"] == 1) &
# (r["eta"] == eta) &

# slicing = (df["status"] == 1) & (df["eta"] == eta) & (df["solve"] == 1)

# subDf = df[slicing]

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

# plt.xlabel("Time (UTC)")

# subDf = df

# Compute ratio of status == 1 per eta

# plt.ylim(0, 102)
# plt.legend()

# -*- coding: utf-8 -*-
"""
Created on Fri Mar 20 11:03:01 2026

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
from architeuthis import presets
from architeuthis.common import _HOME, Domain, wide, tall
from architeuthis.vessel import Vessel
from architeuthis.toolbox.geo_utils import poly_deviated_route
from architeuthis.toolbox.plot_utils import draw, get_steps, plot_report, set_plot_style
from architeuthis.report import ReportCollection, routes_to_table
from architeuthis.core import RoutingAnalysis, Voyage, DEFAULT_SOLVER_OPTIONS, exclusion_zones
from architeuthis.route import Route, RouteLibrary, RouteSet, RouteSetLibrary
from architeuthis.voyage import PassagePlan, PassagePlanLibrary
from architeuthis.forecast import DeterministicHerbieForecast, EnsembleHerbieForecast, CopernicusForecast, Topography


set_plot_style() # figures drawn by hand below use the same style
        
# minimum_longitude=-80.
# maximum_longitude=0.
# minimum_latitude=30.
# maximum_latitude=60.

# minimum_longitude=-90.
# maximum_longitude=-72.
# minimum_latitude=9.
# maximum_latitude=18.

minimum_longitude=-70.
maximum_longitude=5.
minimum_latitude=30.
maximum_latitude=60.

# minimum_longitude=-80.
# maximum_longitude=-50.
# minimum_latitude=35.
# maximum_latitude=50.

steps = list(range(0, 145, 3)) + list(range(150, 361, 6)) # fxx
    
domain = Domain(
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
)

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
    return np.abs(cubic_model(x, p_sfc))

def hotel_load_func(x):
    p_hl = {
        'a': 177.84810351574922,
        'b': -0.011382017491188723,
        'c': 1.0915372379294297e-05
    }
    return quadratic_model(x, p_hl)

vessel_files = [    
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff00.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff15.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff30.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff45.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff60.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff75.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff90.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff100.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff60.nc",
    
    r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_28up_28down_7buff_5m_eff1.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff15.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_28up_28down_7buff_5m_eff30.nc",
    r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_28up_28down_7buff_5m_eff45.nc",
    r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_28up_28down_7buff_5m_eff60.nc",
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
    
    vessel.add_interpolators() # bhp, max_bhp, sails_contribution
    # vessel.add_interpolator("leeway", "stw", "tws", "twa", "hs", "wa", method="linear")
    
    vessels.append(vessel)

#%% BUILD WIND INTERPOLATORS

# global_corr_fac = 1.10 # global models speed correction (120% @ 10m, 105% @ 100m)
global_corr_fac = 1.20 # global models speed correction (120% @ 10m, 105% @ 100m)

recent = pd.Timestamp("now").floor("1d")
# recent = pd.Timestamp('2026-05-30 00:00')
# mirror_end = pd.Timestamp('2025-12-21 12:00')

ATMOS = {}

gust_default_factor = 1.23 # (https://cimmse.wordpress.com/2013/09/20/a-wind-gust-factor-database-of-marine-observations-from-10-tropical-cyclones-2/)

# IFS atmospheric data (10 m wind, MSL pressure, 10 m wind gust)
ATMOS["ifs"] = presets.atmosphere(
    "ifs", domain, date=recent, fxx=steps,
    wind_factor=global_corr_fac, gust_factor=gust_default_factor,
)

# GFS atmospheric data (10 m wind, surface gust, surface pressure)
ATMOS["gfs"] = presets.atmosphere(
    "gfs", domain, date=recent, fxx=steps,
    wind_factor=global_corr_fac, gust_factor=gust_default_factor,
)

# atmos = DeterministicHerbieForecast(
#     "wind", model="ifs", product="scda", regex=r":10[u|v]:", fxx=steps,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     # date=mirror_date
# )

# atmos_ens = EnsembleHerbieForecast(
#     "wind_ens", model="ifs", product="enfo", regex=r":10[u|v]:", fxx=steps,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     date=recent
# )
# atmos_ens.load_data()

# atmos_ens.add_interpolator(
#     "u10", "valid_time", "number", "latitude", "longitude",
#     member_slice=slice(None, None,1),
#     time_slice=slice(None, None,1),
#     latitude_slice=slice(None, None,2),
#     longitude_slice=slice(None, None,2),
#     fac=global_corr_fac
# )
# atmos_ens.add_interpolator(
#     "v10", "valid_time", "number", "latitude", "longitude",
#     member_slice=slice(None, None,1),
#     time_slice=slice(None, None,1),
#     latitude_slice=slice(None, None,2),
#     longitude_slice=slice(None, None,2),
#     fac=global_corr_fac
# )


#%% BUILD WAVE INTERPOLATORS

WAVE = {}

# IFS wave data
WAVE["ifs"] = presets.wave("ifs", domain, date=recent, fxx=steps)

# GFS wave data
WAVE["gfs"] = presets.wave("gfs", domain, date=recent, fxx=steps)

# wave_ens = EnsembleHerbieForecast(
#     "wave_ens", model="ifs", product="waef", regex=r":swh:|:mwd:", fxx=steps,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     date=recent
# )
# wave_ens.load_data()

# wave_ens.add_interpolator(
#     "swh", "valid_time", "number", "latitude", "longitude",
#     member_slice=slice(None, None,1),
#     time_slice=slice(None, None,1),
#     latitude_slice=slice(None, None,2),
#     longitude_slice=slice(None, None,2),
# )
# wave_ens.add_interpolator(
#     "mwd", "valid_time", "number", "latitude", "longitude",
#     member_slice=slice(None, None,1),
#     time_slice=slice(None, None,1),
#     latitude_slice=slice(None, None,2),
#     longitude_slice=slice(None, None,2),
# )


#%% BUILD CURRENT INTERPOLATORS

# Mercator SMOC data
current = presets.current_mercator(
    domain,
    date=recent,
    # date=mirror_date, end=mirror_end
)


#%% BUILD TOPOGRAPHY

# # source file: https://rynda.io/blog/eca-zones/polygons.geojson
# file_path = "C:/Users/jrich/Downloads/formatted_file_mod.geojson"
# selected_ids = ["north-american-atlantic"]

# from architeuthis.toolbox.os_utils import extract_polygons_from_geojson

# eca = extract_polygons_from_geojson(file_path, selected_ids)

# safety = [[
#     [49.22829272317526, -65.94945285687805],
#     [49.24967849277576, -65.39454839496966],
#     [49.20186222198922, -64.93405476164935],
#     [49.083381013855586, -64.56026495050253],
#     [48.85022124091634, -64.18991833941845],
#     [48.03336057443036, -64.51390925616687],
#     [47.066624624398145, -63.993876030092224],
#     [46.87986733827569, -63.96650586029921],
#     [46.7237379730156, -64.01212280995423],
#     [46.56088271827619, -63.62894043284655],
#     [46.4289878564139, -63.03592008732295],
#     [46.47298835466361, -61.9867302452418],
#     [47.0293253396176, -60.49049429653593],
#     [45.961665009785804, -59.82448683156247],
#     [45.27657778932076, -60.967985667251355],
#     [44.50354651869886, -63.50689818993442],
#     [44.49479316788097, -63.923848320183765],
#     [44.39849082233545, -64.25495577655852],
#     [43.96316577728297, -64.69643238505847],
#     [43.448999524918776, -65.41996349343276],
#     [43.42228477857577, -65.6223069389946],
#     [43.742083201791786, -66.10670488443196],
#     [44.26691358799425, -66.41941748211889],
#     [44.804283979142156, -66.98267130409891],
#     [46.98328410288116, -70.61081256523659],
#     [47.17147691449833, -70.31695921902707],
#     [47.49485787111169, -70.01916204070096],
#     [47.71202524104103, -69.69090833278551],
#     [48.02077593848, -69.39311115445867],
#     [48.312664113000466, -68.8980537433381],
#     [48.644669201610526, -68.15356079752212],
#     [49.13802862532202, -66.51780700843068],
#     [49.22829272317526, -65.94945285687805],
# ]]

topo0 = presets.topography(domain, exclusion_zones=exclusion_zones, name="topo0")

# topo = Topography(
#     "topo", depth_offset=-10., z_margin=0.,
#     # "topo", depth_offset=0., z_margin=0.,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     exclusion_zones=exclusion_zones + eca + safety,
# )
# topo.load_data()

# topo.add_interpolator(
#     "distance_to_iso0",
#     "latitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
#     "longitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
#     var_key="z"
# )


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

# departure = np.array([44.517, -63.390]) # CAHAL

arrival = np.array([46.781, -56.091]) # SPM pilot
# departure = np.array([45.831667, -51.700000]) # pos 27/02/2026 14h00 UTC
# departure = np.array([44.993333, -39.533333]) # pos 01/03/2026 14h00 UTC
# departure = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# departure = np.array([37.38330548509701, -74.4866180419922]) # pos 20/02/2026 17h00 UTC
# departure = np.array([43.248056, -62.397778]) # pos 23/02/2026 09h20 UTC
# arrival = np.array([47.112116788143474, -2.4051169026612866]) # Montoir pilot
# departure = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# arrival = np.array([46.50781973122021, -53.33670295591693]) # Cape Race

# departure = np.array([51.381, 3.107]) # BEZEE
departure = np.array([50.489, -0.037])
# arrival = np.array([51.381, 3.107]) # BEZEE
# arrival = np.array([36.995605446063365, -75.94119037659861]) # Cape Henry
# wp = np.array([46.551, -53.321]) # cape race
# wp = np.array([46.166667, -46.916667]) # iip 23/02/2026
wp = np.array([
    # [46.551, -53.321], # cape race
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
    
    # [51.066, 1.644], # calais
    # [50.610, 0.535], # eastbourne
    [49.665, -6.241], # scilly

    [46.551, -53.321], # cape race
    # [49.665, -6.241], # scilly
    # [50.610, 0.535], # eastbourne
    # [51.066, 1.644], # calais
    # [47.72529611513597, -4.379839003826363], # Penmarc'h
])
# arrival = np.array([46.781, -56.091]) # SPM pilot

# departure = np.array([11.3196, -74.2835])
# wp = np.array([
#     [15.4358, -82.9951],
#     [16.0791, -84.9973],
#     [16.0810, -85.9931],
# ])
# arrival = np.array([15.9927, -87.7219])

# lats = [departure[0], arrival[0]]
# lons = [departure[1], arrival[1]]
# Reference routes as Route objects (architeuthis.route), with the same waypoints and
# divergences as before. A Route is called like the former poly_deviated_route
# functions: route(s) -> (lat, lon) for s in [0, 1].
routeSbd = Route(
    "simple_starboard",
    [departure, *wp, arrival],
    divergences=[0., -0.3, 0.0],
)

routeO = Route(
    "simple_ortho",
    [departure, *wp, arrival],
    divergences=list(np.zeros(len(wp) + 1)),
)

routePrt = Route(
    "simple_port",
    [departure, *wp[:-2], arrival],
    divergences=[0.5],
)

# Store the routes: RouteLibrary().load(name) gives them back in any script
# (~/data/route_library/), and route.reversed() gives the return passage.
routes = RouteLibrary()
for route in (routeSbd, routeO, routePrt):
    routes.save(route, overwrite=True)

# The same three routes as one entry: RouteSetLibrary().load("simple") (~/data/route_sets/).
route_set = RouteSet("simple", ortho=routeO, minus=routePrt, plus=routeSbd)
RouteSetLibrary().save(route_set, overwrite=True)


ax = plt.axes(projection=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND, facecolor="khaki")
# ax.add_feature(cfeature.LAND, facecolor="sandybrown")
ax.add_feature(cfeature.OCEAN, facecolor="lavender")
# ax.add_feature(cfeature.OCEAN, facecolor="lightsteelblue")
ax.add_feature(cfeature.COASTLINE, linewidth=0.3)
# ax.add_feature(cfeature.BORDERS, linestyle=":")
gl = ax.gridlines(draw_labels=False, dms=True, x_inline=False, y_inline=False, linewidth=0.5)

ax.plot(*routeSbd(np.linspace(0,1,50))[::-1], c="green", ls="--", lw=1)
ax.plot(*routeO(np.linspace(0,1,50))[::-1], c="black", lw=1)
ax.plot(*routePrt(np.linspace(0,1,50))[::-1], c="red", ls="--", lw=1)

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
restart = None
# restart = ([43.612500, -11.603333], "2026-06-01T06:30") # pos 01/06/2026 06h30 UTC

solver_options = DEFAULT_SOLVER_OPTIONS

reports = ReportCollection()
plans = [] # PassagePlan of each routing (timed positions)

zero_fac = 0.

models = ["ifs", "gfs"]
# models = ["ifs",]
# facs = np.asarray([0., 1.]) + zero_fac
# facs = np.asarray([-1., 0., 1.]) + zero_fac
# facs = np.asarray([-1., 0., 1.]) + zero_fac
facs = [zero_fac]
# topos = [topo]
topos = [topo0]

# members = None
members = [0]
# members = list(range(1,51,1))

def to_time(s):
    return pd.to_datetime(s).timestamp()

timeframes = [
    # (to_time("2026-11-05T11h00"), to_time("2026-11-15T10:00")),
    (to_time("2026-11-06T08h40"), to_time("2026-11-15T04:00")),
    # (to_time("2026-10-16T00h00"), to_time("2026-10-26T05:00")),
]

# for m, fac in product(list(range(1,51,1)), facs):
# for m, fac in product(list(range(1,51,51)), facs):
for solve, tf, model, vessel, fac, m, tpg in (
        list(
            # product([0], timeframes, models, vessels, [zero_fac], [1], [topo0]) # NOT SOLVED ortho cst speed refs
            product([0], timeframes, models[:1], vessels[:1], [zero_fac], [1], [topo0]) # NOT SOLVED ortho cst speed refs
        ) + list(
            product([1], timeframes, models, vessels[1:], facs, members, topos) # SOLVED
        )
    ):
                
    etd, eta = tf
    
    if float(vessel.label.removeprefix("eff")) > 5.0:
        def custom_constraints(ctx):
            return [
                ctx["max_bhp"] < ctx["vessel"].max_power,
                # (wide(ctx["z"]) @ tall(ctx["z"])) == 0.,
                ctx["z"] < 0.,
                ctx["aws_gust"] < 35.0,
                # ctx["aws_gust"] < 30.0,
                # ctx["aws"] < 25.0,
                # ctx["aws"] < 20.0,
                # ctx["aws"] > 10.0,
            ]
    else:
        def custom_constraints(ctx):
            return [
                ctx["max_bhp"] < ctx["vessel"].max_power,
                # (wide(ctx["z"]) @ tall(ctx["z"])) == 0.,
                
                ctx["z"] < 0.,
                # ctx["aws"] < 35.0,
                # ctx["aws"] > 10.0,
            ]
        
        
    voyage = Voyage.from_routes(route_set, etd=etd, eta=eta, name="voyage")
    if restart is not None:
        voyage = voyage.from_position(*restart)

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
        options={"include_gusts": True},
        verbose=False,
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
        vary_fac=0,
        # vary_fac=1,
        solver_options = {
            "ipopt":{
                "acceptable_tol": 1e2,
                # 'linear_solver': 'spral',
                # 'linear_solver': 'mumps',
                "hessian_approximation": "limited-memory",
            },
        },
        # solve=0,
        solve=solve,
        tags={"solve": solve, "model": model, "member": m}, # the vessel label is added by default
    )

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
    
    if report["status"] != 1:
        print(f"💀 WARNING: {model} {vessel.label}% did not converge.")
    reports.append(report)

for report in reports:
    # print(f"{pd.to_datetime(report['etd'], unit='s').strftime('%d/%m %Hh%M UTC')} - {pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}")
    print(f"{pd.to_datetime(report['etd'], unit='s').strftime('%d/%m %Hh%M UTC')} - {pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}")
    print(f"{report['init_fac']}, {report['model']}, {report['vessel'][3:]} %")
    print(f"{report['dist']:.1f} nmi, (+{report['dist_rel'] * 100 - 100:.1f} %)")
    print(f"Avg STW {np.mean(report['stw']):.1f} kts")
    print(f"fuel = {report['fuel']:.1f} t ({report['fuel']/report['transit_time']*24.:.1f} t/day)")
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
ReportCollection(cv_reports).save(os.path.join(_HOME, "routes", json_file))

# Passage plans, reloadable with PassagePlanLibrary().load(name) (~/data/passage_plans/)
plan_library = PassagePlanLibrary()
for plan in plans:
    plan_library.save(plan, overwrite=True)
    
fuel_table = df.pivot_table(
    index='vessel', 
    columns='model', 
    values='fuel', 
    aggfunc='mean'  # Choose the appropriate aggregation function (e.g., 'mean', 'sum', 'first')
)

print(fuel_table)

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
        None, # no voyage needed: the plan gives the positions and times
        ATMOS[model],
        WAVE[model],
        current,
        topos[0],
        verbose=False,
    ).evaluate(plan, tags={"model": model}) # the plan name and vessel label are added by default
    evaluations.append(evaluation)

eval_table = pd.DataFrame(evaluations).pivot_table(
    index="plan",
    columns=["model", "vessel"],
    values="fuel",
)
print(eval_table)

#%% test for later

from architeuthis.modeling import InterpolatedModel

ds = ATMOS["ifs"].data

interp = InterpolatedModel(
    x_data_coordinates={
        "valid_time": ds["valid_time"],
        "latitude": ds["latitude"],
        "longitude": ds["longitude"],
    },
    y_data_structured=ds["u10"].data,
    # method="bspline",
    method="linear",
    # fill_value=0.
)
n = 100

clat, clon = routeO(np.linspace(0, 1, n))
ctim = np.linspace(timeframes[0][0], timeframes[0][1], n)

from architeuthis.optimization import Opti

opti = Opti()

xq = {
    # "valid_time": opti.parameter(ctim),
    "valid_time": ctim,
    "latitude": clat,
    "longitude": clon,
}

interp(xq)

#%% FUEL VS ETA

fuel_reports = (
    pd.DataFrame(reports)
    .groupby(["solve", "vessel", "model"], as_index=False)[["etd", "fuel"]]
    .agg(list)
)

minFuel = (df["fuel"].min() // 2 - 1) * 2.
maxFuel = (df["fuel"].max() // 2 + 1) * 2.

effs = fuel_reports["vessel"].unique()
models = fuel_reports["model"].unique()

markers = {0 : "x", 1: "o"}
names  = {0 : "ortho cst speed", 1: "optimised"}
colors = {model : color for model, color in zip(models, sns.color_palette("viridis", len(models)))}

for eff in effs:
    
    plt.figure(figsize=(10, 3.5))

    sub_fuel_reports = fuel_reports[fuel_reports["vessel"] == eff]
    
    for i in range(len(sub_fuel_reports)):
        fr = sub_fuel_reports.iloc[i]
        
        # plt.plot(
        plt.scatter(
            pd.to_datetime(fr["etd"], unit="s"), fr["fuel"],
            marker=markers[fr["solve"]],
            color = colors[fr["model"]],
            label=f"{fr['model'].upper()} / {names[fr['solve']]}"
        )
    
    plt.xticks(rotation=45.)
    plt.xlabel("ETD (UTC)")
    plt.ylabel("Total fuel consumption / tons")
    plt.title(f"Sails efficiency {eff[3:]} %")
    plt.ylim((minFuel, maxFuel))
    plt.legend()
    plt.show()

#%%

import seaborn as sns

def slicing(r):
    return (
        # (reports.index(r) in [len(reports)-3]) &
        # (r["init_fac"] != 0.) &
        # (r["init_fac"] == 0.) &
        (r["vessel"] == "eff45") &
        # (r["solve"] == 1) &
        (r["model"] != "ifs") &
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

# variable = "stw"
# unit = "kts"

# variable = "aws"
# unit = "kts"

# variable = "tws"
# unit = "kts"

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
plt.figure(figsize=(12, 6), dpi=300)
for i, r in enumerate(plots):
    x, y = get_steps(r, variable)
    plt.plot(x, y, label=options[r["init_fac"]], color=colors[i])
    plt.plot(x, y, label=options[r["init_fac"]], color=colors[i])
    plt.xlim((x.min(), x.max()))
plt.ylim((0., None))
# plt.legend()
plt.xticks(rotation=45)
plt.xlabel("Time (UTC)")
plt.ylabel(f"{variable.upper()} / {unit}")
plt.tight_layout()
plt.show()

#%%

import seaborn as sns
import matplotlib.pyplot as plt

def slicing(r):
    return (
        # (reports.index(r) in [len(reports)-3]) &
        # (r["init_fac"] != 0.) &
        # (r["init_fac"] == 0.) &
        (r["vessel"] == "eff45") &
        # (r["solve"] == 1) &
        (r["model"] != "ifs") &
        # (r["eta"] >= 1772049600.0) &
        # (r["eta"] < 1772049600.0) &
        True
    )

plots = [r for r in reports if slicing(r)]

options = {-1.: "North", 0.: "Ortho cst speed", 1.: "South"}
colors = sns.color_palette(palette="viridis", n_colors=len(plots))

# Create a figure with 3 stacked subplots that share the same x-axis
fig, axes = plt.subplots(nrows=3, ncols=1, figsize=(12, 10), dpi=300, sharex=True)

for i, r in enumerate(plots):
    label = options.get(r["init_fac"], f"Route {r.get('init_fac')}")
    color = colors[i]
    
    # 1. Plot AVG_BHP on the top subplot (axes[0])
    x_bhp, y_bhp = get_steps(r, "avg_bhp")
    axes[0].plot(x_bhp, y_bhp, label=label, color=color)
    
    # Uncomment if you still want max_bhp represented as dashed lines
    # x_mbhp, y_mbhp = get_steps(r, "max_bhp")
    # axes[0].plot(x_mbhp, y_mbhp, ls="--", color=color)
    
    # 2. Plot SWH on the middle subplot (axes[1])
    x_swh, y_swh = get_steps(r, "swh")
    axes[1].plot(x_swh, y_swh, label=label, color=color)
    
    # 3. Plot TWS on the bottom subplot (axes[2])
    x_tws, y_tws = get_steps(r, "tws")
    axes[2].plot(x_tws, y_tws, label=label, color=color)

# --- Formatting Axes ---

# Top subplot: BHP
axes[0].set_ylabel("AVG_BHP / kW")
axes[0].set_ylim((0., None))
axes[0].legend(loc="upper right")

# Middle subplot: SWH
axes[1].set_ylabel("SWH / m")
axes[1].set_ylim((0., None))

# Bottom subplot: TWS
axes[2].set_ylabel("TWS / kts")
axes[2].set_ylim((0., None))

# Format the shared x-axis (bottom-most plot)
axes[2].set_xlabel("Time (UTC)")
plt.setp(axes[2].xaxis.get_majorticklabels(), rotation=45)

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
    # [r["fuel"] for r in reports if (r["init_fac"] < 0.)],
    # [r["fuel"] for r in reports if (r["init_fac"] == 0.)],
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
        # (r["init_fac"] != 0.) &
        # (r["init_fac"] == -1.) &
        # (r["vessel"] == "eff45") &
        # (r["eta"] >= 1772049600.0) &
        # (r["eta"] < 1772049600.0) &
        True
    )

# variable = "swh"
# variable = "tws"
variable = "avg_bhp"
# variable = "max_bhp"
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
plt.legend()
plt.xticks(rotation=45)
plt.xlabel("Time (UTC)")
plt.ylabel(f"{variable.upper()} / {unit}")
plt.tight_layout()
plt.show()

#%%

# variable = "sog"
unit = "kts"
# variable = "swh"
# unit = "m"
variable = "tws"
# variable = "avg_bhp"
# variable = "max_bhp"
# unit = "kW"
# variable = "sails_contribution"

plt.figure(figsize=(9,3))

for r in cv_reports[1:]:
    
    plt.plot(ctim, r[variable], marker="o", ms=3.)
    
    plt.legend()
    plt.xticks(rotation=45)
    # plt.xlabel("Time (UTC)")
    plt.ylabel(f"{variable.upper()} / {unit}")
    plt.tight_layout()
    plt.ylim((0, None))
    # plt.ylim((0, 1000))
plt.show()

#%%

# variable = "sog"
# unit = "kts"
# vmin = 5.
# vmax=11.

# variable = "swh"
# unit = "m"

variable = "sails_contribution"
unit = "%"
vmin = -1
vmax= 101.

# variable = "mwa"
# unit = "deg"

# variable = "avg_bhp"
# variable = "max_bhp"
# unit = "kW"
# vmin = 0.
# vmax = maxBHP * 1.1



def slicing(r):
    return (
        (reports.index(r) in [len(reports)-3]) &
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
        (reports.index(r) in [len(reports)-3]) &
        # (r["init_fac"] != 0.) &
        # (r["init_fac"] == 0.) &
        # (r["vessel"] == "eff45") &
        # (r["eta"] >= 1772049600.0) &
        # (r["eta"] < 1772049600.0) &
        True
    )

for r in [r for r in reports if slicing(r)]:
    # environment_query = np.concatenate([
    #     r["ctim"], r["clat"], r["clon"],
    # ], axis=1)
    
    n = r["ctim"].shape[0]
    
    tim = pd.to_datetime(r["tim"], unit="s")
    ctim = pd.to_datetime(r["ctim"], unit="s")
    
    stw = r["stw"]
    
    plt.figure(figsize=(10,3.5))
    
    osc = r["max_bhp"] - r["avg_bhp"]
    
    plt.plot(ctim, r["avg_bhp"], label="Average BHP")
    plt.plot(ctim, r["max_bhp"], label="Load fluctuations", ls="--")
    plt.plot(ctim, r["max_bhp"] - 2*osc, ls="--")
    plt.fill_between(ctim, r["avg_bhp"] - osc, r["avg_bhp"] + osc, alpha=0.1)
    
    plt.legend()
    
    plt.xticks(rotation=45)
    plt.xlabel("Time (UTC)")
    plt.ylabel("BHP / kW")
    # plt.title(f"{variable.upper()} distribution")
    plt.tight_layout()
    
    # plt.ylim((0., maxBHP*1.05))
    plt.xlim((tim[0], tim[-1]))
    
    plt.show()
    
    env_var = [
        (r["swh"], "swh", "m", 2., 9.),
        (r["tws"], "tws", "kts", 0., 50.),
    ]
    # meteogram = swh
    # variable = "swh"
    # unit = "m"
    # vmin = 2.
    # vmax = 9.
    # meteogram = tws
    # variable = "tws"
    # unit = "kts"
    # vmin = 0.
    # vmax = 50.
    
    for meteogram, variable, unit, vmin, vmax in env_var:
        # q00 = np.quantile(meteogram, 0.01, axis=0)
        # q05 = np.quantile(meteogram, 0.05, axis=0)
        # q25 = np.quantile(meteogram, 0.25, axis=0)
        # q50 = np.quantile(meteogram, 0.50, axis=0)
        # q75 = np.quantile(meteogram, 0.75, axis=0)
        # q95 = np.quantile(meteogram, 0.95, axis=0)
        # q100 = np.quantile(meteogram, 0.99, axis=0)
        
        plt.figure(figsize=(10,3.5))
        
        # plt.fill_between(ctim, q00, q100, alpha=0.1, label="01–99%", color="limegreen")
        # plt.fill_between(ctim, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
        # plt.fill_between(ctim, q25, q75, alpha=0.4, label="25–75%", color="limegreen")
        # plt.plot(ctim, q50, label="Median")
        plt.plot(ctim, meteogram, label="Median")
        plt.legend()
        plt.xticks(rotation=45)
        plt.xlabel("Time (UTC)")
        plt.ylabel(f"{variable.upper()} / {unit}")
        # plt.title(f"{variable.upper()} distribution")
        plt.tight_layout()
        # plt.ylim((-180, 180))
        # plt.ylim((vmin, vmax))
        plt.xlim((tim[0], tim[-1]))
        plt.show()

#%%

variable = "sog"
unit = "kts"

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

# variable = "avg_bhp"
# variable = "max_bhp"
# unit = "kW"

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
            # (r["eta"] >= 1772049600.0) &
            (r["status"] == 1) &
            (r["solve"] == 1) &
            (r["eta"] == eta) &
            True
        )
    # slicing = (df["status"] == 1) & (df["eta"] == eta) & (df["solve"] == 1)

    # # optional slicing
    # subDf = df[slicing]
    
    # variable = "swh"
    # unit = "m"
    # vmax = 10.
    # variable = "tws"
    # unit = "kts"
    # vmax=50.
    variable = "avg_bhp"
    # variable = "max_bhp"
    unit = "kW"
    vmax=1000
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
    
reports = ReportCollection.load(os.path.join(_HOME, "routes", json_file))
    
#%%

# mask = (df["status"] == 1) & (df.index.isin([len(reports)-3]))

# table = routes_to_table(df, mask)

mask = (df["status"] == 1) & (df.index == len(df)-5)

table = routes_to_table(
    df, mask,
    variables = ("sog", "cog", "avg_bhp", "tws", "twa", "aws", "awa", "swh", "mwa")
)

table_fmt = table.copy()

# for col in table_fmt.columns:

#     if col.startswith("sog"):
#         table_fmt[col] = table_fmt[col].map(lambda x: f"{x:.1f}" if pd.notna(x) else "")

#     elif col.startswith(("cog", "avg_bhp", "twa")):
#         table_fmt[col] = table_fmt[col].map(lambda x: f"{x:.0f}" if pd.notna(x) else "")

table_fmt.to_clipboard(index=False, excel=True)

print("Table copied to clipboard. Paste directly into Word.")

#%%

from architeuthis.toolbox.os_utils import save_gpx

for i in [4, 8]:
    r = reports[i]

    # By default: track_<MODEL>_<vessel>_<ETD date>.gpx. save_gpx remains available.
    r.to_gpx(
        f"track_{r['model'].upper()}_{r['vessel']}_{recent.strftime('%Y%m%d')}.gpx",
        track_name=f"track_{r['model'].upper()}"
    )
    
#%%

def slicing(r):
    return (
        # (reports.index(r) in [len(reports) - 3]) &
        (r["vessel"] == "eff60") &
        # (r["model"] == "ifs") &
        True
    )

# # --- Keys to adapt to your report structure ---
# SOG_KEY   = "sog"    # speed over ground
# SAILS_KEY = "sails_contribution"  # sails contribution (set SAILS_SCALE=100. if stored as a 0-1 fraction)
# SAILS_SCALE = 1.

# A4 page of each selected report: see plot_report in toolbox/plot_utils.py and the README.
# plot_report(r, save_as="report.pdf")  # true A4 page
# plot_report(r, figsize=(8.27, 10))
# plot_report(r, ylim={"sog": (6., 13.), "bhp": (0., 3084.)})
for r in [r for r in reports if slicing(r)]:
    plot_report(r, save_as=None)
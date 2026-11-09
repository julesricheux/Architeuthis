# -*- coding: utf-8 -*-
"""
Optimize a voyage with two weather models and several sail efficiencies, then look at the results.

This is the most complete example: vessels, forecasts, topography and your exclusion zones, reference
routes, routing runs, results saved for ui.py, open-loop evaluation, figures, tables, GPX tracks and
the A4 page of each route. Run from the repository root, cell by cell (#%%) or as a script.

Needs the polar files of vessel_files and CMEMS credentials for the currents (CMEMS_USER, CMEMS_PWD).
IFS and GFS need none.

Created on Fri Mar 20 11:03:01 2026

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
from architeuthis.exclusion import ExclusionZone, ExclusionZoneLibrary
from architeuthis.toolbox.plot_utils import (
    draw,
    plot_convergence,
    plot_fuel_distribution,
    plot_fuel_quantiles,
    plot_fuel_vs_etd,
    plot_power_and_weather,
    plot_quantiles,
    plot_report,
    plot_variable,
)

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
    
    vessel.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("max_bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    # vessel.add_interpolator("leeway", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("sails_contribution", "stw", "tws", "twa", "hs", "wa", method="linear")
    
    vessels.append(vessel)

#%% BUILD WIND INTERPOLATORS

# global_corr_fac = 1.10 # global models speed correction (120% @ 10m, 105% @ 100m)
global_corr_fac = 1.20 # global models speed correction (120% @ 10m, 105% @ 100m)

recent = pd.Timestamp("now").floor("1d")
# recent = pd.Timestamp('2026-05-30 00:00')
# mirror_end = pd.Timestamp('2025-12-21 12:00')

ATMOS = {}

# IFS atmospheric data (10 m wind, MSL pressure, 10 m wind gust)
ATMOS["ifs"] = DeterministicHerbieForecast(
    "wind_ifs", model="ifs", product="oper",
    regex=r":(?:10[uv]|10fg|msl):", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent
)

# GFS atmospheric data (10 m wind, surface gust, surface pressure)
ATMOS["gfs"] = DeterministicHerbieForecast(
    "wind_gfs", model="gfs", product="pgrb2.0p25",
    regex=r"(?:(?:U|V)GRD:10 m above ground|GUST:surface|PRES:surface)", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent
)

GUST_VAR = {
    "ifs": "fg10",
    "gfs": "gust",
}

gust_default_factor = 1.23 # (https://cimmse.wordpress.com/2013/09/20/a-wind-gust-factor-database-of-marine-observations-from-10-tropical-cyclones-2/)

for model, atmos in ATMOS.items():
    atmos.load_data()
    
    # Sanity correction: gust can't be lower than the mean 10 m wind speed
    ds = atmos.data
    gust_var = GUST_VAR[model]
    speed = np.hypot(atmos.data.u10, atmos.data.v10)
    ds[gust_var] = ds[gust_var].where(atmos.data[gust_var] >= speed, speed * gust_default_factor)

    atmos.add_interpolator("u10", "valid_time", "latitude", "longitude", fac=global_corr_fac)
    atmos.add_interpolator("v10", "valid_time", "latitude", "longitude", fac=global_corr_fac)

    atmos.add_interpolator(gust_var, "valid_time", "latitude", "longitude", var_key="gust", fac=global_corr_fac)

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

# Stored for ui.py, which displays the iceberg limit and the zones of this library (~/data/exclusion_zones/).
ExclusionZoneLibrary().save(ExclusionZone("north_america", north_america, label="North America"), overwrite=True)
ExclusionZoneLibrary().save(ExclusionZone("brittany", brittany, label="Brittany"), overwrite=True)

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

topo0 = Topography(
    "topo0", depth_offset=0., z_margin=0.,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    exclusion_zones=exclusion_zones,
)
topo0.load_data()

topo0.add_interpolator(
    "distance_to_iso0",
    "lat",
    "lon",
    var_key="z"
)

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
rewind = None
# rewind = ([43.612500, -11.603333], "2026-06-01T06:30") # pos 01/06/2026 06h30 UTC

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
    # (to_time("2026-11-06T08h40"), to_time("2026-11-15T04:00")),
    (to_time(recent + pd.Timedelta(hours=9)), to_time(recent + pd.Timedelta(days=8, hours=20))),
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


# WRITE (ui.py displays the latest file of this folder)
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

#%% FIGURES: COMPARING ROUTES

# Any quantity per segment can be plotted: sog, stw, cog, tws, twa, aws, awa, swh, mwa,
# avg_bhp, max_bhp, sails_contribution, tws_gust, aws_gust...
options = {-1.: "Port route", 0.: "Ortho cst speed", 1.: "Starboard route"}
# options = {-0.5: "North coast", 0.:"Ortho cst speed", 0.75: "North offshore", 3.: "South"}

selected = reports.select(lambda report: report["model"] != "ifs", vessel="eff45")

plot_fuel_vs_etd(reports)
plot_variable(selected, "sog", unit="kts", labels=options)
plot_power_and_weather(selected, labels=options)
plot_variable(reports[1:], "tws", unit="kts", figsize=(9, 3), dpi=100)
plot_variable([reports[-3]], "sails_contribution", unit="%", ylim=(-1., 101.), figsize=(10, 3), dpi=100)
plot_fuel_distribution({f"Eff. {efficiency}%": reports.select(vessel=f"eff{efficiency}") for efficiency in [45, 60]})

#%% FIGURES: SPREAD OF SEVERAL RUNS

# They make sense with several runs: more facs or timeframes, or the members of an ensemble.
solved = reports.select(solve=1)

converged = solved.select(status=1)

plot_quantiles(reports, "avg_bhp", unit="kW")
plot_quantiles(solved, "sog", unit="kts", title="SOG distribution along optimised routes for all scenarios")

for eta in sorted({report["eta"] for report in converged}):
    same_eta = converged.select(eta=eta)
    plot_quantiles(
        same_eta,
        "avg_bhp",
        unit="kW",
        title=f"ETD {same_eta[0].etd_time} UTC - ETA {same_eta[0].eta_time} UTC",
        ylim=(0., 1000.),
        daily_ticks=True,
    )

plot_fuel_quantiles(reports)
plot_fuel_quantiles(reports, daily=True)
plot_convergence(reports)

#%% BACK LATER: RELOAD THE REPORTS

reports = ReportCollection.latest() # or ReportCollection.load(path)

# json_file = "output_ensemble.json"
# reports = ReportCollection.load(os.path.join(_HOME, "routes", json_file))

#%% TABLE TO PASTE IN A DOCUMENT

table = reports.select(solve=1)[:1].table(
    variables=("sog", "cog", "avg_bhp", "tws", "twa", "aws", "awa", "swh", "mwa")
)
table.to_clipboard(index=False, excel=True)
print("Table copied to clipboard. Paste directly into Word.")

#%% GPX TRACKS

# track_<MODEL>_<vessel>_<ETD date>.gpx in the working directory, or give report.to_gpx a file name.
reports.select(solve=1).to_gpx()

#%% A4 PAGE OF EACH ROUTE

# See "Plotting" in docs/user_guide.md for the options, for example:
# plot_report(report, save_as="report.pdf")  # a true A4 page
# plot_report(report, ylim={"sog": (6., 13.), "bhp": (0., 3084.)})
for report in reports.select(vessel="eff60"):
    plot_report(report)

#%% FIGURE AND TABLE SETTINGS OF EARLIER STUDIES

# What the former figures had as comments, in their order: other variables, units, limits, and
# conditions that selected the reports. Pass them to reports.select and to the helpers of plot_utils,
# for example plot_variable(reports.select(init_fac=0.), "swh", unit="m", ylim=(0., 10.)).

# method="bspline",
# fill_value=0.

# "valid_time": opti.parameter(ctim),

# plt.plot(

# (reports.index(r) in [len(reports)-3]) &
# (r["init_fac"] != 0.) &
# (r["init_fac"] == 0.) &
# (r["solve"] == 1) &
# (r["eta"] >= 1772049600.0) &
# (r["eta"] < 1772049600.0) &

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

# plt.legend()

# x_mbhp, y_mbhp = get_steps(r, "max_bhp")
# axes[0].plot(x_mbhp, y_mbhp, ls="--", color=color)

# Format the shared x-axis (bottom-most plot)

# plt.violinplot([r["fuel"] for r in reports])
# plt.boxplot([r["fuel"] for r in reports])

# [r["fuel"] for r in reports if (r["vessel"] == "_eff90")],
# [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
# [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
# [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
# [r["fuel"] for r in reports if (r["init_fac"] < 0.)],
# [r["fuel"] for r in reports if (r["init_fac"] == 0.)],
# [r["fuel"] for r in reports if (r["init_fac"] > 0.)],
# [r["fuel"] for r in cv_reports],

# fig, ax = plt.subplots(figsize=(3, 4))  # width=8, height=3

# colors = ["tab:blue", "tab:orange", "tab:green"]

# ax.set_xticklabels(["Ortho routes", "North routes"])
# ax.set_xticklabels(["North routes", "Ortho routes", "South routes"])
# ax.set_xticks([1])
# ax.set_xticklabels(["All routes"])

# (r["init_fac"] != 0.) &
# (r["init_fac"] == -1.) &
# (r["vessel"] == "eff45") &
# (r["eta"] >= 1772049600.0) &
# (r["eta"] < 1772049600.0) &

# variable = "swh"
# variable = "tws"
# variable = "max_bhp"
# variable = "sails_contribution"

# variable = "sog"
# variable = "swh"
# unit = "m"
# variable = "avg_bhp"
# variable = "max_bhp"
# unit = "kW"
# variable = "sails_contribution"

# plt.xlabel("Time (UTC)")

# plt.ylim((0, 1000))

# variable = "sog"
# unit = "kts"
# vmin = 5.
# vmax=11.
# variable = "swh"
# unit = "m"

# variable = "mwa"
# unit = "deg"
# variable = "avg_bhp"
# variable = "max_bhp"
# unit = "kW"
# vmin = 0.
# vmax = maxBHP * 1.1

# (r["init_fac"] != 0.) &
# (r["init_fac"] == 0.) &
# (r["vessel"] == "eff45") &
# (r["eta"] >= 1772049600.0) &
# (r["eta"] < 1772049600.0) &

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

# plt.title(f"{variable.upper()} distribution")

# plt.ylim((0., maxBHP*1.05))

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

# q00 = np.quantile(meteogram, 0.01, axis=0)
# q05 = np.quantile(meteogram, 0.05, axis=0)
# q25 = np.quantile(meteogram, 0.25, axis=0)
# q50 = np.quantile(meteogram, 0.50, axis=0)
# q75 = np.quantile(meteogram, 0.75, axis=0)
# q95 = np.quantile(meteogram, 0.95, axis=0)
# q100 = np.quantile(meteogram, 0.99, axis=0)

# plt.fill_between(ctim, q00, q100, alpha=0.1, label="01–99%", color="limegreen")
# plt.fill_between(ctim, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
# plt.fill_between(ctim, q25, q75, alpha=0.4, label="25–75%", color="limegreen")
# plt.plot(ctim, q50, label="Median")

# plt.title(f"{variable.upper()} distribution")
# plt.ylim((-180, 180))
# plt.ylim((vmin, vmax))

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

# plt.ylim((-180, 180))
# plt.ylim((0, None))

# (r["init_fac"] != 0.) &
# (r["init_fac"] == -1.) &
# (r["vessel"] == "eff45") &
# (r["eta"] >= 1772049600.0) &

# slicing = (df["status"] == 1) & (df["eta"] == eta) & (df["solve"] == 1)

# subDf = df[slicing]
# variable = "swh"
# unit = "m"
# vmax = 10.
# variable = "tws"
# unit = "kts"
# vmax=50.
# variable = "max_bhp"

# vmax = maxBHP *1.066
# variable = "sog"
# unit = "kts"
# vmax = 13.
# variable = "sails_contribution"
# unit = "%"
# vmax=45.

# subDf = df

# Compute ratio of status == 1 per eta

# plt.ylim(0, 102)
# plt.legend()

# mask = (df["status"] == 1) & (df.index.isin([len(reports)-3]))
# table = routes_to_table(df, mask)

#     if col.startswith("sog"):
#         table_fmt[col] = table_fmt[col].map(lambda x: f"{x:.1f}" if pd.notna(x) else "")
#     elif col.startswith(("cog", "avg_bhp", "twa")):
#         table_fmt[col] = table_fmt[col].map(lambda x: f"{x:.0f}" if pd.notna(x) else "")

# (reports.index(r) in [len(reports) - 3]) &
# (r["model"] == "ifs") &

# SOG_KEY   = "sog"    # speed over ground
# SAILS_KEY = "sails_contribution"  # sails contribution (set SAILS_SCALE=100. if stored as a 0-1 fraction)
# SAILS_SCALE = 1.
# A4 = (8.27, 11.69)  # inches, portrait

# ax_sog.set_ylim(6., 13.)

# ax_bhp.set_ylim(0., 3084)

#%% test for later

# Interpolating a forecast with InterpolatedModel rather than with add_interpolator. To finish:
# the last call fails as it is.

# from architeuthis.modeling import InterpolatedModel

# ds = ATMOS["ifs"].data

# interp = InterpolatedModel(
#     x_data_coordinates={
#         "valid_time": ds["valid_time"],
#         "latitude": ds["latitude"],
#         "longitude": ds["longitude"],
#     },
#     y_data_structured=ds["u10"].data,
#     # method="bspline",
#     method="linear",
#     # fill_value=0.
# )
# n = 100

# clat, clon = routeO(np.linspace(0, 1, n))
# ctim = np.linspace(timeframes[0][0], timeframes[0][1], n)

# from architeuthis.optimization import Opti

# opti = Opti()

# xq = {
#     # "valid_time": opti.parameter(ctim),
#     "valid_time": ctim,
#     "latitude": clat,
#     "longitude": clon,
# }

# interp(xq)

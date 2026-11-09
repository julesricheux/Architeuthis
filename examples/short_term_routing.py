# -*- coding: utf-8 -*-
"""
Short-term routing around Saint-Pierre with the high-resolution HRDPS wind.

A short leg on a small domain, with the latest HRDPS run (one step per hour, about 2.5 km). Needs a
polar file and CMEMS credentials for the currents (CMEMS_USER, CMEMS_PWD). HRDPS covers Canada and its
approaches: stay inside its area. Run from the repository root, cell by cell (#%%) or as a script.

Created on Tue Feb 24 14:04:33 2026

@author: jrich
"""


import pandas as pd
import architeuthis.numpy as np

from architeuthis.vessel import Vessel
from architeuthis.core import RoutingAnalysis, Voyage, DEFAULT_SOLVER_OPTIONS
from architeuthis.icebergs import berg_zone
from architeuthis.report import ReportCollection
from architeuthis.forecast import DeterministicHerbieForecast, HRDPSForecast, CopernicusForecast, Topography
from architeuthis.toolbox.geo_utils import poly_deviated_route
from architeuthis.toolbox.plot_utils import draw, get_steps


# minimum_longitude=-80.
# maximum_longitude=0.
# minimum_latitude=30.
# maximum_latitude=60.

# minimum_longitude=-80.
# maximum_longitude=-50.
# minimum_latitude=35.
# maximum_latitude=50.

minimum_longitude=-61.
maximum_longitude=-53.
minimum_latitude=44.
maximum_latitude=48.

# minimum_longitude=-58.118
# maximum_longitude=-54.646
# minimum_latitude=45.903
# maximum_latitude=47.761

steps = list(range(0, 145, 3)) + list(range(150, 361, 6))
    
#%% BUILD VESSEL INTERPOLATORS

vessel_files = [
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff70.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff90.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff100.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff45.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff60.nc",
    r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_28up_28down_7buff_5m_eff1.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff70.nc",
]

columns = ["bhp", "max_bhp", "leeway"]

vessels = []

# maxBHP = 4000.
maxBHP = 3000.

for i, vessel_data in enumerate(vessel_files):
    vessel = Vessel(f"vessel_{i}", filepath=vessel_data, sfc=224., hotel_load=200., max_power=3100.)
    # vessel = Vessel(f"vessel_{i}", filepath=vessel_data, sfc=196., hotel_load=172., max_power=4100.)
    vessel.load_data()
    
    vessel.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("max_bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    # vessel.add_interpolator("leeway", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("sails_contribution", "stw", "tws", "twa", "hs", "wa", method="linear")
    
    vessels.append(vessel)

#%% BUILD WIND INTERPOLATORS


# mirror_date = pd.Timestamp('2025-12-17 12:00')
# mirror_end = pd.Timestamp('2025-12-21 12:00')

ATMOS = {}

steps=list(range(0, 48+1, 1))

# HRDPS continental, regridded on a regular latitude and longitude grid by HRDPSForecast. Without
# date, the latest run. Warning: the wind direction is about 45 deg off around Saint-Pierre, because
# the components stay relative to the rotated grid of HRDPS. See HRDPSForecast.
atmos = HRDPSForecast(
    "wind_hrdps", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    resolution=0.0225, # ~2.5 km
    # resolution=0.25,
    # date=mirror_date
)
atmos.load_data()

atmos.add_interpolator("u10", "valid_time", "latitude", "longitude")
atmos.add_interpolator("v10", "valid_time", "latitude", "longitude")

recent = pd.to_datetime(atmos.f00)
# recent = pd.Timestamp("now").floor("1h") - pd.Timedelta("1h")

# The same box with GFS, which has no rotated grid to correct:
# atmos = DeterministicHerbieForecast(
#     "wind_hrdps", model="gfs", product="pgrb2b.0p25", regex=r"(?:U|V)GRD:AGL-10m", fxx=steps,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     # date=mirror_date
# )
# atmos.load_data()


#%% BUILD WAVE INTERPOLATORS

# IFS ocean data
wave = DeterministicHerbieForecast(
    "wave", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=list(range(0, 48+1, 3)),
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    # date=mirror_date
)
wave.load_data()

wave.add_interpolator("swh", "valid_time", "latitude", "longitude")
wave.add_interpolator("mwd", "valid_time", "latitude", "longitude")


#%% BUILD CURRENT INTERPOLATORS

# Mercator SMOC data
current = CopernicusForecast(
    "current", dataset="cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", variables=["uo", "vo"],
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
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

topo = Topography(
    "topo", depth_offset=0., z_margin=0.,
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

# departure = np.array([47.73378179825826, -4.581298828125]) # Montoir pilot
# departure = np.array([47.823964087925354, -4.772235284069338]) # pos 06/02/2026 10h00 UTC
# departure = np.array([53.418611, -22.285278]) # pos 09/02/2026 10h00 UTC
# departure = np.array([53.130556, -38.120833]) # pos 11/02/2026 12h15 UTC
# departure = np.array([50.453056, -42.795278]) # pos 12/02/2026 10h00 UTC
# departure = np.array([47.595000, -47.963333]) # pos 13/02/2026 10h50 UTC
# departure = np.array([44.117702, -60.907898]) # pos 16/02/2026 00h00 UTC
# arrival = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit

# departure = np.array([46.781, -56.091]) # SPM pilot
# departure = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# departure = np.array([37.38330548509701, -74.4866180419922]) # pos 20/02/2026 17h00 UTC
# departure = np.array([43.248056, -62.397778]) # pos 23/02/2026 09h20 UTC
# arrival = np.array([47.112116788143474, -2.4051169026612866]) # Montoir pilot
departure = np.array([45.751500, -59.138333])
# departure = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# arrival = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# departure = np.array([46.781, -56.091]) # SPM pilot
# wp = np.array([46.551, -53.321]) # cape race
wp = np.array([46.166667, -46.916667]) # iip 23/02/2026
wp = np.array([47.211515697578854, -56.282075043080724]) # North Miquelon
arrival = np.array([46.781, -56.091]) # SPM pilot

# lats = [departure[0], 47.673, 46.560, arrival[0]]
# lons = [departure[1], -4.896, -53.033, arrival[1]]
# divs = [0., -0.5, 0.]
lats = [departure[0], wp[0], arrival[0]]
lons = [departure[1], wp[1], arrival[1]]
divs = [-0.5, 0.]
routeN = poly_deviated_route(lats, lons, divs)

lats = [departure[0], wp[0], arrival[0]]
lons = [departure[1], wp[1], arrival[1]]
divs = [0., 0.]
routeO = poly_deviated_route(lats, lons, divs)

lats = [departure[0], wp[0], arrival[0]]
lons = [departure[1], wp[1], arrival[1]]
divs = [0.5, 0.]
routeS = poly_deviated_route(lats, lons, divs)

# s = np.linspace(0, 1, 100)
# latN, lonN = routeN(s)
# latS, lonS = routeS(s)
# latO, lonO = routeO(s)


# etd = pd.to_datetime("2026-02-05T20:00").timestamp() # LT 21h ATD
# etd = pd.to_datetime("2026-02-06T10:00").timestamp() # 06/02/2026 10h00 UTC
# etd = pd.to_datetime("2026-02-09T10:00").timestamp() # 09/02/2026 01h30 UTC
# etd = pd.to_datetime("2026-02-11T12:15").timestamp() # 11/02/2026 12h15 UTC
# etd = pd.to_datetime("2026-02-12T10:00").timestamp() # 12/02/2026 10h00 UTC
# etd = pd.to_datetime("2026-02-13T10:50").timestamp() # 13/02/2026 10h50 UTC
# etd = pd.to_datetime("2026-02-20T10:30").timestamp()
# etd = pd.to_datetime("2026-02-20T17h00").timestamp() 
# etd = pd.to_datetime("2026-02-24T20h00").timestamp()
etd = (recent + pd.Timedelta(hours=1)).timestamp()
# etd = pd.to_datetime("2026-02-26T06h00").timestamp()
# etd = pd.to_datetime("2026-02-16T00:00").timestamp() # 16/02/2026 00h00 UTC
# eta = pd.to_datetime("2026-02-25T11:00").timestamp()
# eta = pd.to_datetime("2026-02-18T22:00").timestamp() # LT 17h

solver_options = DEFAULT_SOLVER_OPTIONS

reports = ReportCollection()

from itertools import product

zero_fac = 0.

# models = ["ifs", "gfs"]
models = ["ifs",]
# facs = np.asarray([-1., 0., 1.]) + zero_fac
facs = [zero_fac]
# topos = [topo]
# topos = [topo0 ,topo]

# members = None
members = [1]
# members = list(range(1,51,1))

etas = [
    # pd.to_datetime("2026-03-07T06:00").timestamp(),
    # pd.to_datetime("2026-02-24T17:00").timestamp(),
    # pd.to_datetime("2026-02-25T20:00").timestamp(),
    (recent + pd.Timedelta(hours=25)).timestamp(),
]

# for m, fac in product(list(range(1,51,1)), facs):
# for m, fac in product(list(range(1,51,51)), facs):
for solve, vessel, model, fac, eta, m in (
        list(
            product([0], vessels, models, [zero_fac], etas, [1]) # NOT SOLVED ortho cst speed refs
        ) + list(
            product([1], vessels, models, facs, etas, members) # SOLVED
        )
    ):
    
    analysis = RoutingAnalysis(
        "analysis",
        vessel,
        Voyage(
            name="voyage",
            etd = etd,
            eta = eta,
            departure = departure,
            arrival = arrival,
            route_minus=routeS,
            route_ortho=routeO,
            route_plus=routeN,
        ),
        # ATMOS[model],
        atmos,
        # atmos_ens,
        wave,
        # wave_ens,
        current,
        topo,
        # atmosphere_member=m,
        # wave_member=m,
    )
    
    report = analysis.run(
        max_iter=2000,
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
                "acceptable_tol": 1e9,
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
    
    print(f"{pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')} - {pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}")
    print(f"fuel = {report['fuel']:.1f} t i.e. {report['fuel']/report['transit_time']*24.:.1f} t/day")
    
    # if report["status"] == 1:
    reports.append(report)

for report in reports:
    # print(f"{pd.to_datetime(report['etd'], unit='s').strftime('%d/%m %Hh%M UTC')} - {pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}")
    print(f"{report['init_fac']}, {report['model']}")
    print(f"{report['dist']:.1f}, {report['dist_rel'] * 100 - 100:.1f}")
    print(f"{np.mean(report['sog']):.1f} {np.mean(report['sog']) / report['transit_sog'] * 100 - 100:.1f} ")
    print(f"fuel = {report['fuel']:.1f} t i.e. {report['fuel']/report['transit_time']*24.:.1f} t/day")
    print()
    
draw(reports, barbs=1)

#%% FIGURE AND TABLE SETTINGS OF EARLIER STUDIES

# What the former figures had as comments, in their order: other variables, units, limits, and
# conditions that selected the reports. Pass them to reports.select and to the helpers of plot_utils,
# for example plot_variable(reports.select(init_fac=0.), "swh", unit="m", ylim=(0., 10.)).

# "wind_hrdps", model="hrdps", product="continental", regex=r"(?:U|V)GRD:AGL-10m", fxx=steps,

# self._locate_data()
# self._download_data()
# self._read_data()

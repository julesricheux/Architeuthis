# -*- coding: utf-8 -*-
"""
A first routing, in the fewest lines: one vessel, one optimization, on a past forecast.

Needs a polar file and CMEMS credentials for the currents (CMEMS_USER, CMEMS_PWD). Run from the
repository root, cell by cell (#%%) or as a script.

Created on Mon Feb  2 12:26:52 2026

@author: jrich
"""

import pandas as pd
import architeuthis.numpy as np

from architeuthis.vessel import Vessel
from architeuthis.forecast import (
    DeterministicHerbieForecast,
    CopernicusForecast,
    Topography,
)
from architeuthis.core import (
    RoutingAnalysis,
    Voyage,
    DEFAULT_SOLVER_OPTIONS,
)
from architeuthis.icebergs import berg_zone
from architeuthis.toolbox.plot_utils import draw, get_steps

# minimum_longitude=-80.
# maximum_longitude=0.
# minimum_latitude=30.
# maximum_latitude=60.

minimum_longitude=-80.
maximum_longitude=-50.
minimum_latitude=35.
maximum_latitude=50.

steps = list(range(0, 145, 3)) #+ list(range(150, 361, 6))

departure = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# arrival = np.array([47.112116788143474, -2.4051169026612866]) # Montoir pilot
# arrival = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# departure = np.array([47.112116788143474, -2.4051169026612866]) # Montoir pilot
# departure = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# arrival = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# departure = np.array([46.781, -56.091]) # SPM pilot
arrival = np.array([46.781, -56.091]) # SPM pilot

etd = pd.to_datetime("2025-12-17T11:30").timestamp() # LT 21h
eta = pd.to_datetime("2025-12-21T11:30").timestamp() # LT 17h
# eta = pd.to_datetime("2026-02-05T23:00").timestamp()
# eta = pd.to_datetime("2026-01-22T12:00").timestamp()

solver_options = DEFAULT_SOLVER_OPTIONS
    
#%% BUILD VESSEL INTERPOLATORS

# vessel_data = r"C:\\Users\\jules\\output_sails.nc"
# vessel_data = "C:/Users/jules/data/polar/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff100.nc"
# vessel_data = r"C:/Users/jules/data/polar/neoliner_origin.nc"
# vessel_data = r"C:/Users/jules/data/polar/polar_sails_2-2-0extrap.csv"
# vessel_data = 'C:/Users/jules/data/polar/polar_sails_2-2-0extrap.nc
# vessel_data = 'C:/Users/jrich/data/polar/polar_sails_2-2-0extrap.nc'
vessel_data = r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff90.nc"
# vessel_data = 'C:/Users/jules/data/polar/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff92.nc'
# vessel_data = "C:\\Users\\jrich\\output_sails.nc"

columns = ["bhp", "max_bhp", "leeway"]

vessel = Vessel("base_vessel", filepath=vessel_data, sfc=196., hotel_load=172., max_power=3e3)
vessel.load_data()

vessel.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
vessel.add_interpolator("max_bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
# vessel.add_interpolator("leeway", "stw", "tws", "twa", "hs", "wa", method="linear")
vessel.add_interpolator("sails_contribution", "stw", "tws", "twa", "hs", "wa", method="linear")
    

#%% BUILD WIND INTERPOLATORS

mirror_date = pd.Timestamp('2025-12-17 12:00')
mirror_end = pd.Timestamp('2025-12-21 12:00')

# IFS atmospheric data
atmos = DeterministicHerbieForecast(
    "wind", model="ifs", product="oper", regex=r":10[u|v]:|:msl:", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=mirror_date
)
atmos.load_data()

atmos.add_interpolator("u10", "valid_time", "latitude", "longitude")
atmos.add_interpolator("v10", "valid_time", "latitude", "longitude")

#%% BUILD WAVE INTERPOLATORS

# IFS ocean data
wave = DeterministicHerbieForecast(
    "wave", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=mirror_date
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
    date=mirror_date, end=mirror_end
)
current.load_data()

current.add_interpolator(
    "uo", "valid_time", "latitude", "longitude",
    latitude_slice=slice(None, None, 1),
    longitude_slice=slice(None, None, 1),
    time_slice=slice(None, None, 3),
)
current.add_interpolator(
    "vo", "valid_time", "latitude", "longitude",
    latitude_slice=slice(None, None, 1),
    longitude_slice=slice(None, None, 1),
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

for m in range(1,51,50):
    analysis = RoutingAnalysis(
        "analysis",
        vessel,
        Voyage(
            name="voyage",
            etd = etd,
            eta = eta,
            departure = departure,
            arrival = arrival,
        ),
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
        max_iter=1000,
        # init_fac=-3.,
        # init_fac=-0.5,
        init_fac=0,
        # init_fac=0.5,
        # init_fac=1.,
        # init_fac=1.2,
        # init_fac=1.5,
        # init_fac=1.75,
        # init_fac=2.,
        # init_fac=3.,
        # vary_fac=True,
        solver_options = {
            "ipopt":{
                "acceptable_tol": 1e9,
                # 'linear_solver': 'spral',
                'linear_solver': 'mumps',
                "hessian_approximation": "limited-memory",
            },
        },
        # solve=0,
    ) # TODO report should probably be a class of its own
        
    draw([report])
    
    ctime = pd.to_datetime(report["ctim"], unit="s")
    
    # plt.clf()
    # # plt.scatter(ctime, unit="s"), report["avg_bhp"])
    # plt.plot(*get_steps(report, "avg_bhp"))
    # # plt.plot(ctime, report["sails_contribution"])
    # # plt.plot(ctime, report["sails_contribution"])
    # plt.xticks(rotation=45)
    # plt.tight_layout()
    # plt.show()
    
    print(f"{pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}, fuel = {report['fuel']:.1f} t i.e. {report['fuel']/report['transit_time']*24.:.1f} t/day")

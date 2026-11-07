# -*- coding: utf-8 -*-
"""
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
    exclusion_zones,
)

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

topo = Topography(
    "topo", depth_offset=0., z_margin=0.,
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

def draw(reports, barbs=1):
        
    from architeuthis.toolbox.plot_utils import plot_route

    # cvtim = pd.to_datetime(self.report["ctim"], unit="s")
    # vtim = pd.to_datetime(self.report["tim"], unit="s")
    
    lons = [r["lon"] for r in reports]
    lats = [r["lat"] for r in reports]
    clons = [r["clon"] for r in reports]
    clats = [r["clat"] for r in reports]
    tws = [r["tws"] for r in reports]
    twd = [r["twd"] for r in reports]
    
    plot_route(lons, lats, clons, clats, tws, twd, barbs)

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
        
    # plt.clf()
    # # plt.scatter(ctime, unit="s"), report["avg_bhp"])
    # plt.plot(*get_steps(report, "avg_bhp"))
    # # plt.plot(ctime, report["sails_contribution"])
    # # plt.plot(ctime, report["sails_contribution"])
    # plt.xticks(rotation=45)
    # plt.tight_layout()
    # plt.show()
    
    print(f"{pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}, fuel = {report['fuel']:.1f} t i.e. {report['fuel']/report['transit_time']*24.:.1f} t/day")
    
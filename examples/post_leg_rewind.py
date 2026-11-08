# -*- coding: utf-8 -*-
"""
Created on Mon Feb  2 12:26:52 2026

@author: jrich
"""

import pandas as pd
import architeuthis.numpy as np

from architeuthis import presets
from architeuthis.common import Domain
from architeuthis.route import Route
from architeuthis.vessel import Vessel
from architeuthis.toolbox.plot_utils import draw, get_steps
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

domain = Domain(
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
)

steps = list(range(0, 145, 3)) #+ list(range(150, 361, 6))

departure = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# arrival = np.array([47.112116788143474, -2.4051169026612866]) # Montoir pilot
# arrival = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# departure = np.array([47.112116788143474, -2.4051169026612866]) # Montoir pilot
# departure = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# arrival = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# departure = np.array([46.781, -56.091]) # SPM pilot
arrival = np.array([46.781, -56.091]) # SPM pilot

route = Route("post_leg", [departure, arrival])

etd = pd.to_datetime("2025-12-17T11:30").timestamp() # LT 21h
eta = pd.to_datetime("2025-12-21T11:30").timestamp() # LT 17h
# eta = pd.to_datetime("2026-02-05T23:00").timestamp()
# eta = pd.to_datetime("2026-01-22T12:00").timestamp()

# Routing after the start of the leg: the voyage restarts from this position, reached at
# this time, and keeps its ETA (Voyage.from_position). None routes the whole leg.
restart = None
# restart = ([43.612500, -60.603333], "2025-12-18T12:00")

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

vessel.add_interpolators() # bhp, max_bhp, sails_contribution
# vessel.add_interpolator("leeway", "stw", "tws", "twa", "hs", "wa", method="linear")
    

#%% BUILD WIND INTERPOLATORS

mirror_date = pd.Timestamp('2025-12-17 12:00')
mirror_end = pd.Timestamp('2025-12-21 12:00')

# IFS atmospheric data
atmos = presets.atmosphere("ifs", domain, date=mirror_date, fxx=steps, regex=r":10[u|v]:|:msl:", name="wind")

#%% BUILD WAVE INTERPOLATORS

# IFS ocean data
wave = presets.wave("ifs", domain, date=mirror_date, fxx=steps, name="wave")


#%% BUILD CURRENT INTERPOLATORS

# Mercator SMOC data
current = presets.current_mercator(domain, date=mirror_date, end=mirror_end, stride=1)


#%% BUILD TOPOGRAPHY

topo = presets.topography(domain, exclusion_zones=exclusion_zones)

#%%

voyage = Voyage(name="voyage", etd=etd, eta=eta, route=route)
if restart is not None:
    voyage = voyage.from_position(*restart)

for m in range(1,51,50):
    analysis = RoutingAnalysis(
        "analysis",
        vessel,
        voyage,
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
    )
        
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
    
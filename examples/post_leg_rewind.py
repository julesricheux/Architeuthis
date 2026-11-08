# -*- coding: utf-8 -*-
"""
Replay a past leg: the optimal route with the forecasts available when the vessel sailed.

The forecasts are those of a past date, and the schedule is the one of the leg. This is the
shortest routing script: one vessel, one model, one route, and a map of the result.

Needs a polar file in ~/data/polars/ and CMEMS credentials for the currents (CMEMS_USER,
CMEMS_PWD). The past forecast must still be available from the providers. Run from the
repository root, cell by cell (#%%) or as a script.
"""

import os

import pandas as pd

from architeuthis import presets
from architeuthis.common import Domain
from architeuthis.core import RoutingAnalysis
from architeuthis.route import Route, Waypoint
from architeuthis.toolbox.plot_utils import draw
from architeuthis.voyage import Voyage

#%% SETTINGS

POLAR_FILE = os.path.expanduser("~/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff90.nc")

DOMAIN = Domain(min_lon=-80., max_lon=-50., min_lat=35., max_lat=50.)
STEPS = list(range(0, 145, 3)) # lead times, in hours

FORECAST_DATE = pd.Timestamp("2025-12-17 12:00") # base time of the forecasts
CURRENT_END = pd.Timestamp("2025-12-21 12:00") # last time of the currents

DEPARTURE = Waypoint(36.995605446063365, -75.94119037659861, "Chesapeake exit")
ARRIVAL = Waypoint(46.781, -56.091, "SPM pilot")
ETD = "2025-12-17T11:30" # UTC
ETA = "2025-12-21T11:30" # UTC

# To replay the leg from a position at sea: position reached, and when. The ETA is kept.
RESTART = None
# RESTART = ([43.612500, -60.603333], "2025-12-18T12:00")

#%% VESSEL, FORECASTS AND TOPOGRAPHY

vessel = presets.vessel(POLAR_FILE, sfc=196., hotel_load=172., max_power=3e3)

atmosphere = presets.atmosphere("ifs", DOMAIN, date=FORECAST_DATE, fxx=STEPS, regex=r":10[u|v]:|:msl:", name="wind")
wave = presets.wave("ifs", DOMAIN, date=FORECAST_DATE, fxx=STEPS, name="wave")
current = presets.current_mercator(DOMAIN, date=FORECAST_DATE, end=CURRENT_END, stride=1)
topography = presets.topography(DOMAIN)

#%% ROUTING

voyage = Voyage("voyage", etd=ETD, eta=ETA, route=Route("post_leg", [DEPARTURE, ARRIVAL]))
if RESTART is not None:
    voyage = voyage.from_position(*RESTART)

analysis = RoutingAnalysis("analysis", vessel, voyage, atmosphere, wave, current, topography)

report = analysis.run(
    max_iter=1000,
    solver_options={
        "ipopt": {
            "acceptable_tol": 1e9,
            "linear_solver": "mumps",
            "hessian_approximation": "limited-memory",
        },
    },
)

#%% RESULT

print(f"{report.eta_time:%d/%m %Hh%M UTC}, fuel = {report['fuel']:.1f} t i.e. {report['fuel'] / report['transit_time'] * 24.:.1f} t/day")

draw([report])

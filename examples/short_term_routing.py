# -*- coding: utf-8 -*-
"""
Short-term routing around Saint-Pierre with the high-resolution HRDPS wind.

A short leg on a small domain, with the latest HRDPS run (one step per hour, about 2.5 km):
`presets.hrdps_atmosphere` regrids it on a regular grid. Compared with the other examples, only
the wind source and the scale change.

Needs a polar file in ~/data/polars/ and CMEMS credentials for the currents (CMEMS_USER,
CMEMS_PWD). HRDPS covers Canada and its approaches: stay inside its area. The forecasts are the
latest ones, so set ETD and ETA within the next 48 h. Run from the repository root, cell by cell
(#%%) or as a script.
"""

import os

from architeuthis import presets
from architeuthis.common import Domain
from architeuthis.core import RoutingAnalysis
from architeuthis.report import ReportCollection
from architeuthis.route import Route, RouteSet, Waypoint
from architeuthis.toolbox.plot_utils import draw
from architeuthis.voyage import Voyage

#%% SETTINGS

POLAR_FILE = os.path.expanduser("~/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff60.nc")

DOMAIN = Domain(min_lon=-61., max_lon=-53., min_lat=44., max_lat=48.)
STEPS = list(range(0, 49)) # lead times, in hours

DEPARTURE = Waypoint(45.751500, -59.138333, "Departure")
NORTH_MIQUELON = Waypoint(47.211515697578854, -56.282075043080724, "North Miquelon")
ARRIVAL = Waypoint(46.781, -56.091, "SPM pilot")

ETD = "2026-02-24T20:00" # UTC
ETA = "2026-02-25T20:00" # UTC

#%% VESSEL, FORECASTS AND TOPOGRAPHY

vessel = presets.vessel(POLAR_FILE, sfc=224., hotel_load=200., max_power=3100.)

# Warning: the wind direction is about 45 deg off here, because the components stay relative to
# the rotated grid of HRDPS. See HRDPSForecast.
atmosphere = presets.hrdps_atmosphere(DOMAIN, fxx=STEPS)
wave = presets.wave("ifs", DOMAIN, fxx=STEPS)
current = presets.current_mercator(DOMAIN)
topography = presets.topography(DOMAIN)

#%% ROUTES

route_set = RouteSet(
    "short_term",
    ortho=Route("short_term_ortho", [DEPARTURE, NORTH_MIQUELON, ARRIVAL]),
    minus=Route("short_term_south", [DEPARTURE, NORTH_MIQUELON, ARRIVAL], divergences=[0.5, 0.]),
    plus=Route("short_term_north", [DEPARTURE, NORTH_MIQUELON, ARRIVAL], divergences=[-0.5, 0.]),
)
voyage = Voyage.from_routes(route_set, etd=ETD, eta=ETA)

#%% ROUTING

reports = ReportCollection()

# The reference route at constant speed, then the optimization.
for solve in (False, True):
    analysis = RoutingAnalysis("analysis", vessel, voyage, atmosphere, wave, current, topography)
    reports.append(
        analysis.run(
            max_iter=2000,
            vary_fac=True, # the optimizer may also move the route towards the south or north route
            solve=solve,
            solver_options={
                "ipopt": {
                    "acceptable_tol": 1e9,
                    "linear_solver": "mumps",
                    "hessian_approximation": "limited-memory",
                },
            },
            tags={"member": 1},
        )
    )

#%% RESULTS

print(reports.summary().to_string())

draw(reports, barbs=True)

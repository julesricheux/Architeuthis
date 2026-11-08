# -*- coding: utf-8 -*-
"""
Ensemble routing: one optimization per member of the IFS ensemble.

It gives the spread of the fuel and of the conditions met, how likely the ETA is to be possible,
and how a plan optimized for one member fares in the others. It also shows a fuel consumption and
a hotel load that depend on the power, given as functions.

Read simple_routing.py first: this example goes faster over the same steps.

Needs a polar file in ~/data/polars/ and CMEMS credentials for the currents (CMEMS_USER,
CMEMS_PWD). All the members take time: reduce MEMBERS for a first try. Run from the repository
root, cell by cell (#%%) or as a script.
"""

import os

from itertools import product

import pandas as pd

from architeuthis import presets
from architeuthis.common import Domain
from architeuthis.core import RoutingAnalysis
from architeuthis.report import ReportCollection
from architeuthis.route import Route, RouteLibrary, RouteSet, RouteSetLibrary, Waypoint
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
from architeuthis.voyage import PassagePlanLibrary, Voyage

#%% SETTINGS

POLAR_FILE = os.path.expanduser("~/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff100.nc")
MAX_POWER = 4100. # kW


def sfc_fit(power):
    """Specific fuel consumption, in g/kWh, against the power, in kW."""
    return -6.660802866517442e-09 * power**3 + 5.216985806784128e-05 * power**2 - 0.13133435575556507 * power + 325.7684374001559


def hotel_load_fit(power):
    """Hotel load, in kW, against the power, in kW."""
    return 1.0915372379294297e-05 * power**2 - 0.011382017491188723 * power + 177.84810351574922


DOMAIN = Domain(min_lon=-80., max_lon=0., min_lat=30., max_lat=60.)
FORECAST_DATE = pd.Timestamp("now").floor("1d") # base time of the forecasts: today, 00 UTC
STEPS = list(range(0, 145, 3)) + list(range(150, 361, 6)) # lead times, in hours
WIND_FACTOR = 1.10 # speed correction of global models at 10 m
MEMBERS = list(range(1, 51))

DEPARTURE = Waypoint(47.01483765543116, -2.63720447676916, "Montoir pilot")
IIP_EAST = Waypoint(44.66666, -43.75000, "IIP limit, east")
IIP_WEST = Waypoint(44.66666, -50.33333, "IIP limit, west")
ARRIVAL = Waypoint(46.781, -56.091, "SPM pilot")

ETD = "2026-05-29T00:01" # UTC
ETA = "2026-06-10T04:00" # UTC

# To route the rest of a leg already started: position reached, and when. The ETA is kept.
RESTART = None
# RESTART = ([43.612500, -11.603333], "2026-06-01T06:30")

SOLVER_OPTIONS = {
    "ipopt": {
        "acceptable_tol": 1e9,
        "linear_solver": "mumps",
        "hessian_approximation": "limited-memory",
    },
}

#%% VESSEL, FORECASTS AND TOPOGRAPHY

vessel = presets.vessel(POLAR_FILE, sfc=sfc_fit, hotel_load=hotel_load_fit, max_power=MAX_POWER)

atmos_ens = presets.ensemble_atmosphere("ifs", DOMAIN, date=FORECAST_DATE, fxx=STEPS, wind_factor=WIND_FACTOR)
wave_ens = presets.ensemble_wave("ifs", DOMAIN, date=FORECAST_DATE, fxx=STEPS)
current = presets.current_mercator(DOMAIN, date=FORECAST_DATE)
topography = presets.topography(DOMAIN)

#%% ROUTES

route_set = RouteSet(
    "ensemble",
    ortho=Route("ensemble_ortho", [DEPARTURE, IIP_EAST, IIP_WEST, ARRIVAL]),
    minus=Route("ensemble_south", [DEPARTURE, IIP_EAST, ARRIVAL], divergences=[0., -0.4]),
    plus=Route("ensemble_north", [DEPARTURE, IIP_EAST, IIP_WEST, ARRIVAL], divergences=[0., 0., 0.4]),
)

RouteSetLibrary().save(route_set, overwrite=True)
for route in route_set.routes.values():
    RouteLibrary().save(route, overwrite=True)

voyage = Voyage.from_routes(route_set, etd=ETD, eta=ETA)
if RESTART is not None:
    voyage = voyage.from_position(*RESTART)

#%% ROUTING

reports = ReportCollection()
plans = []

# The reference route at constant speed in each member, then an optimization in each member.
for solve, member in product([False, True], MEMBERS):
    analysis = RoutingAnalysis(
        "analysis",
        vessel,
        voyage,
        atmos_ens,
        wave_ens,
        current,
        topography,
        atmosphere_member=member,
        wave_member=member,
    )
    report = analysis.run(
        max_iter=2000,
        vary_fac=True, # the optimizer may also move the route towards the south or north route
        solve=solve,
        solver_options=SOLVER_OPTIONS,
    )
    reports.append(report)

    plan = analysis.passage_plan
    plan.name = f"{plan.name}_ifs{vessel.label}_m{member}_{'solved' if solve else 'ref'}"
    plans.append(plan)

#%% RESULTS

print(reports.summary().to_string())

converged = reports.select(status=1)

draw(converged, barbs=False)

converged.save() # displayed by ui.py

for plan in plans:
    PassagePlanLibrary().save(plan, overwrite=True)

#%% OPEN-LOOP EVALUATION

# Each optimized plan in every member, positions and times unchanged: how the plan optimized
# for one member fares in the others. len(plans) x len(MEMBERS) evaluations, without IPOPT.
solved_plans = [plan for plan in plans if plan.metadata["tags"]["solve"]]

evaluations = ReportCollection(
    RoutingAnalysis(
        "evaluation",
        vessel,
        None, # the plan gives the positions and times
        atmos_ens,
        wave_ens,
        current,
        topography,
        atmosphere_member=member,
        wave_member=member,
        verbose=False,
    ).evaluate(plan, tags={"plan_member": plan.metadata["tags"]["member"]})
    for plan, member in product(solved_plans, MEMBERS)
)
print(evaluations.frame().pivot_table(index="plan_member", columns="member", values="fuel"))

#%% FIGURES

# Any quantity per segment can be plotted: sog, stw, tws, swh, avg_bhp, max_bhp, sails_contribution...
SIDES = {-1.: "South route", 0.: "Ortho cst speed", 1.: "North route"}

solved = reports.select(solve=1)
prefix = "IFS ensemble "

plot_fuel_vs_etd(reports)
plot_variable(reports, "sog", unit="kts", labels=SIDES, figsize=(8, 4), dpi=100)
plot_variable(reports, "avg_bhp", unit="kW", ylim=(0., MAX_POWER), figsize=(10, 3.5), dpi=100)
plot_fuel_distribution(
    {"Optimised routes": solved, "Ortho cst. speed": reports.select(solve=0)},
    horizontal=True,
)
plot_quantiles(reports, "avg_bhp", unit="kW", prefix=prefix, figsize=(8, 4))
plot_quantiles(solved, "swh", unit="m", title="SWH distribution along optimised routes for all scenarios", figsize=(9, 4))
plot_quantiles(
    solved,
    "max_bhp",
    unit="kW",
    prefix=prefix,
    title=f"ETD {pd.to_datetime(voyage.etd, unit='s')} UTC - ETA {pd.to_datetime(voyage.eta, unit='s')} UTC",
    daily_ticks=True,
)
plot_fuel_quantiles(reports)
plot_fuel_quantiles(reports, daily=True)
plot_convergence(reports)

# The weather of all the members along the route optimized for one of them.
plot_ensemble_along_route(solved[0], atmos_ens, wave_ens, ylim={"swh": (0., 8.), "tws": (0., 50.)})

#%% BACK LATER: RELOAD THE REPORTS

reports = ReportCollection.latest()

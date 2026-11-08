# -*- coding: utf-8 -*-
"""
Long-term routing: start the optimization from several routes, and read the risk from an ensemble.

The optimum of a crossing depends on where the optimization starts. This example starts it from
several points between a port and a starboard route, with both weather models and two sail
efficiencies, and lets the optimizer also vary this deviation (`vary_fac`). It then shows the
weather spread of an ensemble along the selected routes, even though they were optimized with
deterministic forecasts.

Read simple_routing.py first: this example goes faster over the same steps.

Needs the polar files in ~/data/polars/ and CMEMS credentials for the currents (CMEMS_USER,
CMEMS_PWD). Run from the repository root, cell by cell (#%%) or as a script.
"""

import os

from itertools import product

import pandas as pd

from architeuthis import presets
from architeuthis.common import Domain, tall, wide
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

POLAR_FILE = os.path.expanduser("~/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff{}.nc")
EFFICIENCIES = [45, 60] # sails efficiencies, in %
SFC = 220. # g/kWh
HOTEL_LOAD = 194. # kW
MAX_POWER = 4100. # kW

DOMAIN = Domain(min_lon=-60., max_lon=0., min_lat=30., max_lat=60.)
FORECAST_DATE = pd.Timestamp("now").floor("1d") # base time of the forecasts: today, 00 UTC
STEPS = list(range(0, 145, 3)) + list(range(150, 361, 6)) # lead times, in hours
MODELS = ["ifs", "gfs"]
WIND_FACTOR = 1.0 # speed correction of global models at 10 m

DEPARTURE = Waypoint(46.781, -56.091, "SPM pilot")
CAPE_RACE = Waypoint(46.551, -53.321, "Cape Race")
PENMARCH = Waypoint(47.72529611513597, -4.379839003826363, "Penmarc'h")
ARRIVAL = Waypoint(47.112116788143474, -2.4051169026612866, "Montoir pilot")

TIMEFRAMES = [("2026-09-04T15:00", "2026-09-14T02:00")] # (ETD, ETA), in UTC

# To route the rest of a leg already started: position reached, and when. The ETA is kept.
RESTART = None
# RESTART = ([43.612500, -11.603333], "2026-06-01T06:30")

INIT_FACS = [-0.9, -0.2, 0.2, 0.9] # where each optimization starts: -1 port route, +1 starboard route

SOLVER_OPTIONS = {
    "ipopt": {
        "acceptable_tol": 1e2,
        "linear_solver": "mumps",
        "hessian_approximation": "limited-memory",
    },
}


def constraints(ctx):
    """What the optimized routes must respect. `ctx` holds every quantity of the passage."""
    return [
        ctx["max_bhp"] < ctx["vessel"].max_power,
        (wide(ctx["z"]) @ tall(ctx["z"])) == 0.,
    ]


#%% VESSELS, FORECASTS AND TOPOGRAPHY

vessels = [
    presets.vessel(POLAR_FILE.format(efficiency), sfc=SFC, hotel_load=HOTEL_LOAD, max_power=MAX_POWER)
    for efficiency in EFFICIENCIES
]

# `regex` chooses the fields to download: wind only here, so gusts use the standard ratio.
REGEX = {"ifs": r":10[u|v]:|:msl:", "gfs": r"(?:U|V)GRD:10 m"}
ATMOS = {
    model: presets.atmosphere(model, DOMAIN, date=FORECAST_DATE, fxx=STEPS, wind_factor=WIND_FACTOR, regex=REGEX[model])
    for model in MODELS
}
WAVE = {model: presets.wave(model, DOMAIN, date=FORECAST_DATE, fxx=STEPS) for model in MODELS}
current = presets.current_mercator(DOMAIN, date=FORECAST_DATE)
topography = presets.topography(DOMAIN, depth_offset=-30.) # water shallower than 30 m counts as land

# Only used to show the weather spread along the routes.
atmos_ens = presets.ensemble_atmosphere("ifs", DOMAIN, date=FORECAST_DATE, fxx=STEPS, wind_factor=WIND_FACTOR)
wave_ens = presets.ensemble_wave("ifs", DOMAIN, date=FORECAST_DATE, fxx=STEPS)

#%% ROUTES

route_set = RouteSet(
    "long_term",
    ortho=Route("long_term_ortho", [DEPARTURE, CAPE_RACE, ARRIVAL]),
    minus=Route("long_term_port", [DEPARTURE, CAPE_RACE, PENMARCH, ARRIVAL], divergences=[0., 0.4, 0.]),
    plus=Route("long_term_starboard", [DEPARTURE, ARRIVAL], divergences=[-0.5]),
)

RouteSetLibrary().save(route_set, overwrite=True)
for route in route_set.routes.values():
    RouteLibrary().save(route, overwrite=True)

#%% ROUTING

# References on the ortho route at constant speed, then each optimization.
runs = [
    *((False, model, vessel, 0., 1) for model, vessel in product(MODELS, vessels)),
    *((True, model, vessel, init_fac, 0) for model, vessel, init_fac in product(MODELS, vessels, INIT_FACS)),
]

reports = ReportCollection()
plans = []

for (etd, eta), (solve, model, vessel, init_fac, member) in product(TIMEFRAMES, runs):
    voyage = Voyage.from_routes(route_set, etd=etd, eta=eta)
    if RESTART is not None:
        voyage = voyage.from_position(*RESTART)

    analysis = RoutingAnalysis(
        "analysis",
        vessel,
        voyage,
        ATMOS[model],
        WAVE[model],
        current,
        topography,
        constraints=constraints,
    )
    report = analysis.run(
        max_iter=1000,
        init_fac=init_fac,
        vary_fac=True, # the optimizer may also move the route towards the port or starboard route
        solve=solve,
        solver_options=SOLVER_OPTIONS,
        tags={"member": member},
    )
    reports.append(report)

    plan = analysis.passage_plan
    plan.name = f"{plan.name}_{model}{vessel.label}_fac{init_fac:+.2f}_m{member}_{'solved' if solve else 'ref'}"
    plans.append(plan)

#%% RESULTS

print(reports.summary().to_string()) # its index gives the number of each report, used below

draw(reports, barbs=False, sails_threshold=10.)

reports.save() # displayed by ui.py

for plan in plans:
    PassagePlanLibrary().save(plan, overwrite=True)

#%% OPEN-LOOP EVALUATION

solved_plans = [plan for plan in plans if plan.metadata["tags"]["solve"]]

evaluations = ReportCollection(
    RoutingAnalysis(
        "evaluation",
        vessel,
        None, # the plan gives the positions and times
        ATMOS[model],
        WAVE[model],
        current,
        topography,
        verbose=False,
    ).evaluate(plan)
    for plan, model, vessel in product(solved_plans, MODELS, vessels)
)
print(evaluations.frame().pivot_table(index="plan", columns=["model", "vessel"], values="fuel"))

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

compared = ReportCollection(reports[index] for index in (4, 9))

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

#%% TABLE TO PASTE IN A DOCUMENT

table = reports.select(solve=1)[:2].table()

for column in table.columns:
    if column.startswith("sog"):
        table[column] = table[column].map(lambda value: f"{value:.1f}" if pd.notna(value) else "")
    elif column.startswith(("cog", "avg_bhp", "twa")):
        table[column] = table[column].map(lambda value: f"{value:.0f}" if pd.notna(value) else "")

table.to_clipboard(index=False, excel=True)
print("Table copied to clipboard. Paste directly into Word.")

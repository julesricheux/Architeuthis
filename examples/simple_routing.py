# -*- coding: utf-8 -*-
"""
Optimize a voyage with two weather models and several sail efficiencies, then look at the results.

This is the most complete example: every step of a routing study, in order.

1. Vessels, forecasts and topography, built with `presets`.
2. Reference routes, kept together in a `RouteSet` and stored in a library.
3. Routing runs, collected in a `ReportCollection`, with one `PassagePlan` per run.
4. Results saved where `ui.py` displays them.
5. Open-loop evaluation of the plans with the other models and vessels.
6. Figures, tables, GPX tracks and the A4 page of each route.

Needs the polar files in ~/data/polars/ and CMEMS credentials for the currents (CMEMS_USER,
CMEMS_PWD). IFS and GFS need none. Run from the repository root, cell by cell (#%%) or as a
script. Edit the settings to study another voyage: reference_data.py lists usual positions,
polars and alternative settings.
"""

import os

from itertools import product

import pandas as pd

from architeuthis import presets
from architeuthis.common import Domain
from architeuthis.core import RoutingAnalysis
from architeuthis.exclusion import ExclusionZoneLibrary, default_exclusion_zones, merge_exclusion_zones
from architeuthis.report import ReportCollection
from architeuthis.route import Route, RouteLibrary, RouteSet, RouteSetLibrary, Waypoint
from architeuthis.toolbox.plot_utils import (
    draw,
    plot_convergence,
    plot_fuel_distribution,
    plot_fuel_quantiles,
    plot_fuel_vs_etd,
    plot_power_and_weather,
    plot_quantiles,
    plot_report,
    plot_route_set,
    plot_variable,
)
from architeuthis.voyage import PassagePlanLibrary, Voyage

#%% SETTINGS

POLAR_FILE = os.path.expanduser("~/data/polars/neoliner_origin_v2-2-0_mc0_sc0_28up_28down_7buff_5m_eff{}.nc")
REFERENCE_EFFICIENCY = 1 # sails efficiency of the reference route, not optimized, in %
EFFICIENCIES = [45, 60] # sails efficiencies of the optimized routes, in %
SFC = 220. # g/kWh
HOTEL_LOAD = 194. # kW
MAX_POWER = 4100. # kW

DOMAIN = Domain(min_lon=-70., max_lon=5., min_lat=30., max_lat=60.)
FORECAST_DATE = pd.Timestamp("now").floor("1d") # base time of the forecasts: today, 00 UTC
STEPS = list(range(0, 145, 3)) + list(range(150, 361, 6)) # lead times, in hours
MODELS = ["ifs", "gfs"]
WIND_FACTOR = 1.20 # speed correction of global models at 10 m

DEPARTURE = Waypoint(50.489, -0.037, "Departure")
SCILLY = Waypoint(49.665, -6.241, "Scilly")
CAPE_RACE = Waypoint(46.551, -53.321, "Cape Race")
ARRIVAL = Waypoint(46.781, -56.091, "SPM pilot")

TIMEFRAMES = [("2026-11-06T08:40", "2026-11-15T04:00")] # (ETD, ETA), in UTC: add some to compare departures

# To route the rest of a leg already started: position reached, and when. The ETA is kept.
RESTART = None
# RESTART = ([43.612500, -11.603333], "2026-06-01T06:30")

INIT_FACS = [0.] # where the optimization starts: -1 port route, 0 ortho route, +1 starboard route

SOLVER_OPTIONS = {
    "ipopt": {
        "acceptable_tol": 1e2,
        "hessian_approximation": "limited-memory",
    },
}


def constraints(ctx):
    """What the optimized routes must respect. `ctx` holds every quantity of the passage."""
    limits = [
        ctx["max_bhp"] < ctx["vessel"].max_power,
        ctx["z"] < 0., # stay at sea and out of the exclusion zones
    ]
    if float(ctx["vessel"].label.removeprefix("eff")) > 5.:
        limits.append(ctx["aws_gust"] < 35.) # with sails up, in knots
    return limits


#%% VESSELS

# The label of a vessel, such as eff45, comes from the polar file name. Reports are tagged with it.
vessels = [
    presets.vessel(POLAR_FILE.format(efficiency), sfc=SFC, hotel_load=HOTEL_LOAD, max_power=MAX_POWER)
    for efficiency in [REFERENCE_EFFICIENCY, *EFFICIENCIES]
]

#%% FORECASTS AND TOPOGRAPHY

ATMOS = {
    model: presets.atmosphere(model, DOMAIN, date=FORECAST_DATE, fxx=STEPS, wind_factor=WIND_FACTOR)
    for model in MODELS
}
WAVE = {model: presets.wave(model, DOMAIN, date=FORECAST_DATE, fxx=STEPS) for model in MODELS}
current = presets.current_mercator(DOMAIN, date=FORECAST_DATE) # same currents for both models

# North America, Brittany, the latest iceberg limit, and the zones of ExclusionZoneLibrary,
# which ui.py also displays: see the safety margin in reference_data.py to add one.
exclusion_zones = merge_exclusion_zones(default_exclusion_zones(), ExclusionZoneLibrary())
topography = presets.topography(DOMAIN, exclusion_zones=exclusion_zones)

#%% ROUTES

route_ortho = Route("simple_ortho", [DEPARTURE, SCILLY, CAPE_RACE, ARRIVAL])
route_starboard = Route("simple_starboard", [DEPARTURE, SCILLY, CAPE_RACE, ARRIVAL], divergences=[0., -0.3, 0.])
route_port = Route("simple_port", [DEPARTURE, ARRIVAL], divergences=[0.5])

route_set = RouteSet("simple", ortho=route_ortho, minus=route_port, plus=route_starboard)

# Stored for later: RouteSetLibrary().load("simple") or RouteLibrary().load("simple_ortho") in
# any script, and route_set.reversed() for the return passage.
RouteSetLibrary().save(route_set, overwrite=True)
for route in route_set.routes.values():
    RouteLibrary().save(route, overwrite=True)

plot_route_set(route_set)

#%% ROUTING

# A reference on the ortho route at constant speed, then each optimization.
runs = [
    (False, MODELS[0], vessels[0], 0., 1),
    *((True, model, vessel, init_fac, 0) for model, vessel, init_fac in product(MODELS, vessels[1:], INIT_FACS)),
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
        verbose=False,
    )
    report = analysis.run(
        max_iter=1000,
        init_fac=init_fac,
        solve=solve,
        solver_options=SOLVER_OPTIONS,
        tags={"member": member}, # solve, model and vessel are added by default
    )
    reports.append(report)

    # The timed positions of this run, with the settings that gave them in plan.metadata.
    plan = analysis.passage_plan
    plan.name = f"{plan.name}_{model}{vessel.label}_fac{init_fac:+.2f}_m{member}_{'solved' if solve else 'ref'}"
    plans.append(plan)

#%% RESULTS

# Check status (1: converged) and max_z (negative: at sea): failed runs still give a route.
print(reports.summary().to_string())
print(reports.frame().pivot_table(index="vessel", columns="model", values="fuel"))

draw(reports, barbs=False, sails_threshold=10.) # dots where the sails contribute more than 10 %

reports.save() # ~/data/routes/output_<today>.json: run ui.py to display the latest file

for plan in plans:
    PassagePlanLibrary().save(plan, overwrite=True) # reload with PassagePlanLibrary().load(name)

#%% OPEN-LOOP EVALUATION

# Each optimized plan with every model and vessel, positions and times unchanged: how its
# consumption depends on the conditions it was optimized for. Nothing is optimized here, and
# the default constraints are measured in max_constraint_violation.
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

#%% FIGURES: COMPARING ROUTES

# Any quantity per segment can be plotted: sog, stw, cog, tws, twa, aws, awa, swh, mwa,
# avg_bhp, max_bhp, sails_contribution, tws_gust, aws_gust...
SIDES = {-1.: "Port route", 0.: "Ortho cst speed", 1.: "Starboard route"}

selected = reports.select(lambda report: report["model"] != "ifs", vessel="eff45")

plot_fuel_vs_etd(reports)
plot_variable(selected, "sog", unit="kts", labels=SIDES)
plot_power_and_weather(selected, labels=SIDES)
plot_variable(reports[1:], "tws", unit="kts", figsize=(9, 3), dpi=100)
plot_variable([reports[-3]], "sails_contribution", unit="%", ylim=(-1., 101.), figsize=(10, 3), dpi=100)
plot_fuel_distribution({f"Eff. {efficiency}%": reports.select(vessel=f"eff{efficiency}") for efficiency in EFFICIENCIES})

#%% FIGURES: SPREAD OF SEVERAL RUNS

# They make sense with several runs: more INIT_FACS or TIMEFRAMES, or the members of an ensemble.
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

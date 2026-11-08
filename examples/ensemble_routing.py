# -*- coding: utf-8 -*-
"""
Created on Tue Feb  3 14:35:10 2026

@author: jrich
"""

import os
import json

import pandas as pd
import seaborn as sns
import cartopy.crs as ccrs
import architeuthis.numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import cartopy.feature as cfeature

from itertools import product
from architeuthis import presets
from architeuthis.common import _HOME, Domain
from architeuthis.vessel import Vessel
from architeuthis.toolbox.geo_utils import poly_deviated_route
from architeuthis.toolbox.plot_utils import draw, get_steps, plot_report, set_plot_style
from architeuthis.report import ReportCollection
from architeuthis.core import RoutingAnalysis, Voyage, DEFAULT_SOLVER_OPTIONS, exclusion_zones
from architeuthis.route import Route, RouteLibrary, RouteSet, RouteSetLibrary
from architeuthis.voyage import PassagePlan, PassagePlanLibrary
from architeuthis.forecast import DeterministicHerbieForecast, EnsembleHerbieForecast, CopernicusForecast, Topography


set_plot_style() # figures drawn by hand below use the same style
        
minimum_longitude=-80.
maximum_longitude=0.
minimum_latitude=30.
maximum_latitude=60.

# minimum_longitude=-80.
# maximum_longitude=-50.
# minimum_latitude=35.
# maximum_latitude=50.

steps = list(range(0, 145, 3)) + list(range(150, 361, 6))
    
domain = Domain(
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
)

#%% BUILD VESSEL INTERPOLATORS

def cubic_model(x, p):
    return p["d"] * x**3 + p["c"] * x**2 + p["b"] * x + p["a"]

def quadratic_model(x, p):
    return p["c"] * x**2 + p["b"] * x + p["a"]

p_sfc = {
    'a': 325.7684374001559,
    'b': -0.13133435575556507,
    'c': 5.216985806784128e-05,
    'd': -6.660802866517442e-09
}
p_hl = {
    'a': 177.84810351574922,
    'b': -0.011382017491188723,
    'c': 1.0915372379294297e-05
}

sfc_func = lambda x: cubic_model(x, p_sfc)
hotel_load_func = lambda x: quadratic_model(x, p_hl)

vessel_files = [    
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff15.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff30.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff45.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff90.nc",
    r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff100.nc",
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
        # sfc=220.,
        # hotel_load=194.,
        sfc=sfc_func,
        hotel_load=hotel_load_func,
        max_power=maxBHP
    )
    # vessel = Vessel(f"vessel_{i}", filepath=vessel_data, sfc=196., hotel_load=172., max_power=maxBHP)
    vessel.load_data()
    
    vessel.add_interpolators() # bhp, max_bhp, sails_contribution
    # vessel.add_interpolator("leeway", "stw", "tws", "twa", "hs", "wa", method="linear")
    
    vessels.append(vessel)

#%% BUILD WIND INTERPOLATORS

global_corr_fac = 1.10 # global models speed correction (115% @ 10m, 105% @ 100m)

recent = pd.Timestamp("now").floor("1d") #- pd.Timedelta("12h")
# mirror_end = pd.Timestamp('2025-12-21 12:00')

ATMOS = {}

# IFS atmospheric data
ATMOS["ifs"] = presets.atmosphere(
    "ifs", domain, date=recent, fxx=steps, wind_factor=global_corr_fac,
    regex=r":10[u|v]:|:msl:",
)

# GFS atmospheric data
ATMOS["gfs"] = presets.atmosphere(
    "gfs", domain, date=recent, fxx=steps, wind_factor=global_corr_fac,
    regex=r"(?:U|V)GRD:10 m",
)

# atmos = DeterministicHerbieForecast(
#     "wind", model="ifs", product="scda", regex=r":10[u|v]:", fxx=steps,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     # date=mirror_date
# )

atmos_ens = presets.ensemble_atmosphere("ifs", domain, date=recent, fxx=steps, wind_factor=global_corr_fac)


#%% BUILD WAVE INTERPOLATORS

# IFS ocean data
wave = presets.wave("ifs", domain, date=recent, fxx=steps, name="wave")

wave_ens = presets.ensemble_wave("ifs", domain, date=recent, fxx=steps)


#%% BUILD CURRENT INTERPOLATORS

# Mercator SMOC data
current = presets.current_mercator(
    domain,
    date=recent,
    # date=mirror_date, end=mirror_end
)


#%% BUILD TOPOGRAPHY

# topo0 = Topography(
#     "topo0", depth_offset=0., z_margin=0.,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     exclusion_zones=exclusion_zones[:-1],
# )
# topo0.load_data()

# topo0.add_interpolator(
#     "distance_to_iso0",
#     "latitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
#     "longitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
#     var_key="z"
# )

topo = presets.topography(domain, exclusion_zones=exclusion_zones)

#%%

departure = np.array([47.01483765543116, -2.63720447676916]) # Montoir pilot
# departure = np.array([47.823964087925354, -4.772235284069338]) # pos 06/02/2026 10h00 UTC
# departure = np.array([53.418611, -22.285278]) # pos 09/02/2026 10h00 UTC
# departure = np.array([53.130556, -38.120833]) # pos 11/02/2026 12h15 UTC
# departure = np.array([50.453056, -42.795278]) # pos 12/02/2026 10h00 UTC
# departure = np.array([47.595000, -47.963333]) # pos 13/02/2026 10h50 UTC
# departure = np.array([44.117702, -60.907898]) # pos 16/02/2026 00h00 UTC


# departure = np.array([47.68366513909249, -3.5247528817988893]) # Lorient
# arrival = np.array([47.68366513909249, -3.5247528817988893]) # Lorient

# departure = np.array([45.3868773482704, -54.57870483398438]) # 15/05 00h01 UTC
# departure = np.array([46.781, -56.091]) # SPM pilot
arrival = np.array([46.781, -56.091]) # SPM pilot
# departure = np.array([45.831667, -51.700000]) # pos 27/02/2026 14h00 UTC
# departure = np.array([44.993333, -39.533333]) # pos 01/03/2026 14h00 UTC
# departure = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# departure = np.array([37.38330548509701, -74.4866180419922]) # pos 20/02/2026 17h00 UTC
# departure = np.array([43.248056, -62.397778]) # pos 23/02/2026 09h20 UTC
# arrival = np.array([47.112116788143474, -2.4051169026612866]) # Montoir pilot
# departure = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# arrival = np.array([46.50781973122021, -53.33670295591693]) # Cape Race

# arrival = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
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
    
    [44.66666, -43.75000], # iip 28/05/2026
    [44.66666, -50.33333], # iip 28/05/2026
    
    # [41.666667, -50.583333], # iip 15/05/2026
    # [41.916667, -47.833333], # iip 15/05/2026

    # [46.551, -53.321], # cape race
    # [47.72529611513597, -4.379839003826363], # Penmarc'h
    
    # [47.79657767419367, -4.876263748342499], # Penmarc'h
])
# arrival = np.array([46.781, -56.091]) # SPM pilot

# lats = [departure[0], arrival[0]]
# lons = [departure[1], arrival[1]]
# divs = [0.5]
# Reference routes as Route objects (architeuthis.route), with the same waypoints and
# divergences as before. A Route is called like the former poly_deviated_route
# functions: route(s) -> (lat, lon) for s in [0, 1].
routeN = Route(
    "ensemble_north",
    [departure, *wp, arrival],
    divergences=[0., 0., 0.4,],
)


# lats = [departure[0], arrival[0]]
# lons = [departure[1], arrival[1]]
# divs = [0.0]
routeO = Route(
    "ensemble_ortho",
    [departure, *wp, arrival],
    divergences=[0., 0., 0.],
)


routeS = Route(
    "ensemble_south",
    [departure, *wp[:1], arrival],
    divergences=[0., -0.4],
)

# Store the routes: RouteLibrary().load(name) gives them back in any script
# (~/data/route_library/), and route.reversed() gives the return passage.
routes = RouteLibrary()
for route in (routeN, routeO, routeS):
    routes.save(route, overwrite=True)

# The same three routes as one entry: RouteSetLibrary().load("ensemble") (~/data/route_sets/).
route_set = RouteSet("ensemble", ortho=routeO, minus=routeS, plus=routeN)
RouteSetLibrary().save(route_set, overwrite=True)


ax = plt.axes(projection=ccrs.PlateCarree())

ax.add_feature(cfeature.LAND, facecolor="khaki")
# ax.add_feature(cfeature.LAND, facecolor="sandybrown")
ax.add_feature(cfeature.OCEAN, facecolor="lavender")
# ax.add_feature(cfeature.OCEAN, facecolor="lightsteelblue")
ax.add_feature(cfeature.COASTLINE, linewidth=0.3)
# ax.add_feature(cfeature.BORDERS, linestyle=":")
gl = ax.gridlines(draw_labels=False, dms=True, x_inline=False, y_inline=False, linewidth=0.5)

ax.plot(*routeN(np.linspace(0,1,50))[::-1])
ax.plot(*routeO(np.linspace(0,1,50))[::-1])
ax.plot(*routeS(np.linspace(0,1,50))[::-1])

plt.show()

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
restart = None
# restart = ([43.612500, -11.603333], "2026-06-01T06:30") # pos 01/06/2026 06h30 UTC


solver_options = DEFAULT_SOLVER_OPTIONS

reports = ReportCollection()
plans = [] # PassagePlan of each routing (timed positions)


zero_fac = 0.

# models = ["ifs", "gfs"]
models = ["ifs",]
# facs = np.asarray([0., 1.]) + zero_fac
# facs = np.asarray([-1., 0., 1.]) + zero_fac
facs = [zero_fac]
# topos = [topo]
# topos = [topo0 ,topo]

# members = None
# members = [0]
members = list(range(1,51,1))

def to_time(s):
    return pd.to_datetime(s).timestamp()

timeframes = [
    (to_time("2026-05-29T00h01"), to_time("2026-06-10T04:00")),
]

# for m, fac in product(list(range(1,51,1)), facs):
# for m, fac in product(list(range(1,51,51)), facs):
for solve, tf, model, vessel, fac, m in (
        list(
            # product([0], timeframes, models, vessels, [zero_fac], [1]) # NOT SOLVED ortho cst speed refs
            product([0], timeframes, models, vessels, facs, members) # NOT SOLVED ortho cst speed refs
        ) + list(
            product([1], timeframes, models, vessels, facs, members) # SOLVED
        )
    ):
                
    etd, eta = tf
    
    voyage = Voyage.from_routes(route_set, etd=etd, eta=eta, name="voyage")
    if restart is not None:
        voyage = voyage.from_position(*restart)

    analysis = RoutingAnalysis(
        "analysis",
        vessel,
        voyage,
        # ATMOS[model],
        atmos_ens,
        # wave,
        wave_ens,
        current,
        topo,
        atmosphere_member=m,
        wave_member=m,
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
        tags={"solve": solve, "model": model, "member": m}, # the vessel label is added by default
    )

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

df = pd.DataFrame(reports)

cv_reports = [r for r in reports if (r["status"]==1)] # TODO rather name raw_reports and reports

draw(cv_reports, barbs=0)
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


# WRITE
ReportCollection(cv_reports).save(os.path.join(_HOME, "routes", json_file))

# Passage plans, reloadable with PassagePlanLibrary().load(name) (~/data/passage_plans/)
plan_library = PassagePlanLibrary()
for plan in plans:
    plan_library.save(plan, overwrite=True)

#%% OPEN-LOOP EVALUATION OF THE PASSAGE PLANS

# Each optimized plan (one per member) is evaluated in every ensemble member, its
# positions and times fixed (no optimization): how the plan optimized for one member
# fares in the others. len(plans) x len(members) evaluations, without IPOPT.
# A stored plan can be evaluated the same way: PassagePlanLibrary().load(name).
vessels_by_tag = {v.label: v for v in vessels}

evaluations = []
for plan, member in product(
        [p for p in plans if p.metadata["solve"]],
        members,
    ):
    evaluation = RoutingAnalysis(
        "evaluation",
        vessels_by_tag[plan.metadata["vessel_tag"]],
        None, # no voyage needed: the plan gives the positions and times
        atmos_ens,
        wave_ens,
        current,
        topo,
        atmosphere_member=member,
        wave_member=member,
        verbose=False,
    ).evaluate(plan, tags={"plan_member": plan.metadata["member"], "member": member})
    evaluations.append(evaluation)

eval_table = pd.DataFrame(evaluations).pivot_table(
    index="plan_member",
    columns="member",
    values="fuel",
)
print(eval_table)

#%% FUEL VS ETA

fuel_reports = (
    pd.DataFrame(reports)
    .groupby(["solve", "vessel", "model"], as_index=False)[["eta", "fuel"]]
    .agg(list)
)

effs = fuel_reports["vessel"].unique()
models = fuel_reports["model"].unique()

markers = {0 : "x", 1: "o"}
names  = {0 : "ortho cst speed", 1: "optimised"}
colors = {model : color for model, color in zip(models, sns.color_palette("viridis", len(models)))}

for eff in effs:
    
    plt.figure(figsize=(10, 3.5))

    sub_fuel_reports = fuel_reports[fuel_reports["vessel"] == eff]
    
    for i in range(len(sub_fuel_reports)):
        fr = sub_fuel_reports.iloc[i]
        plt.plot(
            pd.to_datetime(fr["eta"], unit="s"), fr["fuel"],
            marker=markers[fr["solve"]],
            color = colors[fr["model"]],
            label=f"{fr['model'].upper()} / {names[fr['solve']]}"
        )
    
    plt.xticks(rotation=45.)
    plt.xlabel("ETA (UTC)")
    plt.ylabel("Total fuel consumption / tons")
    plt.title(f"Sails efficiency {eff[4:]} %")
    # plt.ylim((30., 85.))
    plt.legend()
    plt.show()

#%%

import seaborn as sns

def slicing(r):
    return (
        # (r["init_fac"] != 0.) &
        # (r["init_fac"] == 0.) &
        # (r["vessel"] == "eff45") &
        # (r["eta"] >= 1772049600.0) &
        # (r["eta"] < 1772049600.0) &
        True
    )

plots = [r for r in reports if slicing(r)]

# options = {-0.5: "North coast", 0.:"Ortho cst speed", 0.75: "North offshore", 3.: "South"}
options = {-1.: "North", 0.:"Ortho cst speed", 1.: "South"}

colors = sns.color_palette(palette="viridis", n_colors=len(plots))

variable = "sog"
unit = "kts"

# variable = "swh"
# unit = "m"

# variable = "sails_contribution"
# unit = "%"

# variable = "mwa"
# unit = "deg"

# variable = "avg_bhp"
# variable = "max_bhp"
# unit = "kW"

plt.clf()
plt.figure(figsize=(8, 4))
for i, r in enumerate(plots):
    x, y = get_steps(r, variable)
    x, y = get_steps(r, variable)
    plt.plot(x, y, label=options[r["init_fac"]], color=colors[i])
    plt.xlim((x.min(), x.max()))
# plt.legend()
plt.xticks(rotation=45)
plt.xlabel("Time (UTC)")
plt.ylabel(f"{variable.upper()} / {unit}")
plt.tight_layout()
plt.show()

#%%

# fuel plot
# plt.clf()
# plt.violinplot([r["fuel"] for r in reports])
# plt.boxplot([r["fuel"] for r in reports])
# plt.show()

data = [
    # [r["fuel"] for r in reports if (r["vessel"] == "_eff90")],
    # [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],
    # [r["fuel"] for r in reports if (r["init_fac"] < 0.)],
    # [r["fuel"] for r in reports if (r["init_fac"] == 0.)],
    # [r["fuel"] for r in reports if (r["init_fac"] > 0.)],
    [r["fuel"] for r in reports if (r["solve"] == 1)],
    [r["fuel"] for r in reports if (r["solve"] == 0)],
    # [r["fuel"] for r in cv_reports],
]

# labels = ["All routes"]
labels = ["Optimised routes", "Ortho cst. speed"]

hz = True
# hz = False

vert = not hz  # matplotlib uses 'vert'

fig, ax = plt.subplots(figsize=(8, 3))

vp = ax.violinplot(data, showextrema=False, vert=vert)
bp = ax.boxplot(data, patch_artist=True, vert=vert)

for box in bp["boxes"]:
    box.set(facecolor="limegreen")

if vert:
    ax.set_xticks(range(1, len(data) + 1))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Fuel / tons")
else:
    ax.set_yticks(range(1, len(data) + 1))
    ax.set_yticklabels(labels)
    ax.set_xlabel("Fuel / tons")

#%%

def slicing(r):
    return (
        # (r["init_fac"] != 0.) &
        # (r["init_fac"] == -1.) &
        # (r["vessel"] == "eff45") &
        # (r["eta"] >= 1772049600.0) &
        # (r["eta"] < 1772049600.0) &
        True
    )

plt.figure(figsize=(8,4))

# variable = "swh"
# variable = "tws"
variable = "avg_bhp"

# variable = "sails_contribution"

tim = pd.to_datetime(report["tim"], unit="s")
ctim = pd.to_datetime(report["ctim"], unit="s")

meteogram = np.array([r[variable] for r in reports if slicing(r)])

q00 = np.quantile(meteogram, 0.01, axis=0)
q05 = np.quantile(meteogram, 0.05, axis=0)
q25 = np.quantile(meteogram, 0.25, axis=0)
q50 = np.quantile(meteogram, 0.50, axis=0)
q75 = np.quantile(meteogram, 0.75, axis=0)
q95 = np.quantile(meteogram, 0.95, axis=0)
q100 = np.quantile(meteogram, 0.99, axis=0)

plt.fill_between(ctim, q00, q100, alpha=0.10, label="IFS ensemble 1–99%", color="limegreen")
plt.fill_between(ctim, q05, q95, alpha=0.25, label="IFS ensemble 05–95%", color="limegreen")
plt.fill_between(ctim, q25, q75, alpha=0.40, label="IFS ensemble 25–75%", color="limegreen")
plt.plot(ctim, q50, label="Median")
plt.legend()
plt.xticks(rotation=45)
plt.xlabel("Time (UTC)")
plt.ylabel(f"{variable.upper()} / {unit}")
plt.tight_layout()
plt.show()

#%%

# variable = "sog"
# unit = "kts"
# vmin = 6.
# vmax=14.

# variable = "swh"
# unit = "m"

# variable = "sails_contribution"
# unit = "%"

# variable = "mwa"
# unit = "deg"

variable = "avg_bhp"
# variable = "max_bhp"
unit = "kW"
vmin = 0.
vmax = maxBHP

plt.figure(figsize=(10,3.5))

for r in reports:
    # environment_query = np.concatenate([
    #     r["ctim"], r["clat"], r["clon"],
    # ], axis=1)
    
    n = r["ctim"].shape[0]
    
    tim = pd.to_datetime(r["tim"], unit="s")
    ctim = pd.to_datetime(r["ctim"], unit="s")
    
    
    
    # plt.fill_between(ctim, q00, q100, alpha=0.1, label="01–99%", color="limegreen")
    # plt.fill_between(ctim, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
    # plt.fill_between(ctim, q25, q75, alpha=0.4, label="25–75%", color="limegreen")
    plt.plot(*get_steps(r, variable))
plt.legend()
plt.xticks(rotation=45)
plt.xlabel("Time (UTC)")
plt.ylabel(f"{variable.upper()} / {unit}")
# plt.title(f"{variable.upper()} distribution")
plt.tight_layout()
# plt.ylim((-180, 180))
plt.ylim((vmin, vmax))
plt.xlim((tim[0], tim[-1]))
plt.show()

#%%

for r in reports:
    # environment_query = np.concatenate([
    #     r["ctim"], r["clat"], r["clon"],
    # ], axis=1)
    
    n = r["ctim"].shape[0]
    
    tim = pd.to_datetime(r["tim"], unit="s")
    ctim = pd.to_datetime(r["ctim"], unit="s")

    environment_query = np.column_stack([
        np.repeat(r["ctim"].reshape(-1), 50),
        np.tile(np.arange(1, 51), n),
        np.repeat(r["clat"].reshape(-1), 50),
        np.repeat(r["clon"].reshape(-1), 50),
    ])
    
    u10 = np.asarray(atmos_ens("u10", environment_query).reshape((50, n))) # unbeatable in terms of speed
    v10 = np.asarray(atmos_ens("v10", environment_query).reshape((50, n))) # unbeatable in terms of speed
    swh = np.asarray(wave_ens("swh", environment_query).reshape((50, n))) # unbeatable in terms of speed
    mwd = np.asarray(wave_ens("mwd", environment_query).reshape((50, n))) # unbeatable in terms of speed
    
    # environment_query = xr.Dataset(
    #     {
    #         "valid_time": ("points", r["ctim"]),
    #         "latitude": ("points", r["clat"]),
    #         "longitude": ("points", r["clon"]),
    #     }
    # )
        
    # atmos_meteogram = atmos_ens.data.interp(environment_query, assume_sorted=1, method="linear")
    # wave_meteogram = wave_ens.data.interp(environment_query, assume_sorted=1, method="linear")
    
    # u10 = atmos_meteogram.u10.data.T
    # v10 = atmos_meteogram.v10.data.T
    
    # swh = wave_meteogram.swh.data.T
    # mwd = wave_meteogram.mwd.data.T
    
    tws = np.sqrt(u10**2. + v10**2.) * 3600./1852. # wind speed in kts
    twd = np.mod(np.arctan2d(u10, v10)+180., 360.) # wind direction from 0 to 360 deg
    
    cog = r["cog"][np.newaxis, ...]
    
    twa = np.mod(twd-cog + 180., 360.) - 180
    mwa = np.mod(mwd-cog + 180., 360.) - 180
    
    # twa = np.zeros(npts-1) + 90*np.ones(npts-1)
    # mwa = np.zeros(npts-1)
    # d = distances(lat, lon)
    # dt = np.diff(tim) / 3600.
    sog = r["sog"]
    
    # cog_r = np.radians(cog)
    # tcd_r = np.radians(tcd)
    
    duog = sog * np.sind(cog) # eastward sog in kts
    dvog = sog * np.cosd(cog) # northward sog in kts
    
    # norm = np.sqrt(dlat**2. + dlon**2. + 1e-9)
    
    # duog = sog * dlat / norm
    # dvog = sog * dlon / norm
    
    # dutw = duog - uc # eastward stw in kts
    # dvtw = dvog - vc # northward stw in kts
    
    # TODO compute stw
    
    stw = r["stw"]
    # ctw = np.mod(np.arctan2d(dutw, dvtw), 360.) # course through water from 0 to 360
    
    # stw = sog
    
    # vessel_query = np.concatenate([
    #     stw, tws, np.abs(twa), swh, np.abs(mwa),
    # ], axis=1)
    
    # hotel_load = self.vessel.hotel_load # KW
    
    # avg_bhp = self.vessel("bhp", vessel_query)
    # max_bhp = self.vessel("max_bhp", vessel_query)
    # # leeway = vessel("leeway", vessel_query)        
    # sc = self.vessel("sails_contribution", vessel_query)
    
    # meteogram = swh
    # variable = "swh"
    # unit = "m"
    # vmin = 2.
    # vmax = 8.
    meteogram = tws
    variable = "tws"
    unit = "kts"
    vmin = 0.
    vmax = 50.
        
    q00 = np.quantile(meteogram, 0.01, axis=0)
    q05 = np.quantile(meteogram, 0.05, axis=0)
    q25 = np.quantile(meteogram, 0.25, axis=0)
    q50 = np.quantile(meteogram, 0.50, axis=0)
    q75 = np.quantile(meteogram, 0.75, axis=0)
    q95 = np.quantile(meteogram, 0.95, axis=0)
    q100 = np.quantile(meteogram, 0.99, axis=0)
    
    plt.figure(figsize=(10,3.5))
    
    plt.fill_between(ctim, q00, q100, alpha=0.1, label="01–99%", color="limegreen")
    plt.fill_between(ctim, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
    plt.fill_between(ctim, q25, q75, alpha=0.4, label="25–75%", color="limegreen")
    plt.plot(ctim, q50, label="Median")
    plt.legend()
    plt.xticks(rotation=45)
    plt.xlabel("Time (UTC)")
    plt.ylabel(f"{variable.upper()} / {unit}")
    # plt.title(f"{variable.upper()} distribution")
    plt.tight_layout()
    # plt.ylim((-180, 180))
    plt.ylim((vmin, vmax))
    plt.xlim((tim[0], tim[-1]))
    plt.show()

#%%

plt.figure(figsize=(9,4))

# variable = "sog"
# unit = "kts"

# variable = "tws"
# unit = "kts"

# variable = "twa"
# unit = "deg"

variable = "swh"
unit = "m"

# variable = "mwa"
# unit = "deg"

# variable = "sails_contribution"
# unit = "%"

# variable = "mwa"
# unit = "deg"

# variable = "avg_bhp"
# # # variable = "max_bhp"
# unit = "kW"

    # [r["fuel"] for r in reports if (r["vessel"] == "_eff90")],
    # [r["fuel"] for r in reports if (r["vessel"] == "_eff60")],

# meteogram = np.array([r[variable] for r in reports if (r["vessel"] == "_eff90")])
# meteogram = np.array([r[variable] for r in reports if (r["vessel"] == "_eff60")])
# meteogram = np.array([np.abs(r[variable]) for r in reports if (r["solve"] == 1)])
meteogram = np.array([r[variable] for r in reports if (r["solve"] == 1)])
    
q00 = np.quantile(meteogram, 0.01, axis=0)
q05 = np.quantile(meteogram, 0.05, axis=0)
q25 = np.quantile(meteogram, 0.25, axis=0)
q50 = np.quantile(meteogram, 0.50, axis=0)
q75 = np.quantile(meteogram, 0.75, axis=0)
q95 = np.quantile(meteogram, 0.95, axis=0)
q100 = np.quantile(meteogram, .99, axis=0)

plt.fill_between(ctim, q00, q100, alpha=0.1, label="01–99%", color="limegreen")
plt.fill_between(ctim, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
plt.fill_between(ctim, q25, q75, alpha=0.4, label="25–75%", color="limegreen")
plt.plot(ctim, q50, label="Median")
plt.legend()
plt.xticks(rotation=45)
plt.xlabel("Time (UTC)")
plt.ylabel(f"{variable.upper()} / {unit}")
plt.title(f"{variable.upper()} distribution along optimised routes for all scenarios")
plt.tight_layout()
# plt.ylim((-180, 180))
# plt.ylim((0, None))
plt.xlim((tim[0], tim[-1]))
plt.show()



#%%

etas = np.sort(np.unique([r["eta"] for r in reports]))

for eta in etas:
    def slicing(r):
        return (
            # (r["init_fac"] != 0.) &
            # (r["init_fac"] == -1.) &
            # (r["vessel"] == "eff45") &
            # (r["eta"] >= 1772049600.0) &
            (r["status"] == 1) &
            (r["solve"] == 1) &
            (r["eta"] == eta) &
            True
        )
    # slicing = (df["status"] == 1) & (df["eta"] == eta) & (df["solve"] == 1)

    # # optional slicing
    # subDf = df[slicing]
    
    # variable = "swh"
    # unit = "m"
    # vmax = 10.
    # variable = "tws"
    # unit = "kts"
    # vmax=50.
    # variable = "avg_bhp"
    variable = "max_bhp"
    unit = "kW"
    # vmax = maxBHP *1.066
    # variable = "sog"
    # unit = "kts"
    # vmax = 13.
    # variable = "sails_contribution"
    # unit = "%"
    # vmax=45.
    
    subr = [r for r in reports if slicing(r)]
    
    etd = pd.to_datetime(subr[0]["etd"], unit="s")
    tim = pd.to_datetime(subr[0]["tim"], unit="s")
    ctim = pd.to_datetime(subr[0]["ctim"], unit="s")
    
    plt.figure(figsize=(10, 4))
    
    meteogram = np.array([r[variable] for r in reports if slicing(r)])
    
    q00 = np.quantile(meteogram, 0.01, axis=0)
    q05 = np.quantile(meteogram, 0.05, axis=0)
    q25 = np.quantile(meteogram, 0.25, axis=0)
    q50 = np.quantile(meteogram, 0.50, axis=0)
    q75 = np.quantile(meteogram, 0.75, axis=0)
    q95 = np.quantile(meteogram, 0.95, axis=0)
    q100 = np.quantile(meteogram, .99, axis=0)
    
    
    plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=1))   # every 24 h
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    
    plt.fill_between(ctim, q00, q100, alpha=0.1, label="IFS ensemble 1–99%", color="limegreen")
    plt.fill_between(ctim, q05, q95, alpha=0.25, label="IFS ensemble 05–95%", color="limegreen")
    plt.fill_between(ctim, q25, q75, alpha=0.4, label="IFS ensemble 25–75%", color="limegreen")
    plt.plot(ctim, q50, label="Median", marker="o", ms=3.)
    plt.legend(loc="upper left")
    # plt.ylim((0,vmax))
    plt.xticks(rotation=45)
    # plt.xlabel("Time (UTC)")
    plt.ylabel(f"{variable.upper()} / {unit}")
    plt.title(f"ETD {pd.to_datetime(etd, unit='s')} UTC - ETA {pd.to_datetime(eta, unit='s')} UTC")
    plt.tight_layout()
    plt.show()


#%% FUEL CONSUMPTION

plt.figure(figsize=(8, 4))

slicing = (df["status"] == 1)

df["daily_fuel"] = df["fuel"] / df["transit_time"] * 24.

# optional slicing
subDf = df[slicing]

# subDf = df

quantiles = subDf.groupby("eta")["fuel"].quantile(
    [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
).unstack()

x = pd.to_datetime(quantiles.index.values, unit="s")

q00 = quantiles[0.01].values
q05 = quantiles[0.05].values
q25 = quantiles[0.25].values
q50 = quantiles[0.50].values
q75 = quantiles[0.75].values
q95 = quantiles[0.95].values
q100 = quantiles[0.99].values

plt.fill_between(x, q00, q100, alpha=0.1, label="1–99%", color="limegreen")
plt.fill_between(x, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
plt.fill_between(x, q25, q75, alpha=0.4, label="25–75%", color="limegreen")

plt.plot(x, q50, label="Median", marker="o")

plt.legend()
plt.xticks(rotation=45)
plt.xlabel("ETA")
plt.ylabel("TOTAL FUEL CONS. / tons")
plt.tight_layout()
plt.show()


# FUEL CONSUMPTION DAILY

plt.figure(figsize=(8, 4))

slicing = (df["status"] == 1)

df["daily_fuel"] = df["fuel"] / df["transit_time"] * 24.

# optional slicing
subDf = df[slicing]

# subDf = df

quantiles = subDf.groupby("eta")["daily_fuel"].quantile(
    [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
).unstack()

x = pd.to_datetime(quantiles.index.values, unit="s")

q00 = quantiles[0.01].values
q05 = quantiles[0.05].values
q25 = quantiles[0.25].values
q50 = quantiles[0.50].values
q75 = quantiles[0.75].values
q95 = quantiles[0.95].values
q100 = quantiles[0.99].values

plt.fill_between(x, q00, q100, alpha=0.1, label="1–99%", color="limegreen")
plt.fill_between(x, q05, q95, alpha=0.25, label="05–95%", color="limegreen")
plt.fill_between(x, q25, q75, alpha=0.4, label="25–75%", color="limegreen")

plt.plot(x, q50, label="Median", marker="o")

plt.legend()
plt.xticks(rotation=45)
plt.xlabel("ETA")
plt.ylabel("DAILY FUEL CONS. / tons/day")
plt.tight_layout()
plt.show()


# CONVERGED RATIO

# Compute ratio of status == 1 per eta
ratio = df.groupby("eta")["status"].apply(lambda s: (s == 1).mean())

# Arrays for plotting if needed
x = pd.to_datetime(ratio.index.values, unit="s")
prob = ratio.values

plt.figure(figsize=(8, 4))

# Plot
plt.plot(x, prob*100, marker="o")
plt.xlabel("ETA")
plt.ylabel("Probability of possible ETA / %")
# plt.ylim(0, 102)
plt.xticks(rotation=45)
# plt.legend()
plt.tight_layout()
plt.show()

#%%    
# json_file = "output_ensemble.json"
    
reports = ReportCollection.load(os.path.join(_HOME, "routes", json_file))
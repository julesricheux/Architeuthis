# -*- coding: utf-8 -*-
"""
Route a voyage with a vessel whose polar is a function, not a NetCDF table.

A minimal version of simple_routing.py: one IFS run, calm water and a dummy
semi-empirical polar with fitted parameters. The polar depends on stw, swh, mwa,
the true wind averaged between 10 m and 100 m, and slightly on the air temperature.
The routing computes stw, swh and mwa, and the wind at both heights relative to the
vessel: tws and twa from u10 and v10, tws100 and twa100 from u100 and v100, which the
atmospheric forecast provides. The air temperature is not a routing quantity, so it
is read from that forecast too, which has a model of that name.

The routing also computes variables that the polar does not use, for constraints
and reports: the IFS gusts and a wave slope, swh / mwp, which the wave forecast
computes as a function of its own fields.

Needs no polar file and no credentials: IFS comes through Herbie, and the current
is calm. Run from the repository root, cell by cell (#%%) or as a script.

Created on Tue Nov 17 2026

@author: jrich
"""


import os

import pandas as pd
import architeuthis.numpy as np

from datetime import datetime
from architeuthis.core import DEFAULT_SOLVER_OPTIONS, RoutingAnalysis, Voyage
from architeuthis.common import _HOME
from architeuthis.forecast import DeterministicHerbieForecast, Topography
from architeuthis.icebergs import berg_zone
from architeuthis.report import ReportCollection
from architeuthis.route import Route
from architeuthis.vessel import Vessel

domain = {"min_lon": -70.0, "max_lon": 5.0, "min_lat": 30.0, "max_lat": 60.0}
steps = list(range(0, 145, 3)) + list(range(150, 361, 6))
recent = (pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta("9h")).floor("1d")  # latest 00 UTC run

#%% DUMMY FUNCTION-BASED POLAR

# Fitted parameters of the dummy model, passed to it as fixed arguments.
parameters = {
    "c_calm": 1.2,  # kW/kt³: calm water power
    "c_wave": 3.0,  # kW/(m² kt): added power in head seas
    "c_sail": 0.11,  # kW/(kt² kt): sail power on a beam reach
    "k_air": 0.004,  # 1/°C: denser cold air, more sail power
    "t_ref": 15.0,  # °C: temperature of the fit
}


def dummy_polar(x, p):
    """
    Brake power of a dummy sailing vessel, and its components.

    Written with architeuthis.numpy and without branching on values, so
    that the routing differentiates through it.

    Args:
        x: Dict with stw, tws, twa, tws100, twa100, swh, mwa and
            air_temperature.
        p: Fitted parameters.

    Returns:
        The brake power in kW, and a dict of its components.
    """
    calm = p["c_calm"] * x["stw"] ** 3
    # Head seas (mwa = 0) cost the most, following seas nothing
    waves = p["c_wave"] * x["swh"] ** 2 * x["stw"] * (1. + np.cosd(x["mwa"])) / 2.
    # The sails see the wind between 10 m and 100 m: average of both heights.
    # The angles are absolute, in [0, 180], so their plain mean has no wrap
    tws = (x["tws"] + x["tws100"]) / 2.
    twa = (x["twa"] + x["twa100"]) / 2.
    # Sails pull most on a beam reach, a little more in cold air
    air_density = 1. - p["k_air"] * (x["air_temperature"] - p["t_ref"])
    sails = p["c_sail"] * air_density * tws ** 2 * x["stw"] * np.sind(twa) ** 2

    # The engine cannot absorb power: smooth floor at 10 % of the calm water power
    bhp = np.softmax(calm + waves - sails, 0.1 * calm, softness=10.)

    return bhp, {"calm": calm, "waves": waves, "sails": sails, "leeway": 0*sails}


# tws100 and twa100: the routing computes them from u100 and v100, as tws and twa from u10 and v10
polar_inputs = ["stw", "tws", "twa", "tws100", "twa100", "swh", "mwa", "air_temperature"]

vessel = Vessel(
    "dummy_vessel",
    sfoc=196.,
    hotel_load=172.,
    max_power=4100.,
    fuel_type="mdo",  # a key of architeuthis.fuels.FUELS: its density turns L/h into tonnes
    # fuel_density=0.86,  # kg/L, from the bunker delivery note, instead of that of the fuel type
)  # no file, no load_data
# The fuel only needs the consumption: here the brake power, plus the hotel load, burnt
# at the sfoc, in kg/h, then in L/h through the fuel density. The other models are
# computed when the analysis lists them in its variables.
vessel.add_function("bhp", dummy_polar, polar_inputs, args={"p": parameters})
# Other ways to give the consumption, the first the vessel has being used:
# vessel.add_function("sfoc", lambda x: 180. + 1e-6 * (x["total_power"] - 3000.)**2, ["total_power"])  # sfoc curve
# vessel.add_constant("hotel_load", 172.)  # a model, as hotel_load=172.
# vessel.add_function("total_power", lambda x: dummy_polar(x, parameters)[0] + 172., polar_inputs)  # with sfoc
# vessel.add_function("hourly_consumption", lambda x: 196e-3 * (dummy_polar(x, parameters)[0] + 172.) / vessel.fuel_density, polar_inputs)  # L/h
vessel.add_function("max_bhp", dummy_polar, polar_inputs, args={"p": parameters})
vessel.add_function("sails_contribution", dummy_polar, polar_inputs, args={"p": parameters}, output="sails")
vessel.add_function("leeway", dummy_polar, polar_inputs, args={"p": parameters}, output="leeway")

print(vessel("bhp", {
    "stw": 11., "tws": 20., "twa": 90., "tws100": 25., "twa100": 85.,
    "swh": 2., "mwa": 30., "air_temperature": 10.,
}))

#%% FORECASTS AND TOPOGRAPHY

# IFS 10 m and 100 m wind, 10 m gust and 2 m air temperature
atmosphere = DeterministicHerbieForecast(
    "wind_ifs", model="ifs", product="oper", regex=r":(?:10[uv]|10fg|100[uv]|2t):",
    fxx=steps, date=recent, **domain,
)
atmosphere.load_data()
for key in ("u10", "v10", "u100", "v100", "t2m"):
    atmosphere.add_interpolator(key, "valid_time", "latitude", "longitude", method="bspline")
# The gust, in m/s, under the key the routing reads for tws_gust and aws_gust
atmosphere.add_interpolator("fg10", "valid_time", "latitude", "longitude", var_key="gust", method="bspline")

# The routing reads the inputs of the polar from the atmosphere, wave and current
# forecasts: the atmosphere gets an air_temperature model, in °C as the polar takes it
atmosphere.add_function(
    "air_temperature",
    lambda x: atmosphere("t2m", x) - 273.15,
    inputs=["valid_time", "latitude", "longitude"],
)

wave = DeterministicHerbieForecast(
    "wave_ifs", model="ifs", product="wave", regex=r":swh:|:mwd:|:mwp:",
    fxx=steps, date=recent, **domain,
)
wave.load_data()
wave.add_wave_components()
for key in ("swh", "uw", "vw", "mwp"):
    wave.add_interpolator(key, "valid_time", "latitude", "longitude", method="bspline")

# Wave slope (m/s), a comfort criterion that the polar does not use. The period is 0
# on land and past the horizon, so it is smoothly kept above 1 s.
wave.add_function(
    "slope",
    lambda x: wave("swh", x) / np.softmax(wave("mwp", x), 1., softness=0.1),
    inputs=["valid_time", "latitude", "longitude"],
)

# No current, so that no credentials are needed: the routing takes it as zero
current = None

#%% TOPOGRAPHY

north_america = [
    [46.6475507, -53.0879974], [47.1448975, -52.6904297],
    [47.8057761, -52.6574707], [48.7272088, -53.0310059],
    [52.2547088, -55.5688477], [57.0646303, -61.6992188],
    [59.1759282, -64.0283203], [60.5221575, -64.8193359],
    [62.0833149, -66.2255859], [63.5485522, -70.3125000],
    [64.4348920, -73.6083984], [64.8862654, -77.3876953],
    [66.0715465, -86.4404297], [64.1681069, -92.1093750],
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
    [44.2412638, -66.3958740], [43.3930737, -66.0305786],
    [43.3850899, -65.6268311], [43.5007524, -65.2807617],
    [44.4631908, -63.5641479], [45.2555553, -60.9851074],
    [46.0045933, -59.6667480], [47.0252060, -60.3918457],
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

# Stored for ui.py, which displays the iceberg limit and the zones of this library (~/data/exclusion_zones/).
# ExclusionZoneLibrary().save(ExclusionZone("north_america", north_america, label="North America"), overwrite=True)
# ExclusionZoneLibrary().save(ExclusionZone("brittany", brittany, label="Brittany"), overwrite=True)

topography = Topography("topography", exclusion_zones=[berg_zone] + exclusion_zones, **domain)  # berg_zone: the latest IIP iceberg limit
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z", method="bspline")

#%% ROUTING

departure = np.array([50.489, -0.037])
arrival = np.array([46.781, -56.091])  # SPM pilot
route = Route(
    "channel_spm",
    [departure, [49.665, -6.241], [46.551, -53.321], arrival],  # Scilly, Cape Race
    divergences=[0., 0., 0.],
)

voyage = Voyage(
    "crossing",
    etd=recent + pd.Timedelta(hours=9),
    eta=recent + pd.Timedelta(days=8, hours=20),
    route=route,
)

def constraints(ctx):
    return [
        ctx["max_bhp"] < ctx["vessel"].max_power,
        # ctx["leeway"] < 1.,
        ctx["z"] < -1,
        # ctx["tws_gust"] < 45.,  # no gust over 45 kt
        # ctx["gust_excess"] < 15.,  # nor gusts 15 kt above the mean wind
        # ctx["slope"] < 0.5,  # nor steep seas
    ]


analysis = RoutingAnalysis(
    "ifs", vessel, voyage, atmosphere, wave, current, topography,
    constraints=constraints,
    # Computed along the route, in ctx for the constraints and in the reports: the
    # fuel only needs bhp, so max_bhp and sails_contribution are listed; "gust" gives tws_gust and aws_gust in kt (from the forecast "gust", else
    # tws * GUST_DEFAULT_RATIO), then any model of the forecasts or vessel by its key
    # ("wave.slope" to name the source), the wind at 100 m, and functions of the
    # variables before them.
    variables=[
        "max_bhp",  # vessel models that the fuel does not need: in ctx and the reports
        "sails_contribution",
        "gust",
        "slope",
        "tws100",
        "air_temperature",
        "leeway",
        {"gust_excess": lambda ctx: ctx["tws_gust"] - ctx["tws"]},
    ],
)
# solver_options = {"ipopt": DEFAULT_SOLVER_OPTIONS["ipopt"] | {"linear_solver": "mumps", }}

solver_options = {
    "ipopt":{
        "acceptable_tol": 1e2,
        'linear_solver': 'spral',
        # 'linear_solver': 'mumps',
        "hessian_approximation": "limited-memory",
    },
}

reports = ReportCollection()
reports.append(analysis.run(solve=False, solver_options=solver_options))  # reference route
reports.append(analysis.run(max_iter=1000, solver_options=solver_options))

now = datetime.now()

json_file = f"output_{now.strftime(r'%Y-%m-%d')}.json"

# WRITE (ui.py displays the latest file of this folder)
reports.save(os.path.join(_HOME, "routes", json_file))

print(reports.summary())
print(reports[-1].table(["tws", "tws_gust", "gust_excess", "swh", "slope"]))

# The consumption along the route is in L/h, the fuel of the voyage in tonnes, and its
# emissions follow from the factors of the fuel type (FuelEU Maritime defaults)
print(reports[-1].table(["sog", "bhp", "hourly_consumption"]))
fuel = reports[-1]["fuel"]
print(f"Fuel {fuel:.2f} t of {vessel.fuel.label} ({vessel.fuel_density} kg/L): "
      f"{vessel.fuel.co2(fuel):.1f} t of CO2, {vessel.fuel.ghg(fuel):.1f} t of CO2 equivalent well to wake")

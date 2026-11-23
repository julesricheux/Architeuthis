# -*- coding: utf-8 -*-
"""
Route a voyage in the wind alone, without waves or current.

Only the IFS 10 m wind is downloaded. The wave and current forecasts are
left out of RoutingAnalysis: each missing source is a calm_forecast, whose
fields are zero, a flat sea and no current. The vessel is the dummy
function polar of function_polar_routing.py, reduced to the 10 m wind.

Needs no polar file and no credentials: IFS comes through Herbie. Run from
the repository root, cell by cell (#%%) or as a script.

Created on Thu Nov 19 2026

@author: jrich
"""

import pandas as pd
import architeuthis.numpy as np

from architeuthis.core import RoutingAnalysis, Voyage
from architeuthis.forecast import DeterministicHerbieForecast, Topography
from architeuthis.report import ReportCollection
from architeuthis.vessel import Vessel

domain = {"min_lon": -11.0, "max_lon": -2.0, "min_lat": 42.0, "max_lat": 50.0}
recent = pd.Timestamp("now").floor("9h").floor("1d")  # latest 00 UTC run

#%% DUMMY FUNCTION POLAR

parameters = {"c_calm": 1.2, "c_wave": 3.0, "c_sail": 0.11}


def dummy_polar(x, p):
    """
    Brake power of a dummy sailing vessel, in kW.

    The polar of function_polar_routing.py with the 10 m wind only. The
    waves still count: they are zero here, the routing having no wave
    forecast.

    Args:
        x: Dict with stw, tws, twa, swh and mwa.
        p: Fitted parameters.

    Returns:
        The brake power, in kW.
    """
    calm = p["c_calm"] * x["stw"] ** 3
    waves = p["c_wave"] * x["swh"] ** 2 * x["stw"] * (1. + np.cosd(x["mwa"])) / 2.
    sails = p["c_sail"] * x["tws"] ** 2 * x["stw"] * np.sind(x["twa"]) ** 2
    return np.softmax(calm + waves - sails, 0.1 * calm, softness=10.)


vessel = Vessel("dummy_vessel", sfoc=196., hotel_load=172., max_power=4100.)
vessel.add_function("bhp", dummy_polar, ["stw", "tws", "twa", "swh", "mwa"], args={"p": parameters})

#%% WIND AND TOPOGRAPHY: THE ONLY DATA

atmosphere = DeterministicHerbieForecast(
    "wind_ifs", model="ifs", product="oper", regex=r":10[uv]:",
    fxx=list(range(0, 73, 3)), date=recent, **domain,
)
atmosphere.load_data()
for key in ("u10", "v10"):
    atmosphere.add_interpolator(key, "valid_time", "latitude", "longitude")

topography = Topography("topography", **domain)
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

#%% ROUTING

voyage = Voyage(
    "brest_coruna",
    etd=recent + pd.Timedelta(hours=9),
    eta=recent + pd.Timedelta(hours=42),
    departure=np.array([48.25, -4.85]),  # off Brest
    arrival=np.array([43.42, -8.40]),  # La Coruña
)

# No wave nor current given: the routing takes them as zero
analysis = RoutingAnalysis("wind_only", vessel, voyage, atmosphere, topography=topography)
print(analysis.wave.name, analysis.current.name)  # calm_wave calm_current

solver_options = {"ipopt": {"linear_solver": "mumps"}}
reports = ReportCollection()
reports.append(analysis.run(solve=False, solver_options=solver_options))  # reference route
reports.append(analysis.run(max_iter=300, solver_options=solver_options))

print(reports.summary()[["solve", "status", "fuel", "sog", "max_z"]])
print(reports[-1].table(["sog", "tws", "twa", "swh", "cs", "bhp"]))

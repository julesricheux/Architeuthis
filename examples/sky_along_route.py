# -*- coding: utf-8 -*-
"""
Describe the sky along a route with IFS and GFS, without routing.

The nine fields of architeuthis.sky (total, low, middle and high cloud covers,
CAPE, precipitation rate, 2 m temperature and dewpoint, temperature at 700 hPa)
are downloaded from each model, read along a great circle sailed at constant
speed, and turned into the cloud genera an observer would see from deck, one line
per point. Both models are put side by side, as a table and as meteograms in both
styles: a table of the étages, and a picture of the clouds.

GFS has no middle and high cloud covers at step 0, so the steps start at 3 h,
and so does the departure.

Needs no polar file and no credentials: IFS and GFS come through Herbie. Run from
the repository root, cell by cell (#%%) or as a script.

Created on Tue Nov 17 2026

@author: jrich
"""

import numpy as np
import pandas as pd

from architeuthis import sky
from architeuthis.forecast import DeterministicHerbieForecast
from architeuthis.toolbox.geo_utils import great_circle_route

domain = {"min_lon": -35.0, "max_lon": 0.0, "min_lat": 30.0, "max_lat": 55.0}
steps = list(range(3, 121, 3))
recent = pd.Timestamp("now").floor("9h").floor("1d")  # latest 00 UTC run

# Brest to Ponta Delgada (Azores) at 12 kt, leaving at the first step
departure = [48.2, -5.0]
arrival = [37.6, -25.6]
speed = 12.0  # kt
points = 41

#%% FORECASTS

# Each model has its own names and units: add_sky_models registers them under the
# keys and in the units of architeuthis.sky
forecasts = {
    "ifs": DeterministicHerbieForecast(
        "sky_ifs", model="ifs", product="oper", regex=sky.IFS_SKY_REGEX,
        fxx=steps, date=recent, **domain,
    ),
    "gfs": DeterministicHerbieForecast(
        "sky_gfs", model="gfs", product="pgrb2.0p25", regex=sky.GFS_SKY_REGEX,
        fxx=steps, date=recent, **domain,
    ),
}
for forecast in forecasts.values():
    forecast.load_data()
    sky.add_sky_models(forecast)

#%% ROUTE

# Points equally spaced on the great circle, hence equally spaced in time
latitude, longitude, distance = great_circle_route(departure, arrival, points)
latitude, longitude = np.asarray(latitude, dtype=float), np.asarray(longitude, dtype=float)
distance = float(np.max(distance))
etd = recent + pd.Timedelta(hours=steps[0])
duration = pd.Timedelta(hours=distance / speed)
times = pd.date_range(etd, etd + duration, periods=points)
valid_time = (times - pd.Timestamp("1970-01-01")).total_seconds().to_numpy()

#%% SKY

skies = {}
for model, forecast in forecasts.items():
    fields = sky.sample(forecast, valid_time, latitude, longitude)
    diagnosis = sky.diagnose(fields)
    skies[model] = fields | diagnosis

table = pd.DataFrame({
    "time": times.strftime("%d %H:%MZ"),
    "lat": latitude.round(1),
    "lon": longitude.round(1),
    **{f"sky {model.upper()}": sky.describe(result) for model, result in skies.items()},
})

with pd.option_context("display.max_colwidth", None, "display.width", 200):
    print(f"Sky from {departure} to {arrival}, {distance:.0f} nm at {speed:.0f} kt, run of {recent:%Y-%m-%d %HZ}")
    print(table.to_string(index=False))

#%% AGREEMENT OF THE MODELS

# Share of points where both models see the same genus at each étage
for etage in sky.ETAGES:
    same = np.mean(skies["ifs"][f"cloud_{etage}"] == skies["gfs"][f"cloud_{etage}"])
    print(f"{etage:>6} étage: same genus at {same:.0%} of the points")

#%% METEOGRAMS

# The cover of each étage and its genus over time, the cloud base and the precipitation
# "cells": the table of the étages; "smooth": the picture, with nights from the positions
figures = {
    (model, style): sky.draw(
        result, valid_time, style=style, latitude=latitude, longitude=longitude,
        title=f"Sky from Brest to the Azores, {model.upper()} run of {recent:%Y-%m-%d %HZ}",
    )
    for model, result in skies.items()
    for style in ("cells", "smooth")
}

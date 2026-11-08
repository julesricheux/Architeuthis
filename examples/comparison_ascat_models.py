# -*- coding: utf-8 -*-
"""
Validate the wind of IFS and GFS against ASCAT satellite observations.

The forecasts of a past run are interpolated at the time and position of each observation, and
the errors on speed and direction are summed up in a table. No vessel and no routing here: this
is how to query a forecast directly, as `forecast("u10", points)`.

Needs EUMETSAT credentials (EUMDAC_USER, EUMDAC_PWD). IFS and GFS need none. Run from the
repository root.
"""

import datetime

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from architeuthis import presets
from architeuthis.common import Domain
from architeuthis.satellite import ASCATData

DOMAIN = Domain(min_lon=-80., max_lon=0., min_lat=30., max_lat=60.)
LOOK_WIDTH = 48 # hours of observations, until now
FORECAST_PRIOR = 48 # age of the forecast at the end of the observations, in hours
# LOOK_WIDTH = 96
# FORECAST_PRIOR = 192 # mid future, from +4 d to +8 d

MODEL_REGEX = {"ifs": r":10[u|v]:", "gfs": r"(?:U|V)GRD:10 m"}


def circular_diff_deg(model, obs):
    """Minimal signed angular difference model - obs in degrees."""
    return np.degrees(
        np.arctan2(
            np.sin(np.radians(model - obs)),
            np.cos(np.radians(model - obs)),
        )
    )


def stats_linear(model, obs):
    err = model - obs
    return dict(
        N=err.size,
        Bias=np.mean(err),
        RMSE=np.sqrt(np.mean(err**2)),
        Std=np.std(err),
        Corr=pearsonr(model, obs)[0],
    )


def stats_direction(model, obs):
    dtheta = circular_diff_deg(model, obs)
    return dict(
        N=dtheta.size,
        Bias=np.mean(dtheta),
        RMSE=np.sqrt(np.mean(dtheta**2)),
        Std=np.std(dtheta),
    )


def observations(ascat, forecast):
    """Time, position, wind speed (m/s) and direction (deg) of the valid observations in a forecast."""
    tim, lat, lon, speed, direction = (
        ascat.data[key].values.ravel(order="C")
        for key in ("valid_time", "lat", "lon", "wind_speed", "wind_dir")
    )
    mask = (
        ~(np.isnan(lat) | np.isnan(lon) | np.isnan(tim) | np.isnan(speed) | np.isnan(direction))
        & (tim > forecast.data["valid_time"].values.min())
    )
    return np.vstack([tim[mask], lat[mask], lon[mask]]).T, speed[mask], direction[mask]


def compare_ascat_vs_models(domain, look_width=24, forecast_prior=24):
    """Statistics of each model against the observations of the last `look_width` hours."""
    end_look = datetime.datetime.now()
    start_look = end_look - datetime.timedelta(hours=look_width)

    ref_f00 = pd.Timestamp(end_look - datetime.timedelta(hours=forecast_prior)).floor("d")
    steps = list(range(forecast_prior - look_width, forecast_prior, 6))

    ascat = ASCATData("ascat", start=start_look, end=end_look, **domain)
    ascat.load_data()

    results = {}

    for model, regex in MODEL_REGEX.items():
        forecast = presets.atmosphere(model, domain, date=ref_f00, fxx=steps, regex=regex, name=model)

        # Wind speed from u and v, to interpolate it directly
        forecast.data = forecast.data.herbie.with_wind()
        forecast.add_interpolator("si10", "valid_time", "latitude", "longitude")

        ascat_query, speed_obs, direction_obs = observations(ascat, forecast)

        speed_model = np.array(forecast("si10", ascat_query)).ravel()
        u_model = np.array(forecast("u10", ascat_query)).ravel()
        v_model = np.array(forecast("v10", ascat_query)).ravel()
        direction_model = (np.degrees(np.arctan2(u_model, v_model)) + 360.) % 360.

        results[model] = dict(
            speed=stats_linear(speed_model, speed_obs),
            direction=stats_direction(direction_model, direction_obs),
        )

    return ref_f00, ascat_query, results


def build_validation_report(ref_f00, ascat_query, results):
    report = f"""
====================================================================
             ASCAT – Atmospheric Model Wind Validation
====================================================================

• Models runtime:  {ref_f00.strftime('%Y/%m/%d %Hh%M UTC')}
• Earliest ASCAT:  {pd.to_datetime(ascat_query[:, 0].min(), unit='s').strftime('%Y/%m/%d %Hh%M UTC')}
• Latest ASCAT:    {pd.to_datetime(ascat_query[:, 0].max(), unit='s').strftime('%Y/%m/%d %Hh%M UTC')}

"""

    header = (
        f"{'Model':<6} | "
        f"{'Var':<6} | "
        f"{'N':>6} | "
        f"{'Bias':>8} | "
        f"{'RMSE':>8} | "
        f"{'Std':>8} | "
        f"{'Corr':>8}"
    )

    report += header + "\n"
    report += "-" * len(header) + "\n"

    for model, res in results.items():

        sp = res["speed"]
        dr = res["direction"]

        report += (
            f"{model.upper():<6} | "
            f"{'Speed':<6} | "
            f"{sp['N']:6d} | "
            f"{sp['Bias']:8.3f} | "
            f"{sp['RMSE']:8.3f} | "
            f"{sp['Std']:8.3f} | "
            f"{sp['Corr']:8.3f}\n"
        )

        report += (
            "       | "
            f"{'Dir':<6} | "
            f"{dr['N']:6d} | "
            f"{dr['Bias']:8.3f} | "
            f"{dr['RMSE']:8.3f} | "
            f"{dr['Std']:8.3f} | "
            f"{'–':>8}\n"
        )

    report += """
Notes:
• Speed units: m/s
• Direction units: degrees (meteorological)
• Direction errors use minimal circular difference
====================================================================
"""

    return report


if __name__ == "__main__":
    ref_f00, ascat_query, results = compare_ascat_vs_models(DOMAIN, LOOK_WIDTH, FORECAST_PRIOR)

    print(build_validation_report(ref_f00, ascat_query, results))

# -*- coding: utf-8 -*-
"""
Created on Mon Feb  2 02:10:58 2026

@author: jules
"""

import datetime

import numpy as np
import pandas as pd
import xarray as xr
from scipy.stats import pearsonr

from architeuthis.satellite import ASCATData
from architeuthis.forecast import DeterministicHerbieForecast

#%%

def circular_diff_deg(model, obs):
    """
    Minimal signed angular difference model - obs in degrees
    """
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


def build_validation_report(
        ref_f00,
        ascat_query,
        results,
):
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

    # print(report)
    return report


def compare_ascat_vs_models(
        minimum_longitude: float,
        maximum_longitude: float,
        minimum_latitude: float,
        maximum_latitude: float,
        
        look_width: int = 24, # hours
        forecast_prior: int = 24, # hours
    ):

    end_look = datetime.datetime.now()
    start_look = end_look - datetime.timedelta(hours=look_width)


    
    # ref_f00 = pd.Timestamp("2026-02-03 12:00:00")
    ref_f00 = pd.Timestamp(end_look - datetime.timedelta(hours=forecast_prior)).floor("d")
    
    # steps = list(range(0, 24, 3))
    steps = list(range(forecast_prior - look_width, forecast_prior, 6)) # mid future from +4d to +6d
    
    # =========================================================================
    # DOWNLOAD MODELS
    # =========================================================================
    
    # IFS atmospheric data
    atmos_ifs = DeterministicHerbieForecast(
        "ifs", model="ifs", product="oper", regex=r":10[u|v]:", fxx=steps,
        min_lon=minimum_longitude, max_lon=maximum_longitude,
        min_lat=minimum_latitude, max_lat=maximum_latitude,
        date=ref_f00,
    )
    atmos_ifs.load_data()
    
    atmos_ifs.data = atmos_ifs.data.herbie.with_wind()
    
    # GFS atmospheric data
    atmos_gfs = DeterministicHerbieForecast(
        "gfs", model="gfs", regex=r"(?:U|V)GRD:10 m", fxx=steps,
        min_lon=minimum_longitude, max_lon=maximum_longitude,
        min_lat=minimum_latitude, max_lat=maximum_latitude,
        date=ref_f00,
    )
    atmos_gfs.load_data()
    
    atmos_gfs.data = atmos_gfs.data.herbie.with_wind()
    
    # =========================================================================
    # DOWNLOAD ASCAT DATA
    # =========================================================================
    
    ascat = ASCATData(
        "ascat", start=start_look, end=end_look,
        min_lon=minimum_longitude, max_lon=maximum_longitude,
        min_lat=minimum_latitude, max_lat=maximum_latitude,
    )
    ascat.load_data()
    
    results = {}
    
    step = 1
    
    fac = 1.0
    
    for atmos in [atmos_ifs, atmos_gfs]:
        
        # Prepare ASCAT dataset
        lat = ascat.data["lat"].values.ravel(order="C")
        lon = ascat.data["lon"].values.ravel(order="C")
        tim = ascat.data["valid_time"].values.ravel(order="C")
        
        si = ascat.data["wind_speed"].values.ravel(order="C")       # m/s
        wdir = ascat.data["wind_dir"].values.ravel(order="C")       # degrees, meteorological
        
        mask = (
            (~(np.isnan(lat) | np.isnan(lon) | np.isnan(tim) | np.isnan(si) | np.isnan(wdir))) &
            (tim > atmos.data["valid_time"].values.min()) &
            True
        )
        
        lat = lat[mask][::step]
        lon = lon[mask][::step]
        tim = tim[mask][::step]
        
        si_obs = si[mask][::step] * fac # m/s
        wdir_obs = wdir[mask][::step]   # degrees, meteorological
        
        ascat_query = np.vstack([
            tim, lat, lon,
        ]).T
        
        # Build interpolators
        atmos.add_interpolator("si10", "valid_time", "latitude", "longitude")
        atmos.add_interpolator("u10", "valid_time", "latitude", "longitude")
        atmos.add_interpolator("v10", "valid_time", "latitude", "longitude")
    
        # Interpolation
        model_si = atmos("si10", ascat_query)
        model_u = atmos("u10", ascat_query)
        model_v = atmos("v10", ascat_query)
    
        model_wdir = (np.degrees(np.arctan2(model_u, model_v)).ravel() + 360.0) % 360.0
    
        # si_obs = si[valid]
        # wdir_obs = wdir[valid]
    
        si_mod = np.array(model_si).ravel()
        wdir_mod = np.array(model_wdir).ravel()
    
        results[atmos.name] = dict(
            speed=stats_linear(si_mod, si_obs),
            direction=stats_direction(wdir_mod, wdir_obs),
        )
    
    # ============================================================
    # Console summary table
    # ============================================================
    
    return ref_f00, ascat_query, results
    
    
if __name__=="__main__":
    # look_width = 96 # hours
    # forecast_prior = 192 # hours
    look_width = 48 # hours
    forecast_prior = 48 # hours
    
    minimum_longitude=-80.
    maximum_longitude=0.
    minimum_latitude=30.
    maximum_latitude=60.
    
    ref_f00, ascat_query, results = compare_ascat_vs_models(
        minimum_longitude,
        maximum_longitude,
        minimum_latitude,
        maximum_latitude,
        
        look_width,
        forecast_prior,
    )
    
    report = build_validation_report(ref_f00, ascat_query, results)
    
    print(report)

# -*- coding: utf-8 -*-
"""
Latest ASCAT winds over the Bay of Biscay, from Copernicus Marine.

The CMEMS product WIND_GLO_PHY_L3_NRT_012_002 holds the ASCAT swaths of
Metop-B and -C on a regular 0.125 deg grid (also 0.25 deg), one dataset
per satellite and orbit direction, one time step per day. The toolbox
`copernicusmarine` (already a dependency of Architeuthis) subsets it
on the server (ARCO Zarr), so only the area, the days and the variables
asked for are read. The latest day is about one day old: fine for
analysis, not for the latest pass. The CMEMS credentials of
Architeuthis are used.

Run from the repository root:
    python temp-experimental/cmems_ascat_wind.py
"""

import os
import sys
import time
import datetime

import numpy as np
import copernicusmarine

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repository root

from architeuthis.credentials import require_credentials
from summary import WIND_NSWE, report, wind_dataset

DATASET = "cmems_obs-wind_glo_phy_nrt_l3-{satellite}-ascat-{orbit}-0.125deg_P1D-i"
VARIABLES = ["eastward_wind", "northward_wind", "measurement_time"]


def swaths(username, password, days=3):
    """
    Daily swaths of each Metop and orbit direction over the area.

    Args:
        username: CMEMS user name.
        password: CMEMS password.
        days: How many days back to read.

    Yields:
        (name, swath, bytes read), with `swath` a dataset of one day.
    """
    north, south, west, east = WIND_NSWE
    end = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    for satellite in ["metopb", "metopc"]:
        for orbit in ["asc", "des"]:
            data = copernicusmarine.open_dataset(
                dataset_id=DATASET.format(satellite=satellite, orbit=orbit),
                username=username,
                password=password,
                variables=VARIABLES,
                minimum_longitude=west,
                maximum_longitude=east,
                minimum_latitude=south,
                maximum_latitude=north,
                start_datetime=end - datetime.timedelta(days=days),
                end_datetime=end,
            ).load()
            for day in data.time.values:
                swath = data.sel(time=day)
                name = f"Metop-{satellite[-1].upper()} {orbit}"
                yield name, swath, swath.nbytes


if __name__ == "__main__":
    tic = time.time()
    username, password = require_credentials(
        "CMEMS_USER", "CMEMS_PWD", provider="Copernicus Marine"
    )

    # Latest swath covering at least 10 % of the area
    best, read = None, 0
    for name, swath, size in swaths(username, password):
        read += size
        times = swath["measurement_time"].values.ravel()
        times = times[~np.isnat(times)]
        if times.size < 0.1 * swath["eastward_wind"].size:
            continue
        moment = np.median(times.astype("int64")).astype("datetime64[ns]")
        if best is None or moment > best[2]:
            best = (name, swath, moment)
    name, swath, moment = best

    u, v = swath["eastward_wind"], swath["northward_wind"]
    lat, lon = np.meshgrid(swath.latitude, swath.longitude, indexing="ij")
    valid = np.isfinite(u.values)
    report(
        case="wind",
        library="cmems",
        source=f"{name} ASCAT, CMEMS L3 0.125 deg",
        image_time=str(np.datetime64(moment, "m")).replace("T", " ") + " UTC",
        downloaded=read,
        full_product=None,
        seconds=time.time() - tic,
        data=wind_dataset(
            speed=np.hypot(u.values, v.values)[valid],
            direction=np.rad2deg(np.arctan2(u.values, v.values))[valid],
            latitude=lat[valid],
            longitude=lon[valid],
            convention="to",
        ),
        notes="server-side subset (ARCO); size read, uncompressed",
    )

# -*- coding: utf-8 -*-
"""
Latest Sentinel-3 SLSTR IR 10.85 um image over France, with openEO.

The Copernicus Data Space Ecosystem (CDSE) openEO backend crops,
reprojects and resamples on the server, so only the requested grid is
downloaded. Its catalogue holds no geostationary imagery, so the IR
source is the polar-orbiting SLSTR (band S8), at most a few passes a
day over France, mosaicked per day by the backend.

Authentication is OpenID Connect with a free CDSE account: the first
run prints a link to log in through the browser, then the refresh token
is kept by the openeo client. Processing uses CDSE credits.

There is no ASCAT, nor any other wind product, on the CDSE openEO
backends (checked on openeo and openeofed.dataspace.copernicus.eu).

Run from the repository root:
    python temp-experimental/openeo_slstr_ir.py
"""

import os
import time
import datetime

import numpy as np
import openeo
import xarray as xr

from summary import DATA, IR_NSWE, RESOLUTION, ir_dataset, report


if __name__ == "__main__":
    tic = time.time()
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "openeo_raw.nc")

    connection = openeo.connect("https://openeo.dataspace.copernicus.eu")
    connection.authenticate_oidc()  # browser login the first time

    north, south, west, east = IR_NSWE
    today = datetime.datetime.now(datetime.timezone.utc).date()
    cube = connection.load_collection(
        "SENTINEL3_SLSTR",
        spatial_extent={"west": west, "south": south, "east": east, "north": north},
        temporal_extent=[str(today - datetime.timedelta(days=1)), str(today + datetime.timedelta(days=1))],
        bands=["S8"],
    )
    cube = cube.resample_spatial(resolution=RESOLUTION, projection=4326, method="near")
    cube.download(path, format="netCDF")  # synchronous, small requests only

    # h5netcdf: netCDF4 fails on Windows paths with accents
    with xr.open_dataset(path, engine="h5netcdf") as raw:
        raw = raw.load()
    # Latest day with data: the daily mosaic of the passes of that day
    filled = [float(np.isfinite(raw["S8"].isel(t=i)).mean()) for i in range(raw.sizes["t"])]
    last = max(i for i, fraction in enumerate(filled) if fraction > 0.1)
    bt = raw["S8"].isel(t=last)
    data = ir_dataset(bt.values, raw["y"].values, raw["x"].values)

    report(
        case="ir",
        library="openeo",
        source="Sentinel-3 SLSTR S8 (10.85 um)",
        image_time=f"{str(raw['t'].values[last])[:10]} (daily mosaic)",
        downloaded=os.path.getsize(path),
        full_product=None,
        seconds=time.time() - tic,
        data=data,
        notes=f"server-side crop and resampling; {raw.sizes['t']} day(s) returned",
    )

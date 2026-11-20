# -*- coding: utf-8 -*-
"""
Latest GOES-East IR image over the NW Atlantic, with goes2go.

goes2go reads the NOAA GOES archive on AWS (bucket `noaa-goes19`,
anonymous, no account). It downloads whole files: here the full disk
of the L2 Cloud and Moisture Imagery product (ABI-L2-CMIP), band 13 only,
10.3 um brightness temperature at 2 km, every 10 min. The CONUS sector
(5 min) stops short of the area. The file is in the geostationary
projection, and is resampled here on a regular grid (nearest pixel).

`goes_latest` only looks in the folder of the current UTC hour, empty
for a few minutes after the hour: then `latest` asks for the last file
of the last 30 minutes. On first import, goes2go writes `~/.config/goes2go/config.toml`.

Run from the repository root:
    python temp-experimental/goes2go_goes_ir.py
"""

import os
import time
import datetime

import numpy as np
import pyproj
from goes2go import goes_latest, goes_nearesttime

from summary import ATLANTIC_NSWE, DATA, folder_size, ir_dataset, report

RESOLUTION = 0.02  # deg, the 2 km of the band


def regrid(data, nswe, resolution):
    """
    Nearest pixel of a GOES ABI image on a latitude-longitude grid.

    Args:
        data: Dataset from goes2go, with `CMI` on `y` and `x`.
        nswe: Bounds as [north, south, west, east].
        resolution: Grid step, in degrees.

    Returns:
        Dataset from `summary.ir_dataset`.
    """
    projection = data["goes_imager_projection"].attrs
    height = projection["perspective_point_height"]
    geos = pyproj.CRS.from_cf(projection)
    to_geos = pyproj.Transformer.from_crs("EPSG:4326", geos, always_xy=True)

    north, south, west, east = nswe
    latitude = np.arange(north, south, -resolution)
    longitude = np.arange(west, east, resolution)
    lon, lat = np.meshgrid(longitude, latitude)
    x, y = to_geos.transform(lon, lat)  # metres; ABI x and y are angles
    x, y = x / height, y / height

    # Nearest scan angles (x increasing, y decreasing)
    xs, ys = data["x"].values, data["y"].values
    i = np.clip(np.searchsorted(-ys, -y), 0, ys.size - 1)
    j = np.clip(np.searchsorted(xs, x), 0, xs.size - 1)
    # Crop first: reading the full disk is the slow part
    i0, i1, j0, j1 = i.min(), i.max() + 1, j.min(), j.max() + 1
    window = data["CMI"].isel(y=slice(i0, i1), x=slice(j0, j1)).values
    values = np.where(np.isfinite(x), window[i - i0, j - j0], np.nan)
    return ir_dataset(values, latitude, longitude)


def latest(**query):
    """
    Latest file of a GOES product, even just after the hour.

    Args:
        **query: Arguments of `goes_latest`.

    Returns:
        Dataset from goes2go.
    """
    try:
        return goes_latest(**query)
    except FileNotFoundError:
        # Nearest to now is the latest; skip the empty hour folder
        return goes_nearesttime(
            datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
            within=datetime.timedelta(minutes=30),
            ignore_missing=True,
            **query,
        )


if __name__ == "__main__":
    tic = time.time()
    folder = os.path.join(DATA, "goes2go")
    data = latest(
        satellite="noaa-goes19",  # GOES-East
        product="ABI-L2-CMIP",
        domain="F",
        bands=13,
        save_dir=folder,
    )
    # The files read: goes2go keeps their AWS paths below save_dir
    paths = [os.path.join(folder, path) for path in data.attrs["path"]]
    report(
        case="goes",
        library="goes2go",
        source="GOES-East ABI 10.3 um (geostationary)",
        image_time=str(np.datetime64(data.t.values, "m")).replace("T", " ") + " UTC",
        downloaded=folder_size(paths),
        full_product=folder_size(paths),
        seconds=time.time() - tic,
        data=regrid(data, ATLANTIC_NSWE, RESOLUTION),
        notes="whole full-disk file from AWS, regridded locally",
    )

# -*- coding: utf-8 -*-
"""
Latest ASCAT winds over the Bay of Biscay, from NASA PO.DAAC.

earthaccess searches the NASA catalogue (CMR) anonymously. PO.DAAC
redistributes the OSI SAF ASCAT coastal winds of EUMETSAT
(`ASCATB-L2-Coastal`, `ASCATC-L2-Coastal`, 12.5 km): the same data as
eumdac, one file per orbit (whole, no subsetting). Downloading needs a
free NASA Earthdata login (https://urs.earthdata.nasa.gov), read from
`EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` or from `~/.netrc`.
Without one, the script stops after the search.

Run from the repository root:
    python temp-experimental/earthaccess_ascat_wind.py
"""

import os
import time
import datetime

import numpy as np
import xarray as xr
import earthaccess

from summary import DATA, WIND_NSWE, folder_size, report, wind_dataset

COLLECTIONS = ["ASCATB-L2-Coastal", "ASCATC-L2-Coastal"]


def search(hours=24):
    """
    ASCAT orbits crossing the area, newest first.

    Args:
        hours: How far back to search.

    Returns:
        List of earthaccess granules.
    """
    north, south, west, east = WIND_NSWE
    end = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    start = end - datetime.timedelta(hours=hours)
    granules = []
    for name in COLLECTIONS:
        granules += earthaccess.search_data(
            short_name=name,
            bounding_box=(west, south, east, north),
            temporal=(start.isoformat(), end.isoformat()),
        )
    return sorted(
        granules,
        key=lambda g: g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"],
        reverse=True,
    )


def logged_in():
    """
    Whether an Earthdata login is available, without prompting.

    Returns:
        True if earthaccess could log in.
    """
    for strategy in ["environment", "netrc"]:
        try:
            if earthaccess.login(strategy=strategy).authenticated:
                return True
        except Exception:
            pass
    return False


def swath(path):
    """
    Wind vectors of an OSI SAF ASCAT file inside the area.

    Args:
        path: Path of the NetCDF file.

    Returns:
        Dataset from `summary.wind_dataset`.
    """
    north, south, west, east = WIND_NSWE
    with xr.open_dataset(path, engine="h5netcdf") as data:
        lat = data["lat"].values
        lon = (data["lon"].values + 180) % 360 - 180
        speed, direction = data["wind_speed"].values, data["wind_dir"].values
    inside = (
        (lat <= north) & (lat >= south) & (lon >= west) & (lon <= east)
        & np.isfinite(speed)
    )
    return wind_dataset(
        speed=speed[inside],
        direction=direction[inside],
        latitude=lat[inside],
        longitude=lon[inside],
        convention="to",  # wind_to_direction
    )


if __name__ == "__main__":
    tic = time.time()
    granules = search()
    for granule in granules:
        extent = granule["umm"]["TemporalExtent"]["RangeDateTime"]
        print(
            f"{extent['BeginningDateTime'][:16]}  {granule.size:6.1f} MB  "
            f"{granule['meta']['native-id']}"
        )
    if not granules:
        raise SystemExit("No ASCAT orbit found (PO.DAAC lags by a few hours).")
    if not logged_in():
        raise SystemExit("No Earthdata login: search only.")

    latest = granules[0]
    folder = os.path.join(DATA, "earthaccess")
    paths = earthaccess.download([latest], local_path=folder)
    extent = latest["umm"]["TemporalExtent"]["RangeDateTime"]
    report(
        case="wind",
        library="earthaccess",
        source="Metop ASCAT coastal 12.5 km (OSI SAF, PO.DAAC)",
        image_time=extent["BeginningDateTime"][:16].replace("T", " ") + " UTC",
        downloaded=folder_size(paths),
        full_product=sum(g.size for g in granules) * 1e6,
        seconds=time.time() - tic,
        data=swath(paths[0]),
        notes="whole orbit files, cropped locally",
    )

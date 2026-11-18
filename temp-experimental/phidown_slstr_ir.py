# -*- coding: utf-8 -*-
"""
Latest Sentinel-3 SLSTR IR 10.85 um image over France, with phidown.

phidown searches the Copernicus Data Space Ecosystem (CDSE) catalogue,
anonymously, then downloads from its S3 endpoint. It cannot crop or
resample: the finest it does is one file of a product. So only the S8
brightness temperature and its geolocation are downloaded from each
granule of the latest pass (about 10 MB of the 350 MB granule), and the
swath is regridded here, on a 0.01 deg grid (~1 km).

Downloading needs CDSE S3 keys (not the CDSE login), created at
https://eodata-s3keysmanager.dataspace.copernicus.eu and kept in plain
text in CONFIG_FILE, an INI file. Without them, the script stops after
the search. CONFIG_FILE:

    [default]
    aws_access_key_id = <access key>
    aws_secret_access_key = <secret key>
    aws_region = eu-central-1
    host_base = eodata.dataspace.copernicus.eu
    host_bucket = eodata.dataspace.copernicus.eu
    use_https = true
    check_ssl_certificate = true

Run from the repository root:
    python temp-experimental/phidown_slstr_ir.py
"""

import os
import time
import datetime

import numpy as np
import xarray as xr
from scipy.spatial import cKDTree
from phidown.search import CopernicusDataSearcher
from phidown.native_download import download_s3_resumable

from summary import IR_NSWE, OUTPUT, RESOLUTION, folder_size, ir_dataset, report

CONFIG_FILE = os.path.expanduser("~/.s5cfg")  # outside the repository
FILES = ["S8_BT_in.nc", "geodetic_in.nc"]  # IR 10.85 um, nadir view


def wkt_box(nswe):
    """
    WKT polygon of a box.

    Args:
        nswe: Bounds as [north, south, west, east], in degrees.

    Returns:
        The WKT string.
    """
    north, south, west, east = nswe
    return (
        f"POLYGON(({west} {south}, {east} {south}, {east} {north}, "
        f"{west} {north}, {west} {south}))"
    )


def search_latest_pass(hours=24):
    """
    Granules of the latest SLSTR L1 pass over France.

    Args:
        hours: How far back to search.

    Returns:
        DataFrame of the granules, one per row.
    """
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(hours=hours)
    searcher = CopernicusDataSearcher()
    searcher.query_by_filter(
        collection_name="SENTINEL-3",
        product_type="S3SLSTR",
        attributes={"productType": "SL_1_RBT___"},
        aoi_wkt=wkt_box(IR_NSWE),
        start_date=start.strftime("%Y-%m-%dT%H:%M:%S"),
        end_date=end.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    products = searcher.execute_query()
    # Name: S3B_SL_1_RBT____<start>_<end>_<created>_<dur>_<cycle>_<orbit>_...
    pass_id = products["Name"].str[:3] + products["Name"].str[69:76]
    return products[pass_id == pass_id.iloc[0]]


def regrid(paths):
    """
    Nearest-neighbour regridding of SLSTR granules on the France grid.

    Args:
        paths: Pairs of paths, (brightness temperature, geolocation).

    Returns:
        Dataset with `bt` in K on `latitude` and `longitude`.
    """
    lat, lon, bt = [], [], []
    for bt_path, geo_path in paths:
        # h5netcdf: netCDF4 fails on Windows paths with accents
        with xr.open_dataset(bt_path, engine="h5netcdf") as ds, \
                xr.open_dataset(geo_path, engine="h5netcdf") as geo:
            bt.append(ds["S8_BT_in"].values.ravel())
            lat.append(geo["latitude_in"].values.ravel())
            lon.append(geo["longitude_in"].values.ravel())
    lat, lon, bt = map(np.concatenate, (lat, lon, bt))

    north, south, west, east = IR_NSWE
    grid_lat = np.arange(north, south, -RESOLUTION)
    grid_lon = np.arange(west, east, RESOLUTION)
    glon, glat = np.meshgrid(grid_lon, grid_lat)
    distance, index = cKDTree(np.c_[lat, lon]).query(np.c_[glat.ravel(), glon.ravel()])
    values = np.where(distance < 2 * RESOLUTION, bt[index], np.nan)
    return ir_dataset(values.reshape(glat.shape), grid_lat, grid_lon)


if __name__ == "__main__":
    tic = time.time()
    granules = search_latest_pass()
    print(granules[["Name", "ContentLength"]].to_string())

    if not os.path.exists(CONFIG_FILE):
        raise SystemExit(f"No CDSE S3 keys in {CONFIG_FILE}: search only.")

    folder = os.path.join(OUTPUT, "phidown")
    paths = []
    for s3_path in granules["S3Path"]:
        granule = os.path.join(folder, os.path.basename(s3_path))
        for name in FILES:
            download_s3_resumable(
                s3_path=f"{s3_path}/{name}",
                output_dir=granule,
                config_file=CONFIG_FILE,
                persist_state=False,
            )
        paths.append([os.path.join(granule, name) for name in FILES])

    data = regrid(paths)
    start = granules["ContentDate"].iloc[-1]["Start"][:16]
    end = granules["ContentDate"].iloc[0]["End"][11:16]
    report(
        case="ir",
        library="phidown",
        source="Sentinel-3 SLSTR S8 (10.85 um)",
        image_time=f"{start.replace('T', ' ')}-{end} UTC",
        downloaded=folder_size([p for pair in paths for p in pair]),
        full_product=granules["ContentLength"].sum(),
        seconds=time.time() - tic,
        data=data,
        notes="whole files, regridded locally (KD-tree)",
    )

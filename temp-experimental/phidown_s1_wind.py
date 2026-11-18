# -*- coding: utf-8 -*-
"""
Latest Sentinel-1 SAR winds over the Bay of Biscay, with phidown.

There is no ASCAT in the CDSE catalogue (only the land soil water index
derived from it), so this is the closest CDSE product: the ocean wind
field (OWI) of the Sentinel-1 Level 2 OCN products, ~1 km, on narrow
swaths along the coasts. Of each product only the `-ocn-` NetCDF of the
`measurement` folder is downloaded (about 40 of 150 MB): phidown cannot
cut inside a file. Its file names come from the public OData catalogue.

Needs the CDSE S3 keys of `phidown_slstr_ir.py`.

Run from the repository root:
    python temp-experimental/phidown_s1_wind.py
"""

import os
import time
import datetime

import numpy as np
import requests
import xarray as xr
from phidown.search import CopernicusDataSearcher
from phidown.native_download import download_s3_resumable

from phidown_slstr_ir import CONFIG_FILE, wkt_box
from summary import OUTPUT, WIND_NSWE, folder_size, report, wind_dataset

ODATA = "https://catalogue.dataspace.copernicus.eu/odata/v1"


def search_latest_datatake(hours=24):
    """
    OCN products of the latest Sentinel-1 acquisition over the domain.

    Args:
        hours: How far back to search.

    Returns:
        DataFrame of the products, one per row.
    """
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(hours=hours)
    searcher = CopernicusDataSearcher()
    searcher.query_by_filter(
        collection_name="SENTINEL-1",
        product_type="OCN",
        aoi_wkt=wkt_box(WIND_NSWE),
        start_date=start.strftime("%Y-%m-%dT%H:%M:%S"),
        end_date=end.strftime("%Y-%m-%dT%H:%M:%S"),
    )
    products = searcher.execute_query()
    products = products[~products["Name"].str.contains("_WV_")]  # no wind field
    datatake = products["Name"].str.split("_").str[-2]
    return products[datatake == datatake.iloc[0]]


def ocn_file(product):
    """
    Name of the wind NetCDF in the measurement folder of a product.

    Args:
        product: Row of the search results.

    Returns:
        The file name.
    """
    url = f"{ODATA}/Products({product['Id']})/Nodes({product['Name']})/Nodes(measurement)/Nodes"
    nodes = requests.get(url, timeout=60).json()["result"]
    return next(node["Name"] for node in nodes if "-ocn-" in node["Name"])


if __name__ == "__main__":
    tic = time.time()
    products = search_latest_datatake()
    print(products[["Name", "ContentLength"]].to_string())

    folder = os.path.join(OUTPUT, "phidown")
    paths = []
    for _, product in products.iterrows():
        name = ocn_file(product)
        target = os.path.join(folder, product["Name"])
        download_s3_resumable(
            s3_path=f"{product['S3Path']}/measurement/{name}",
            output_dir=target,
            config_file=CONFIG_FILE,
            persist_state=False,
        )
        paths.append(os.path.join(target, name))

    speed, direction, lat, lon = [], [], [], []
    for path in paths:
        # h5netcdf: netCDF4 fails on Windows paths with accents
        with xr.open_dataset(path, engine="h5netcdf") as ds:
            # owiMask: 0 valid, 1 land, 2 ice, 4 no data, 8 RFI
            sea = (ds["owiMask"].values == 0) & np.isfinite(ds["owiWindSpeed"].values)
            speed.append(ds["owiWindSpeed"].values[sea])
            direction.append(ds["owiWindDirection"].values[sea])  # from, deg
            lat.append(ds["owiLat"].values[sea])
            lon.append(ds["owiLon"].values[sea])
    speed, direction, lat, lon = map(np.concatenate, (speed, direction, lat, lon))

    start = products["ContentDate"].iloc[-1]["Start"][:16]
    report(
        case="wind",
        library="phidown",
        source=f"Sentinel-1 SAR winds, ~1 km ({products['Name'].iloc[0][4:6]} mode)",
        image_time=f"{start.replace('T', ' ')} UTC (latest acquisition)",
        downloaded=folder_size(paths),
        full_product=products["ContentLength"].sum(),
        seconds=time.time() - tic,
        data=wind_dataset(speed, direction, lat, lon, convention="from"),
        notes=f"not ASCAT; {len(paths)} products, one whole file each",
    )

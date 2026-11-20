# -*- coding: utf-8 -*-
"""
Latest ASCAT coastal winds over the Bay of Biscay, with eumdac.

Uses the Architeuthis wrapper `ASCATData` (OSI-104, 12.5 km swath grid)
as it is, except for one change: its search gets a bounding box, so only
the passes crossing the area are downloaded. As is, the wrapper searches
by time only and downloads every pass of the period, around the globe.
The script counts both, to show the gain.

ASCAT is only on EUMETSAT: neither the CDSE openEO backends nor the CDSE
catalogue (phidown) hold ASCAT winds. `phidown_s1_wind.py` shows the
closest CDSE product, the Sentinel-1 SAR winds.

Run from the repository root:
    python temp-experimental/eumdac_ascat_wind.py
"""

import os
import sys
import time
import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repository root

from architeuthis.satellite import ASCATData
from summary import WIND_NSWE, report, wind_dataset

HOURS = 12


class RegionalASCATData(ASCATData):
    """
    ASCAT winds whose search is restricted to the domain.

    Args:
        Those of `ASCATData`.
    """

    def _locate_data(self):
        super()._locate_data()
        search = self.collection.search
        bbox = f"{self.min_lon}, {self.min_lat}, {self.max_lon}, {self.max_lat}"
        self.everywhere = list(search(dtstart=self.start, dtend=self.end))
        self.collection.search = lambda **query: search(bbox=bbox, **query)


if __name__ == "__main__":
    tic = time.time()
    north, south, west, east = WIND_NSWE
    end = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    ascat = RegionalASCATData(
        "ascat_biscay",
        start=end - datetime.timedelta(hours=HOURS),
        end=end,
        min_lon=west,
        max_lon=east,
        min_lat=south,
        max_lat=north,
    )
    ascat.load_data()

    # Latest pass covering the domain, not just a corner of it: passes
    # are split at gaps of 30 min, and need a quarter of the largest one
    data = ascat.data
    inside = np.isfinite(data["wind_speed"].values)
    time_s = data["time"].values.astype("datetime64[s]")
    times = np.sort(time_s[inside])
    breaks = np.flatnonzero(np.diff(times) > np.timedelta64(30, "m")) + 1
    passes = np.split(times, breaks)
    largest = max(len(p) for p in passes)
    chosen = [p for p in passes if len(p) >= largest / 4][-1]
    latest = chosen[0]
    keep = inside & (time_s >= chosen[0]) & (time_s <= chosen[-1])

    report(
        case="wind",
        library="eumdac",
        source="Metop ASCAT coastal winds, 12.5 km (OSI-104)",
        image_time=f"{str(latest)[:16].replace('T', ' ')} UTC (latest covering pass)",
        downloaded=sum(product.size for product in ascat.products) * 1e3,
        full_product=sum(product.size for product in ascat.everywhere) * 1e3,
        seconds=time.time() - tic,
        data=wind_dataset(
            data["wind_speed"].values[keep],
            data["wind_dir"].values[keep],
            data["lat"].values[keep],
            data["lon"].values[keep],
            convention="to",  # wind_to_direction
        ),
        notes=(
            f"{len(ascat.products)} passes with bbox vs "
            f"{len(ascat.everywhere)} without, in {HOURS} h; whole orbit files"
        ),
    )

# -*- coding: utf-8 -*-
"""
Download ASCAT winds from EUMETSAT and from Copernicus Marine, and compare them.

ASCAT is the scatterometer of the Metop satellites. Its winds come from two
sources, which give the same variables (lat, lon, time, valid_time, wind_speed,
wind_dir), on different dimensions:

- EUMETSAT (EUMETSATASCATData): the OSI SAF coastal winds at 12.5 km along the
  swaths, a couple of hours after sensing. Needs EUMDAC_KEY and EUMDAC_SECRET.
- Copernicus Marine (CopernicusASCATData): the same swaths on a regular grid,
  one file per day, about a day behind, subset by the server. Needs CMEMS_USER
  and CMEMS_PWD.

ASCATData takes the first source that works, EUMETSAT then Copernicus Marine by
default, and says which in `source`. The script uses it both ways, then each
source directly, and compares the winds of both on the passes they share.

wind_dir is the direction the wind blows to (oceanographic), not the one it
comes from: add 180 deg to compare it with a weather report.

Run from the repository root, cell by cell (#%%) or as a script.

Created on Thu Nov 19 2026

@author: jrich
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from architeuthis.satellite import ASCATData, CopernicusASCATData, EUMETSATASCATData

# Bay of Biscay and its western approaches
domain = {"min_lon": -20.0, "max_lon": 0.0, "min_lat": 40.0, "max_lat": 52.0}
# domain = {"min_lon": -64.0, "max_lon": -48.5, "min_lat": 41.0, "max_lat": 51.5}  # Saint-Pierre and Newfoundland
# domain = {"min_lon": -80.0, "max_lon": 0.0, "min_lat": 30.0, "max_lat": 60.0}  # North Atlantic

# The last 36 hours: Copernicus Marine is about a day behind, so both sources
# have passes in this period
end = pd.Timestamp("now", tz="UTC").floor("1h")
start = end - pd.Timedelta(36, unit="h")
# start, end = "2026-11-17 00:00Z", "2026-11-18 00:00Z"

grid_step = 0.125  # deg, the grid of Copernicus Marine, to match both sources
max_time_gap = 30.0  # min, between the measurements of the same pass

#%% DEFAULT: EUMETSAT, ELSE COPERNICUS MARINE

# The usual way: EUMETSAT, and Copernicus Marine only if EUMETSAT fails
# (missing credentials, server errors, no product in the period...)
default = ASCATData("ascat", start=start, end=end, **domain)
default.load_data()
print(f"ASCATData took its winds from {default.source}.")

#%% COPERNICUS MARINE ONLY

cmems_only = ASCATData("ascat_cmems", start=start, end=end, sources="cmems", **domain)
# cmems_only = ASCATData("ascat_cmems", start=start, end=end, sources=["cmems", "eumetsat"], **domain)  # the other order
cmems_only.load_data()
print(f"ASCATData took its winds from {cmems_only.source}.")

#%% EACH SOURCE DIRECTLY

# The source classes take their own options: the Metop satellites, orbit
# directions and grid step of Copernicus Marine, for example
eumetsat = EUMETSATASCATData("ascat_eumetsat", start=start, end=end, **domain)
eumetsat.load_data()

cmems = CopernicusASCATData(
    "ascat_cmems",
    start=start,
    end=end,
    satellites=("metopb", "metopc"),
    orbits=("asc", "des"),
    resolution=grid_step,
    **domain,
)
# cmems = CopernicusASCATData("ascat_cmems", start=start, end=end, satellites=["metopc"], orbits=["des"], resolution=0.25, **domain)
cmems.load_data()


#%% THE SAME TABLE FROM BOTH

def observations(ascat):
    """
    The measurements of an ASCAT object, one per row, whatever its source.

    Args:
        ascat: A loaded ASCAT object.

    Returns:
        DataFrame of lat, lon, valid_time, wind_speed (m/s) and wind_dir
        (deg, where the wind goes), with the measurement time.
    """
    names = ["lat", "lon", "valid_time", "wind_speed", "wind_dir"]
    table = pd.DataFrame({name: np.asarray(ascat.data[name]).ravel() for name in names}).dropna()
    table["time"] = pd.to_datetime(table["valid_time"], unit="s")
    return table.reset_index(drop=True)


tables = {"EUMETSAT": observations(eumetsat), "Copernicus Marine": observations(cmems)}

summary = pd.DataFrame({
    name: {
        "measurements": len(table),
        "first": table["time"].min(),
        "last": table["time"].max(),
        "mean speed (m/s)": table["wind_speed"].mean(),
        "max speed (m/s)": table["wind_speed"].max(),
    }
    for name, table in tables.items()
})
print(summary.to_string())

#%% BOTH SOURCES ON THE SAME PASSES

# Copernicus Marine grids the swaths of EUMETSAT: each EUMETSAT measurement is
# matched with the grid cell it falls in, measured within max_time_gap
cells = {}
for name, table in tables.items():
    cells[name] = table.assign(
        cell_lat=np.floor(table["lat"] / grid_step).astype(int),
        cell_lon=np.floor(table["lon"] / grid_step).astype(int),
    )

pairs = cells["EUMETSAT"].merge(cells["Copernicus Marine"], on=["cell_lat", "cell_lon"], suffixes=("_eumetsat", "_cmems"))
pairs = pairs[np.abs(pairs["valid_time_eumetsat"] - pairs["valid_time_cmems"]) <= max_time_gap * 60.0]
# One pair per grid cell and pass: the EUMETSAT measurements in the cell, averaged
pairs = pairs.groupby(["cell_lat", "cell_lon", "valid_time_cmems"], as_index=False)[["wind_speed_eumetsat", "wind_speed_cmems"]].mean()

if pairs.empty:
    print("No pass in common: widen the period or the domain.")
else:
    difference = pairs["wind_speed_cmems"] - pairs["wind_speed_eumetsat"]
    print(
        f"{len(pairs)} cells measured by both: "
        f"bias {difference.mean():+.2f} m/s, RMS difference {np.sqrt((difference ** 2).mean()):.2f} m/s"
    )

#%% FIGURE

fig = plt.figure(figsize=(16, 5))
extent = [domain["min_lon"], domain["max_lon"], domain["min_lat"], domain["max_lat"]]
for column, (name, table) in enumerate(tables.items()):
    ax = fig.add_subplot(1, 3, column + 1, projection=ccrs.PlateCarree())
    points = ax.scatter(
        table["lon"], table["lat"], c=table["wind_speed"], s=2,
        vmin=0.0, vmax=25.0, cmap="viridis", transform=ccrs.PlateCarree(),
    )
    ax.coastlines(linewidth=0.5)
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    ax.set_title(f"{name}: {len(table)} measurements")
fig.colorbar(points, ax=fig.axes, shrink=0.8, label="Wind speed (m/s)")

ax = fig.add_subplot(1, 3, 3)
ax.scatter(pairs["wind_speed_eumetsat"], pairs["wind_speed_cmems"], s=4)
ax.plot([0.0, 25.0], [0.0, 25.0], color="0.5", linewidth=0.8)
ax.set_xlabel("EUMETSAT (m/s)")
ax.set_ylabel("Copernicus Marine (m/s)")
ax.set_title("Same cells, same passes")
ax.set_aspect("equal")

plt.show()

# -*- coding: utf-8 -*-
"""
Shared output of the example scripts: data, metrics and a figure.

Each example ends with `report`, which writes, in `output/`:
`<case>_<library>.nc` (the data drawn), `<case>_<library>.json` (sizes,
times) and `<case>_<library>.png` (the map with its metrics).
`compare.py` redraws them all side by side from these files, with no
download.
"""

import os
import json

import numpy as np
import xarray as xr
import matplotlib

matplotlib.use("Agg")  # files only
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(HERE, "output")

# France for the IR image, Bay of Biscay for the winds, as [N, S, W, E]
IR_NSWE = [51.5, 41.0, -5.5, 10.0]
WIND_NSWE = [52.0, 40.0, -20.0, 0.0]
RESOLUTION = 0.01  # deg, ~1 km
NO_DATA = "#e9dcc3"  # map background where there is no data


def folder_size(paths):
    """
    Total size of files, in bytes.

    Args:
        paths: Paths of files.

    Returns:
        Their total size.
    """
    return sum(os.path.getsize(path) for path in paths)


def ir_dataset(bt, latitude, longitude):
    """
    Standard IR dataset: brightness temperature on a regular grid.

    Args:
        bt: Brightness temperature, in K, on (latitude, longitude).
        latitude: Latitudes, in degrees.
        longitude: Longitudes, in degrees.

    Returns:
        Dataset with `bt`.
    """
    return xr.Dataset(
        {"bt": (("latitude", "longitude"), np.asarray(bt, dtype="float32"))},
        coords={"latitude": np.asarray(latitude), "longitude": np.asarray(longitude)},
    )


def wind_dataset(speed, direction, latitude, longitude, convention):
    """
    Standard wind dataset: scattered wind vectors.

    Args:
        speed: Wind speed, in m/s, 1D.
        direction: Wind direction, in degrees, 1D.
        latitude: Latitudes, in degrees, 1D.
        longitude: Longitudes, in degrees, 1D.
        convention: "from" (meteorological, Sentinel-1) or "to"
            (oceanographic, ASCAT `wind_to_direction`).

    Returns:
        Dataset with `u` and `v`, the components the wind goes to.
    """
    theta = np.deg2rad(np.asarray(direction) + (180 if convention == "from" else 0))
    speed = np.asarray(speed)
    return xr.Dataset({
        "u": ("point", (speed * np.sin(theta)).astype("float32")),
        "v": ("point", (speed * np.cos(theta)).astype("float32")),
        "latitude": ("point", np.asarray(latitude, dtype="float32")),
        "longitude": ("point", np.asarray(longitude, dtype="float32")),
    })


def report(
    case,
    library,
    source,
    image_time,
    downloaded,
    full_product,
    seconds,
    data,
    notes="",
):
    """
    Save the data, the metrics and the summary figure of a run.

    Args:
        case: "ir" or "wind".
        library: "eumdac", "openeo" or "phidown".
        source: Satellite and instrument.
        image_time: Time of the observation, as a string.
        downloaded: Bytes downloaded.
        full_product: Bytes of the whole products, without subsetting,
            or None if unknown.
        seconds: Wall time of the run.
        data: Dataset from `ir_dataset` or `wind_dataset`.
        notes: Free text shown on the figure.

    Returns:
        The metrics, as a dict.
    """
    metrics = {
        "case": case,
        "library": library,
        "source": source,
        "image_time": image_time,
        "downloaded_mb": downloaded / 1e6,
        "full_product_mb": None if full_product is None else full_product / 1e6,
        "seconds": seconds,
        "notes": notes,
    }
    os.makedirs(OUTPUT, exist_ok=True)
    stem = os.path.join(OUTPUT, f"{case}_{library}")
    with open(stem + ".json", "w", encoding="utf-8") as file:
        json.dump(metrics, file, indent=2)
    # h5netcdf: netCDF4 fails on Windows paths with accents
    data.to_netcdf(stem + ".nc", engine="h5netcdf")

    fig = plt.figure(figsize=(8, 6))
    ax = fig.add_axes([0.05, 0.2, 0.8, 0.7], projection=ccrs.PlateCarree())
    draw_panel(ax, metrics, data)
    fig.text(0.05, 0.03, describe(metrics), fontsize=8, family="monospace")
    fig.savefig(stem + ".png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(describe(metrics))
    print(f"Figure: {stem}.png")
    return metrics


def describe(metrics):
    """
    Metrics as a few lines of text.

    Args:
        metrics: Dict written by `report`.

    Returns:
        Text for the console and the figures.
    """
    full = metrics["full_product_mb"]
    text = f"downloaded {metrics['downloaded_mb']:.1f} MB"
    if full:
        saved = 100 * (1 - metrics["downloaded_mb"] / full)
        text += f" of {full:.0f} MB ({saved:.0f} % avoided)"
    text += f"\nwall time {metrics['seconds']:.0f} s"
    if metrics["notes"]:
        text += f"\n{metrics['notes']}"
    return text


def draw_panel(ax, metrics, data, colorbar=True):
    """
    Map of one run: data, coastlines and title.

    Args:
        ax: Cartopy axis.
        metrics: Dict written by `report`.
        data: Dataset from `ir_dataset` or `wind_dataset`.
        colorbar: Whether to add a colorbar.

    Returns:
        The mappable of the data, for a shared colorbar.
    """
    north, south, west, east = IR_NSWE if metrics["case"] == "ir" else WIND_NSWE
    ax.set_extent([west, east, south, north], crs=ccrs.PlateCarree())
    ax.patch.set_facecolor(NO_DATA)
    if metrics["case"] == "ir":
        mappable = draw_ir(ax, data)
        label = "Brightness temperature (K)"
    else:
        mappable = draw_wind(ax, data)
        label = "Wind speed (m/s)"
    ax.add_feature(cfeature.COASTLINE, linewidth=0.6, edgecolor="tab:orange")
    ax.add_feature(cfeature.BORDERS, linewidth=0.4, edgecolor="tab:orange")
    ax.set_title(
        f"{metrics['library']}: {metrics['source']}\n{metrics['image_time']}",
        fontsize=9,
    )
    if colorbar:
        plt.colorbar(mappable, ax=ax, shrink=0.7, label=label)
    return mappable


def draw_ir(ax, data):
    """
    Brightness temperature, cold cloud tops white as on IR images.

    Args:
        ax: Cartopy axis.
        data: Dataset from `ir_dataset`.

    Returns:
        The mappable.
    """
    return ax.pcolormesh(
        data["longitude"], data["latitude"], data["bt"],
        cmap="gray_r", vmin=210, vmax=295,
        transform=ccrs.PlateCarree(), shading="auto", rasterized=True,
    )


def draw_wind(ax, data, arrow_step=0.5):
    """
    Wind speed at each point, and mean wind arrows on a coarse grid.

    Args:
        ax: Cartopy axis.
        data: Dataset from `wind_dataset`.
        arrow_step: Grid step of the averaged arrows, in degrees.

    Returns:
        The mappable.
    """
    lon, lat = data["longitude"].values, data["latitude"].values
    u, v = data["u"].values, data["v"].values
    points = ax.scatter(
        lon, lat, c=np.hypot(u, v), s=1, cmap="viridis", vmin=0, vmax=25,
        transform=ccrs.PlateCarree(), rasterized=True,
    )
    north, south, west, east = WIND_NSWE
    bins = [np.arange(west, east + arrow_step, arrow_step),
            np.arange(south, north + arrow_step, arrow_step)]
    with np.errstate(invalid="ignore"):
        count = np.histogram2d(lon, lat, bins=bins)[0]
        mean_u = np.histogram2d(lon, lat, bins=bins, weights=u)[0] / count
        mean_v = np.histogram2d(lon, lat, bins=bins, weights=v)[0] / count
    cell_lon, cell_lat = np.meshgrid(
        bins[0][:-1] + arrow_step / 2, bins[1][:-1] + arrow_step / 2, indexing="ij"
    )
    ax.quiver(
        cell_lon, cell_lat, mean_u, mean_v,
        transform=ccrs.PlateCarree(), scale=500, width=0.002,
    )
    return points

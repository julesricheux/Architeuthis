# -*- coding: utf-8 -*-
"""
Side-by-side summary of the example runs, with no download.

Reads what the examples left in `output/` (`<case>_<library>.json` and
`.nc`) and draws `output/comparison.png`: one map per case and library,
then the downloaded size and the wall time of each run. A run that is
missing shows why, from `MISSING`.

Run from the repository root, after the examples:
    python temp-experimental/compare.py
"""

import os
import json

import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from summary import IR_NSWE, OUTPUT, WIND_NSWE, describe, draw_panel

LIBRARIES = ["eumdac", "openeo", "phidown"]
CASES = {"ir": "IR image, France, 1 km", "wind": "Winds, Bay of Biscay"}

# Why a run has no output, when it has none
MISSING = {
    ("ir", "eumdac"): "Meteosat imagery: 403 Unauthorised\nfor this EUMETSAT key",
    ("wind", "eumdac"): "no output: EUMETSAT 504 on the last run\n(worked earlier, see COMPARISON.md)",
    ("wind", "openeo"): "no ASCAT, nor any wind\ncollection, on CDSE openEO",
    ("wind", "phidown"): "no ASCAT in the CDSE catalogue",
}


def load(case, library):
    """
    Metrics and data of a run, if it has any.

    Args:
        case: "ir" or "wind".
        library: Library name.

    Returns:
        (metrics, data), or None.
    """
    stem = os.path.join(OUTPUT, f"{case}_{library}")
    if not os.path.exists(stem + ".json"):
        return None
    with open(stem + ".json", encoding="utf-8") as file:
        metrics = json.load(file)
    # h5netcdf: netCDF4 fails on Windows paths with accents
    with xr.open_dataset(stem + ".nc", engine="h5netcdf") as data:
        return metrics, data.load()


if __name__ == "__main__":
    runs = {(c, l): load(c, l) for c in CASES for l in LIBRARIES}

    fig = plt.figure(figsize=(18, 15))
    grid = fig.add_gridspec(3, 3, height_ratios=[1, 1, 0.7], hspace=0.35, wspace=0.05)
    for row, case in enumerate(CASES):
        mappable = None
        axes = []
        for col, library in enumerate(LIBRARIES):
            ax = fig.add_subplot(grid[row, col], projection=ccrs.PlateCarree())
            axes.append(ax)
            run = runs[(case, library)]
            if run is None:
                ax.set_title(f"{library}: not available", fontsize=9)
                reason = MISSING.get((case, library), "not run")
                ax.text(0.5, 0.5, reason, ha="center", va="center",
                        transform=ax.transAxes, fontsize=11, color="0.4")
                north, south, west, east = IR_NSWE if case == "ir" else WIND_NSWE
                ax.set_extent([west, east, south, north], crs=ccrs.PlateCarree())
                ax.coastlines(linewidth=0.4, color="0.7")
                continue
            metrics, data = run
            mappable = draw_panel(ax, metrics, data, colorbar=False)
            ax.text(0.01, -0.02, describe(metrics), transform=ax.transAxes,
                    fontsize=7, family="monospace", va="top")
        if mappable is not None:
            label = "Brightness temperature (K)" if case == "ir" else "Wind speed (m/s)"
            fig.colorbar(mappable, ax=axes, shrink=0.8, pad=0.01, label=label)
        axes[0].text(-0.08, 0.5, CASES[case], transform=axes[0].transAxes,
                     rotation=90, va="center", fontsize=12, weight="bold")

    # Sizes and times
    done = [(key, run[0]) for key, run in runs.items() if run is not None]
    names = [f"{library}\n{case}" for (case, library), _ in done]
    x = np.arange(len(done))

    ax = fig.add_subplot(grid[2, :2])
    full = [m["full_product_mb"] or np.nan for _, m in done]
    ax.bar(x - 0.2, full, 0.4, color="0.8", label="whole products")
    ax.bar(x + 0.2, [m["downloaded_mb"] for _, m in done], 0.4,
           color="tab:blue", label="downloaded")
    ax.set_yscale("log")
    ax.set_xticks(x, names)
    ax.set_ylabel("MB (log)")
    ax.set_title("Data volume (whole products unknown for openEO)")
    ax.legend()

    ax = fig.add_subplot(grid[2, 2])
    ax.bar(x, [m["seconds"] for _, m in done], color="tab:orange")
    ax.set_xticks(x, names)
    ax.set_ylabel("s")
    ax.set_title("Wall time (search + download + reading)")

    path = os.path.join(OUTPUT, "comparison.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    print(f"Figure: {path}")

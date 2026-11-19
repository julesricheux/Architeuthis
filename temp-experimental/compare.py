# -*- coding: utf-8 -*-
"""
Side-by-side summary of the example runs, with no download.

Reads what the examples left in `downloads/` (`<case>_<library>.json`
and `.nc`) and draws `output/comparison.png`: one row of maps per case
of `summary.CASES`, one map per library that ran, then the downloaded
size and the wall time of each run. A library that could not produce
a map shows why, from `MISSING`.

Run from the repository root, after the examples:
    python temp-experimental/compare.py
"""

import os
import json
import glob

import numpy as np
import xarray as xr
import matplotlib.pyplot as plt
import cartopy.crs as ccrs

from summary import CASES, DATA, OUTPUT, describe, draw_panel

# Column order: geostationary or ASCAT data, then rendered images, then
# polar-orbiting imagers
ORDER = ["eumdac", "goes2go", "cmems", "earthaccess", "eumetview", "gibs", "openeo", "phidown"]

# Runs that cannot produce a map, and why
MISSING = {
    ("wind", "earthaccess"): "search only: downloading needs\na NASA Earthdata login",
}

LABELS = {"ir": "Brightness temperature (K)", "goes": "Brightness temperature (K)",
          "wind": "Wind speed (m/s)"}


def load(case, library):
    """
    Metrics and data of a run.

    Args:
        case: Key of `summary.CASES`.
        library: Library name.

    Returns:
        (metrics, data).
    """
    stem = os.path.join(DATA, f"{case}_{library}")
    with open(stem + ".json", encoding="utf-8") as file:
        metrics = json.load(file)
    # h5netcdf: netCDF4 fails on Windows paths with accents
    with xr.open_dataset(stem + ".nc", engine="h5netcdf") as data:
        return metrics, data.load()


def libraries(case):
    """
    Libraries to show for a case: those that ran, then `MISSING`.

    Args:
        case: Key of `summary.CASES`.

    Returns:
        List of library names, in `ORDER`.
    """
    ran = {
        os.path.basename(path)[len(case) + 1:-5]
        for path in glob.glob(os.path.join(DATA, f"{case}_*.json"))
    }
    ran |= {library for c, library in MISSING if c == case}
    return sorted(ran, key=lambda l: ORDER.index(l) if l in ORDER else len(ORDER))


if __name__ == "__main__":
    rows = {case: libraries(case) for case in CASES}
    columns = max(len(names) for names in rows.values())

    fig = plt.figure(figsize=(5.2 * columns, 4.6 * len(CASES) + 3.5))
    grid = fig.add_gridspec(
        len(CASES) + 1, columns,
        height_ratios=[1] * len(CASES) + [0.75], hspace=0.4, wspace=0.08,
    )
    done = []
    for row, case in enumerate(CASES):
        title, (north, south, west, east) = CASES[case]
        mappable, axes = None, []
        for col, library in enumerate(rows[case]):
            ax = fig.add_subplot(grid[row, col], projection=ccrs.PlateCarree())
            axes.append(ax)
            if (case, library) in MISSING:
                ax.set_title(f"{library}: no map", fontsize=9)
                ax.text(0.5, 0.5, MISSING[(case, library)], ha="center", va="center",
                        transform=ax.transAxes, fontsize=10, color="0.4")
                ax.set_extent([west, east, south, north], crs=ccrs.PlateCarree())
                ax.coastlines(linewidth=0.4, color="0.7")
                continue
            metrics, data = load(case, library)
            done.append((case, library, metrics))
            mappable = draw_panel(ax, metrics, data, colorbar=False) or mappable
            ax.text(0.01, -0.03, describe(metrics), transform=ax.transAxes,
                    fontsize=7, family="monospace", va="top")
        if mappable is not None:
            fig.colorbar(mappable, ax=axes, shrink=0.8, pad=0.01, label=LABELS[case])
        axes[0].text(-0.08, 0.5, title, transform=axes[0].transAxes,
                     rotation=90, va="center", fontsize=12, weight="bold")

    # Sizes and times
    names = [f"{library}\n{case}" for case, library, _ in done]
    x = np.arange(len(done))
    split = max(1, columns * 2 // 3)

    ax = fig.add_subplot(grid[-1, :split])
    full = [m["full_product_mb"] or np.nan for *_, m in done]
    ax.bar(x - 0.2, full, 0.4, color="0.8", label="whole products")
    ax.bar(x + 0.2, [max(m["downloaded_mb"], 1e-3) for *_, m in done], 0.4,
           color="tab:blue", label="downloaded")
    ax.set_yscale("log")
    ax.set_xticks(x, names, fontsize=8)
    ax.set_ylabel("MB (log)")
    ax.set_title("Data volume (whole products unknown for subsetting services)")
    ax.legend()

    ax = fig.add_subplot(grid[-1, split:])
    ax.bar(x, [m["seconds"] for *_, m in done], color="tab:orange")
    ax.set_xticks(x, names, fontsize=8, rotation=90)
    ax.set_ylabel("s")
    ax.set_title("Wall time (search + download + reading)")

    path = os.path.join(OUTPUT, "comparison.png")
    fig.savefig(path, dpi=90, bbox_inches="tight")
    print(f"Figure: {path}")

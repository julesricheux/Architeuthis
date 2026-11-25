"""
Build the land maps of the share viewer from Natural Earth.

Writes `architeuthis/dux/data/land.json`, drawn on the whole globe, and
`land_detail.json`, drawn close up, from the 1:10m land of Natural
Earth (public domain), simplified at two tolerances. Run it from the
repository root: `python tools/make_land.py`. Cartopy downloads the
shapefile the first time.

Created on Mon Nov 23 2026

@author: jrich
"""

import json
from pathlib import Path

import numpy as np
from cartopy.io import shapereader

DATA = Path(__file__).resolve().parents[1] / "architeuthis" / "dux" / "data"

# File, simplification tolerance and quantum of the coordinates, in deg.
LEVELS = (
    ("land.json", 0.05, 0.01),
    ("land_detail.json", 0.005, 0.002),
)


def encode(ring, quantum: float) -> list:
    """
    A ring as a flat list of steps in units of `quantum`.

    Args:
        ring: Coordinates, longitude first, closed.
        quantum: Unit of the steps, in deg.

    Returns:
        Longitude and latitude steps, the first from 0, without
        repeated points.
    """
    points = np.rint(np.asarray(ring, dtype=float)[:, :2] / quantum).astype(np.int64)
    keep = np.concatenate([[True], np.any(np.diff(points, axis=0) != 0, axis=1)])
    points = points[keep]
    if len(points) < 4:
        return []
    steps = np.diff(points, axis=0, prepend=[[0, 0]])
    return steps.ravel().tolist()


def polygons(tolerance: float, quantum: float) -> list:
    """
    The land as lists of rings, simplified at `tolerance`.

    Args:
        tolerance: Simplification tolerance, in deg.
        quantum: Unit of the steps, in deg.

    Returns:
        One list of encoded rings per polygon, its outline first.
    """
    path = shapereader.natural_earth(resolution="10m", category="physical", name="land")
    result = []
    for geometry in shapereader.Reader(path).geometries():
        simple = geometry.simplify(tolerance, preserve_topology=True)
        parts = [simple] if simple.geom_type == "Polygon" else list(getattr(simple, "geoms", []))
        for polygon in parts:
            if polygon.is_empty:
                continue
            outline = encode(polygon.exterior.coords, quantum)
            if not outline:
                continue
            holes = [encode(interior.coords, quantum) for interior in polygon.interiors]
            result.append([outline] + [hole for hole in holes if hole])
    return result


def main():
    """
    Write both land files.
    """
    for name, tolerance, quantum in LEVELS:
        land = polygons(tolerance, quantum)
        description = (
            "Land of the world, one polygon per list of rings, for the offline map of the "
            f"share viewer. Natural Earth 1:10m land (public domain), simplified at {tolerance} deg "
            "by tools/make_land.py. Each ring is a flat list of longitude and latitude steps, "
            "in units of `quantum` degrees, the first step from 0."
        )
        text = json.dumps({"description": description, "quantum": quantum, "polygons": land}, separators=(",", ":"))
        (DATA / name).write_text(text, encoding="utf-8", newline="\n")
        points = sum(len(ring) // 2 for rings in land for ring in rings)
        print(f"{name}: {len(land)} polygons, {points} points, {len(text) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()

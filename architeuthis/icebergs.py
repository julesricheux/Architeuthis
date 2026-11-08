# -*- coding: utf-8 -*-
"""
Created on Mon Feb  9 14:14:45 2026

@author: jrich
"""

import os
import io
import re
import zipfile
import requests

import pandas as pd
import geopandas as gpd
from pathlib import Path

from architeuthis.common import _HOME, status


# TODO concatenate into spatial data and proper methods

# ---------------------------------------------------------------------
# PARSE TEXT BULLETIN
# ---------------------------------------------------------------------

# Helper to extract coordinate block from start keyword to first period
def extract_coord_block(text, start_phrase):
    # find start
    start_idx = text.find(start_phrase)
    if start_idx == -1:
        raise ValueError(f"Start phrase '{start_phrase}' not found")
    # find end of block (first period after start)
    end_idx = text.find('.', start_idx)
    if end_idx == -1:
        raise ValueError("No terminating period found for block")
    block_text = text[start_idx:end_idx+1]
    return block_text

# Helper to parse coordinates from block
coord_pattern = re.compile(r"(\d{1,2}-\d{2}[NS])\s+(\d{2,3}-\d{2}[EW])")
def parse_coords(block_text):
    coords = []
    for lat_str, lon_str in coord_pattern.findall(block_text):
        # Latitude
        lat_deg, lat_min = map(int, lat_str[:-1].split('-'))
        lat = lat_deg + lat_min/60.0
        if lat_str[-1] == 'S':
            lat = -lat
        # Longitude
        lon_deg, lon_min = map(int, lon_str[:-1].split('-'))
        lon = lon_deg + lon_min/60.0
        if lon_str[-1] == 'W':
            lon = -lon
        coords.append([lat, lon])
    return coords

def get_iip_zone_from_bulletin(text):
    # Extract and parse the blocks
    iceberg_block = extract_coord_block(text, "ICEBERG LIMIT ALONG TRACKLINE JOINING")
    # western_block = extract_coord_block(text, "WESTERN ICEBERG LIMIT ALONG TRACKLINE JOINING")
    
    iceberg_coords = parse_coords(iceberg_block)
    # western_coords = parse_coords(western_block)
    western_coords = [
        [iceberg_coords[-1][0], iceberg_coords[-1][1] - 10.],
        [iceberg_coords[-1][0] - 1., iceberg_coords[-1][1] - 10.],
        # [iceberg_coords[0][0], iceberg_coords[0][1] - 10.],
    ]
    
    # 5) Combine into closed polygon
    polygon = iceberg_coords + western_coords
    if polygon[0] != polygon[-1]:
        polygon.append(polygon[0])
        
    return polygon

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------

BULLETIN_URL = "https://www.navcen.uscg.gov/sites/default/files/iip/bulletin/IcebergBulletin.txt"
ZIP_URL = "https://www.navcen.uscg.gov/sites/default/files/iip/shape/currentShape.zip"
WORKDIR = Path(os.path.join(_HOME, "iip"))
BULLETIN_CACHE = WORKDIR / "IcebergBulletin.txt"

# (connect, read) timeouts in seconds: fail fast when the server is unreachable.
TIMEOUT = (10, 60)


def _age(path: Path) -> str:
    return pd.Timestamp(path.stat().st_mtime, unit="s").strftime("%d/%m/%Y %Hh%M UTC")


def get_latest_iip_zone():
    """
    Iceberg limit polygon from the latest IIP bulletin. If the server cannot be reached,
    the last downloaded bulletin is used, and an empty polygon if there is none.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        resp = requests.get(BULLETIN_URL, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        zone = get_iip_zone_from_bulletin(resp.text)
        WORKDIR.mkdir(parents=True, exist_ok=True)
        BULLETIN_CACHE.write_text(resp.text, encoding="utf-8")
        return zone
    except Exception as e:
        if BULLETIN_CACHE.exists():
            status(f"⚠️ Warning: could not fetch the latest IIP iceberg bulletin ({type(e).__name__}). "
                  f"Using the bulletin downloaded on {_age(BULLETIN_CACHE)}.")
            try:
                return get_iip_zone_from_bulletin(BULLETIN_CACHE.read_text(encoding="utf-8"))
            except Exception as cache_error:
                status(f"⚠️ Warning: the cached IIP bulletin cannot be read ({cache_error}).")
        status(f"⚠️ Warning: could not fetch the IIP iceberg bulletin ({type(e).__name__}). "
              "No iceberg exclusion zone: check the iceberg limit yourself.")
        return []


# ---------------------------------------------------------------------
# DOWNLOAD & EXTRACT
# ---------------------------------------------------------------------

def download_and_extract_zip(url: str, out_dir: Path) -> None:
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(out_dir)


# ---------------------------------------------------------------------
# LOAD ALL SHP FILES
# ---------------------------------------------------------------------


def load_all_shapefiles(base_dir: Path) -> gpd.GeoDataFrame:
    shp_files = list(base_dir.rglob("*.shp"))

    if not shp_files:
        raise FileNotFoundError("No .shp files found in extracted archive.")

    gdfs = []

    for shp in shp_files:
        parent_name = shp.parent.name.lower()

        if parent_name.startswith("blim"):
            style = {
                "color": "#00ffff",
                "weight": 2,
                "dashArray": None,
            }
            
            gdf = gpd.read_file(shp)
    
            if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
    
            gdf = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])]
    
            if gdf.empty:
                continue
    
            # Attach per-feature Leaflet style
            gdf["style"] = [style] * len(gdf)
    
            gdfs.append(gdf)
            
        elif parent_name.startswith("ilim"):
            style = {
                "color": "#00ffff",
                "weight": 2,
                "dashArray": "6,6",
            }
        
        else:
            # Explicitly ignore other folders
            continue

    if not gdfs:
        raise ValueError("No valid BLIM/ILIM polyline geometries found.")

    return gpd.GeoDataFrame(
        pd.concat(gdfs, ignore_index=True),
        crs="EPSG:4326"
    )


# ---------------------------------------------------------------------
# MAIN DATA PREP
# ---------------------------------------------------------------------

def get_berg_geojson() -> dict:
    """
    Iceberg limit lines (display only, for the UI). If the server cannot be reached, the
    last downloaded shapefiles are used, and an empty collection if there are none.
    """
    try:
        download_and_extract_zip(ZIP_URL, WORKDIR)
    except Exception as e:
        status(f"⚠️ Warning: could not download the IIP iceberg shapefiles ({type(e).__name__}). "
              "Using the last downloaded ones, if any.")

    try:
        return load_all_shapefiles(WORKDIR).__geo_interface__
    except Exception as e:
        status(f"⚠️ Warning: no IIP iceberg shapefiles available ({e}). The iceberg limit will not be drawn.")
        return {"type": "FeatureCollection", "features": []}


# ---------------------------------------------------------------------
# DATA, FETCHED ON FIRST USE
# ---------------------------------------------------------------------

_cache = {}


def iceberg_polygon() -> list:
    """Iceberg limit polygon, downloaded once per session. See `refresh`."""
    if "polygon" not in _cache:
        _cache["polygon"] = get_latest_iip_zone()
    return _cache["polygon"]


def iceberg_geojson() -> dict:
    """Iceberg limit lines, downloaded once per session. See `refresh`."""
    if "geojson" not in _cache:
        _cache["geojson"] = get_berg_geojson()
    return _cache["geojson"]


def refresh() -> None:
    """Forget the downloaded data, so that the next use fetches the latest bulletin."""
    _cache.clear()


def __getattr__(name: str):
    # polygon, berg_zone and berg_geojson remain module attributes, without any download
    # when the module is imported.
    if name in ("polygon", "berg_zone"):
        return iceberg_polygon()
    if name == "berg_geojson":
        return iceberg_geojson()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    
    from dash import Dash
    import dash_leaflet as dl
    
    # ---------------------------------------------------------------------
    # DASH APP
    # ---------------------------------------------------------------------

    app = Dash(__name__)

    app.layout = dl.Map(
        center=[55, -30],
        zoom=4,
        children=[
            dl.TileLayer(),
            dl.GeoJSON(
                id="berg-limit",
                data=iceberg_geojson(),
                # options={
                #     "style": {
                #         "color": "#00ffff",
                #         "weight": 2,
                #     }
                # },
            ),
        ],
        style={"width": "100%", "height": "100vh"},
    )


    # ---------------------------------------------------------------------
    # RUN
    # ---------------------------------------------------------------------
    
    app.run(debug=True)

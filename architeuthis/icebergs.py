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
import dash_leaflet as dl

from dash import Dash
from pathlib import Path

from architeuthis.common import _HOME


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
        [iceberg_coords[0][0], iceberg_coords[0][1] - 10.],
    ]
    
    # 5) Combine into closed polygon
    polygon = iceberg_coords + western_coords
    if polygon[0] != polygon[-1]:
        polygon.append(polygon[0])
        
    return polygon

def get_latest_iip_zone():
    # Download the iceberg bulletin
    url = "https://www.navcen.uscg.gov/sites/default/files/iip/bulletin/IcebergBulletin.txt"
    resp = requests.get(url)
    resp.raise_for_status()
    text = resp.text
    
    return get_iip_zone_from_bulletin(text)

polygon = get_latest_iip_zone()
# polygon = get_iip_zone_from_bulletin(text)


# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------

ZIP_URL = "https://www.navcen.uscg.gov/sites/default/files/iip/shape/currentShape.zip"
WORKDIR = Path(os.path.join(_HOME, "iip"))
WORKDIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------
# DOWNLOAD & EXTRACT
# ---------------------------------------------------------------------

def download_and_extract_zip(url: str, out_dir: Path) -> None:
    r = requests.get(url, timeout=60)
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

download_and_extract_zip(ZIP_URL, WORKDIR)
berg_gdf = load_all_shapefiles(WORKDIR)
berg_geojson = berg_gdf.__geo_interface__
berg_zone = polygon


if __name__ == "__main__":
    
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
                data=berg_geojson,
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

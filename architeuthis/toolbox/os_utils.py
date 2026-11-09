# -*- coding: utf-8 -*-
"""
File helpers: GPX tracks and polygons of GeoJSON files.

Created on Tue Dec 16 16:45:27 2025

@author: jrich
"""

import json
import numbers

import architeuthis.numpy as np
import xml.etree.ElementTree as ET

import pandas as pd

from datetime import datetime

#%%

def save_gpx(
    lat,
    lon,
    valid_time,
    filename,
    track_name="Track"
):
    """
    Write a track to a GPX 1.1 file.

    Args:
        lat: Latitudes in degrees.
        lon: Longitudes in degrees.
        valid_time: Times: numbers are epoch seconds, and datetime64,
            str and Timestamp values are parsed as they are.
        filename: Path of the file.
        track_name: Name of the track.

    Raises:
        ValueError: If the lengths differ or a time is invalid.
    """
    if not (len(lat) == len(lon) == len(valid_time)):
        raise ValueError("lat, lon and valid_time must have the same length")

    gpx = ET.Element(
        "gpx",
        version="1.1",
        creator="Python",
        xmlns="http://www.topografix.com/GPX/1/1"
    )

    trk = ET.SubElement(gpx, "trk")
    name = ET.SubElement(trk, "name")
    name.text = track_name

    trkseg = ET.SubElement(trk, "trkseg")

    for la, lo, t in zip(lat, lon, valid_time):
        trkpt = ET.SubElement(
            trkseg,
            "trkpt",
            lat=f"{float(la):.8f}",
            lon=f"{float(lo):.8f}"
        )
        time_el = ET.SubElement(trkpt, "time")
    
        # Numbers are epoch seconds, like every time in Architeuthis (pandas would read them
        # as nanoseconds, in 1970). datetime64, str and Timestamp are parsed as they are.
        ts = pd.to_datetime(t, unit="s") if isinstance(t, numbers.Real) else pd.to_datetime(t)
        if pd.isna(ts):
            raise ValueError(f"Invalid/NaT time value encountered: {t!r}")
        time_el.text = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    tree = ET.ElementTree(gpx)
    tree.write(filename, encoding="utf-8", xml_declaration=True)


def extract_polygons_from_geojson(geojson_path, target_ids):
    """
    Extracts coordinates as [[lat, lon], ...] grouped per specified ID.

    Args:
        geojson_path: Path to the .geojson file.
        target_ids: List of feature IDs to look for.

    Returns:
        List of lists, where each sublist belongs to one matching
        feature ID.
    """
    with open(geojson_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Index features by ID (checks both top-level 'id' and 'properties.id')
    features_by_id = {}
    for feature in data.get('features', []):
        feat_id = feature.get('id') or feature.get('properties', {}).get('id')
        if feat_id:
            features_by_id[feat_id] = feature

    result = []

    for target_id in target_ids:
        if target_id not in features_by_id:
            continue

        feature = features_by_id[target_id]
        geometry = feature.get('geometry', {})
        geom_type = geometry.get('type')
        coords = geometry.get('coordinates', [])

        raw_coords = []
        if geom_type == "Point":
            raw_coords = [coords]
        elif geom_type in ("LineString", "MultiPoint"):
            raw_coords = coords
        elif geom_type in ("Polygon", "MultiLineString"):
            for ring in coords:
                raw_coords.extend(ring)
        elif geom_type == "MultiPolygon":
            for polygon in coords:
                for ring in polygon:
                    raw_coords.extend(ring)

        # Convert GeoJSON [lon, lat] to [lat, lon]
        id_lat_lons = [[pt[1], pt[0]] for pt in raw_coords if len(pt) >= 2]

        if id_lat_lons:
            result.append(id_lat_lons)

    return result
# -*- coding: utf-8 -*-
"""
Created on Tue Dec 16 16:45:27 2025

@author: jrich
"""

import json

import architeuthis.numpy as np
import xml.etree.ElementTree as ET

from datetime import datetime

#%%

def save_gpx(
    lat,
    lon,
    valid_time,
    filename,
    track_name="Track"
):
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

        # Robust time handling
        if isinstance(t, np.datetime64):
            t = t.astype("datetime64[ms]").astype(datetime)
        elif isinstance(t, str):
            t = datetime.fromisoformat(t)

        time_el.text = t.strftime("%Y-%m-%dT%H:%M:%SZ")

    tree = ET.ElementTree(gpx)
    tree.write(filename, encoding="utf-8", xml_declaration=True)


def extract_polygons_from_geojson(geojson_path, target_ids):
    """
    Extracts coordinates as [[lat, lon], ...] grouped per specified ID.
    
    :param geojson_path: Path to the .geojson file
    :param target_ids: List of feature IDs to look for
    :return: List of lists, where each sublist belongs to one matching feature ID
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
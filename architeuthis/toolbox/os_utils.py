# -*- coding: utf-8 -*-
"""
Created on Tue Dec 16 16:45:27 2025

@author: jrich
"""

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
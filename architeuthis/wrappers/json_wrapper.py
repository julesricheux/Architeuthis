# -*- coding: utf-8 -*-
"""
GeoJSON of route reports, for the map of the UI.

Importing it writes `assets/dashExtensions_default.js` to the working
directory.

Created on Sun Jan 25 21:54:43 2026

@author: jules
"""

import pandas as pd

from dash_extensions.javascript import assign

# The JSON codec lives in toolbox.json_utils, without Dash; it stays importable from here.
from architeuthis.toolbox.json_utils import CustomEncoder, custom_decoder  # noqa: F401


def route_to_geojson(route: dict, valid_time: float | None = None, color: str = "#ffffff") -> dict:
    """
    A route report as GeoJSON, for the map of the UI.

    It holds the line of the route and one point per segment center,
    with a tooltip of the conditions there. The point at `valid_time` is
    a larger arrow along the course.

    Args:
        route: The report, which also needs `init_fac`.
        valid_time: Time of the position shown, in epoch seconds.
        color: Color of the line and of the current position.

    Returns:
        A GeoJSON FeatureCollection, as a dict.
    """
    lat = route["lat"]
    lon = route["lon"]
    ctim = route["ctim"]
    clat = route["clat"]
    clon = route["clon"]
    cog = route["cog"]
    sog = route["sog"]
    cog = route["cog"]
    tws = route["tws"]
    twa = route["twa"]
    swh = route["swh"]
    mwa = route["mwa"]
    avg_bhp = route["avg_bhp"]
    max_bhp = route["max_bhp"]
    sc = route["sails_contribution"]
    fuel = route["fuel"]
    member = route["member"]
    
    model = route['model']
    fac= route['init_fac']
    vessel = str(route['vessel']).removeprefix("eff")

    line_feature = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[lo, la] for lo, la in zip(lon, lat)]},
        "properties": {"kind": "route", "color": color, "weight": 3, "opacity": 1.0},
    }
    line_bg = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[lo, la] for lo, la in zip(lon, lat)]},
        "properties": {"kind": "route", "color": "#ffffff", "weight": 4, "opacity": 0.85},
    }

    point_features = []
    for i, (cla, clo, cogi, ctimi) in enumerate(zip(clat, clon, cog, ctim)):
        is_nav_point = (ctimi == valid_time)
        point_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [clo, cla]},
            "properties": {
                "kind": "waypoint",
                "index": i,
                "icon": "material-symbols:navigation-rounded" if is_nav_point else "material-symbols:circle-outline",
                "opacity": 1.0 if is_nav_point else 0.85,
                "size": 40 if is_nav_point else 9,
                # "color": color if is_nav_point else "#ffffff",
                "color": "#ffffff",
                "angle": cogi,
                "tooltip": (
                    f"{pd.to_datetime(ctimi, unit='s').strftime('%Y-%m-%dT%H:%M')}<br>"
                    # f"Colloc. pt. {i}<br>"
                    # f"Lat: {cla:.3f}, Lon: {clo:.3f}<br>"
                    f"{model} / {fac} / {vessel} / m{member}<br>"
                    f"SOG {sog[i]:.1f} / COG {cog[i]:.0f}<br>"
                    f"TWS {tws[i]:.1f} / TWA {twa[i]:.0f}<br>"
                    f"SWH {swh[i]:.1f} / MWA {mwa[i]:.0f}<br>"
                    f"BHP {avg_bhp[i]:.1f} / MAX {max_bhp[i]:.0f}<br>"
                    f"Sails contribution {sc[i]:.1f} %<br>"
                    f"Fuel: {fuel:.2f} t"
                ),
            },
        })
        if is_nav_point:
            point_features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [clo, cla]},
                "properties": {
                    "kind": "waypoint",
                    "index": i,
                    "icon": "material-symbols:navigation-rounded" if is_nav_point else "material-symbols:circle",
                    "opacity": 1.0 if is_nav_point else 0.85,
                    "size": 32 if is_nav_point else 8,
                    "color": color,
                    "angle": cogi,
                },
            })

    return {"type": "FeatureCollection", "features": [line_bg] + [line_feature] + point_features}


# --- Javascript helpers ---
point_to_layer = assign("""
function(feature, latlng){
    const size  = feature.properties.size  || 0;
    const color = feature.properties.color || "#ff0000";
    const angle = feature.properties.angle || 0;
    const opacity = feature.properties.opacity || 0.80;
    const icon = feature.properties.icon ||  "material-symbols:circle";
    const html = `<span class="iconify"
        data-icon=${icon}
        data-width="${size}"
        data-height="${size}"
        style="
        transform: rotate(${angle}deg);
        color: ${color};
        display: block;
        opacity: ${opacity};
        ">
    </span>`;
    return L.marker(latlng, {
        icon: L.divIcon({html: html, className: "", iconSize: [size, size], iconAnchor: [size/2, size/2]})
    });
}
""")

style_func = assign("""
function(feature){
    if (feature.properties.kind === "route") {
        return {
            color: feature.properties.color || "#ff0000",
            weight: feature.properties.weight || 2,
            opacity: feature.properties.opacity || 0.80,
        };
    }
    return {};
}
""")

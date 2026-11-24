# -*- coding: utf-8 -*-
"""
Self-contained HTML viewer of routes and forecasts, to share them.

`share_routes` writes one HTML file holding the chosen routes, the
forecast layers of the voyage, the exclusion zones and a land map, with
a globe, a timeline and a layers panel. It opens in any browser without
a server, so it can be sent by email or copied to a ship, and works
offline. `ui.py` previews the same page and downloads it.

The globe is drawn by MapLibre GL JS, downloaded once to
`~/data/viewer/` and inlined in each file. When it cannot be
downloaded, the file loads it from a CDN instead, and then needs a
connection when it is opened.

Forecast fields are stored as PNG frames of 8-bit values, a few kB
each: 255 marks missing values (land for waves), and each quantity has
its own offset and scale. The page interpolates them in space and time.

Example:
    >>> from architeuthis.report import ReportCollection
    >>> from architeuthis.dux.share import share_routes
    >>> reports = ReportCollection.latest()
    >>> share_routes(
    ...     reports.select(solve=1),
    ...     forecasts={"IFS": [atmosphere, wave]},
    ...     variables=["sog", "tws", "twa", "swh"],
    ...     title="Saint-Nazaire to Baltimore",
    ... )
"""

from __future__ import annotations

import base64
import html
import io
import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Optional, Sequence

import numpy as np
import pandas as pd
import requests
import xarray as xr
from PIL import Image

from architeuthis import sky
from architeuthis.common import _HOME, status
from architeuthis.toolbox.windy_colormaps import (
    CLOUD_RAIN_HOURS,
    CLOUD_RAIN_STOPS,
    DEFAULT_FIELD_COLORMAP,
    FIELD_COLORMAPS,
    PRECIPITATION_TYPES,
    get_field_cmap,
)


MAPLIBRE_VERSION = "5.24.0"
MAPLIBRE_URLS = (
    "https://unpkg.com/maplibre-gl@{version}/dist/{name}",
    "https://cdn.jsdelivr.net/npm/maplibre-gl@{version}/dist/{name}",
)
# The JavaScript and stylesheet of MapLibre, and a text that each holds.
MAPLIBRE_FILES = {"js": ("maplibre-gl.js", "maplibregl"), "css": ("maplibre-gl.css", ".maplibregl-map")}

VIEWER_DIRECTORY = os.path.join(_HOME, "viewer")
SHARED_DIRECTORY = os.path.join(_HOME, "shared")

_DATA = Path(__file__).parent / "data"
_TEMPLATES = _DATA / "viewer"

KNOTS_PER_MS = 1.0 / 0.514444

DEFAULT_RESOLUTION = 0.5  # deg, grid of the forecast frames
DEFAULT_MARGIN = 10.0  # deg of forecast kept around the routes
DEFAULT_TIME_MARGIN = 12 * 3600.0  # s of forecast kept before and after
MAX_GRID_CELLS = 60_000  # the grid is thinned further above this size
NO_DATA = 255

# Herbie and Copernicus forecasts end with two fake steps, 1e6 s and 1e7 s
# after the last real one (forecast.py): any later gap this long is one.
PADDING_GAP = 0.999e6

# Per-segment report entries: label, unit, decimals and description.
VARIABLES = {
    "sog": ("SOG", "kt", 1, "Speed over ground"),
    "stw": ("STW", "kt", 1, "Speed through water"),
    "cog": ("COG", "°", 0, "Course over ground"),
    "ctw": ("CTW", "°", 0, "Course through water"),
    "tws": ("TWS", "kt", 1, "True wind speed"),
    "twd": ("TWD", "°", 0, "True wind direction, coming from"),
    "twa": ("TWA", "°", 0, "True wind angle"),
    "tws_gust": ("Gust", "kt", 1, "True wind gust"),
    "aws": ("AWS", "kt", 1, "Apparent wind speed"),
    "awa": ("AWA", "°", 0, "Apparent wind angle"),
    "aws_gust": ("App. gust", "kt", 1, "Apparent wind gust"),
    "swh": ("Hs", "m", 1, "Significant wave height"),
    "mwd": ("MWD", "°", 0, "Mean wave direction, coming from"),
    "mwa": ("MWA", "°", 0, "Mean wave angle"),
    "cs": ("Current", "kt", 1, "Current speed"),
    "cd": ("Current dir.", "°", 0, "Current direction, going to"),
    "bhp": ("BHP", "kW", 0, "Brake power"),
    "max_bhp": ("Max BHP", "kW", 0, "Maximum brake power"),
    "total_power": ("Power", "kW", 0, "Total power"),
    "hotel_load": ("Hotel load", "kW", 0, "Hotel load"),
    "sfoc": ("SFOC", "g/kWh", 0, "Specific fuel oil consumption"),
    "hourly_consumption": ("Consumption", "L/h", 0, "Fuel consumption"),
    "sails_contribution": ("Sails", "%", 0, "Contribution of the sails"),
    "z": ("Land", "nm", 1, "Distance to land or an exclusion zone, negative at sea: the largest on the segment"),
}

# Entries sampled more finely than the segments, shown by their largest
# value on a segment rather than their mean: the worst point.
SEGMENT_MAXIMA = {"z"}

# Entries sampled between the interior nodes only, as the topography of
# `RoutingAnalysis`, rather than between all of them.
INTERIOR_SAMPLED = {"z"}

# Shown in the tooltips by default, when the reports have them.
DEFAULT_VARIABLES = (
    "sog",
    "cog",
    "tws",
    "twa",
    "swh",
    "mwa",
    "bhp",
    "hourly_consumption",
    "sails_contribution",
)

# Drawn in the plots of the page, beside the map, when a report has them:
# speeds, sails, power and consumption, wind and waves along the route.
PLOT_VARIABLES = (
    "sog",
    "stw",
    "sails_contribution",
    "hotel_load",
    "bhp",
    "total_power",
    "max_bhp",
    "hourly_consumption",
    "tws",
    "tws_gust",
    "aws",
    "aws_gust",
    "swh",
)

# The pressure of a report, under the first of these names, in Pa or hPa:
# the `msl` or `prmsl` of an atmosphere listed in the routing `variables`.
PRESSURE_NAMES = ("pressure", "msl", "prmsl", "mslp")

# The sky along a route, as stored in the scene: entry of the scene, entry
# of `sky.diagnose` or of its fields in the report, and decimals.
SKY_ENTRIES = (
    ("lcc", "lcc", 2),
    ("mcc", "mcc", 2),
    ("hcc", "hcc", 2),
    ("cape", "cape", 0),
    ("prate", "prate", 2),
    ("t2m", "t2m", 1),
    ("base", "cloud_base", 0),
    ("oktas", "cloud_oktas", 0),
    ("low", "cloud_low", 0),
    ("middle", "cloud_middle", 0),
    ("high", "cloud_high", 0),
    ("low_genera", "cloud_low_genera", 0),
    ("middle_genera", "cloud_middle_genera", 0),
    ("high_genera", "cloud_high_genera", 0),
    ("fog", "fog", 0),
)

# Route colours, chosen to stand out on the wind and wave scales.
ROUTE_COLORS = (
    "#ffd60a",
    "#ff4d6d",
    "#4cc9f0",
    "#80ffdb",
    "#ff9e00",
    "#e0aaff",
    "#f1faee",
    "#b5e48c",
    "#ff70a6",
    "#70d6ff",
)

# Entries of a report that are geometry, not tooltip variables.
_GEOMETRY = {"tim", "lat", "lon", "pos", "ctim", "clat", "clon", "cpos"}

# Quantities of the built-in layers, in the order they are packed three by
# three. The other fields follow, as quantities named after their layer.
QUANTITIES = (
    "wind_u",
    "wind_v",
    "pressure",
    "swh",
    "wave_x",
    "wave_y",
    "current_u",
    "current_v",
    "gust",
)

# Built-in map layers and the quantities each one needs.
LAYER_QUANTITIES = {
    "wind": ("wind_u", "wind_v"),
    "gust": ("gust",),
    "waves": ("swh", "wave_x", "wave_y"),
    "current": ("current_u", "current_v"),
    "pressure": ("pressure",),
}

# Arrows drawn over a layer, and the quantities they need: a layer brings
# those of its arrows into the file.
ARROW_QUANTITIES = {
    "wind": ("wind_u", "wind_v"),
    "waves": ("swh", "wave_x", "wave_y"),
    "current": ("current_u", "current_v"),
}

GRAVITY = 9.80665  # m/s2


def _kelvin_to_celsius(values):
    return values - 273.15


def _rate_to_mm_per_hour(values):
    return values * 3600.0  # kg m-2 s-1 > mm/h


def _cover_to_percent(values):
    # IFS gives covers from 0 to 1, GFS in %.
    units = str(values.attrs.get("units", values.attrs.get("GRIB_units", ""))).strip()
    if units == "%" or float(values.max(skipna=True).fillna(0.0)) > 1.0 + 1e-6:
        return values
    return values * 100.0


# Fields shown besides the built-in layers, by layer, found under the
# first of `names` that a forecast has: label, unit, conversion to that
# unit, colour scale (`windy_colormaps.FIELD_COLORMAPS`) or categories,
# ticks, decimals, values under which nothing is drawn (`floor`), and
# arrows drawn with it. `slope` is computed from the waves and their
# period. Any other field of a forecast is shown in its own units, on a
# scale of its values, and so are the `add_function` models of a
# `Forecast` of time and position.
FIELDS = {
    "period": {
        "names": ("mwp", "mp2", "pp1d", "perpw"),
        "label": "Wave period",
        "unit": "s",
        "description": "Mean wave period",
        "colormap": FIELD_COLORMAPS["period"],
        "ticks": [0, 4, 8, 12, 16],
        "digits": 1,
        "arrows": "waves",
    },
    "slope": {
        "names": (),
        "label": "Wave slope",
        "unit": "%",
        "description": "Wave steepness, 2 pi Hs / (g T2), from the height and period",
        "colormap": FIELD_COLORMAPS["slope"],
        "ticks": [0, 2, 4, 6, 8],
        "digits": 1,
        "arrows": "waves",
    },
    "temperature": {
        "names": ("t2m",),
        "label": "Temperature",
        "unit": "°C",
        "description": "Air temperature at 2 m",
        "convert": _kelvin_to_celsius,
        "colormap": FIELD_COLORMAPS["temperature"],
        "ticks": [-20, -10, 0, 10, 20, 30],
        "digits": 0,
        "arrows": "wind",
    },
    "cape": {
        "names": ("mucape", "cape"),
        "label": "CAPE",
        "unit": "J/kg",
        "description": "Convective available potential energy",
        "colormap": FIELD_COLORMAPS["cape"],
        "ticks": [0, 500, 1000, 2000, 3000],
        "digits": 0,
        "floor": 50.0,
        "arrows": "wind",
    },
    "precipitation": {
        "names": ("tprate", "prate"),
        "label": "Precipitation",
        "unit": "mm/h",
        "description": "Precipitation rate",
        "convert": _rate_to_mm_per_hour,
        "colormap": FIELD_COLORMAPS["precipitation"],
        "ticks": [0, 1, 2, 5, 10],
        "digits": 1,
        "floor": 0.1,
        "arrows": "wind",
    },
    "ptype": {
        "names": ("ptype",),
        "label": "Precipitation type",
        "unit": "",
        "description": "Precipitation type",
        "categories": PRECIPITATION_TYPES,
        "digits": 0,
        "arrows": "wind",
    },
    "clouds": {
        "names": ("tcc",),
        "label": "Clouds",
        "unit": "%",
        "description": "Total cloud cover, with the precipitation over it",
        "convert": _cover_to_percent,
        "colormap": FIELD_COLORMAPS["clouds"],
        "ticks": [0, 25, 50, 75, 100],
        "digits": 0,
        "arrows": "wind",
    },
}

# The Clouds layer of a forecast with a total cloud cover: the covers by
# étage are part of it, never layers of their own, and the precipitation
# rate, when the forecast has one, is drawn over it as on Windy, in mm per
# `CLOUD_RAIN_HOURS` on the steps of `CLOUD_RAIN_STOPS`, from `floor`.
CLOUD_NAMES = ("tcc", "lcc", "mcc", "hcc")
CLOUD_RAIN = {
    "quantity": "precipitation",
    "hours": CLOUD_RAIN_HOURS,
    "unit": f"mm/{CLOUD_RAIN_HOURS:g}h",
    "floor": 0.2,
    "stops": [[value, colour] for value, colour in CLOUD_RAIN_STOPS],
}

# Names of forecast variables that the built-in layers may read.
_WIND_NAMES = (("u10", "v10"), ("si10", "wdir10"))
_GUST_NAMES = ("gust", "i10fg", "fg10")
_PRESSURE_NAMES = ("msl", "prmsl")
_WAVE_DIRECTION_NAMES = ("mwd", "dirpw")
# Wave components of `Forecast.add_wave_components`, not fields of their own.
_WAVE_COMPONENTS = ("uw", "vw")

# The quantities each built-in layer colours, which it needs to be shown.
_LAYER_COLOURS = {
    "wind": ("wind_u", "wind_v"),
    "gust": ("gust",),
    "waves": ("swh",),
    "current": ("current_u", "current_v"),
    "pressure": ("pressure",),
}

# Label and arrows of the built-in layers; `_layers` gives the rest.
_BUILT_IN_LAYERS = {
    "wind": ("Wind", "wind"),
    "gust": ("Gusts", "wind"),
    "waves": ("Waves", "waves"),
    "current": ("Current", "current"),
    "pressure": ("Pressure", None),
}


def segment_variables(report: Mapping) -> list:
    """
    The entries of a report that tooltips can show, by segment.

    These are its numeric arrays with one value per segment, per node,
    or sampled evenly between nodes, as the topography `z`, other than
    the positions and times of the route. `segment_values` gives their
    value on each segment.

    Args:
        report: A routing report.

    Returns:
        Their names, in the order of the report.
    """
    return [key for key in report if key not in _GEOMETRY and segment_values(report, key) is not None]


def segment_values(report: Mapping, name: str) -> Optional[np.ndarray]:
    """
    The value of a report entry on each segment of the route.

    An entry per segment is kept. An entry per node, or sampled evenly
    between the nodes (the interior ones only for the entries of
    `INTERIOR_SAMPLED`, such as the topography `z`), takes the samples
    of each segment, ends included: their mean, or their largest value
    for the entries of `SEGMENT_MAXIMA`, such as `z`.

    Args:
        report: A routing report.
        name: Name of the entry.

    Returns:
        One value per segment, or None for an entry of another shape.
    """
    value = report.get(name)
    if value is None or isinstance(value, (str, bytes)) or np.isscalar(value):
        return None
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    count = np.ravel(report["ctim"]).size
    if array.ndim != 1 or count == 0:
        return None
    if array.size == count:
        return array

    # Position of each sample in node intervals: the nodes are 0 to count.
    size = array.size
    if name in INTERIOR_SAMPLED:
        if count <= 2 or size < 2 or (size - 1) % (count - 2):
            return None
        positions = 1.0 + np.arange(size) * (count - 2) / (size - 1)
    elif size > 1 and (size - 1) % count == 0:
        positions = np.arange(size) * count / (size - 1)
    else:
        return None
    reduce = np.nanmax if name in SEGMENT_MAXIMA else np.nanmean
    values = np.full(count, np.nan)
    for k in range(count):
        inside = array[(positions >= k - 1e-9) & (positions <= k + 1 + 1e-9)]
        if np.isfinite(inside).any():
            values[k] = reduce(inside)
    return values


def route_label(report: Mapping) -> str:
    """
    A short name for a route, from its tags.

    It holds the model, the vessel, the member and initial deviation
    when they are not 0, and marks reference routes as baselines.

    Args:
        report: A routing report.

    Returns:
        The label, such as `IFS eff60` or `GFS eff45 (baseline)`.
    """
    parts = []
    if report.get("model"):
        parts.append(str(report["model"]).upper())
    if report.get("vessel"):
        parts.append(str(report["vessel"]))
    if report.get("member") not in (None, 0):
        parts.append(f"m{report['member']}")
    if report.get("init_fac") not in (None, 0):
        parts.append(f"init {float(report['init_fac']):+g}")
    label = " ".join(parts) or "route"
    if report.get("solve") is not None and not report.get("solve"):
        label += " (baseline)"
    return label


def route_labels(reports: Sequence[Mapping]) -> list:
    """
    The `route_label` of each report, numbered where they repeat.

    Args:
        reports: Routing reports.
    """
    return _unique_labels([route_label(report) for report in reports])


def default_variables(reports: Sequence[Mapping]) -> list:
    """
    The variables shown in the tooltips by default.

    These are those of `DEFAULT_VARIABLES` that a report has.

    Args:
        reports: Routing reports.
    """
    available = set().union(*(segment_variables(report) for report in reports)) if reports else set()
    return [name for name in DEFAULT_VARIABLES if name in available]


def build_scene(
    reports: Sequence[Mapping],
    forecasts: Optional[Mapping] = None,
    routes: Optional[Sequence[int]] = None,
    variables: Optional[Sequence[str]] = None,
    labels: Optional[Sequence[str]] = None,
    comments: Optional[Mapping] = None,
    zones: Sequence = (),
    overlays: Sequence[Mapping] = (),
    title: Optional[str] = None,
    note: str = "",
    settings: Optional[Mapping] = None,
    member: Optional[int] = None,
    fields: Optional[Sequence[str]] = None,
    resolution: float = DEFAULT_RESOLUTION,
    margin: float = DEFAULT_MARGIN,
    time_margin: float = DEFAULT_TIME_MARGIN,
) -> dict:
    """
    Everything the viewer shows, as a dict that can be written as JSON.

    Args:
        reports: Routing reports, such as a `ReportCollection`.
        forecasts: Forecast layers by label, such as
            `{"IFS": [atmosphere, wave]}`. Each value is a `Forecast`,
            an `xarray.Dataset` or a list of them, the others then
            interpolated on the grid of the first. The built-in layers
            read `u10` and `v10` (or `si10` and `wdir10`), `gust`,
            `msl` (or `prmsl`), `swh` with `mwd` (or `dirpw`), `uo` and
            `vo`; `FIELDS` gives other known fields, and any other
            field, or `add_function` model of a `Forecast`, is a layer
            of its own (`forecast_fields`).
        routes: Indices of the reports to include, all by default. A
            route keeps its index as identifier, `r<index>`, and its
            colour.
        variables: Per-segment entries shown in the tooltips, in this
            order; `default_variables` by default. Only these are
            stored, with `cog` and, for the plots beside the map, the
            `PLOT_VARIABLES` that the reports have, their pressure
            (`PRESSURE_NAMES`) and their sky (`route_sky`).
        labels: One name per report, `route_label` by default.
        comments: The analyst's notes on the routes, by report index:
            `{index: {"description": text, "points": {segment: text}}}`,
            or a description alone as text. A point is a segment of
            the route, the index of its centre in `ctim`. A report's
            own `description` entry is used when none is given.
        zones: Exclusion zones, `ExclusionZone` or `[lat, lon]` lists.
        overlays: Images drawn over the map, dicts with `label`, `url`
            (an address or data URI), `bounds` (`[[lat, lon], [lat,
            lon]]`), and optionally `visible`, `opacity` and `time`,
            the valid time of a chart (epoch seconds or a date), to
            which the timeline goes when it is shown.
        title: Title of the page, by default with today's date.
        note: Message shown under the title, for the crew.
        settings: Initial selection of `ui.py`: `routes`, `sources`,
            `overlays` and `fields` (identifiers shown) and `hover`
            (variables shown), None, the default for each, showing
            everything; `theme`, `"dark"` (default) or `"light"`.
        member: Ensemble member of the forecasts, the first by default.
        fields: Layers of the forecasts to put in the file, such as
            `["wind", "waves", "period"]`, all by default. A layer
            brings the fields of its arrows: wave arrows with `period`.
        resolution: Grid spacing of the forecast frames, in deg.
        margin: Forecast kept around the routes, in deg.
        time_margin: Forecast kept before and after the routes, in s.

    Returns:
        The scene, as read by `viewer_html`.
    """
    reports = list(reports)
    indices = list(range(len(reports))) if routes is None else [int(index) for index in routes]
    included = [reports[index] for index in indices]

    if variables is None:
        variables = default_variables(included)
    variables = list(dict.fromkeys(variables))
    known = set().union(*(segment_variables(report) for report in included)) if included else set()
    missing = [name for name in variables if name not in known]
    if included and missing:
        status(f"⚠️ No route has {', '.join(missing)}: left out of the tooltips.")
    variables = [name for name in variables if name in known]

    names = _unique_labels(labels) if labels is not None else route_labels(reports)
    scene_routes = [
        _route(
            reports[index],
            route_id=f"r{index}",
            label=names[index],
            color=ROUTE_COLORS[index % len(ROUTE_COLORS)],
            variables=variables,
            comments=_comments(
                reports[index],
                next((comments[key] for key in (index, str(index), f"r{index}") if key in (comments or {})), None),
            ),
        )
        for index in indices
    ]

    box = _route_box(included, margin)
    window = _route_window(included, time_margin)
    sources = []
    extra_layers = {}
    for label, forecast in (forecasts or {}).items():
        source = _forecast_source(
            forecast,
            label=str(label),
            box=box,
            window=window,
            member=member,
            resolution=resolution,
            fields=fields,
        )
        if source is not None:
            source["id"] = _unique_id(_slug(label), [other["id"] for other in sources])
            for layer, info in source.pop("fields").items():
                extra_layers[layer] = _merge_ranges(extra_layers.get(layer), info)
            sources.append(source)

    if title is None:
        title = f"Routes of {datetime.now(timezone.utc):%d %b %Y}"

    extra = {}
    if any("sky" in scene_route for scene_route in scene_routes):
        extra["cloud_genera"] = [
            {"abbreviation": genus["abbreviation"], "name": genus["name"], "etage": genus["etage"]}
            for genus in sky.load_genera()["genera"]
        ]

    return {
        "version": 1,
        "title": str(title),
        "note": str(note or ""),
        "created": round(datetime.now(timezone.utc).timestamp()),
        "settings": {
            "routes": None,
            "sources": None,
            "overlays": None,
            "hover": None,
            "fields": None,
            **dict(settings or {}),
        },
        "variables": {name: variable_info(name) for name in variables},
        "routes": scene_routes,
        "sources": sources,
        "layers": _layers(extra_layers),
        "zones": [_zone(zone, index) for index, zone in enumerate(zones)],
        "overlays": [_overlay(overlay, index) for index, overlay in enumerate(overlays)],
        "land": land(),
        "credits": ", ".join(source["label"] for source in sources),
        **extra,
    }


def viewer_html(scene: Mapping, library: str = "inline") -> str:
    """
    The page of the viewer, holding a scene.

    Args:
        scene: As given by `build_scene`.
        library: `"inline"` to put MapLibre in the page, so that it
            opens offline, or `"cdn"` to load it from a CDN. `"inline"`
            falls back to `"cdn"` when MapLibre cannot be downloaded.

    Returns:
        The HTML text.
    """
    if library not in ("inline", "cdn"):
        raise ValueError(f"library should be 'inline' or 'cdn', not {library!r}.")

    files = maplibre_files() if library == "inline" else None
    if files is not None:
        maplibre_css = f"<style>{files['css']}</style>"
        maplibre_js = f"<script>{_script(files['js'])}</script>"
    else:
        maplibre_css = f'<link rel="stylesheet" href="{_maplibre_url("css")}">'
        maplibre_js = f'<script src="{_maplibre_url("js")}"></script>'

    parts = {
        "TITLE": html.escape(str(scene.get("title", "Architeuthis"))),
        "MAPLIBRE_CSS": maplibre_css,
        "VIEWER_CSS": f"<style>{_template('viewer.css')}</style>",
        "SCENE": json.dumps(scene, separators=(",", ":"), allow_nan=False).replace("</", "<\\/"),
        "MAPLIBRE_JS": maplibre_js,
        "VIEWER_JS": f"<script>{_script(_template('viewer.js'))}</script>",
    }
    return re.sub(r"<!--@(\w+)@-->", lambda match: parts[match.group(1)], _template("viewer.html"))


def share_routes(
    reports: Sequence[Mapping],
    path: Optional[str] = None,
    library: str = "inline",
    verbose: bool = True,
    **options,
) -> str:
    """
    Write the viewer of some routes as one HTML file.

    Args:
        reports: Routing reports, such as a `ReportCollection`.
        path: File to write, by default `~/data/shared/<title>.html`.
        library: How the page gets MapLibre; see `viewer_html`.
        verbose: Whether to report the file written.
        **options: Options of `build_scene`, such as `forecasts`,
            `variables`, `zones`, `title` and `note`.

    Returns:
        The path of the file.

    Example:
        >>> share_routes(reports, forecasts={"GFS": gfs}, note="North")
    """
    scene = build_scene(reports, **options)
    if path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        path = os.path.join(SHARED_DIRECTORY, f"{_slug(scene['title'])}_{stamp}.html")

    text = viewer_html(scene, library=library)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)

    if verbose:
        size = len(text.encode("utf-8")) / 1e6
        status(f"➕ {len(scene['routes'])} routes shared in {path} ({size:.1f} MB).")
    return path


def maplibre_files(download: bool = True) -> Optional[dict]:
    """
    The JavaScript and stylesheet of MapLibre GL JS, as texts.

    They are kept in `~/data/viewer/` and downloaded there on first
    use.

    Args:
        download: Whether to download them when they are not there.

    Returns:
        `{"js": ..., "css": ...}`, or None when they are not available.
    """
    folder = Path(VIEWER_DIRECTORY)
    files = {}
    for kind, (name, marker) in MAPLIBRE_FILES.items():
        path = folder / name.replace("maplibre-gl", f"maplibre-gl-{MAPLIBRE_VERSION}")
        if not path.exists():
            if not download:
                return None
            text = _download_maplibre(kind)
            if text is None:
                return None
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        files[kind] = path.read_text(encoding="utf-8")
    return files


@lru_cache(maxsize=1)
def land() -> dict:
    """
    The land of the world, for the offline map of the viewer.

    Natural Earth 1:10m land at two levels, built by
    `tools/make_land.py`: simplified at 0.05 deg for the whole globe,
    and at 0.005 deg under `detail`, which the page reads once it is
    shown and draws close up.

    Returns:
        A dict with `quantum`, the unit in deg, `polygons`: lists of
        rings, each a flat list of longitude and latitude steps, and
        `detail`, the finer land in the same form.
    """
    levels = []
    for name in ("land.json", "land_detail.json"):
        with open(_DATA / name, encoding="utf-8") as file:
            data = json.load(file)
        levels.append({"quantum": data["quantum"], "polygons": data["polygons"]})
    return levels[0] | {"detail": levels[1]}


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def _route(
    report: Mapping,
    route_id: str,
    label: str,
    color: str,
    variables: Sequence[str],
    comments: Optional[Mapping] = None,
) -> dict:
    """
    One route of the scene, with its tooltip variables and comments.
    """
    comments = comments or {"description": "", "points": []}
    values = {}
    for name in variables:
        segments = segment_values(report, name)
        if segments is not None:
            values[name] = _numbers(segments, variable_info(name)["digits"] + 1)
    series = {}
    for name in PLOT_VARIABLES:
        segments = segment_values(report, name)
        if segments is not None:
            series[name] = _numbers(segments, variable_info(name)["digits"] + 1)
    pressure = route_pressure(report)
    if pressure is not None:
        series["pressure"] = _numbers(pressure, 1)
    z = report.get("z")
    summary = {
        "model": _plain(report.get("model")),
        "vessel": _plain(report.get("vessel")),
        "member": _plain(report.get("member")),
        "solve": _plain(report.get("solve")),
        "status": _plain(report.get("status")),
        "fuel": _number(report.get("fuel"), 2),
        "distance": _number(report.get("dist"), 1),
        "sog": _number(report.get("transit_sog", np.nanmean(np.ravel(report["sog"]))), 2),
        "max_z": None if z is None else _number(np.nanmax(np.ravel(z)), 1),
    }
    sky_values = route_sky(report)
    tim = np.ravel(report["tim"])
    return {
        "id": route_id,
        "label": label,
        "color": color,
        "etd": _number(report.get("etd", tim[0]), 0),
        "eta": _number(report.get("eta", tim[-1]), 0),
        "summary": summary,
        "tim": _numbers(tim, 0),
        "lat": _numbers(report["lat"], 4),
        "lon": _numbers(report["lon"], 4),
        "ctim": _numbers(report["ctim"], 0),
        "clat": _numbers(report["clat"], 4),
        "clon": _numbers(report["clon"], 4),
        "cog": _numbers(report["cog"], 1),
        "values": values,
        "series": series,
        **({"sky": sky_values} if sky_values is not None else {}),
        "description": comments["description"],
        "comments": [
            {"k": k, "text": text}
            for k, text in comments["points"]
            if 0 <= k < np.ravel(report["ctim"]).size
        ],
    }


def _comments(report: Mapping, given) -> dict:
    """
    The description of a route and its comments on points, cleaned.

    Points are given by segment index, as `int` or text, and empty
    texts are left out.
    """
    if isinstance(given, str):
        given = {"description": given}
    given = dict(given or {})
    description = given.get("description")
    if description is None:
        description = report.get("description") if isinstance(report.get("description"), str) else ""
    points = []
    for k, text in dict(given.get("points") or {}).items():
        text = str(text or "").strip()
        if text:
            points.append((int(k), text))
    return {"description": str(description).strip(), "points": sorted(points)}


def variable_info(name: str) -> dict:
    """
    The label, unit, decimals and description of a tooltip variable.

    A name of several words, such as `air_temperature`, is written out
    when it has no entry in `VARIABLES`.

    Args:
        name: Name of the report entry.

    Returns:
        A dict with `label`, `unit`, `digits` and `description`.
    """
    text = name.replace("_", " ").capitalize() if "_" in name else name
    label, unit, digits, description = VARIABLES.get(name, (text, "", 2, text))
    return {"label": label, "unit": unit, "digits": digits, "description": description}


def _unique_labels(labels: Sequence[str]) -> list:
    """
    The labels, numbered where they repeat.
    """
    labels = [str(label) for label in labels]
    seen = {}
    unique = []
    for label in labels:
        seen[label] = seen.get(label, 0) + 1
        unique.append(label if labels.count(label) == 1 else f"{label} #{seen[label]}")
    return unique


def _route_box(reports: Sequence[Mapping], margin: float) -> Optional[tuple]:
    """
    South, north, west and east limits of the routes, with a margin.
    """
    if not reports:
        return None
    lat = np.concatenate([np.ravel(report["lat"]) for report in reports])
    lon = np.concatenate([np.ravel(report["lon"]) for report in reports])
    return (
        float(np.nanmin(lat)) - margin,
        float(np.nanmax(lat)) + margin,
        float(np.nanmin(lon)) - margin,
        float(np.nanmax(lon)) + margin,
    )


def _route_window(reports: Sequence[Mapping], time_margin: float) -> Optional[tuple]:
    """
    First departure and last arrival of the routes, with a margin.
    """
    if not reports:
        return None
    tim = np.concatenate([np.ravel(report["tim"]) for report in reports])
    return float(np.nanmin(tim)) - time_margin, float(np.nanmax(tim)) + time_margin


# --------------------------------------------------------------------------
# Forecasts
# --------------------------------------------------------------------------


def forecast_fields(forecasts: Mapping, member: Optional[int] = None) -> dict:
    """
    The layers that some forecasts can show, and their labels.

    Args:
        forecasts: Forecasts by label, as for `build_scene`.
        member: Ensemble member, the first by default.

    Returns:
        `{layer: label}`, the built-in layers first, then the others in
        the order the forecasts give them, such as
        `{"wind": "Wind", "waves": "Waves", "period": "Wave period"}`.
    """
    found = {}
    for forecast in forecasts.values():
        dataset = _dataset(forecast, member)
        dataset = dataset.isel(valid_time=slice(0, 1), latitude=slice(0, 2), longitude=slice(0, 2))
        dataset = dataset.assign(_model_fields(forecast, dataset))
        quantities, extras = _fields(dataset)
        for layer in _available_layers(quantities, extras):
            label = _BUILT_IN_LAYERS[layer][0] if layer in _BUILT_IN_LAYERS else extras[layer]["label"]
            found.setdefault(layer, label)
    built_in = [layer for layer in _BUILT_IN_LAYERS if layer in found]
    return {layer: found[layer] for layer in built_in + [layer for layer in found if layer not in built_in]}


def route_sky(report: Mapping) -> Optional[dict]:
    """
    The sky along a route, from the nine fields of its report.

    A routing gives them when its `variables` list "clouds" (the
    nine `sky.SKY_VARIABLES` of its atmosphere).
    They are diagnosed by `sky.diagnose` at the centre of each segment:
    cloud covers, genera, base and oktas, with the CAPE, precipitation
    and temperature, as the cloud plot of the page draws them.

    Args:
        report: A routing report.

    Returns:
        Lists keyed as `SKY_ENTRIES`, one value per segment, None where
        a field is missing; or None when the report lacks a field.

    Example:
        >>> analysis.run(variables=["clouds"])  # doctest: +SKIP
        >>> route_sky(analysis.report)["oktas"]  # doctest: +SKIP
    """
    fields = {}
    for key in sky.SKY_VARIABLES:
        values = segment_values(report, key)
        if values is None:
            return None
        fields[key] = np.asarray(values, dtype=float)
    inside = np.logical_and.reduce([np.isfinite(values) for values in fields.values()])
    found = fields | sky.diagnose({key: np.nan_to_num(values) for key, values in fields.items()})
    return {
        entry: [
            _number(value, digits) if ok else None
            for value, ok in zip(np.ravel(np.asarray(found[key], dtype=float)), inside)
        ]
        for entry, key, digits in SKY_ENTRIES
    }


def route_pressure(report: Mapping) -> Optional[np.ndarray]:
    """
    The pressure along a route in hPa, from its report.

    Args:
        report: A routing report, with an entry of `PRESSURE_NAMES` in
            Pa or hPa, such as the `msl` of its atmosphere listed in the
            routing `variables`.

    Returns:
        The pressure at the centre of each segment, or None.
    """
    for name in PRESSURE_NAMES:
        values = segment_values(report, name)
        if values is not None:
            values = np.asarray(values, dtype=float)
            # Pa rather than hPa.
            return values / 100.0 if np.nanmedian(values) > 2000.0 else values
    return None


def _forecast_source(
    forecast,
    label: str,
    box: Optional[tuple],
    window: Optional[tuple],
    member: Optional[int],
    resolution: float,
    fields: Optional[Sequence[str]] = None,
) -> Optional[dict]:
    """
    The frames of a forecast around the routes, or None without fields.

    The source holds `fields`, the description of its layers other than
    the built-in ones, which `build_scene` takes out.
    """
    dataset = _dataset(forecast, member)
    times = _times(dataset)
    keep = _window_indices(times, window)
    dataset = dataset.isel(valid_time=keep)
    times = times[keep]
    dataset = _crop(dataset, box)
    dataset = _thin(dataset, resolution)
    dataset = dataset.assign(_model_fields(forecast, dataset))

    quantities, extras = _fields(dataset)
    layers = _available_layers(quantities, extras)
    if not layers:
        status(f"⚠️ Forecast {label}: no field to show among {sorted(dataset.data_vars)}.")
        return None
    if fields is not None:
        layers = [layer for layer in layers if layer in fields]
        if not layers:
            return None

    latitude = dataset["latitude"].to_numpy().astype(float)
    longitude = dataset["longitude"].to_numpy().astype(float)
    if latitude.size < 2 or longitude.size < 2:
        status(f"⚠️ Forecast {label}: fewer than two points in a direction, left out.")
        return None

    # The quantities of the layers and of their arrows, built-in ones first.
    needed = []
    for layer in layers:
        arrows = _BUILT_IN_LAYERS[layer][1] if layer in _BUILT_IN_LAYERS else extras[layer]["arrows"]
        rain = (extras[layer]["rain"]["quantity"],) if "rain" in extras.get(layer, {}) else ()
        for name in (*LAYER_QUANTITIES.get(layer, (layer,)), *rain, *ARROW_QUANTITIES.get(arrows, ())):
            if name in quantities and name not in needed:
                needed.append(name)
    needed.sort(key=lambda name: QUANTITIES.index(name) if name in QUANTITIES else len(QUANTITIES))

    stored = {}
    arrays = {}
    for name in needed:
        values = quantities[name].transpose("valid_time", "latitude", "longitude").to_numpy().astype(float)
        categorical = "categories" in extras.get(name, {})
        arrays[name], offset, scale = _quantize(values, exact=categorical)
        stored[name] = {"offset": round(offset, 6), "scale": round(scale, 8)}
        if categorical:
            stored[name]["categorical"] = True
        elif name in extras and extras[name].get("range") is None:
            finite = values[np.isfinite(values)]
            extras[name]["data_range"] = (
                [float(np.percentile(finite, 2)), float(np.percentile(finite, 98))] if finite.size else [0.0, 1.0]
            )

    names = list(arrays)
    packs = []
    for start in range(0, len(names), 3):
        group = names[start:start + 3]
        frames = []
        for step in range(times.size):
            pixels = np.zeros((latitude.size, longitude.size, 3), dtype=np.uint8)
            for channel, name in enumerate(group):
                pixels[..., channel] = arrays[name][step]
            frames.append(_png(pixels))
        packs.append({"quantities": group, "frames": frames})

    return {
        "id": _slug(label),
        "label": label,
        "grid": {
            "lat0": round(float(latitude[0]), 6),
            "dlat": round(float(latitude[1] - latitude[0]), 6),
            "nlat": int(latitude.size),
            "lon0": round(float(longitude[0]), 6),
            "dlon": round(float(longitude[1] - longitude[0]), 6),
            "nlon": int(longitude.size),
        },
        "times": [int(round(time)) for time in times],
        "quantities": stored,
        "packs": packs,
        "layers": layers,
        "fields": {layer: extras[layer] for layer in layers if layer in extras},
    }


def _available_layers(quantities: Mapping, extras: Mapping) -> list:
    """
    The layers a forecast can show: built-in ones, then the others.

    A built-in layer needs the quantities it colours: the wind its two
    components and the waves their height.
    """
    built_in = [layer for layer, needs in _LAYER_COLOURS.items() if set(needs) <= set(quantities)]
    return built_in + list(extras)


def _model_fields(forecast, dataset: xr.Dataset) -> dict:
    """
    The `add_function` models of the forecasts, on a dataset's grid.

    Only the models of time and position that are not fields of the
    dataset are evaluated; one that fails is left out with a warning.
    """
    from architeuthis.common import FORECAST_KEYS, FunctionModel

    items = forecast if isinstance(forecast, (list, tuple)) else [forecast]
    models = [
        (item, key)
        for item in items
        for key, model in (getattr(item, "models", None) or {}).items()
        if isinstance(model, FunctionModel)
        and key not in dataset.data_vars
        and set(model.input_names()) <= set(FORECAST_KEYS)
    ]
    if not models:
        return {}
    time, latitude, longitude = (dataset[name].to_numpy().astype(float) for name in FORECAST_KEYS)
    grids = np.meshgrid(time, latitude, longitude, indexing="ij")
    query = dict(zip(FORECAST_KEYS, (grid.ravel() for grid in grids)))
    found = {}
    for item, key in models:
        if key in found:
            continue
        try:
            values = np.asarray(item(key, query), dtype=float).reshape(grids[0].shape)
        # A model may fail on the grid in any way: it is then only left out.
        except Exception as error:  # noqa: BLE001
            status(f"⚠️ {key} of {getattr(item, 'name', 'a forecast')} cannot be shown: {error}")
            continue
        found[key] = (("valid_time", "latitude", "longitude"), values)
    return found


def _dataset(forecast, member: Optional[int] = None) -> xr.Dataset:
    """
    A forecast as a dataset on `valid_time`, `latitude`, `longitude`.

    Lists are merged on the grid and times of their first item.
    Times are in epoch seconds and coordinates sorted.
    """
    if isinstance(forecast, (list, tuple)):
        datasets = [_dataset(item, member) for item in forecast]
        reference = datasets[0]
        others = [
            dataset.interp(
                valid_time=reference["valid_time"],
                latitude=reference["latitude"],
                longitude=reference["longitude"],
            )
            for dataset in datasets[1:]
        ]
        return xr.merge([reference, *others], compat="override", join="left")

    data = forecast if isinstance(forecast, xr.Dataset) else getattr(forecast, "data", None)
    if not isinstance(data, xr.Dataset):
        raise TypeError(f"A forecast should be a Forecast or an xarray.Dataset, not {type(forecast).__name__}.")

    renames = {"lat": "latitude", "lon": "longitude"}
    if "valid_time" not in data.dims and "time" in data.dims:
        renames["time"] = "valid_time"
    data = data.rename({old: new for old, new in renames.items() if old in data.dims or old in data.coords})

    for dimension in ("number", "member"):
        if dimension in data.dims:
            values = data[dimension].to_numpy() if dimension in data.coords else []
            if member is not None and member in values:
                data = data.sel({dimension: member})
            else:
                data = data.isel({dimension: 0})

    for dimension in ("valid_time", "latitude", "longitude"):
        if dimension not in data.dims:
            raise ValueError(f"A forecast needs a {dimension} dimension, got {tuple(data.dims)}.")
    extra = [dimension for dimension in data.dims if dimension not in ("valid_time", "latitude", "longitude")]
    data = data.isel({dimension: 0 for dimension in extra})

    time = data["valid_time"].to_numpy()
    if np.issubdtype(time.dtype, np.datetime64):
        data = data.assign_coords(valid_time=(time - np.datetime64(0, "s")) / np.timedelta64(1, "s"))
    data = data.assign_coords(longitude=((data["longitude"] + 180.0) % 360.0) - 180.0)
    return data.sortby(["valid_time", "latitude", "longitude"])


def _fields(dataset: xr.Dataset) -> tuple:
    """
    The quantities of the viewer in a dataset, and its other layers.

    Speeds are in kt, pressures in hPa and wave heights in m. Wave
    directions are unit vectors towards where the waves come from.
    Every other field of time and position is a layer of its own, a
    quantity of the same name: those of `FIELDS` in their units, the
    others in theirs.

    Returns:
        The quantities, `{name: DataArray}`, and the description of the
        other layers, `{layer: dict}`, in the order of the dataset.
    """
    names = [name for name in dataset.data_vars if set(dataset[name].dims) == {"valid_time", "latitude", "longitude"}]
    used = set(_WAVE_COMPONENTS)
    found = {}

    def first(candidates):
        return next((name for name in candidates if name in names), None)

    for u_name, v_name in _WIND_NAMES:
        if {u_name, v_name} <= set(names):
            if u_name == "u10":
                found["wind_u"] = dataset["u10"] * KNOTS_PER_MS
                found["wind_v"] = dataset["v10"] * KNOTS_PER_MS
            else:
                speed = dataset["si10"] * KNOTS_PER_MS
                found["wind_u"] = -speed * np.sin(np.radians(dataset["wdir10"]))
                found["wind_v"] = -speed * np.cos(np.radians(dataset["wdir10"]))
            used |= {u_name, v_name}
            break
    name = first(_GUST_NAMES)
    if name:
        found["gust"] = dataset[name] * KNOTS_PER_MS
        used.add(name)
    name = first(_PRESSURE_NAMES)
    if name:
        found["pressure"] = dataset[name] / 100.0
        used.add(name)
    if "swh" in names:
        found["swh"] = dataset["swh"]
        used.add("swh")
        name = first(_WAVE_DIRECTION_NAMES)
        if name:
            found["wave_x"] = np.sin(np.radians(dataset[name]))
            found["wave_y"] = np.cos(np.radians(dataset[name]))
            used.add(name)
    if {"uo", "vo"} <= set(names):
        found["current_u"] = dataset["uo"] * KNOTS_PER_MS
        found["current_v"] = dataset["vo"] * KNOTS_PER_MS
        used |= {"uo", "vo"}

    # Known fields, then the others, each at the place of its first name.
    order = {name: index for index, name in enumerate(names)}
    extras = {}
    position = {}
    for layer, info in FIELDS.items():
        name = first(info["names"])
        if name is None:
            continue
        convert = info.get("convert")
        found[layer] = convert(dataset[name]) if convert else dataset[name]
        extras[layer] = _field_info(info)
        position[layer] = order[name]
        used.add(name)
    if "clouds" in extras:
        used |= set(CLOUD_NAMES)
        if "precipitation" in found:
            extras["clouds"]["rain"] = dict(CLOUD_RAIN)
    period = first(FIELDS["period"]["names"])
    if "swh" in names and period:
        # The steepness of the waves: their height over their deep water length.
        slope = 100.0 * 2.0 * np.pi * dataset["swh"] / (GRAVITY * dataset[period] ** 2)
        found["slope"] = slope.where(np.isfinite(slope))
        extras["slope"] = _field_info(FIELDS["slope"])
        position["slope"] = order[period] + 0.5

    taken = set(QUANTITIES) | set(LAYER_QUANTITIES) | set(found)
    for name in names:
        if name in used:
            continue
        layer = _unique_id(_slug(name).replace("-", "_"), taken)
        taken.add(layer)
        attrs = dataset[name].attrs
        text = name.replace("_", " ").capitalize() if "_" in name else name
        label = str(attrs.get("GRIB_name") or attrs.get("long_name") or text)
        found[layer] = dataset[name]
        extras[layer] = {
            "label": label,
            "unit": str(attrs.get("GRIB_units") or attrs.get("units") or ""),
            "description": label,
            "colormap": DEFAULT_FIELD_COLORMAP,
            "range": None,
            "ticks": None,
            "digits": None,
            "floor": None,
            "arrows": None,
        }
        position[layer] = order[name]
    return found, dict(sorted(extras.items(), key=lambda item: position[item[0]]))


def _field_info(info: Mapping) -> dict:
    """
    The description of a layer of `FIELDS`, without its names.
    """
    described = {
        "label": info["label"],
        "unit": info["unit"],
        "description": info.get("description", info["label"]),
        "digits": info.get("digits"),
        "floor": info.get("floor"),
        "arrows": info.get("arrows"),
    }
    if "categories" in info:
        described["categories"] = info["categories"]
    else:
        colormap, low, high = info["colormap"]
        described.update(colormap=colormap, range=[low, high], ticks=info.get("ticks"))
    return described


def _merge_ranges(first: Optional[dict], second: dict) -> dict:
    """
    A layer described by two sources, over both their ranges.
    """
    if first is None:
        return dict(second)
    merged = dict(first)
    if "rain" in second and "rain" not in merged:
        merged["rain"] = second["rain"]
    if "data_range" in second:
        low, high = second["data_range"]
        if "data_range" in first:
            low, high = min(low, first["data_range"][0]), max(high, first["data_range"][1])
        merged["data_range"] = [low, high]
    return merged


def _times(dataset: xr.Dataset) -> np.ndarray:
    """
    The real times of a forecast, without its fake final steps.
    """
    times = dataset["valid_time"].to_numpy().astype(float)
    count = times.size
    while count > 1 and times[count - 1] - times[count - 2] >= PADDING_GAP:
        count -= 1
    return times[:count]


def _window_indices(times: np.ndarray, window: Optional[tuple]) -> np.ndarray:
    """
    Indices of the times within a window, with one more on each side.

    All of them when the window is None or holds none of them.
    """
    every = np.arange(times.size)
    if window is None:
        return every
    inside = np.flatnonzero((times >= window[0]) & (times <= window[1]))
    if inside.size == 0:
        return every
    return every[max(inside[0] - 1, 0):min(inside[-1] + 2, times.size)]


def _crop(dataset: xr.Dataset, box: Optional[tuple]) -> xr.Dataset:
    """
    The part of a dataset inside a box, or all of it outside.
    """
    if box is None:
        return dataset
    south, north, west, east = box
    cropped = dataset.sel(latitude=slice(south, north), longitude=slice(west, east))
    if cropped.sizes["latitude"] < 2 or cropped.sizes["longitude"] < 2:
        return dataset
    return cropped


def _thin(dataset: xr.Dataset, resolution: float) -> xr.Dataset:
    """
    A dataset on a regular grid of about `resolution` deg.

    It keeps one point in n, more when the grid would be too large.
    An irregular grid is first interpolated on a regular one.
    """
    for name in ("latitude", "longitude"):
        values = dataset[name].to_numpy().astype(float)
        if values.size > 2:
            steps = np.diff(values)
            if not np.allclose(steps, steps[0], rtol=1e-3, atol=1e-6):
                dataset = dataset.interp({name: np.linspace(values[0], values[-1], values.size)})

    latitude = dataset["latitude"].to_numpy()
    native = abs(float(latitude[1] - latitude[0])) if latitude.size > 1 else resolution
    stride = max(1, int(round(resolution / native))) if native > 0 else 1
    while (
        -(-dataset.sizes["latitude"] // stride) * -(-dataset.sizes["longitude"] // stride) > MAX_GRID_CELLS
    ):
        stride += 1
    return dataset.isel(latitude=slice(None, None, stride), longitude=slice(None, None, stride))


def _quantize(values: np.ndarray, exact: bool = False) -> tuple:
    """
    Values as bytes, with the offset and scale to read them back.

    The value of byte b is `offset + scale * b`; 255 marks NaN.
    Integers spanning fewer than 255 values, such as categories, are
    kept exactly, with a scale of 1; `exact` rounds values to integers
    first.
    """
    values = np.asarray(values, dtype=float)
    if exact:
        values = np.round(values)
    finite = np.isfinite(values)
    if finite.any():
        low = float(values[finite].min())
        high = float(values[finite].max())
    else:
        low = high = 0.0
    integers = bool(finite.any()) and bool(np.all(values[finite] == np.round(values[finite]))) and high - low < NO_DATA
    scale = 1.0 if integers or not high > low else (high - low) / (NO_DATA - 1)
    data = np.full(values.shape, NO_DATA, dtype=np.uint8)
    data[finite] = np.clip(np.round((values[finite] - low) / scale), 0, NO_DATA - 1)
    return data, low, scale


def _png(pixels: np.ndarray) -> str:
    """
    An RGB array as a PNG data URI.
    """
    buffer = io.BytesIO()
    Image.fromarray(pixels, mode="RGB").save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _hex_scale(colour, low: float, high: float, count: int = 96) -> list:
    """
    A colour function sampled from low to high, as hexadecimal colours.
    """
    return [
        "#{:02x}{:02x}{:02x}".format(*(int(round(255 * channel)) for channel in colour(value)[:3]))
        for value in np.linspace(low, high, count)
    ]


def _layers(extras: Optional[Mapping] = None) -> dict:
    """
    Label, unit, colour scale, legend and arrows of each map layer.

    A layer colours a `quantity`, or the norm of a `vector` of two, and
    draws the arrows of `ARROW_QUANTITIES` it names, if any. The
    built-in layers come first, then the others of the sources
    (`extras`): on the scale of `FIELDS`, or on one over most values of
    the sources, or in categories.
    """
    from matplotlib.ticker import MaxNLocator

    from architeuthis.toolbox.windy_colormaps import get_wave_cmap, get_wind_cmap, named_cmap

    wind, wind_norm = get_wind_cmap()
    wave, wave_norm = get_wave_cmap()
    wind_colours = _hex_scale(lambda kt: wind(wind_norm(kt / KNOTS_PER_MS)), 0.0, 70.0)
    current, current_norm = get_field_cmap("current")
    pressure, pressure_norm = get_field_cmap("pressure")
    layers = {
        "wind": {
            "colormap": {"min": 0.0, "max": 70.0, "colors": wind_colours},
            "ticks": [0, 10, 20, 30, 40, 50, 60],
            "unit": "kt",
            "digits": 0,
            "description": "Wind at 10 m",
            "vector": ["wind_u", "wind_v"],
        },
        "gust": {
            "colormap": {"min": 0.0, "max": 70.0, "colors": wind_colours},
            "ticks": [0, 10, 20, 30, 40, 50, 60],
            "unit": "kt",
            "digits": 0,
            "description": "Wind gusts at 10 m",
            "quantity": "gust",
        },
        "waves": {
            "colormap": {"min": 0.0, "max": 12.0, "colors": _hex_scale(lambda m: wave(wave_norm(m)), 0.0, 12.0)},
            "ticks": [0, 1, 2, 3, 4, 6, 8, 10],
            "unit": "m",
            "digits": 1,
            "description": "Significant wave height",
            "quantity": "swh",
        },
        "current": {
            "colormap": {
                "min": 0.0,
                "max": 3.0,
                "colors": _hex_scale(lambda kt: current(current_norm(kt)), 0.0, 3.0),
            },
            "ticks": [0, 0.5, 1, 1.5, 2, 2.5],
            "unit": "kt",
            "digits": 1,
            "description": "Surface current",
            "vector": ["current_u", "current_v"],
        },
        "pressure": {
            "colormap": {
                "min": 960.0,
                "max": 1050.0,
                "colors": _hex_scale(lambda hpa: pressure(pressure_norm(hpa)), 960.0, 1050.0),
            },
            "ticks": [960, 980, 1000, 1020, 1040],
            "unit": "hPa",
            "digits": 0,
            "description": "Mean sea level pressure",
            "quantity": "pressure",
        },
    }
    for layer, (label, arrows) in _BUILT_IN_LAYERS.items():
        layers[layer] = {"label": label, **layers[layer], "arrows": arrows}

    for layer, info in (extras or {}).items():
        entry = {
            "label": info["label"],
            "unit": info["unit"],
            "description": info["description"],
            "quantity": layer,
            "arrows": info["arrows"],
        }
        if info.get("floor") is not None:
            entry["floor"] = info["floor"]
        if "rain" in info:
            entry["rain"] = info["rain"]
        if "categories" in info:
            entry["digits"] = 0
            entry["categories"] = [
                {"value": int(value), "label": label, "color": color}
                for value, (label, color) in info["categories"].items()
            ]
            layers[layer] = entry
            continue
        low, high = info.get("range") or info.get("data_range") or [0.0, 1.0]
        if not high > low:
            low, high = low - 0.5, low + 0.5
        ticks = info.get("ticks")
        if not ticks:
            ticks = [float(tick) for tick in MaxNLocator(5).tick_values(low, high) if low <= tick <= high]
            ticks = [int(tick) if tick == int(tick) else round(tick, 6) for tick in ticks]
        digits = info.get("digits")
        if digits is None:
            span = high - low
            digits = 0 if span >= 50 else 1 if span >= 5 else 2 if span >= 0.5 else 3
        colour = named_cmap(info["colormap"])
        entry.update(
            colormap={
                "min": round(float(low), 6),
                "max": round(float(high), 6),
                "colors": _hex_scale(lambda value: colour((value - low) / (high - low)), low, high),
            },
            ticks=ticks,
            digits=int(digits),
        )
        layers[layer] = entry
    return layers


# --------------------------------------------------------------------------
# Zones and overlays
# --------------------------------------------------------------------------


def _zone(zone, index: int) -> dict:
    """
    An exclusion zone of the scene, with its outline as `[lon, lat]`.
    """
    outline = getattr(zone, "outline", zone)
    return {
        "id": f"z{index}",
        "label": str(getattr(zone, "label", f"Zone {index + 1}")),
        "color": str(getattr(zone, "color", "#ff4040")),
        "visible": bool(getattr(zone, "visible", True)),
        "outline": [[round(float(lon), 4), round(float(lat), 4)] for lat, lon in outline],
    }


def _overlay(overlay: Mapping, index: int) -> dict:
    """
    An image drawn over the map, between two corners.
    """
    (lat_a, lon_a), (lat_b, lon_b) = overlay["bounds"]
    return {
        "id": f"o{index}",
        "label": str(overlay.get("label", f"Overlay {index + 1}")),
        "url": str(overlay["url"]),
        "north": float(max(lat_a, lat_b)),
        "south": float(min(lat_a, lat_b)),
        "west": float(min(lon_a, lon_b)),
        "east": float(max(lon_a, lon_b)),
        "visible": bool(overlay.get("visible", False)),
        "opacity": float(overlay.get("opacity", 0.9)),
        "time": _epoch(overlay.get("time")),
    }


def _epoch(value) -> Optional[float]:
    """
    A time as epoch seconds: a number, a date or None.
    """
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return float(timestamp.timestamp())


def png_data_uri(content: bytes) -> str:
    """
    PNG bytes as a data URI, for the `url` of an overlay.

    Args:
        content: The PNG file.
    """
    return "data:image/png;base64," + base64.b64encode(content).decode("ascii")


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _template(name: str) -> str:
    """
    A file of the viewer template.
    """
    return (_TEMPLATES / name).read_text(encoding="utf-8")


def _script(text: str) -> str:
    """
    JavaScript that can be put in a script element.
    """
    return text.replace("</script", "<\\/script")


def _maplibre_url(kind: str) -> str:
    """
    The CDN address of the MapLibre JavaScript or stylesheet.
    """
    return MAPLIBRE_URLS[0].format(version=MAPLIBRE_VERSION, name=MAPLIBRE_FILES[kind][0])


def _download_maplibre(kind: str) -> Optional[str]:
    """
    The MapLibre JavaScript or stylesheet from a CDN, or None.
    """
    name, marker = MAPLIBRE_FILES[kind]
    status(f"⬇️ Downloading MapLibre GL JS {MAPLIBRE_VERSION} ({name}) to {VIEWER_DIRECTORY}.")
    for url in MAPLIBRE_URLS:
        try:
            response = requests.get(url.format(version=MAPLIBRE_VERSION, name=name), timeout=(10, 60))
            response.raise_for_status()
            text = response.content.decode("utf-8")
        # Any failure, a missing network or an unexpected answer, leaves the CDN fallback.
        except Exception:  # noqa: BLE001
            continue
        if marker in text:
            return text
    status(
        "⚠️ MapLibre GL JS could not be downloaded: shared pages will load it "
        "from a CDN, and need a connection when opened."
    )
    return None


# --------------------------------------------------------------------------
# JSON values
# --------------------------------------------------------------------------


def _plain(value):
    """
    A tag as a JSON value: numbers, strings, booleans and None.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return _number(value, 6)
    return str(value)


def _number(value, digits: int):
    """
    A number rounded for JSON, None when missing or not finite.
    """
    if value is None:
        return None
    value = float(value)
    if not np.isfinite(value):
        return None
    value = round(value, digits)
    return int(value) if digits <= 0 else value


def _numbers(values, digits: int) -> list:
    """
    An array rounded for JSON, with None for values not finite.
    """
    return [_number(value, digits) for value in np.ravel(np.asarray(values, dtype=float))]


def _slug(text) -> str:
    """
    A text reduced to letters, digits, dashes and underscores.
    """
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text)).strip("-").lower()
    return slug or "share"


def _unique_id(identifier: str, taken: Sequence[str]) -> str:
    """
    An identifier, numbered if it is already taken.
    """
    candidate, number = identifier, 2
    while candidate in taken:
        candidate = f"{identifier}-{number}"
        number += 1
    return candidate

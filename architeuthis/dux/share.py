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

from architeuthis.common import _HOME, status


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
    "hourly_consumption": ("Consumption", "kg/h", 0, "Fuel consumption"),
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

# Quantities of the frames, in the order they are packed three by three.
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

# Map layers and the quantities each one needs.
LAYER_QUANTITIES = {
    "wind": ("wind_u", "wind_v"),
    "gust": ("gust",),
    "waves": ("swh",),
    "current": ("current_u", "current_v"),
    "pressure": ("pressure",),
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
            interpolated on the grid of the first. Recognized fields
            are `u10` and `v10` (or `si10` and `wdir10`), `gust`, `msl`
            (or `prmsl`), `swh` with `mwd` (or `dirpw`), `uo` and `vo`.
        routes: Indices of the reports to include, all by default. A
            route keeps its index as identifier, `r<index>`, and its
            colour.
        variables: Per-segment entries shown in the tooltips, in this
            order; `default_variables` by default. Only these are
            stored, with `cog`.
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
        settings: Initial selection of `ui.py`: `routes`, `sources` and
            `overlays` (identifiers shown) and `hover` (variables
            shown), None, the default for each, showing everything;
            `theme`, `"dark"` (default) or `"light"`.
        member: Ensemble member of the forecasts, the first by default.
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
    for label, forecast in (forecasts or {}).items():
        source = _forecast_source(
            forecast,
            label=str(label),
            box=box,
            window=window,
            member=member,
            resolution=resolution,
        )
        if source is not None:
            source["id"] = _unique_id(_slug(label), [other["id"] for other in sources])
            sources.append(source)

    if title is None:
        title = f"Routes of {datetime.now(timezone.utc):%d %b %Y}"

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
            **dict(settings or {}),
        },
        "variables": {name: variable_info(name) for name in variables},
        "routes": scene_routes,
        "sources": sources,
        "layers": _layers(),
        "zones": [_zone(zone, index) for index, zone in enumerate(zones)],
        "overlays": [_overlay(overlay, index) for index, overlay in enumerate(overlays)],
        "land": land(),
        "credits": ", ".join(source["label"] for source in sources),
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

    Returns:
        A dict with `quantum`, the unit in deg, and `polygons`: lists
        of rings, each a flat list of longitude and latitude steps.
    """
    with open(_DATA / "land.json", encoding="utf-8") as file:
        data = json.load(file)
    return {"quantum": data["quantum"], "polygons": data["polygons"]}


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


def _forecast_source(
    forecast,
    label: str,
    box: Optional[tuple],
    window: Optional[tuple],
    member: Optional[int],
    resolution: float,
) -> Optional[dict]:
    """
    The frames of a forecast around the routes, or None without fields.
    """
    dataset = _dataset(forecast, member)
    times = _times(dataset)
    keep = _window_indices(times, window)
    dataset = dataset.isel(valid_time=keep)
    times = times[keep]
    dataset = _crop(dataset, box)
    dataset = _thin(dataset, resolution)

    quantities = _quantities(dataset)
    if not quantities:
        status(f"⚠️ Forecast {label}: no field to show among {sorted(dataset.data_vars)}.")
        return None

    latitude = dataset["latitude"].to_numpy().astype(float)
    longitude = dataset["longitude"].to_numpy().astype(float)
    if latitude.size < 2 or longitude.size < 2:
        status(f"⚠️ Forecast {label}: fewer than two points in a direction, left out.")
        return None

    stored = {}
    arrays = {}
    for name in QUANTITIES:
        if name in quantities:
            values = quantities[name].transpose("valid_time", "latitude", "longitude").to_numpy()
            arrays[name], offset, scale = _quantize(values)
            stored[name] = {"offset": round(offset, 6), "scale": round(scale, 8)}

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
        "layers": [layer for layer, needs in LAYER_QUANTITIES.items() if set(needs) <= set(stored)],
    }


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


def _quantities(dataset: xr.Dataset) -> dict:
    """
    The fields of the viewer found in a dataset, in its units.

    Speeds are in kt, pressures in hPa and wave heights in m. Wave
    directions are unit vectors towards where the waves come from.
    """
    names = set(dataset.data_vars)
    found = {}
    if {"u10", "v10"} <= names:
        found["wind_u"] = dataset["u10"] * KNOTS_PER_MS
        found["wind_v"] = dataset["v10"] * KNOTS_PER_MS
    elif {"si10", "wdir10"} <= names:
        speed = dataset["si10"] * KNOTS_PER_MS
        found["wind_u"] = -speed * np.sin(np.radians(dataset["wdir10"]))
        found["wind_v"] = -speed * np.cos(np.radians(dataset["wdir10"]))
    for name in ("gust", "i10fg", "fg10"):
        if name in names:
            found["gust"] = dataset[name] * KNOTS_PER_MS
            break
    for name in ("msl", "prmsl"):
        if name in names:
            found["pressure"] = dataset[name] / 100.0
            break
    if "swh" in names:
        found["swh"] = dataset["swh"]
        for name in ("mwd", "dirpw"):
            if name in names:
                found["wave_x"] = np.sin(np.radians(dataset[name]))
                found["wave_y"] = np.cos(np.radians(dataset[name]))
                break
    if {"uo", "vo"} <= names:
        found["current_u"] = dataset["uo"] * KNOTS_PER_MS
        found["current_v"] = dataset["vo"] * KNOTS_PER_MS
    return found


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


def _quantize(values: np.ndarray) -> tuple:
    """
    Values as bytes, with the offset and scale to read them back.

    The value of byte b is `offset + scale * b`; 255 marks NaN.
    """
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    if finite.any():
        low = float(values[finite].min())
        high = float(values[finite].max())
    else:
        low = high = 0.0
    scale = (high - low) / (NO_DATA - 1) if high > low else 1.0
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


def _layers() -> dict:
    """
    Label, unit, colour scale and legend of each map layer.
    """
    from matplotlib import colormaps

    from architeuthis.toolbox.windy_colormaps import get_wave_cmap, get_wind_cmap

    wind, wind_norm = get_wind_cmap()
    wave, wave_norm = get_wave_cmap()

    def scale(colour, low, high, count=96):
        values = np.linspace(low, high, count)
        return [
            "#{:02x}{:02x}{:02x}".format(*(int(round(255 * channel)) for channel in colour(value)[:3]))
            for value in values
        ]

    wind_colours = scale(lambda kt: wind(wind_norm(kt / KNOTS_PER_MS)), 0.0, 70.0)
    return {
        "wind": {
            "label": "Wind",
            "unit": "kt",
            "colormap": {"min": 0.0, "max": 70.0, "colors": wind_colours},
            "ticks": [0, 10, 20, 30, 40, 50, 60],
        },
        "gust": {
            "label": "Gusts",
            "unit": "kt",
            "colormap": {"min": 0.0, "max": 70.0, "colors": wind_colours},
            "ticks": [0, 10, 20, 30, 40, 50, 60],
        },
        "waves": {
            "label": "Waves",
            "unit": "m",
            "colormap": {"min": 0.0, "max": 12.0, "colors": scale(lambda m: wave(wave_norm(m)), 0.0, 12.0)},
            "ticks": [0, 1, 2, 3, 4, 6, 8, 10],
        },
        "current": {
            "label": "Current",
            "unit": "kt",
            "colormap": {"min": 0.0, "max": 3.0, "colors": scale(lambda kt: colormaps["viridis"](kt / 3.0), 0.0, 3.0)},
            "ticks": [0, 0.5, 1, 1.5, 2, 2.5],
        },
        "pressure": {
            "label": "Pressure",
            "unit": "hPa",
            "colormap": {
                "min": 960.0,
                "max": 1050.0,
                "colors": scale(lambda hpa: colormaps["RdYlBu_r"]((hpa - 960.0) / 90.0), 960.0, 1050.0),
            },
            "ticks": [960, 980, 1000, 1020, 1040],
        },
    }


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

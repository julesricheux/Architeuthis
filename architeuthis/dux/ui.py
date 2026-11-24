# -*- coding: utf-8 -*-
"""
Analyst's page to choose the routes to share, beside their globe.

This is a script, not a library: importing it downloads forecasts and
needs a report in `~/data/routes/`. Run it from the repository root
with `python -m architeuthis.dux.ui`. It serves on port 8052 and needs
the `dux` extra: `pip install architeuthis[dux]`.

The page shows the viewer of `share.py` with the forecasts and the
routes of a report file, and, beside it, what to share: routes, tooltip
variables, forecasts and their fields, title and a note to the crew.
Each route takes a name and a description, and clicking a point of a
route in the viewer comments on it. Changes show at once in the viewer,
and the download button writes the same page as one HTML file, which
opens in any browser, offline.

Created on Sun Jan 25 21:18:08 2026

@author: jules
"""

import os
import sys

# `python ui.py` puts this folder first on the path, and `architeuthis/` must never be
# there, where architeuthis/numpy would hide the real numpy. Everything is imported from
# the repository root instead, two folders above.
if "__file__" in globals():
    _ui_folder = os.path.dirname(os.path.abspath(__file__))
    _package_folder = os.path.dirname(_ui_folder)
    sys.path[:] = [
        os.path.dirname(_package_folder),
        *(
            path
            for path in sys.path
            if os.path.abspath(path or os.getcwd()) not in (_ui_folder, _package_folder)
        ),
    ]

import copy
import io
from datetime import timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
import xarray as xr
import matplotlib

# Nothing is drawn with pyplot any more, but a GUI backend kills the process from a server thread.
matplotlib.use("Agg")

from PIL import Image

from architeuthis.dux import require_extra

with require_extra():
    import dash_mantine_components as dmc
    from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
    from dash import _dash_renderer
    from flask import Response, abort, request

# Dash Mantine Components 3 needs React 19, which Dash 4.5 ships but does not
# load by default. This must run before the page is first served.
_dash_renderer._set_react_version("19.2.4")

from architeuthis import sky
from architeuthis.common import _HOME, status
from architeuthis.exclusion import (
    ExclusionZoneLibrary,
    iceberg_zone,
    merge_exclusion_zones,
)
from architeuthis.forecast import (
    DeterministicHerbieForecast,
    EnsembleHerbieForecast,
)
from architeuthis.report import ReportCollection, latest_report_file
from architeuthis.dux.share import (
    ROUTE_COLORS,
    build_scene,
    default_variables,
    forecast_fields,
    maplibre_files,
    png_data_uri,
    route_labels,
    segment_variables,
    variable_info,
    viewer_html,
)

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

DEFAULT_MEMBER = 1

PRODUCT = "oper"
MODELS = ["ifs", "gfs"]

# PRODUCT = "enfo"
# MODELS = ["ifs"]

minimum_longitude = -70
maximum_longitude = 5.
minimum_latitude = 30.
maximum_latitude = 60.

# minimum_longitude=-90.
# maximum_longitude=-72.
# minimum_latitude=9.
# maximum_latitude=18.

steps_00_12 = list(range(0, 145, 3)) + list(range(150, 361, 6))

# Fields downloaded from the atmospheric and wave models, by the names of
# GRIB_SEARCH: comment a line out to leave a field out. The routes need the
# wind and the wave height and direction; a field a model lacks is left out.
ATMOSPHERE_FIELDS = [
    "wind",
    "pressure",
    "gust",
    "cape",
    "precipitation_type",
    "precipitation",
    "temperature",
]
WAVE_FIELDS = [
    "wave_height",
    "wave_direction",
    "wave_period",
]

# Whether to download, with the forecasts, the nine fields of the cloud plots of the
# share file (sky.SKY_VARIABLES), for the routes whose reports lack them (a routing
# that listed "clouds" in its variables already has them, and keeps its own), and the
# Clouds layer of the map: the total cover with the precipitation over it, as on Windy.
INCLUDE_CLOUDS = True

# The search string of each field in the GRIB index of each Herbie model:
# IFS names hold for oper and enfo, wave and waef. Add a field here to
# download and share it.
GRIB_SEARCH = {
    "ifs": {
        "wind": ":10[uv]:",
        "pressure": ":msl:",
        "gust": ":10fg:",
        "cape": ":mucape:",
        "precipitation_type": ":ptype:",
        "precipitation": ":tprate:",
        "temperature": ":2t:",
        "wave_height": ":swh:",
        "wave_direction": ":mwd:",
        "wave_period": ":mwp:",
    },
    "gfs": {
        "wind": ":(?:U|V)GRD:10 m above ground",
        "pressure": ":PRMSL:",
        "gust": ":GUST:surface",
        "cape": ":CAPE:255-0 mb above ground",
        "precipitation": ":PRATE:surface:[0-9]+ hour fcst",  # not the average
        "temperature": ":TMP:2 m above ground",
    },
    "gfs_wave": {
        "wave_height": ":HTSGW:",
        "wave_direction": ":DIRPW:",
        "wave_period": ":PERPW:",
    },
}

# NOAA's analysis of the North Atlantic surface, drawn between these corners.
SFC_URL = "https://ocean.weather.gov/shtml/A_full_00hrsfc.gif"
SFC_BOUNDS = [[65.15, -100.0], [14.4, 10.0]]
WHITE_THRESHOLD = 250  # RGB threshold for "white"


# ---------------------------------------------------------------------
# NOAA surface analysis
# ---------------------------------------------------------------------
def remove_white_pixels(
    image: bytes,
    threshold: int = 240,
) -> bytes:
    """
    Make the white pixels of an image transparent.

    Args:
        image: The image file, in any format Pillow reads.
        threshold: Value of the three channels above which a pixel
            counts as white.

    Returns:
        The image as PNG bytes.
    """
    data = np.array(Image.open(io.BytesIO(image)).convert("RGBA"))
    white = (data[..., 0] >= threshold) & (data[..., 1] >= threshold) & (data[..., 2] >= threshold)
    data[white, 3] = 0  # set alpha channel to transparent

    buffer = io.BytesIO()
    Image.fromarray(data, mode="RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def analysis_time(last_modified):
    """
    The valid time of the NOAA analysis, from the date of its file.

    The chart gives its time only in its picture. It is drawn every
    6 hours and published about 2 hours later: its time is taken as
    the last synoptic hour at least 1.5 hours before the file changed.

    Args:
        last_modified: The `Last-Modified` header of the chart, or
            None.

    Returns:
        The valid time as a UTC `pd.Timestamp`, or None if unknown.
    """
    if not last_modified:
        return None
    try:
        written = pd.Timestamp(parsedate_to_datetime(last_modified))
    except (TypeError, ValueError):
        return None
    written = written.tz_localize("UTC") if written.tzinfo is None else written.tz_convert("UTC")
    # A datetime.timedelta: pd.Timedelta warns with NumPy 2.5.
    return (written - timedelta(minutes=90)).floor("6h")


def noaa_chart():
    """
    The latest NOAA surface analysis and its valid time.

    Returns:
        The chart as PNG bytes with white made transparent, and its
        time from `analysis_time`; None and None if unavailable.
    """
    try:
        response = requests.get(SFC_URL, timeout=30)
        response.raise_for_status()
        chart = remove_white_pixels(response.content, WHITE_THRESHOLD)
    except (requests.RequestException, OSError) as error:
        status(f"⚠️ NOAA surface analysis unavailable: {error}")
        return None, None
    return chart, analysis_time(response.headers.get("Last-Modified"))


NOAA_CHART, NOAA_TIME = noaa_chart()


def grib_regex(
    model: str,
    fields: list,
) -> str:
    """
    The Herbie search of fields in the GRIB index of a model.

    Args:
        model: The Herbie model, a key of `GRIB_SEARCH`.
        fields: Names of fields in `GRIB_SEARCH[model]`. Those the
            model lacks are left out, with a warning.

    Returns:
        The regular expression of the fields.
    """
    searches = GRIB_SEARCH[model]
    missing = [field for field in fields if field not in searches]
    if missing:
        status(f"⚠️ {model} has no {', '.join(missing)}: left out")
    return "|".join(searches[field] for field in fields if field in searches)


#%% FORECASTS

recent = (pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta("9h")).floor("1d")
# recent = pd.Timestamp('2026-11-08 00:00:00')

ATMOS = {}
WAVE = {}
domain = dict(
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    date=recent,
)

if PRODUCT == "oper":
    ATMOS["ifs"] = DeterministicHerbieForecast(
        "wind_ifs", model="ifs", product="oper", regex=grib_regex("ifs", ATMOSPHERE_FIELDS), fxx=steps_00_12, **domain,
    )
    ATMOS["gfs"] = DeterministicHerbieForecast(
        "wind_gfs",
        model="gfs",
        product="pgrb2.0p25",
        regex=grib_regex("gfs", ATMOSPHERE_FIELDS),
        fxx=steps_00_12,
        **domain,
    )
    WAVE["ifs"] = DeterministicHerbieForecast(
        "wave_ifs", model="ifs", product="wave", regex=grib_regex("ifs", WAVE_FIELDS), fxx=steps_00_12, **domain,
    )
    WAVE["gfs"] = DeterministicHerbieForecast(
        "wave_gfs", model="gfs_wave", product="global.0p25", regex=grib_regex("gfs_wave", WAVE_FIELDS), fxx=steps_00_12, **domain,
    )
elif PRODUCT == "enfo":
    ATMOS["ifs"] = EnsembleHerbieForecast(
        "wind_ens", model="ifs", product="enfo", regex=grib_regex("ifs", ATMOSPHERE_FIELDS), fxx=steps_00_12, **domain,
    )
    WAVE["ifs"] = EnsembleHerbieForecast(
        "wave_ens", model="ifs", product="waef", regex=grib_regex("ifs", WAVE_FIELDS), fxx=steps_00_12, **domain,
    )
else:
    raise ValueError("PRODUCT should be in ['enfo', 'oper']")

for model in MODELS:
    ATMOS[model].load_data()
    WAVE[model].load_data()

# The nine cloud fields of each model (sky.SKY_VARIABLES), always from the deterministic
# run: the plots read them along the routes, and their total cover and precipitation rate
# make the Clouds layer of the map (cloud_fields). GFS has no middle and high covers at
# step 0.
SKY = {}
if INCLUDE_CLOUDS:
    for model in MODELS:
        SKY[model] = DeterministicHerbieForecast(
            f"sky_{model}",
            model=model,
            product="oper" if model == "ifs" else "pgrb2.0p25",
            regex=sky.IFS_SKY_REGEX if model == "ifs" else sky.GFS_SKY_REGEX,
            fxx=[step for step in steps_00_12 if model == "ifs" or step >= 3],
            **domain,
        )
        SKY[model].load_data()
        sky.add_sky_models(SKY[model], model=model)


def cloud_fields(
    forecast,
    like: xr.Dataset,
) -> xr.Dataset:
    """
    The cover and precipitation of a sky forecast, on a model's grid.

    share.py draws them as one Clouds layer, the precipitation over the
    cover; the other fields of the sky stay off the map. A field that
    `like` already has is left out.

    Args:
        forecast: A forecast of the sky fields, loaded.
        like: The dataset of the model, on `valid_time`, `latitude`
            and `longitude`.

    Returns:
        `tcc`, and `tprate` or `prate`, interpolated on its grid.
    """
    names = [name for name in ("tcc", "tprate", "prate") if name in forecast.data and name not in like]
    return forecast.data[names].interp(
        valid_time=like["valid_time"],
        latitude=like["latitude"],
        longitude=like["longitude"],
    )


# One dataset per model, the waves on the grid of the wind. share.py reads the GFS names
# (prmsl, dirpw, perpw) as well as the IFS ones, and shows any other field: add it to
# ATMOSPHERE_FIELDS or WAVE_FIELDS to share it. The wave slope comes from the height and period.
DS = {}
for model in MODELS:
    atmosphere = ATMOS[model].data
    DS[model] = xr.merge(
        [atmosphere, WAVE[model].data.interp_like(atmosphere)]
        + ([cloud_fields(SKY[model], atmosphere)] if model in SKY else []),
        join="exact",
        compat="no_conflicts",
    )

FORECASTS = {model.upper(): DS[model] for model in MODELS}

# Every layer of the forecasts, which the analyst ticks to share it: {layer: label}. The
# precipitation of the sky only makes the Clouds layer, unless ATMOSPHERE_FIELDS asks for it.
FIELDS = forecast_fields(FORECASTS)
if "precipitation" not in ATMOSPHERE_FIELDS:
    FIELDS.pop("precipitation", None)


#%% ROUTES AND ZONES

ROUTES_DIR = Path(_HOME, "routes")

# The most recently modified file is shown first
latest_file = latest_report_file(ROUTES_DIR)
reports = ReportCollection.load(latest_file)

def shared_zones() -> list:
    """
    The zones of the globe, of which only the iceberg limit shows.

    The latest iceberg limit is shown at first, and the zones stored in
    `~/data/exclusion_zones/` are hidden at first, whatever their
    `visible`.
    """
    iceberg = iceberg_zone()
    zones = []
    for zone in merge_exclusion_zones([iceberg], ExclusionZoneLibrary()):
        if zone is not iceberg:
            zone = copy.copy(zone)
            zone.visible = False
        zones.append(zone)
    return zones


exclusion_zones = shared_zones()


def zones_shown(zones=None) -> dict:
    """
    The zones shown at first in the preview, by their scene identifier.

    Args:
        zones: Zones of the preview, `exclusion_zones` by default.

    Returns:
        `{"z<index>": shown}`, as the preview sends its zones.
    """
    zones = exclusion_zones if zones is None else zones
    return {
        f"z{index}": bool(getattr(zone, "visible", True)) and len(getattr(zone, "outline", zone)) >= 2
        for index, zone in enumerate(zones)
    }


def ticked_zones(shown=None) -> list:
    """
    The zones of the share file: those ticked in the preview.

    The zones left unticked by the analyst are not shared, and those
    shared are shown when the file opens.

    Args:
        shown: The zones ticked, as the preview sends them,
            `{"z<index>": shown}`; those of `zones_shown` when None.

    Returns:
        Copies of the ticked zones of `exclusion_zones`, all visible.
    """
    shown = zones_shown() if shown is None else shown
    zones = []
    for index, zone in enumerate(exclusion_zones):
        if shown.get(f"z{index}"):
            zone = copy.copy(zone)
            zone.visible = True
            zones.append(zone)
    return zones

# MapLibre is put in the pages, so that shared files open offline, once downloaded.
LIBRARY = "inline" if maplibre_files() is not None else "cdn"


def report_files() -> list:
    """
    The report files of `~/data/routes/`, the most recent first.
    """
    return sorted(ROUTES_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def report_path(name: str) -> Path:
    """
    The path of a report file of `~/data/routes/`, from its name.

    Any other name, such as a path outside this folder, raises
    `FileNotFoundError`.
    """
    for path in report_files():
        if path.name == name:
            return path
    raise FileNotFoundError(name)


def with_sky(collection) -> ReportCollection:
    """
    The reports, with the sky along the routes that lack it.

    With `INCLUDE_CLOUDS`, the nine fields of `sky.SKY_VARIABLES` are
    read at the centre of each segment from the cloud fields of the
    model of the report (its `model` tag), else of the first model.
    A report that has them keeps its own.

    Args:
        collection: The reports of a file.

    Returns:
        A new collection, of copies where the sky was added.
    """
    if not SKY:
        return collection
    reports = []
    for report in collection:
        if not all(key in report for key in sky.SKY_VARIABLES):
            forecast = SKY.get(str(report.get("model", "")).lower(), next(iter(SKY.values())))
            report = copy.copy(report)
            report.update(sky.sample(
                forecast,
                np.ravel(report["ctim"]),
                np.ravel(report["clat"]),
                np.ravel(report["clon"]),
            ))
        reports.append(report)
    return ReportCollection(reports)


def load_reports(name: str) -> ReportCollection:
    """
    The reports of a file of `~/data/routes/`.
    """
    return ReportCollection.load(report_path(name))


def default_routes(collection) -> list:
    """
    Identifiers of the routes shared by default: the optimized ones.

    All of them when none is optimized.
    """
    optimized = [f"r{index}" for index, report in enumerate(collection) if report.get("solve")]
    return optimized or [f"r{index}" for index in range(len(collection))]


def default_title(collection) -> str:
    """
    The title of a share file, from the first departure.
    """
    if not len(collection):
        return "Routes"
    etd = min(pd.to_datetime(report["etd"], unit="s") for report in collection)
    return f"Routes departing {etd:%d %b %Y}"


def all_variables(collection) -> list:
    """
    The per-segment variables of any report, defaults first.
    """
    found = []
    for report in collection:
        found += [name for name in segment_variables(report) if name not in found]
    defaults = default_variables(collection)
    return defaults + [name for name in found if name not in defaults]


def overlays(visible: bool = False) -> list:
    """
    The images that can be drawn over the map: the NOAA analysis.

    It is always shared, when available, and the crew can show or hide
    it in the layers.

    Args:
        visible: Whether it is shown when the file opens.
    """
    if NOAA_CHART is None:
        return []
    return [
        {
            "label": "NOAA surface analysis",
            "url": png_data_uri(NOAA_CHART),
            "bounds": SFC_BOUNDS,
            "visible": bool(visible),
            "time": NOAA_TIME,
        }
    ]


def noaa_label() -> str:
    """
    The label of the NOAA analysis, with its valid time.
    """
    if NOAA_CHART is None:
        return "NOAA surface analysis (unavailable)"
    if NOAA_TIME is None:
        return "NOAA surface analysis"
    return f"NOAA surface analysis, {NOAA_TIME:%a %d %H} UTC"


_preview = {}


def preview_scene(name: str, member: int) -> dict:
    """
    The scene of the preview: every route, variable and forecast.

    The analyst's choices are sent to the page as they change. The
    scene of the last file and member is kept.
    """
    path = report_path(name)
    key = (path.name, path.stat().st_mtime, member)
    if key not in _preview:
        collection = with_sky(ReportCollection.load(path))
        _preview.clear()
        _preview[key] = build_scene(
            collection,
            forecasts=FORECASTS,
            variables=all_variables(collection),
            zones=exclusion_zones,
            overlays=overlays(),
            title=default_title(collection),
            member=member,
            fields=list(FIELDS),
            settings={
                "routes": default_routes(collection),
                "hover": default_variables(collection),
            },
        )
    return _preview[key]


def viewer_url(name: str, member: int = DEFAULT_MEMBER) -> str:
    """
    The address of the preview of a report file.
    """
    return f"/viewer?file={quote(name)}&member={member}"


# ---------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------

# The page needs no asset of its own: the viewer brings its style and scripts.
app = Dash(__name__, title="Architeuthis", assets_ignore=r".*", update_title=None)
server = app.server


@server.route("/viewer")
def viewer():
    """
    The viewer of a report file, as it will be shared.

    The query gives `file`, a name in `~/data/routes/`, and `member`.
    """
    name = request.args.get("file", latest_file.name)
    try:
        member = int(request.args.get("member", DEFAULT_MEMBER))
        scene = preview_scene(name, member)
    except (FileNotFoundError, ValueError):
        abort(404)
    return Response(viewer_html(scene, library=LIBRARY), mimetype="text/html")


# ---------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------


def file_options() -> list:
    """
    The report files as options, with their date.
    """
    return [
        {
            "value": path.name,
            "label": f"{path.stem} · {pd.Timestamp(path.stat().st_mtime, unit='s'):%d %b %H:%M}",
        }
        for path in report_files()
    ]


def route_options(collection) -> list:
    """
    One checkbox per route, with its colour, fuel and distance.

    The name beside it is a box written in place: its label by default,
    edited by clicking it. Under each, a box takes the description of
    the route for the crew.
    """
    options = []
    for index, (report, label) in enumerate(zip(collection, route_labels(collection))):
        color = ROUTE_COLORS[index % len(ROUTE_COLORS)]
        details = []
        if report.get("fuel") is not None:
            details.append(f"{report['fuel']:.1f} t")
        if report.get("dist") is not None:
            details.append(f"{report['dist']:.0f} nm")
        badges = []
        if report.get("status") == 2:
            badges.append(dmc.Badge("not converged", color="orange", variant="light", size="xs"))
        # z is positive on land, in shallow water and inside exclusion zones.
        if "z" in report and float(np.max(report["z"])) > 0:
            badges.append(dmc.Badge("land or zone", color="red", variant="light", size="xs"))
        description = report.get("description")
        options.append(
            dmc.Stack(
                [
                    dmc.Group(
                        [
                            dmc.Checkbox(value=f"r{index}", **{"aria-label": label}),
                            html.Span(style={"display": "inline-block", "width": 16, "height": 4, "borderRadius": 2, "background": color, "flex": "none"}),
                            # The name, written once and edited in place.
                            dmc.TextInput(
                                id={"type": "route-name", "index": index},
                                placeholder=label,
                                value=label,
                                variant="unstyled",
                                size="sm",
                                style={"flex": 1, "minWidth": 0},
                                styles={
                                    "input": {
                                        "fontWeight": 600,
                                        "height": "auto",
                                        "minHeight": 0,
                                        "lineHeight": 1.4,
                                        "borderBottom": "1px dotted var(--mantine-color-default-border)",
                                        "cursor": "text",
                                    }
                                },
                            ),
                            *badges,
                        ],
                        gap=8,
                        wrap="nowrap",
                    ),
                    dmc.Text(" · ".join(details), size="xs", c="dimmed", ml=32, mt=-6),
                    dmc.Textarea(
                        id={"type": "route-description", "index": index},
                        placeholder="Description of this route for the crew",
                        value=description if isinstance(description, str) else "",
                        autosize=True,
                        minRows=1,
                        maxRows=6,
                        size="xs",
                        ml=32,
                    ),
                ],
                gap=4,
            )
        )
    return options


def variable_options(collection) -> list:
    """
    The tooltip variables as options, with their description.
    """
    options = []
    for name in all_variables(collection):
        info = variable_info(name)
        unit = f" ({info['unit']})" if info["unit"] else ""
        options.append({"value": name, "label": f"{info['label']} · {info['description']}{unit}"})
    return options


def section(title, *children):
    """
    A titled group of controls.
    """
    return dmc.Stack([dmc.Text(title, size="xs", fw=700, c="dimmed", tt="uppercase"), *children], gap=6)


sidebar = dmc.Stack(
    gap="lg",
    children=[
        dmc.Stack(
            gap=2,
            children=[
                dmc.Group(
                    [
                        dmc.Title("Share routes", order=3),
                        dmc.Switch(id="theme-switch", label="Light map", checked=False, size="sm"),
                    ],
                    justify="space-between",
                ),
                dmc.Text(
                    "Choose what the crew will see, then download one HTML file. "
                    "It opens in any browser, offline.",
                    size="sm",
                    c="dimmed",
                ),
            ],
        ),
        dmc.Select(
            id="file-select",
            label="Routes file",
            data=file_options(),
            value=latest_file.name,
            allowDeselect=False,
        ),
        section(
            "Message",
            dmc.TextInput(id="title-input", placeholder="Title", value=default_title(reports)),
            dmc.Textarea(
                id="note-input",
                placeholder="Note to the crew, shown under the title",
                autosize=True,
                minRows=2,
                maxRows=8,
            ),
        ),
        section(
            "Routes to share",
            dmc.Group(
                [
                    dmc.Button("Optimized", id="routes-optimized", variant="subtle", size="compact-xs"),
                    dmc.Button("All", id="routes-all", variant="subtle", size="compact-xs"),
                    dmc.Button("None", id="routes-none", variant="subtle", size="compact-xs"),
                ],
                gap=4,
            ),
            dmc.CheckboxGroup(
                id="routes-select",
                children=dmc.Stack(route_options(reports), gap=10, id="routes-options"),
                value=default_routes(reports),
            ),
            dmc.Text(
                "Click a point of a route in the preview to comment on it: "
                "the crew reads the comment there.",
                size="xs",
                c="dimmed",
            ),
        ),
        section(
            "Tooltips",
            dmc.MultiSelect(
                id="hover-select",
                placeholder="Variables shown on the routes",
                data=variable_options(reports),
                value=default_variables(reports),
                searchable=True,
                clearable=True,
                hidePickedOptions=True,
            ),
        ),
        section(
            "Weather",
            dmc.CheckboxGroup(
                id="sources-select",
                children=dmc.Group([dmc.Checkbox(label=model.upper(), value=model) for model in MODELS]),
                value=list(MODELS),
            ),
            dmc.MultiSelect(
                id="fields-select",
                label="Fields",
                placeholder="Forecast fields shared",
                data=[{"value": layer, "label": label} for layer, label in FIELDS.items()],
                value=list(FIELDS),
                searchable=True,
                clearable=True,
                hidePickedOptions=True,
            ),
            html.Div(
                dmc.NumberInput(
                    id="member-select",
                    label="Ensemble member",
                    value=DEFAULT_MEMBER,
                    min=0,
                    max=50,
                    w=160,
                ),
                # Deterministic forecasts have a single member.
                style={"display": "block" if PRODUCT == "enfo" else "none"},
            ),
            dmc.Checkbox(
                id="noaa-check",
                label=noaa_label(),
                description=(
                    "Always shared, shown at opening when ticked"
                    + (": valid time estimated from the date of the file" if NOAA_TIME is not None else "")
                ),
                checked=False,
                disabled=NOAA_CHART is None,
            ),
        ),
        dmc.Stack(
            gap=4,
            children=[
                dmc.Button("Download the share file", id="download-button", fullWidth=True, size="md"),
                dmc.Text(id="download-info", size="xs", c="dimmed"),
                dcc.Download(id="download"),
            ],
        ),
    ],
)

app.layout = dmc.MantineProvider(
    id="provider",
    forceColorScheme="dark",
    children=html.Div(
        style={"display": "flex", "height": "100vh", "width": "100vw", "overflow": "hidden"},
        children=[
            html.Div(
                sidebar,
                style={
                    "width": 380,
                    "flex": "none",
                    "overflowY": "auto",
                    "padding": "18px 18px 24px",
                    "background": "var(--mantine-color-body)",
                    "borderRight": "1px solid var(--mantine-color-default-border)",
                },
            ),
            html.Iframe(
                id="viewer-frame",
                src=viewer_url(latest_file.name),
                title="Preview of the share file",
                style={"flex": "1", "border": "0", "height": "100%"},
            ),
            dcc.Store(id="viewer-settings"),
            # The analyst's comments on points of the routes, sent by the preview:
            # {"r<index>": {"<segment>": text}}.
            dcc.Store(id="route-comments", data={}),
            # The zones ticked in the preview, the only ones shared: {"z<index>": shown}.
            dcc.Store(id="zones-shown", data=zones_shown()),
        ],
    ),
)


# ---------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------


@app.callback(
    Output("routes-options", "children"),
    Output("routes-select", "value"),
    Output("hover-select", "data"),
    Output("hover-select", "value"),
    Output("title-input", "value"),
    Output("route-comments", "data"),
    Input("file-select", "value"),
    prevent_initial_call=True,
)
def select_file(name):
    """
    The choices of another report file, at their defaults.

    Its routes come with their own descriptions and no comment.

    Args:
        name: Name of the file in `~/data/routes/`.
    """
    collection = load_reports(name)
    return (
        route_options(collection),
        default_routes(collection),
        variable_options(collection),
        default_variables(collection),
        default_title(collection),
        {},
    )


@app.callback(
    Output("provider", "forceColorScheme"),
    Input("theme-switch", "checked"),
)
def color_scheme(light):
    """
    The theme of this page, that of the map.

    Args:
        light: Whether the light theme is chosen.
    """
    return "light" if light else "dark"


@app.callback(
    Output("viewer-frame", "src"),
    Input("file-select", "value"),
    Input("member-select", "value"),
    prevent_initial_call=True,
)
def show_file(name, member):
    """
    The preview of a report file and ensemble member.

    Args:
        name: Name of the file in `~/data/routes/`.
        member: Ensemble member of the forecasts.
    """
    return viewer_url(name, int(member if member is not None else DEFAULT_MEMBER))


@app.callback(
    Output("routes-select", "value", allow_duplicate=True),
    Input("routes-optimized", "n_clicks"),
    Input("routes-all", "n_clicks"),
    Input("routes-none", "n_clicks"),
    State("file-select", "value"),
    prevent_initial_call=True,
)
def quick_select(optimized, every, none, name):
    """
    Select the optimized routes, all of them or none.

    Args:
        optimized: Clicks on "Optimized".
        every: Clicks on "All".
        none: Clicks on "None".
        name: Name of the report file.
    """
    collection = load_reports(name)
    if ctx.triggered_id == "routes-none":
        return []
    if ctx.triggered_id == "routes-all":
        return [f"r{index}" for index in range(len(collection))]
    return default_routes(collection)


# The viewer answers "architeuthis:ready" once loaded: the bridge then sends it the current
# choices, which may have changed while it was loading. The viewer sends back the comments
# of the analyst ("architeuthis:comments"), its theme ("architeuthis:theme"), the charts
# it shows ("architeuthis:overlays"), so that the NOAA box follows each toggle there, and
# the zones ticked ("architeuthis:zones"), the only ones the file shares.
app.clientside_callback(
    """
    function (routes, hover, sources, title, note, noaa, texts, comments, light, names, fields, ids, nameIds) {
        const descriptions = {};
        (ids || []).forEach(function (id, i) { descriptions["r" + id.index] = (texts || [])[i] || ""; });
        const labels = {};
        (nameIds || []).forEach(function (id, i) { labels["r" + id.index] = (names || [])[i] || ""; });
        const settings = {
            routes: routes || [],
            hover: hover || [],
            sources: sources || [],
            fields: fields || [],
            overlays: null,
            overlaysShown: {o0: !!noaa},
            title: title || "",
            note: note || "",
            theme: light ? "light" : "dark",
            editable: true,
            labels: labels,
            descriptions: descriptions,
            comments: comments || {},
        };
        window.architeuthisSettings = settings;
        if (!window.architeuthisBridge) {
            window.architeuthisBridge = true;
            window.addEventListener("message", function (event) {
                const data = event.data;
                if (!data) return;
                if (data.type === "architeuthis:ready" && event.source) {
                    event.source.postMessage({type: "architeuthis:settings", settings: window.architeuthisSettings}, "*");
                } else if (data.type === "architeuthis:comments") {
                    window.dash_clientside.set_props("route-comments", {data: data.comments || {}});
                } else if (data.type === "architeuthis:overlays") {
                    window.dash_clientside.set_props("noaa-check", {checked: !!(data.overlays || {}).o0});
                } else if (data.type === "architeuthis:zones") {
                    window.dash_clientside.set_props("zones-shown", {data: data.zones || {}});
                } else if (data.type === "architeuthis:theme") {
                    window.dash_clientside.set_props("theme-switch", {checked: data.theme === "light"});
                }
            });
        }
        const frame = document.getElementById("viewer-frame");
        if (frame && frame.contentWindow) {
            frame.contentWindow.postMessage({type: "architeuthis:settings", settings: settings}, "*");
        }
        return settings;
    }
    """,
    Output("viewer-settings", "data"),
    Input("routes-select", "value"),
    Input("hover-select", "value"),
    Input("sources-select", "value"),
    Input("title-input", "value"),
    Input("note-input", "value"),
    Input("noaa-check", "checked"),
    Input({"type": "route-description", "index": ALL}, "value"),
    Input("route-comments", "data"),
    Input("theme-switch", "checked"),
    Input({"type": "route-name", "index": ALL}, "value"),
    Input("fields-select", "value"),
    State({"type": "route-description", "index": ALL}, "id"),
    State({"type": "route-name", "index": ALL}, "id"),
)


def route_notes(descriptions=None, ids=None, comments=None) -> dict:
    """
    The descriptions and comments of the analyst, by report index.

    Args:
        descriptions: Texts of the description boxes.
        ids: Identifiers of these boxes, `{"index": <report index>}`.
        comments: Comments on points of the routes, as the preview
            sends them: `{"r<index>": {"<segment>": text}}`.

    Returns:
        `{index: {"description": text, "points": {segment: text}}}`,
        the `comments` of `share.build_scene`.
    """
    notes = {}
    for identifier, text in zip(ids or [], descriptions or []):
        notes.setdefault(int(identifier["index"]), {})["description"] = text or ""
    for route, points in (comments or {}).items():
        notes.setdefault(int(str(route).lstrip("r")), {})["points"] = {int(k): text for k, text in (points or {}).items()}
    return notes


def route_names(collection, names=None, ids=None) -> list:
    """
    The name of each route: the analyst's, else its label.

    Args:
        collection: The reports.
        names: Texts of the name boxes; an empty one keeps the label.
        ids: Identifiers of these boxes, `{"index": <report index>}`.

    Returns:
        One name per report, the `labels` of `share.build_scene`.
    """
    labels = route_labels(collection)
    for identifier, text in zip(ids or [], names or []):
        index = int(identifier["index"])
        if 0 <= index < len(labels) and (text or "").strip():
            labels[index] = text.strip()
    return labels


@app.callback(
    Output("download", "data"),
    Output("download-info", "children"),
    Input("download-button", "n_clicks"),
    State("file-select", "value"),
    State("routes-select", "value"),
    State("hover-select", "value"),
    State("sources-select", "value"),
    State("title-input", "value"),
    State("note-input", "value"),
    State("member-select", "value"),
    State("noaa-check", "checked"),
    State({"type": "route-description", "index": ALL}, "value"),
    State({"type": "route-description", "index": ALL}, "id"),
    State("route-comments", "data"),
    State("theme-switch", "checked"),
    State({"type": "route-name", "index": ALL}, "value"),
    State({"type": "route-name", "index": ALL}, "id"),
    State("fields-select", "value"),
    State("zones-shown", "data"),
    prevent_initial_call=True,
)
def download(
    clicks,
    name,
    routes,
    hover,
    sources,
    title,
    note,
    member,
    noaa,
    descriptions=None,
    description_ids=None,
    comments=None,
    light=False,
    names=None,
    name_ids=None,
    fields=None,
    zones=None,
):
    """
    The share file of the current choices.

    Args:
        clicks: Clicks on the download button.
        name: Name of the report file.
        routes: Identifiers of the routes to share, `r<index>`.
        hover: Variables of the tooltips.
        sources: Models of the forecasts to share.
        title: Title of the page.
        note: Note to the crew.
        member: Ensemble member of the forecasts.
        noaa: Whether the NOAA surface analysis, always shared, is
            shown when the file opens.
        descriptions: Descriptions of the routes.
        description_ids: Identifiers of their boxes.
        comments: Comments on points of the routes.
        light: Whether the map opens in the light theme.
        names: Names of the routes, their label when empty.
        name_ids: Identifiers of their boxes.
        fields: Layers of the forecasts to share, those of `FIELDS` when
            None.
        zones: Zones ticked in the preview, `{"z<index>": shown}`, the
            only ones shared and shown at opening; when None, those
            shown at first.
    """
    if not clicks:
        return no_update, no_update
    collection = with_sky(load_reports(name))
    title = title or default_title(collection)
    scene = build_scene(
        collection,
        routes=sorted(int(route[1:]) for route in routes or []),
        forecasts={model.upper(): DS[model] for model in MODELS if model in (sources or [])},
        variables=hover or [],
        zones=ticked_zones(zones),
        overlays=overlays(visible=bool(noaa)),
        labels=route_names(collection, names, name_ids),
        title=title,
        note=note or "",
        comments=route_notes(descriptions, description_ids, comments),
        member=int(member if member is not None else DEFAULT_MEMBER),
        fields=list(FIELDS) if fields is None else fields,
        settings={"theme": "light" if light else "dark"},
    )
    text = viewer_html(scene, library=LIBRARY)
    size = len(text.encode("utf-8")) / 1e6
    filename = f"{''.join(c if c.isalnum() or c in '-_' else '_' for c in title).strip('_') or 'routes'}.html"
    info = f"{filename}: {len(scene['routes'])} routes, {size:.1f} MB."
    if LIBRARY == "cdn":
        info += " MapLibre could not be downloaded: the file needs a connection to open."
    return dict(content=text, filename=filename, type="text/html"), info


if __name__ == "__main__":
    app.run(debug=False, port=8052)

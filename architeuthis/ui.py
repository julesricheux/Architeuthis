# -*- coding: utf-8 -*-
"""
Created on Sun Jan 25 21:18:08 2026

@author: jules
"""

import io
import json
from io import BytesIO
from pathlib import Path

import requests
import pandas as pd
import xarray as xr
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from PIL import Image

import dash_mantine_components as dmc
import dash_leaflet as dl
from dash import html, dcc
from dash.dependencies import Input, Output, State
from dash_iconify import DashIconify
from dash_extensions.enrich import DashProxy
from flask import send_file, request, jsonify

from herbie.toolbox import ccrs
from architeuthis.toolbox.windy_colormaps import get_wind_cmap, get_wave_cmap

import architeuthis.numpy as np
from architeuthis.forecast import (
    DeterministicHerbieForecast,
    EnsembleHerbieForecast,
)
from architeuthis.icebergs import polygon
from architeuthis.common import _HOME

from architeuthis.toolbox.chart_utils import density_from_zoom
from architeuthis.toolbox.geo_utils import lonlat_to_web_mercator
from architeuthis.wrappers.json_wrapper import (
    custom_decoder,
    route_to_geojson,
    point_to_layer,
    style_func,
)

sns.set_theme(palette="viridis")

# ---------- CONFIG ----------
# DATA_PATH = "data.nc"   # <-- put your xarray dataset here
TILE_SIZE = 256         # tile pixel size
# Replace these names with the actual variable names in your dataset:
DEFAULT_QUIVER_VAR = "wdir10" # true wind direction
DEFAULT_RASTER_VAR = "si10" # true wind speed
DEFAULT_VECTOR_VAR = "msl" # mean sea level pressure
TIME_DIM = "valid_time" 
MEMBER_DIM = "number"
LAT_NAME = "latitude"
LON_NAME = "longitude"
DEFAULT_MEMBER=1
DEFAULT_MODEL="ifs"
# ----------------------------

PRODUCT = "oper"
MODELS = ["ifs", "gfs"]

# PRODUCT = "enfo"
# MODELS = ["ifs"]

PRODUCTS = {
    "ifs":{
        "oper": {"ens": False},
        "enfo": {"ens": True},
    },
    "gfs":{
        "pgrb2.0p25": {"ens": False},
    },
}

DEFAULT_RASTER_VARS = ["si10", "msl", "swh", "mwp"]
DEFAULT_QUIVER_VARS = ["wdir10", "mwd"]

dir_to_speed = {
    "wdir10": "si10",
    "mwd": "swh",
}

# Weather sensor icon
weather_icon = dict(
    # iconUrl="./assets/icons/wi--thermometer-internal.png",
    # iconUrl="./assets/icons/sensor.png",
    # iconUrl="./assets/icons/material-symbols-light--target.png",
    iconUrl="./assets/icons/mdi--target.png",
    # iconSize=[512, 512],
    # iconAnchor=[256, 512],
    iconSize=np.array([512, 512])/18,
    # iconAnchor=np.array([256, 512])/8,
    # iconSize=[128, 128],
    # iconAnchor=[0, 0],
)

# Theme toggle button
theme_toggle = dmc.ActionIcon(
    [
        dmc.Paper(DashIconify(icon="radix-icons:moon", width=25), darkHidden=True),
        dmc.Paper(DashIconify(icon="radix-icons:sun", width=25), lightHidden=True),
    ],
    variant="transparent",
    color="yellow",
    id="color-scheme-toggle",
    size="lg",
)

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
SFC_URL = "https://ocean.weather.gov/shtml/A_full_00hrsfc.gif"
SFC_OUTPUT = Path("assets/noaa_overlay.png")  # Dash auto-serves assets/
WHITE_THRESHOLD = 250  # RGB threshold for "white"


# ---------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------
def remove_white_pixels(
    image_url: str,
    output_path: Path,
    threshold: int = 240,
):
    response = requests.get(image_url, timeout=30)
    response.raise_for_status()

    img = Image.open(BytesIO(response.content)).convert("RGBA")
    data = np.array(img)

    r, g, b, a = np.rollaxis(data, axis=-1)

    white_mask = (
        (r >= threshold) &
        (g >= threshold) &
        (b >= threshold)
    )

    data[white_mask, 3] = 0  # set alpha channel to transparent

    Image.fromarray(data, mode="RGBA").save(output_path)


# Generate processed image once at startup
SFC_OUTPUT.parent.mkdir(exist_ok=True)
remove_white_pixels(SFC_URL, SFC_OUTPUT, WHITE_THRESHOLD)



#%% PARAMETERS
    
minimum_longitude=-80.
maximum_longitude=0.
minimum_latitude=30.
maximum_latitude=60.

steps_00_12 = list(range(0, 145, 3)) + list(range(150, 361, 6))

# # departure = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# arrival = np.array([46.921716725164956, -2.976149174402496]) # Montoir pilot
# # arrival = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# # departure = np.array([46.921716725164956, -2.976149174402496]) # Montoir pilot
# departure = np.array([46.781, -56.091]) # SPM pilot
# # arrival = np.array([46.781, -56.091]) # SPM pilot

# etd = pd.to_datetime("2026-01-25T01:00").timestamp()
# eta = pd.to_datetime("2026-02-02T23:00").timestamp()
# # eta = pd.to_datetime("2026-02-05T23:00").timestamp()
# # eta = pd.to_datetime("2026-01-22T12:00").timestamp()



#%% BUILD WIND INTERPOLATORS

# mirror_date = pd.Timestamp('2026-02-12 00:00:00')
# mirror_end = pd.Timestamp('2026-01-31 23:00:00')

recent = pd.Timestamp("now").floor("1d")

ATMOS = {}

# # IFS atmospheric data
if PRODUCT == "oper":
    # IFS atmospheric data
    ATMOS["ifs"] = DeterministicHerbieForecast(
        "wind_ifs", model="ifs", product="oper", regex=r":10[u|v]:|:msl:", fxx=steps_00_12,
        min_lon=minimum_longitude, max_lon=maximum_longitude,
        min_lat=minimum_latitude, max_lat=maximum_latitude,
        date=recent,
    )
    # GFS atmospheric data
    ATMOS["gfs"] = DeterministicHerbieForecast(
        "wind_gfs", model="gfs", product="pgrb2.0p25", regex=r"(?:U|V)GRD:10 m|PRMSL", fxx=steps_00_12,
        min_lon=minimum_longitude, max_lon=maximum_longitude,
        min_lat=minimum_latitude, max_lat=maximum_latitude,
        date=recent,
    )
    
elif PRODUCT == "enfo":
    ATMOS["ifs"] = EnsembleHerbieForecast(
        "wind_ens", model="ifs", product="enfo", regex=r":10[u|v]:|:msl:", fxx=steps_00_12,
        min_lon=minimum_longitude, max_lon=maximum_longitude,
        min_lat=minimum_latitude, max_lat=maximum_latitude,
        date=recent,
    )
else:
    raise(ValueError, "PRODUCT should be in ['enfo', 'oper']")


for model in MODELS:
    ATMOS[model].load_data()
    
if PRODUCT == "oper":
    ATMOS["gfs"].data["msl"] = ATMOS["gfs"].data["prmsl"] # TODO find a better fix

# atmos.add_interpolator("u10", "valid_time", "latitude", "longitude")
# atmos.add_interpolator("v10", "valid_time", "latitude", "longitude")


#%% BUILD WAVE INTERPOLATORS

# # IFS ocean data
# wave = DeterministicHerbieForecast(
#     "wave", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=steps_00_12,
#     min_lon=minimum_longitude, max_lon=maximum_longitude,
#     min_lat=minimum_latitude, max_lat=maximum_latitude,
#     # date=mirror_date
# )


recent = pd.Timestamp("now").floor("1d")

WAVE = {}

# # IFS atmospheric data
if PRODUCT == "oper":
    # IFS wave data
    WAVE["ifs"] = DeterministicHerbieForecast(
        "wave_ifs", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=steps_00_12,
        min_lon=minimum_longitude, max_lon=maximum_longitude,
        min_lat=minimum_latitude, max_lat=maximum_latitude,
        date=recent,
    )
    # GFS wave data
    WAVE["gfs"] = DeterministicHerbieForecast(
        "wave_gfs", model="gfs_wave", product="global.0p25", regex=r":HTSGW:|:DIRPW:", fxx=steps_00_12,
        min_lon=minimum_longitude, max_lon=maximum_longitude,
        min_lat=minimum_latitude, max_lat=maximum_latitude,
        date=recent
    )
elif PRODUCT == "enfo":
    WAVE["ifs"] = EnsembleHerbieForecast(
        "wave_ens", model="ifs", product="waef", regex=r":swh:|:mwd:", fxx=steps_00_12,
        min_lon=minimum_longitude, max_lon=maximum_longitude,
        min_lat=minimum_latitude, max_lat=maximum_latitude,
        date=recent,
    )
else:
    raise(ValueError, "PRODUCT should be in ['enfo', 'oper']")

for model in MODELS:
    WAVE[model].load_data()
    
if PRODUCT == "oper":
    WAVE["gfs"].data["mwd"] = WAVE["gfs"].data["dirpw"] # TODO find a better fix

# wave.add_interpolator("swh", "valid_time", "latitude", "longitude")
# wave.add_interpolator("mwd", "valid_time", "latitude", "longitude")


#%% BUILD CURRENT INTERPOLATORS

# # Mercator SMOC data
# current = CopernicusForecast("current", dataset="cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", variables=["uo", "vo"],
#                              min_lon=minimum_longitude, max_lon=maximum_longitude,
#                              min_lat=minimum_latitude, max_lat=maximum_latitude,
#                              date=mirror_date, end=mirror_end)
# current.load_data()

# # current.add_interpolator("uo", "time", "latitude", "longitude", latitude_slice=slice(None, None, 10))
# # current.add_interpolator("vo", "time", "latitude", "longitude", latitude_slice=slice(None, None, 10))


#%% BUILD TOPOGRAPHY

# topo = Topography("topo", depth_offset=10.,
#                   min_lon=minimum_longitude, max_lon=maximum_longitude,
#                   min_lat=minimum_latitude, max_lat=maximum_latitude,)
# topo.load_data()

# # topo.add_interpolator(
# #     "distance_to_iso0",
# #     "latitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
# #     "longitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
# #     var_key="z"
# # )

#%%

DS = {}

if PRODUCT == "oper":
    for model in MODELS:
        for model in MODELS:
            atm = ATMOS[model].data
            wav = WAVE[model].data
            DS[model] = xr.merge(
                [atm, wav.interp_like(atm)],
                    join="exact",
                    compat="no_conflicts",
                ).expand_dims({"number": [1]})
elif PRODUCT == "enfo":
    for model in MODELS:    
            atm = ATMOS[model].data
            wav = WAVE[model].data
            DS[model] = xr.merge(
                [atm, wav.interp_like(atm)],
                join="exact",
                compat="no_conflicts",
            )
else:
    raise(ValueError, "PRODUCT should be in ['enfo', 'oper']")

for model in MODELS:
    DS[model].herbie.with_wind()

times = pd.to_datetime(DS[MODELS[0]][TIME_DIM].to_numpy().astype("datetime64[s]"))

marks = [
    {"value":i, "label":  t.strftime("%Y-%m-%d")}
    for i, t in enumerate(times)
    if t.hour == 0 and t.minute == 0 and t.second == 0
]

ROUTES_DIR = Path(_HOME, "routes")

json_files = list(ROUTES_DIR.glob("*.json"))

if not json_files:
    raise FileNotFoundError("No JSON files found in routes directory.")

# Select most recently modified file
latest_file = max(json_files, key=lambda f: f.stat().st_mtime)

with open(latest_file, "r") as f:
    reports = json.load(f, object_hook=custom_decoder)
    

# Load the GeoJSON file
with open("./assets/countries-coastline-1km.geo.json") as f:
    countries_geojson = json.load(f)


# Create a GeoJSON layer
countries_layer = dl.GeoJSON(
    data=countries_geojson,
    id="countries-layer",
    options=dict(style=dict(color="black", weight=0.33)),  # customize border color & weight
    # hoverStyle=dict(weight=2, color="yellow")          # optional hover effect
)

# sanity checks
for model in MODELS:
    assert LAT_NAME in DS[model].coords, f"Dataset must have coordinate '{LAT_NAME}'"
    assert LON_NAME in DS[model].coords, f"Dataset must have coordinate '{LON_NAME}'"
    assert TIME_DIM in DS[model].dims, f"Dataset must have time dimension '{TIME_DIM}'"

n_time = DS[MODELS[0]].sizes[TIME_DIM]
vars_available = list(DS[MODELS[0]].data_vars.keys())
RASTER_VARS = list(set(DEFAULT_RASTER_VARS).intersection(vars_available))
QUIVER_VARS = list(set(DEFAULT_QUIVER_VARS).intersection(vars_available))

app = DashProxy(
    external_scripts=["https://code.iconify.design/3/3.1.1/iconify.min.js"]
)

server = app.server

@server.route("/wind_arrows.geojson")
def wind_arrows():
    """
    Returns a GeoJSON FeatureCollection containing arrows representing
    wind vectors for a given time index. Arrow length and thickness scale
    with wind speed.
    """
    time_index = int(request.args.get("time", "0"))
    qvar = request.args.get("qvar", DEFAULT_QUIVER_VAR)
    density = int(request.args.get("density", "10"))
    m = int(request.args.get("member", DEFAULT_MEMBER))
    model = request.args.get("model", DEFAULT_MODEL)
    
    # print(m)
    
    q = DS[model][qvar].isel({TIME_DIM: time_index}).sel({MEMBER_DIM: m})
    s = DS[model][dir_to_speed[qvar]].isel({TIME_DIM: time_index}).sel({MEMBER_DIM: m})
    
    q_arr = np.asarray(q.values)
    s_arr = np.asarray(s.values)
    
    lats = np.asarray(DS[model][LAT_NAME].values)
    lons = np.asarray(DS[model][LON_NAME].values)

    lat_idx = np.arange(0, lats.size, max(1, density))
    lon_idx = np.arange(0, lons.size, max(1, density))

    features = []
    for i in lat_idx:
        for j in lon_idx:
            try:
                lat = float(lats[i])
                lon = float(lons[j])
                qq = float(q_arr[i, j])
                ss = float(s_arr[i, j])
            except Exception:
                continue
            

            # Skip calm wind to avoid clutter
            if ss < 0.1:
                continue

            # ------------------------------------------------------------
            # Arrow geometry
            # ------------------------------------------------------------
            # Length scales with speed (adjust factor for your map units)
            length_scale = 0.03   # degrees per (m/s), tune to your taste
            L = ss * length_scale
            
            uu = -np.sind(qq) * ss
            vv = -np.cosd(qq) * ss

            # Compute normalized direction
            dx = (uu / ss) * L
            dy = (vv / ss) * L

            # Arrow shaft: start → end
            x0, y0 = lon - dx/2., lat - dy/2.
            x1, y1 = lon + dx/2., lat + dy/2.

            # ------------------------------------------------------------
            # Arrowhead (optional)
            # ------------------------------------------------------------
            # Small triangle at the tip
            head_scale = 0.4 * L
            hx = x1 - dx * 0.2
            hy = y1 - dy * 0.2

            # perpendicular vector
            px = -dy * 0.15
            py = dx * 0.15

            # Triangle points
            head_left = [hx + px, hy + py]
            head_right = [hx - px, hy - py]

            # Full arrow coordinates (shaft + triangle)
            coords = [
                [x0, y0],
                [x1, y1],
                head_left,
                [x1, y1],
                head_right
            ]

            # ------------------------------------------------------------
            # GeoJSON features
            # ------------------------------------------------------------
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords
                },
                "properties": {
                    "u": uu,
                    "v": vv,
                    "speed": ss,
                    # thickness proportional to speed
                    "weight": max(1, ss * 10),
                    # color suggestions (override in Dash)
                    "color": "#3182bd",
                    # direction bearing (optional)
                    "bearing": (qq+180) % 360
                }
            }

            features.append(feature)

    return jsonify({"type": "FeatureCollection", "features": features})


@server.route("/contour_field.geojson")
def contour_field():
    var = request.args.get("var", DEFAULT_VECTOR_VAR)
    t   = int(request.args.get("time", 0))
    m   = int(request.args.get("member", DEFAULT_MEMBER))
    model = request.args.get("model", DEFAULT_MODEL)

    da = DS[model][var].isel({TIME_DIM: t}).sel({MEMBER_DIM: m}).values / 1e2
    lats = DS[model][LAT_NAME].values
    lons = DS[model][LON_NAME].values
    
    # lons, lats = lonlat_to_web_mercator(lons, lats)
    
    vmin = np.nanmin(da)
    vmax = np.nanmax(da)
    delta = 2  # contour every 10 units
    levels = np.arange(np.floor(vmin / delta) * delta,
                       np.ceil(vmax / delta) * delta + 1,
                       delta)
        
    X, Y = np.meshgrid(lons, lats)
    
    fig = plt.figure(figsize=(6,4), dpi=50)
    # ax = plt.axes(projection=ccrs.PlateCarree())
    # cs = ax.contour(X, Y, da, levels=levels, colors='black',)
    ax  = plt.axes()  # IMPORTANT: no projection → raw mercator coords
    cs = ax.contourf(X, Y, da, levels=levels, colors='black',)
    
    plt.close(fig)   # avoid rendering

    # --- Convert contour to GeoJSON manually ---
    features = []

    for i_level, (path, level) in enumerate(zip(cs.get_paths(), cs.levels)):

        # path = cs.get_paths()[i_level]
        # Path may contain multiple polygons/subpaths
        for poly in path.to_polygons():
            if len(poly) < 2:
                continue

            # poly = Nx2 array (x,y) already in EPSG:3857
            coords = poly.tolist()

            feature = {
                "type": "Feature",
                "properties": {
                    "value": float(level),
                    "stroke": "#FFFFFF",
                    "stroke-width": 1,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
            }

            features.append(feature)

    return jsonify({"type": "FeatureCollection", "features": features})


@server.route("/raster.png")
def raster_png():
    var = request.args.get("var", DEFAULT_RASTER_VAR)
    t   = int(request.args.get("time", 0))
    m   = int(request.args.get("member", DEFAULT_MEMBER))
    model = request.args.get("model", DEFAULT_MODEL)

    da = DS[model][var].isel({TIME_DIM: t}).sel({MEMBER_DIM: m}).values
    lats = DS[model][LAT_NAME].values
    lons = DS[model][LON_NAME].values
    
    lons, lats = lonlat_to_web_mercator(lons, lats)
    
    # sp = ds[DEFAULT_VECTOR_VAR].isel({TIME_DIM: t}).sel({MEMBER_DIM: m}).values / 100.
    
    # vmin = np.nanmin(sp)
    # vmax = np.nanmax(sp)
    # delta = 10  # contour every 15 units
    # levels = np.arange(np.floor(vmin / delta) * delta,
    #                    np.ceil(vmax / delta) * delta + 1,
    #                    delta)
        
    X, Y = np.meshgrid(lons, lats)
    
    if var == 'swh':
        cmap, norm = get_wave_cmap()
    else:
        cmap, norm = get_wind_cmap()

    # Matplotlib figure to buffer
    fig = plt.figure(figsize=(6,4), dpi=100)
    ax = plt.axes(projection=ccrs.Mercator())
    
    # Plot the data in lat/lon
    # pc = ax.imshow(da, origin="lower", extent=[lons.min(), lons.max(), lats.min(), lats.max()], cmap=cmap, norm=norm,)# transform=ccrs.PlateCarree())
    pc = ax.pcolormesh(lons, lats, da, cmap=cmap, norm=norm,)# transform=ccrs.PlateCarree())
    # pc = ax.contourf(X, Y, da, cmap=cmap, norm=norm,)# transform=ccrs.PlateCarree())
    # cs = ax.contour(lons, lats, da, colors='white',)# transform=ccrs.PlateCarree())
    # cs = ax.contour(lons, lats, sp, levels=levels, colors='white')# transform=ccrs.PlateCarree())
    
    ax.axis('off')
    plt.axis("off")

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")



def discrete_cmap_hex(
    cmap_name: str,
    n: int,
):
    """
    Return n discrete colors sampled from a matplotlib colormap as hex strings.
    """
    cmap = plt.get_cmap(cmap_name, n)
    return [mcolors.to_hex(cmap(i)) for i in range(n)]


COLORS = discrete_cmap_hex("nipy_spectral", len(reports))

def create_report_overlays(
    reports,
    valid_time=0,
):
    overlays = []

    for i, (report, color) in enumerate(zip(reports, COLORS)):
        overlays.append(
            dl.Overlay(
                id=f"overlay-{i}",
                children=dl.GeoJSON(
                    id=f"route-geojson-{i}",
                    data=route_to_geojson(
                        report,
                        valid_time=valid_time,
                        color=color,
                    ),
                    pointToLayer=point_to_layer,
                    style=style_func,
                    zoomToBounds=False,
                ),
                name=(
                    f"{report['model']} "
                    f"{report['init_fac']} "
                    f"{report['vessel'][3:]} "
                    f"{report['fuel']:.1f} "
                    f"m{report['member']}"
                ),
                checked=bool(report["solve"]),
            )
        )

    return overlays


# def create_report_overlays(reports, valid_time=0):
#     overlays = []
#     for i, report in enumerate(reports):
#         overlays.append(
#             dl.Overlay(
#                 id=f"overlay-{i}",
#                 children=dl.GeoJSON(
#                     id=f"route-geojson-{i}",
#                     data=route_to_geojson(report, valid_time=valid_time),
#                     pointToLayer=point_to_layer,
#                     style=style_func,
#                     zoomToBounds=False,
#                 ),
#                 name=f"{report['model']} {report['init_fac']} {report['vessel'][3:]} {report['fuel']:.1f}",
#                 checked=True  # Overlay visible by default
#             )
#         )
#     return overlays


image_bounds = [[40.712216, -74.22655], [40.773941, -74.12544]]

# Prepare dropdown variables
varlist = vars_available
initial_raster = DEFAULT_RASTER_VAR if DEFAULT_RASTER_VAR in RASTER_VARS else RASTER_VARS[0]
initial_quiver = DEFAULT_QUIVER_VAR if DEFAULT_QUIVER_VAR in QUIVER_VARS else QUIVER_VARS[0]

iconUrl = "/assets/icons/ic--sharp-keyboard-arrow-up.png"
size = np.array([512, 512])/10
marker = dict(rotate=True, markerOptions=dict(icon=dict(iconUrl=iconUrl, iconSize=size, iconAnchor=size/2)))

patterns = [
    dict(repeat="10", dash=dict(pixelSize=5, pathOptions=dict(color="#fff", weight=1, opacity=0.9))),
    dict(offset="0%", repeat="10%", marker=marker),
]
rotated_markers = dl.PolylineDecorator(
    id="route",
    positions=reports[0]["pos"],
    patterns=patterns,
)

app.layout = dmc.MantineProvider(
    id="mantine-provider",
    children=[
        dcc.Store(id="theme-store", data="light"),
        
        dcc.Store(id="model-store",),
        dcc.Store(id="product-store",),
        dcc.Store(id="dataset-store"),
        
        dmc.Drawer(
            title="OPTIONS",
            id="options-drawer",
            padding="md",
            position="right",
            children=dmc.Stack(
            )
        ),
        
        dmc.Paper([
            dmc.Group([
                dmc.Group([
                
                    dmc.Select(id="model-select", data=[{"label": v, "value": v} for v in MODELS], value=MODELS[0], w=200, label="Model", allowDeselect=False),
                    dmc.Select(id="product-select", data=[{"label": v, "value": v} for v in [PRODUCT]], value=PRODUCT, w=200, label="Product", allowDeselect=False, disabled=(PRODUCT != "enfo")),
                    # dmc.Select(id="product-select", data=[{"label": v, "value": v} for v in PRODUCTS[MODELS[0]].keys()], value=list(PRODUCTS[MODELS[0]].keys())[0], w=200, label="Product", allowDeselect=False),
                    dmc.NumberInput(id="member-select", value=1, min=1, max=50, w=75, label="Member", disabled=(PRODUCT != "enfo")),
                    
                    # dmc.ActionIcon([dmc.Paper(DashIconify(icon="material-symbols:downloading", width=25))], id="save-toggle", variant="transparent", size="lg", color="yellow"),
                    
                ]),
                dmc.Group([
                    dmc.Select(id="raster-var", data=[{"label": v, "value": v} for v in RASTER_VARS], value=initial_raster, w=150, label="Scalar variable", allowDeselect=False),
                    dmc.Select(id="quiver-var", data=[{"label": v, "value": v} for v in QUIVER_VARS], value=initial_quiver, w=150, label="Directional component", allowDeselect=False),
                    
                    # dmc.Image(id="neoline-logo", src="/assets/img/Logo_Neoline_Grand_Picto_RVB.png", w=140),
                    # dmc.ActionIcon([dmc.Paper(DashIconify(icon="line-md:cog-filled", width=25))], id="options-toggle", variant="transparent", size="lg", color="yellow"),
                    # theme_toggle,
                
                ]),
            ], grow=True),
            
            dmc.Stack([
                dmc.Group(
                    children=[
                        dmc.Slider(
                            id="time-slider", min=0, max=n_time-1, step=1, value=0,
                            size="lg", radius="xs",
                            showLabelOnHover=True, labelAlwaysOn=True,
                            marks=marks,
                            # marks = [
                            #     {"value":i, "label":t.strftime("%b %d")}
                            #     for i, t in enumerate(pd.to_datetime(ds[TIME_DIM].values))
                            #     if t.hour == 0 and t.minute == 0 and t.second == 0
                            # ],
                            updatemode="drag"
                        ),
                    ],
                    grow=True
                ),
                
                dmc.Group([
                    dmc.Text(f"Forecast time: {str(DS[MODELS[0]].time.data)[:16]}"),
                    dmc.Text("Valid time: -", id="fxx-valid-time",),
                ]),
            ]),
        ]),
        # ], style={"position":"relative","zIndex":"400","background":"rgba(255,255,255,0.9)","padding":"10px","margin":"10px","borderRadius":"6px"}),
        
        dmc.Divider(),
        
        dmc.Group(
            dl.Map(
                id="map",
                center=[45., -40.],
                zoom=5,
                children=[
                    dl.FeatureGroup([
                        dl.EditControl(id="edit_control"),
                        dl.MeasureControl(id="control"),
                    ]),
                    dl.ScaleControl(position="bottomleft"),
                    dl.LayersControl([
                        dl.BaseLayer(dl.TileLayer(  # base layer
                            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                            attribution="© OpenStreetMap contributors"
                        ), name="base map"),
                        dl.Overlay(dl.ImageOverlay(
                            id="raster",
                            url=f"/raster.png?var={initial_raster}&time=0",
                            bounds=[
                                [float(DS[MODELS[0]][LAT_NAME].min()), float(DS[MODELS[0]][LON_NAME].min())],
                                [float(DS[MODELS[0]][LAT_NAME].max()), float(DS[MODELS[0]][LON_NAME].max())],
                            ],
                            zIndex=1,
                        ), name="contour", checked=True),
                        # Overlay layer: nautical chart from OpenSeaMap
                        dl.Overlay(dl.TileLayer(
                            url="https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
                            attribution="© OpenSeaMap contributors",
                            zIndex=10,
                        ), name="seamark"),
                        dl.Overlay(dl.TileLayer(
                            url="https://tiles.openseamap.org/harbour/{z}/{x}/{y}.png",
                            attribution="© OpenSeaMap contributors",
                            zIndex=10,
                        ), name="harbour"),
                        dl.Overlay(dl.TileLayer(
                            url="https://tiles.openseamap.org/light/{z}/{x}/{y}.png",
                            attribution="© OpenSeaMap contributors",
                            zIndex=10,
                        ), name="lights"),
                        dl.Overlay(dl.TileLayer(
                            url="https://tiles.openseamap.org/lock/{z}/{x}/{y}.png",
                            attribution="© OpenSeaMap contributors",
                            zIndex=10,
                        ), name="locks"),
                        # dl.TileLayer(id="tile-layer", url="/tiles/{z}/{x}/{y}.png?var={var}&time={time}"),
                        dl.Overlay(countries_layer, name="borders", checked=True),
                        dl.Overlay(dl.GeoJSON(id="field", options=dict(style=dict(color="white", weight=.5))), name="field", checked=True),
                        dl.Overlay(dl.GeoJSON(id="arrows", options=dict(style=dict(color="white", weight=2.5, opacity=0.75))), name="arrows", checked=True),
                        
                        dl.Overlay(
                            dl.ImageOverlay(
                                url="/assets/noaa_overlay.png",
                                bounds=[[65.15, -100], [14.4, 10]],
                                opacity=1.0,
                            ),
                            name="Latest NOAA SFC", checked=False,
                        ),
                        dl.Overlay(
                            dl.ImageOverlay(
                                url="https://modeles20.meteociel.fr/satellite/animsatirmtgalt.gif",
                                bounds=[[65.15, -100], [14.5, 10]],
                                opacity=1.0,
                            ),
                            name="EUMETSAT IR gif", checked=False,
                        ),
                        
                        dl.Overlay(
                            # dl.GeoJSON(
                            #     id="berg-limit",
                            #     data=berg_geojson,
                            # ),
                            # dl.Polyline(positions=polygon, fill=True, color="#ff0000", fillOpacity=0.2),
                            dl.Polyline(positions=polygon[:-3], fill=False, color="#ff0000", fillOpacity=0.2),
                            name="Iceberg limit", checked=True,
                            
                        ),
                        
                        # dl.Overlay(rotated_markers, id="active-route", checked=True),
                        
                        # dl.GeoJSON(
                        #     id="route-geojson",
                        #     data=route_to_geojson(reports[0], valid_time=0),
                        #     pointToLayer=point_to_layer,
                        #     style=style_func,
                        #     zoomToBounds=False,
                        # ),
                        
                        dl.Marker(
                            id="sensor", position=[45., -40.],
                            children=dl.Tooltip(id="sensor-tooltip", permanent=True, direction="left", className="weather-tooltip"),
                            draggable=True, interactive=True, bubblingMouseEvents=True,
                            # icon=DashIconify(icon="clarity:settings-line", width=200),
                            icon=weather_icon,
                        ),
                    ] + create_report_overlays(reports)
                    )
                ],
                style={"position":"relative", "width":"100%","height":"100%"},
            ),
            # style={"position":"absolute", 'width': '100%', 'height': '80vh', 'max-height': '80vh', "zIndex": "-1"},
            style={"position":"absolute", 'width': '100%', 'height': '100%', "zIndex": "-1"},
        ),
    ]
)


@app.callback(
    Output("sensor-tooltip", "children"),
    Input("member-select", "value"),
    Input("sensor", "clickData"),
    Input("time-slider", "value"),
    Input("model-select", "value"),
    State("sensor", "position"),
)
def display_data(m, click_data, time_index, model, pos):
    
    if click_data is not None:
        # print(click_data["latlng"])
        # pos = [lat, lon]
    
        lat = click_data["latlng"]["lat"]
        lon = click_data["latlng"]["lng"]
    
        # Extract variables (nearest-neighbour selection)
        # try:
        # subDs = ds.isel({"TIME_DIM":time}).sel({"longitude":lon, "latitude":lat}, method="nearest")
        subDs = DS[model].isel({TIME_DIM:time_index}).sel({MEMBER_DIM: m}).interp(longitude=[lon], latitude=[lat], method="linear")
        si10 = float(subDs["si10"].values.squeeze()) / 0.51444
        wdir10 = float(subDs["wdir10"].values.squeeze())
        swh = float(subDs["swh"].values.squeeze())
        mwd = float(subDs["mwd"].values.squeeze())
        
        # block = (
        #     # f"<b>Time:</b> {time}<br>"
        #     # f"<b>Lat:</b> {lat:.3f} | <b>Lon:</b> {lon:.3f}<br>"
        #     f"<b>TWS\t</b> {si10:.1f} kts<br>"
        #     f"<b>SWH\t</b> {swh:.1f} m"
        # )
        blocks = (
            f"{lat:7.3f}° {lon:7.3f}°",
            f"TWS {si10:4.1f} kts\n",
            f"TWD {wdir10:3.0f} deg\n",
            f"SWH {swh:4.1f} m",
            f"MWD {mwd:3.0f} deg",
        )
        
        # print(blocks)
        
        tt = html.Div([dmc.Text(t, size="xs", fw=100,) for t in blocks])
    
        return tt
    
    
# # Trigger mode (draw marker).
# @app.callback(Output("edit_control", "drawToolbar"), Input("draw_marker", "n_clicks"))
# def trigger_mode(n_clicks):
#     return dict(mode="marker", n_clicks=n_clicks)  # include n_click to ensure prop changes


# # Trigger mode (edit) + action (remove all)
# @app.callback(Output("edit_control", "editToolbar"), Input("clear_all", "n_clicks"))
# def trigger_action(n_clicks):
#     return dict(mode="remove", action="clear all", n_clicks=n_clicks)  # include n_click to ensure prop changes

# @app.callback(
#     [Output("route-geojson-0", "data") for i in range(len(reports))],
#     Input("time-slider", "value")
# )
# def update_time_index(time_index):
#     valid_time = ds.valid_time.data[time_index]
#     return (route_to_geojson(reports[0], valid_time=valid_time),)

@app.callback(
    [Output(f"route-geojson-{i}", "data") for i in range(len(reports))],
    Input("time-slider", "value"),
    Input("model-select", "value"),
)
def update_time_index(time_index, model):
    valid_time = DS[model].valid_time.data[time_index]
    updates = tuple(route_to_geojson(report, valid_time=valid_time, color=color) for report, color in zip(reports, COLORS))
    if len(reports) == 1:
        return updates[0]
    if len(reports) > 1:
        return updates
    

# TODO set product list from model first
# @app.callback(
#     Output("member-select", "disabled"),
    
#     Input("model-select", "value"),
#     Input("product-select", "value"),
# )
# def update_weather_model(model, product):
#     return not PRODUCTS[model][product]["ens"]


# @app.callback(
    
# )
# def load_weather_model():
#     pass

@app.callback(
    Output("raster", "url"),
    Input("member-select", "value"),
    Input("raster-var", "value"),
    Input("time-slider", "value"),
    Input("model-select", "value"),
)
def update_raster(m, var, time_index, model):
    return f"/raster.png?var={var}&time={time_index}&member={m}&model={model}"


@app.callback(
    Output("field", "data"),
    Input("member-select", "value"),
    Input("time-slider", "value"),
    Input("model-select", "value"),
)
def update_contour(m, time_index, model):
    url = f"/contour_field.geojson?var={DEFAULT_VECTOR_VAR}&time={time_index}&member={m}&model={model}"
    
    with server.test_request_context(url):
        resp = contour_field()
        return json.loads(resp.get_data(as_text=True))


@app.callback(
    Output("fxx-valid-time", "children"),
    Input("time-slider", "value"),
    Input("model-select", "value"),
)
def update_valid_time(time_index, model):
    vt = pd.to_datetime(DS[model].valid_time.data[time_index], unit="s").strftime("%Y-%m-%dT%H:%M")
    return f"Valid time: {vt}"


@app.callback(
    Output("arrows", "data"),
    Input("member-select", "value"),
    Input("quiver-var", "value"),
    Input("time-slider", "value"),
    Input("model-select", "value"),
    Input("map", "zoom"),
)
def update_arrows(m, qvar, time_index, model, zoom):
    
    density=density_from_zoom(zoom)
    
    url = (
        f"/wind_arrows.geojson"
        f"?time={time_index}&qvar={qvar}&density={density}&member={m}&model={model}"
    )

    with server.test_request_context(url):
        resp = wind_arrows()
        return json.loads(resp.get_data(as_text=True))


if __name__ == "__main__":
    app.run(debug=True, port=8053)
# -*- coding: utf-8 -*-
"""
Created on Tue Feb 24 14:04:33 2026

@author: jrich
"""


import pandas as pd
import architeuthis.numpy as np

from architeuthis.vessel import Vessel
from architeuthis.core import RoutingAnalysis, Voyage, DEFAULT_SOLVER_OPTIONS, exclusion_zones
from architeuthis.forecast import DeterministicHerbieForecast, CopernicusForecast, Topography


def draw(reports, barbs=True):
        
    from plot_utils import plot_route

    # cvtim = pd.to_datetime(self.report["ctim"], unit="s")
    # vtim = pd.to_datetime(self.report["tim"], unit="s")
    
    lons = [r["lon"] for r in reports]
    lats = [r["lat"] for r in reports]
    clons = [r["clon"] for r in reports]
    clats = [r["clat"] for r in reports]
    tws = [r["tws"] for r in reports]
    twd = [r["twd"] for r in reports]
    
    plot_route(lons, lats, clons, clats, tws, twd, barbs)
    
def get_steps(report, quantity):
    
    tim = pd.to_datetime(report["tim"], unit="s")
    
    X = []
    Y = []
    for i in range(len(report["ctim"])):
        X.append(tim[i])
        X.append(tim[i+1])
        Y.append(report[quantity][i])
        Y.append(report[quantity][i])
        
    return np.asarray(X), np.asarray(Y)
        
# minimum_longitude=-80.
# maximum_longitude=0.
# minimum_latitude=30.
# maximum_latitude=60.

# minimum_longitude=-80.
# maximum_longitude=-50.
# minimum_latitude=35.
# maximum_latitude=50.

minimum_longitude=-61.
maximum_longitude=-53.
minimum_latitude=44.
maximum_latitude=48.


steps = list(range(0, 145, 3)) + list(range(150, 361, 6))
    
#%% BUILD VESSEL INTERPOLATORS

vessel_files = [
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff70.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff90.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff100.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff45.nc",
    r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff60.nc",
    # r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_6m_eff70.nc",
]

columns = ["bhp", "max_bhp", "leeway"]

vessels = []

# maxBHP = 4000.
maxBHP = 3000.

for i, vessel_data in enumerate(vessel_files):
    vessel = Vessel(f"vessel_{i}", filepath=vessel_data, sfc=224., hotel_load=200., max_power=3100.)
    # vessel = Vessel(f"vessel_{i}", filepath=vessel_data, sfc=196., hotel_load=172., max_power=4100.)
    vessel.load_data()
    
    vessel.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("max_bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    # vessel.add_interpolator("leeway", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("sails_contribution", "stw", "tws", "twa", "hs", "wa", method="linear")
    
    vessels.append(vessel)

#%% BUILD WIND INTERPOLATORS


# mirror_date = pd.Timestamp('2025-12-17 12:00')
# mirror_end = pd.Timestamp('2025-12-21 12:00')

ATMOS = {}

import xarray as xr
from herbie import FastHerbie, Herbie, HerbieLatest

# recent = pd.Timestamp("now").floor("1h") - pd.Timedelta("1h")
recent = HerbieLatest(
    model="hrdps",
    product="continental",
    variable="TMP",
    level="AGL-2m"
).valid_date

store = []
for var, lev in zip(["UGRD", "VGRD"], ["AGL-10m", "AGL-10m"]):
    _fh = FastHerbie(
        [recent],
        model="hrdps",
        fxx=list(range(0,48+1,1)),
        product="continental",
        variable=var,
        level=lev,
    )
    
    _paths = _fh.download()
    
    _ds = a = xr.open_mfdataset(
        _paths,
        engine="cfgrib",
        decode_timedelta=False,
        decode_times=True,
        combine="nested",
        concat_dim=["valid_time"],
        coords="different",
        compat="no_conflicts",
    )
    
    store.append(_ds)

ds = xr.merge(store)

#%%

import xarray as xr
import pyproj

# --- 1) Retrieve CRS ---------------------------------------------------------

src_crs = Herbie(
    recent,
    model="hrdps",
    fxx=0,
    product="continental",
    variable="TMP",
    level="AGL-2m",
).xarray().herbie.crs

dst_crs = pyproj.CRS("EPSG:4326")   # Geographic lat/lon

transformer = pyproj.Transformer.from_crs(
    dst_crs,
    src_crs,
    always_xy=True
)

skip = 5

nx = ds.sizes["x"]
ny = ds.sizes["y"]

lat_raw = ds.latitude[::skip,::skip]
lon_raw = ds.longitude[::skip,::skip]

x_raw, y_raw = transformer.transform(lon_raw, lat_raw)

# plt.pcolormesh(
#     # ds.longitude[::skip,::skip],
#     # ds.latitude[::skip,::skip],
#     x_target, y_target,
#     ds.u10[0,::skip,::skip]
# )


# --- 2) Define regular lat/lon target grid ---------------------------------

dlat = 0.0225 # ~2.5 km
dlon = 0.0225 # ~2.5 km
# dlat = 0.25 # ~2.5 km
# dlon = 0.25 # ~2.5 km

# minimum_longitude=-61.
# maximum_longitude=-53.
# minimum_latitude=44.
# maximum_latitude=48.

# minimum_longitude=-58.118
# maximum_longitude=-54.646
# minimum_latitude=45.903
# maximum_latitude=47.761


LAT = np.arange(minimum_latitude, maximum_latitude + dlat, dlat)
LON = np.arange(minimum_longitude, maximum_longitude + dlon, dlon)

lon2d, lat2d = np.meshgrid(LON, LAT)

# --- 3) Project into native CRS ------------------------------

x_target, y_target = transformer.transform(lon2d, lat2d)

x_target = (x_target - x_raw.min()) / (x_raw.max() - x_raw.min()) * nx
y_target = (y_target - y_raw.min()) / (y_raw.max() - y_raw.min()) * ny

x_da = xr.DataArray(
    x_target,
    dims=("lat_new", "lon_new"),
    coords={"lat_new": LAT, "lon_new": LON},
)

y_da = xr.DataArray(
    y_target,
    dims=("lat_new", "lon_new"),
    coords={"lat_new": LAT, "lon_new": LON},
)

# --- 4) Interpolate ------------------------------------------

ds_interp = ds.interp(
    x=x_da,
    y=y_da,
    method="linear"
)

# --- 5) Remove old 2D lat/lon fields ------------------------

ds_interp = ds_interp.drop_vars(["latitude", "longitude"], errors="ignore")

# --- 6) Rename cleanly to CF convention ----------------------

ds_out = (
    ds_interp
    .rename({"lat_new": "latitude", "lon_new": "longitude"})
    .transpose("valid_time", "latitude", "longitude")
)


# for t in ds_out.valid_time[:3]:

#     plt.figure()

#     ds_out.herbie.with_wind()["si10"].sel(valid_time=t).plot(vmin=0, vmax=20, cmap="plasma")

#     plt.title(f"wdir10 – {str(t.values)}")
#     plt.xlabel("x")
#     plt.ylabel("y")

#     plt.tight_layout()
#     plt.show()

#%% BUILD ATMOS INTERPOLATORS

steps=list(range(0, 48+1, 1))

atmos = DeterministicHerbieForecast(
    # "wind_hrdps", model="hrdps", product="continental", regex=r"(?:U|V)GRD:AGL-10m", fxx=steps,
    "wind_hrdps", model="gfs", product="pgrb2b.0p25", regex=r"(?:U|V)GRD:AGL-10m", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    # date=mirror_date
)

# atmos.load_data()

# self._locate_data()
# self._download_data()
# self._read_data()
atmos.data = ds_out
atmos._convert_data()
atmos._extend_data()

atmos.add_interpolator("u10", "valid_time", "latitude", "longitude")
atmos.add_interpolator("v10", "valid_time", "latitude", "longitude")


#%% BUILD WAVE INTERPOLATORS

# IFS ocean data
wave = DeterministicHerbieForecast(
    "wave", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=steps,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    # date=mirror_date
)
wave.load_data()

wave.add_interpolator("swh", "valid_time", "latitude", "longitude")
wave.add_interpolator("mwd", "valid_time", "latitude", "longitude")


#%% BUILD CURRENT INTERPOLATORS

# Mercator SMOC data
current = CopernicusForecast(
    "current", dataset="cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", variables=["uo", "vo"],
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    # date=mirror_date, end=mirror_end
)
current.load_data()

current.add_interpolator(
    "uo", "valid_time", "latitude", "longitude",
    latitude_slice=slice(None, None, 3),
    longitude_slice=slice(None, None, 3),
    time_slice=slice(None, None, 3),
)
current.add_interpolator(
    "vo", "valid_time", "latitude", "longitude",
    latitude_slice=slice(None, None, 3),
    longitude_slice=slice(None, None, 3),
    time_slice=slice(None, None, 3),
)


#%% BUILD TOPOGRAPHY

topo = Topography(
    "topo", depth_offset=0., z_margin=0.,
    min_lon=minimum_longitude, max_lon=maximum_longitude,
    min_lat=minimum_latitude, max_lat=maximum_latitude,
    exclusion_zones=exclusion_zones,
)
topo.load_data()

topo.add_interpolator(
    "distance_to_iso0",
    "latitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
    "longitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
    var_key="z"
)

#%%

# departure = np.array([47.73378179825826, -4.581298828125]) # Montoir pilot
# departure = np.array([47.823964087925354, -4.772235284069338]) # pos 06/02/2026 10h00 UTC
# departure = np.array([53.418611, -22.285278]) # pos 09/02/2026 10h00 UTC
# departure = np.array([53.130556, -38.120833]) # pos 11/02/2026 12h15 UTC
# departure = np.array([50.453056, -42.795278]) # pos 12/02/2026 10h00 UTC
# departure = np.array([47.595000, -47.963333]) # pos 13/02/2026 10h50 UTC
# departure = np.array([44.117702, -60.907898]) # pos 16/02/2026 00h00 UTC
# arrival = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit

# departure = np.array([46.781, -56.091]) # SPM pilot
# departure = np.array([36.995605446063365, -75.94119037659861]) # Chesapeake exit
# departure = np.array([37.38330548509701, -74.4866180419922]) # pos 20/02/2026 17h00 UTC
# departure = np.array([43.248056, -62.397778]) # pos 23/02/2026 09h20 UTC
# arrival = np.array([47.112116788143474, -2.4051169026612866]) # Montoir pilot
departure = np.array([45.751500, -59.138333])
# departure = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# arrival = np.array([46.50781973122021, -53.33670295591693]) # Cape Race
# departure = np.array([46.781, -56.091]) # SPM pilot
# wp = np.array([46.551, -53.321]) # cape race
wp = np.array([46.166667, -46.916667]) # iip 23/02/2026
wp = np.array([47.211515697578854, -56.282075043080724]) # North Miquelon
arrival = np.array([46.781, -56.091]) # SPM pilot

from geo_utils import poly_deviated_route

# lats = [departure[0], 47.673, 46.560, arrival[0]]
# lons = [departure[1], -4.896, -53.033, arrival[1]]
# divs = [0., -0.5, 0.]
lats = [departure[0], wp[0], arrival[0]]
lons = [departure[1], wp[1], arrival[1]]
divs = [-0.5, 0.]
routeN = poly_deviated_route(lats, lons, divs)

lats = [departure[0], wp[0], arrival[0]]
lons = [departure[1], wp[1], arrival[1]]
divs = [0., 0.]
routeO = poly_deviated_route(lats, lons, divs)

lats = [departure[0], wp[0], arrival[0]]
lons = [departure[1], wp[1], arrival[1]]
divs = [0.5, 0.]
routeS = poly_deviated_route(lats, lons, divs)

# s = np.linspace(0, 1, 100)
# latN, lonN = routeN(s)
# latS, lonS = routeS(s)
# latO, lonO = routeO(s)


# etd = pd.to_datetime("2026-02-05T20:00").timestamp() # LT 21h ATD
# etd = pd.to_datetime("2026-02-06T10:00").timestamp() # 06/02/2026 10h00 UTC
# etd = pd.to_datetime("2026-02-09T10:00").timestamp() # 09/02/2026 01h30 UTC
# etd = pd.to_datetime("2026-02-11T12:15").timestamp() # 11/02/2026 12h15 UTC
# etd = pd.to_datetime("2026-02-12T10:00").timestamp() # 12/02/2026 10h00 UTC
# etd = pd.to_datetime("2026-02-13T10:50").timestamp() # 13/02/2026 10h50 UTC
# etd = pd.to_datetime("2026-02-20T10:30").timestamp()
# etd = pd.to_datetime("2026-02-20T17h00").timestamp() 
etd = pd.to_datetime("2026-02-24T20h00").timestamp()
# etd = pd.to_datetime("2026-02-26T06h00").timestamp()
# etd = pd.to_datetime("2026-02-16T00:00").timestamp() # 16/02/2026 00h00 UTC
# eta = pd.to_datetime("2026-02-25T11:00").timestamp()
# eta = pd.to_datetime("2026-02-18T22:00").timestamp() # LT 17h

solver_options = DEFAULT_SOLVER_OPTIONS

reports = []

from itertools import product

zero_fac = 0.

# models = ["ifs", "gfs"]
models = ["ifs",]
# facs = np.asarray([-1., 0., 1.]) + zero_fac
facs = [zero_fac]
# topos = [topo]
# topos = [topo0 ,topo]

# members = None
members = [1]
# members = list(range(1,51,1))

etas = [
    # pd.to_datetime("2026-03-07T06:00").timestamp(),
    # pd.to_datetime("2026-02-24T17:00").timestamp(),
    pd.to_datetime("2026-02-25T20:00").timestamp(),
]

# for m, fac in product(list(range(1,51,1)), facs):
# for m, fac in product(list(range(1,51,51)), facs):
for solve, vessel, model, fac, eta, m in (
        list(
            product([0], vessels, models, [zero_fac], etas, [1]) # NOT SOLVED ortho cst speed refs
        ) + list(
            product([1], vessels, models, facs, etas, members) # SOLVED
        )
    ):
    
    analysis = RoutingAnalysis(
        "analysis",
        vessel,
        Voyage(
            name="voyage",
            etd = etd,
            eta = eta,
            departure = departure,
            arrival = arrival,
            route_minus=routeS,
            route_ortho=routeO,
            route_plus=routeN,
        ),
        # ATMOS[model],
        atmos,
        # atmos_ens,
        wave,
        # wave_ens,
        current,
        topo,
        # atmosphere_member=m,
        # wave_member=m,
    )
    
    report = analysis.run(
        max_iter=2000,
        init_fac=fac,
        # init_fac=-1.,
        # init_fac=-0.5,
        # init_fac=0,
        # init_fac=0.5,
        # init_fac=1.,
        # init_fac=1.5,
        # init_fac=2.,
        # vary_fac=0,
        vary_fac=1,
        solver_options = {
            "ipopt":{
                "acceptable_tol": 1e9,
                # 'linear_solver': 'spral',
                'linear_solver': 'mumps',
                "hessian_approximation": "limited-memory",
            },
        },
        # solve=0,
        solve=solve,
    ) # TODO report should probably be a class of its own
    
    report["solve"] = solve
    report["model"] = model
    report["vessel"] = vessel.path[79:-3]
    report["member"] = m
    
    ctime = pd.to_datetime(report["ctim"], unit="s")
        
    # plt.clf()
    # # plt.scatter(ctime, unit="s"), report["avg_bhp"])
    # plt.plot(*get_steps(report, "avg_bhp"))
    # plt.plot(*get_steps(report, "max_bhp"))
    # plt.plot(*get_steps(report, "swh"))
    # # plt.plot(ctime, report["sails_contribution"])
    # # plt.plot(ctime, report["sails_contribution"])
    # plt.xticks(rotation=45)
    # plt.tight_layout()
    # plt.show()
    
    print(f"{pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')} - {pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}")
    print(f"fuel = {report['fuel']:.1f} t i.e. {report['fuel']/report['transit_time']*24.:.1f} t/day")
    
    # if report["status"] == 1:
    reports.append(report)

for report in reports:
    # print(f"{pd.to_datetime(report['etd'], unit='s').strftime('%d/%m %Hh%M UTC')} - {pd.to_datetime(report['eta'], unit='s').strftime('%d/%m %Hh%M UTC')}")
    print(f"{report['init_fac']}, {report['model']}")
    print(f"{report['dist']:.1f}, {report['dist_rel'] * 100 - 100:.1f}")
    print(f"{np.mean(report['sog']):.1f} {np.mean(report['sog']) / report['transit_sog'] * 100 - 100:.1f} ")
    print(f"fuel = {report['fuel']:.1f} t i.e. {report['fuel']/report['transit_time']*24.:.1f} t/day")
    print()
    
draw(reports, barbs=1)

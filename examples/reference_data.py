# -*- coding: utf-8 -*-
"""
Positions, waypoints, schedules, polars and alternative settings of past studies.

Nothing runs here and no example imports this file. It keeps what the examples used to hold in
commented-out lines, so that they stay readable: copy what you need into the settings of an
example. Positions are [lat, lon], times are in UTC.
"""

#%% PLACES

PLACES = {
    "Montoir pilot": [47.01483765543116, -2.63720447676916],
    "Montoir pilot (other position)": [47.112116788143474, -2.4051169026612866],
    "Montoir pilot (short_term_routing)": [47.73378179825826, -4.581298828125],
    "Lorient": [47.68366513909249, -3.5247528817988893],
    "Penmarc'h": [47.72529611513597, -4.379839003826363],
    "Penmarc'h (further offshore)": [47.79657767419367, -4.876263748342499],
    "SPM pilot": [46.781, -56.091],
    "North Miquelon": [47.211515697578854, -56.282075043080724],
    "Cape Race": [46.551, -53.321],
    "Cape Race (other position)": [46.50781973122021, -53.33670295591693],
    "Cape Henry, Chesapeake exit": [36.995605446063365, -75.94119037659861],
    "CAHAL": [44.517, -63.390],
    "BEZEE": [51.381, 3.107],
    "Calais": [51.066, 1.644],
    "Eastbourne": [50.610, 0.535],
    "Scilly": [49.665, -6.241],
}

# The leg in the Caribbean: departure, three waypoints and arrival.
CARIBBEAN_LEG = [
    [11.3196, -74.2835],
    [15.4358, -82.9951],
    [16.0791, -84.9973],
    [16.0810, -85.9931],
    [15.9927, -87.7219],
]

#%% POSITIONS REPORTED AT SEA, FOR RESTART = (position, time)

# The time is the one noted next to the position, in the format used then.
POSITION_REPORTS = [
    ("06/02/2026 10h00", [47.823964087925354, -4.772235284069338]),
    ("09/02/2026 10h00", [53.418611, -22.285278]),
    ("11/02/2026 12h15", [53.130556, -38.120833]),
    ("12/02/2026 10h00", [50.453056, -42.795278]),
    ("13/02/2026 10h50", [47.595000, -47.963333]),
    ("16/02/2026 00h00", [44.117702, -60.907898]),
    ("20/02/2026 17h00", [37.38330548509701, -74.4866180419922]),
    ("23/02/2026 09h20", [43.248056, -62.397778]),
    ("27/02/2026 14h00", [45.831667, -51.700000]),
    ("01/03/2026 14h00", [44.993333, -39.533333]),
    ("15/05 00h01", [45.3868773482704, -54.57870483398438]),
    ("01/06/2026 06h30", [43.612500, -11.603333]),
    ("01/06/2026 06h30", [42.216111, -15.564167]),
]

#%% WAYPOINTS AROUND THE IIP ICEBERG LIMIT, BY BULLETIN

IIP_WAYPOINTS = [
    ("23/02/2026", [46.166667, -46.916667]),
    ("25/02/2026", [45.750000, -46.750000]),
    ("25/02/2026, 0.50 deg margin", [45.250000, -46.750000]),
    ("27/02/2026", [45.250000, -48.500000]),
    ("27/02/2026", [45.166667, -45.916667]),
    ("27/02/2026, 0.25 deg margin", [44.916667, -46.916667]),
    ("09/03/2026, 0.50 deg margin", [45.916667 - 0.50, -44.166667]),
    ("09/03/2026, 0.50 deg margin", [45.333333 - 0.50, -49.500000]),
    ("16/03/2026", [45.166667, -45.583333]),
    ("16/03/2026", [44.916667, -51.583333]),
    ("31/03/2026, 0.50 deg margin", [46.333333 - 0.50, -46.416667]),
    ("13/05/2026", [41.416667, -50.750000]),
    ("13/05/2026", [41.583333, -46.750000]),
    ("15/05/2026", [41.666667, -50.583333]),
    ("15/05/2026", [41.916667, -47.833333]),
    ("28/05/2026", [44.66666, -43.75000]),
    ("28/05/2026", [44.66666, -50.33333]),
    ("28/05/2026, 1 deg margin", [44.66666 - 1.0, -43.75000]),
    ("28/05/2026, 1 deg margin", [44.66666 - 1.0, -50.33333]),
]

# Waypoints and divergences of a former short-term reference route.
FORMER_SHORT_TERM_ROUTE = {
    "lats": [None, 47.673, 46.560, None], # departure and arrival at both ends
    "lons": [None, -4.896, -53.033, None],
    "divergences": [0., -0.5, 0.],
}

#%% SCHEDULES

# Remarks are those noted next to each date. LT is local time and ATD the actual time of departure.
PAST_ETDS = [
    ("2026-02-05T20:00", "LT 21h ATD"),
    ("2026-02-06T10:00", ""),
    ("2026-02-09T10:00", "noted as 09/02/2026 01h30 UTC"),
    ("2026-02-11T12:15", ""),
    ("2026-02-12T10:00", ""),
    ("2026-02-13T10:50", ""),
    ("2026-02-16T00:00", ""),
    ("2026-02-20T10:30", ""),
    ("2026-02-20T17:00", ""),
    ("2026-02-23T09:20", ""),
    ("2026-02-26T06:00", ""),
    ("2026-02-26T20:00", "ATD"),
    ("2026-02-27T14:00", ""),
    ("2026-03-12T17:00", ""),
    ("2026-03-13T14:00", ""),
]

PAST_ETAS = [
    ("2026-02-18T22:00", "LT 17h"),
    ("2026-02-24T17:00", ""),
    ("2026-02-25T11:00", ""),
    ("2026-03-07T06:00", ""),
    ("2026-01-22T12:00", ""),
    ("2026-02-05T23:00", ""),
]

# (ETD, ETA)
PAST_TIMEFRAMES = [
    ("2026-08-07T07:00", "2026-08-12T11:00"),
    ("2026-08-07T17:00", "2026-08-12T11:00"),
    ("2026-08-13T07:00", "2026-08-22T11:00"),
    ("2026-10-16T00:00", "2026-10-26T05:00"),
    ("2026-11-05T11:00", "2026-11-15T10:00"),
]

# Forecast base times for replays, as `FORECAST_DATE` in post_leg_rewind.py.
PAST_FORECAST_DATES = ["2026-05-30 00:00", "2025-12-17 12:00"]
PAST_CURRENT_ENDS = ["2025-12-21 12:00"]

#%% DOMAINS, AS Domain(min_lon, max_lon, min_lat, max_lat)

DOMAINS = {
    "North Atlantic, from North America": (-80., 0., 30., 60.),
    "North Atlantic, from Newfoundland": (-60., 0., 30., 60.),
    "North Atlantic, to the Channel": (-70., 5., 30., 60.),
    "Western Atlantic": (-80., -50., 35., 50.),
    "Caribbean": (-90., -72., 9., 18.),
    "Saint-Pierre, HRDPS": (-61., -53., 44., 48.),
    "Saint-Pierre, close": (-58.118, -54.646, 45.903, 47.761),
}

#%% POLARS, IN ~/data/polars/

_POLAR = "neoliner_origin_v2-2-0_mc0_sc0_{}_eff{}.nc"

POLARS = [
    *(_POLAR.format("35up_28down_7buff_5m", eff) for eff in ("00", 15, 30, 45, 60, 75, 90, 92, 100)),
    *(_POLAR.format("28up_28down_7buff_5m", eff) for eff in (1, 30, 45, 60)),
    *(_POLAR.format("35up_28down_7buff_6m", eff) for eff in (45, 60, 70, 90, 100)),
    "neoliner_origin.nc",
    "polar_sails_2-2-0extrap.csv",
    "polar_sails_2-2-0extrap.nc",
    "output_sails.nc",
]

# A polar may hold other variables, such as the leeway, which routing does not use yet:
# vessel.add_interpolator("leeway", "stw", "tws", "twa", "hs", "wa", method="linear")

#%% VESSEL PERFORMANCE

MAX_POWERS = [3000., 3100., 4000., 4100.] # kW

# (sfc in g/kWh, hotel load in kW)
SFC_AND_HOTEL_LOAD = [(196., 172.), (220., 194.), (224., 200.)]

# Fits against the power, in kW, for `presets.vessel(sfc=..., hotel_load=...)`: `a + b x + c x^2 + d x^3`.
SFC_FIT = {
    "a": 325.7684374001559,
    "b": -0.13133435575556507,
    "c": 5.216985806784128e-05,
    "d": -6.660802866517442e-09,
}
HOTEL_LOAD_FIT = {
    "a": 177.84810351574922,
    "b": -0.011382017491188723,
    "c": 1.0915372379294297e-05,
}
# The fit of the SFC was limited in two ways, depending on the script:
# np.abs(fit(x)), and np.fmax(fit(x), 200.)

#%% WIND

# Speed correction of global models: 120 % at 10 m, 105 % at 100 m was noted, and 115 % at 10 m.
WIND_FACTORS = [1.0, 1.10, 1.20]

# Ratio of gust to mean wind, presets.atmosphere(gust_factor=...), by default common.GUST_DEFAULT_RATIO:
# https://cimmse.wordpress.com/2013/09/20/a-wind-gust-factor-database-of-marine-observations-from-10-tropical-cyclones-2/
GUST_FACTOR = 1.23

# Forecasts written by hand, for what presets do not offer:
#
# atmos = DeterministicHerbieForecast("wind", model="ifs", product="scda", regex=r":10[u|v]:", fxx=steps, **domain)
#
# Ensemble with explicit strides, in addition to presets.ensemble_atmosphere(stride=2):
# atmos_ens.add_interpolator(
#     "u10", "valid_time", "number", "latitude", "longitude",
#     member_slice=slice(None, None, 1),
#     time_slice=slice(None, None, 1),
#     latitude_slice=slice(None, None, 2),
#     longitude_slice=slice(None, None, 2),
#     fac=global_corr_fac,
# )
#
# Reading an ensemble along a route with xarray rather than with its interpolators, which were
# noted as unbeatable in terms of speed (see plot_utils.plot_ensemble_along_route):
# environment_query = xr.Dataset({
#     "valid_time": ("points", r["ctim"]),
#     "latitude": ("points", r["clat"]),
#     "longitude": ("points", r["clon"]),
# })
# atmos_meteogram = atmos_ens.data.interp(environment_query, assume_sorted=1, method="linear")

#%% EXCLUSION ZONES AND TOPOGRAPHY

# Water treated as land, presets.topography(depth_offset=...), in m.
DEPTH_OFFSETS = [0., -10., -30.]

# Source of the ECA polygons, to read with ExclusionZone.from_geojson(path, "north-american-atlantic"):
ECA_SOURCE = "https://rynda.io/blog/eca-zones/polygons.geojson"

# A zone to avoid around Nova Scotia and the Gulf of St. Lawrence. To use it:
# ExclusionZoneLibrary().save(ExclusionZone("safety", SAFETY_MARGIN, label="Safety margin"))
SAFETY_MARGIN = [
    [49.22829272317526, -65.94945285687805],
    [49.24967849277576, -65.39454839496966],
    [49.20186222198922, -64.93405476164935],
    [49.083381013855586, -64.56026495050253],
    [48.85022124091634, -64.18991833941845],
    [48.03336057443036, -64.51390925616687],
    [47.066624624398145, -63.993876030092224],
    [46.87986733827569, -63.96650586029921],
    [46.7237379730156, -64.01212280995423],
    [46.56088271827619, -63.62894043284655],
    [46.4289878564139, -63.03592008732295],
    [46.47298835466361, -61.9867302452418],
    [47.0293253396176, -60.49049429653593],
    [45.961665009785804, -59.82448683156247],
    [45.27657778932076, -60.967985667251355],
    [44.50354651869886, -63.50689818993442],
    [44.49479316788097, -63.923848320183765],
    [44.39849082233545, -64.25495577655852],
    [43.96316577728297, -64.69643238505847],
    [43.448999524918776, -65.41996349343276],
    [43.42228477857577, -65.6223069389946],
    [43.742083201791786, -66.10670488443196],
    [44.26691358799425, -66.41941748211889],
    [44.804283979142156, -66.98267130409891],
    [46.98328410288116, -70.61081256523659],
    [47.17147691449833, -70.31695921902707],
    [47.49485787111169, -70.01916204070096],
    [47.71202524104103, -69.69090833278551],
    [48.02077593848, -69.39311115445867],
    [48.312664113000466, -68.8980537433381],
    [48.644669201610526, -68.15356079752212],
    [49.13802862532202, -66.51780700843068],
    [49.22829272317526, -65.94945285687805],
]

#%% ROUTING SETTINGS

# Constraints tried, in `constraints(ctx)`:
#
# (wide(ctx["z"]) @ tall(ctx["z"])) == 0.
# ctx["aws_gust"] < 30.
# ctx["aws"] < 35.
# ctx["aws"] < 25.
# ctx["aws"] < 20.
# ctx["aws"] > 10.
# ctx["stw"] <= 20. # STW cap

# Starting points tried, `run(init_fac=...)`, and sets of them.
INIT_FACS = [-3., -1., -0.5, 0., 0.5, 1., 1.2, 1.5, 1.75, 2., 3.]
INIT_FAC_SETS = [[0., 1.], [-1., 0., 1.], [-0.3, 0., 0.3], [-0.9, -0.2, 0.2, 0.9]]

# Solver options tried: "acceptable_tol" 1e2 or 1e9, and "linear_solver" "mumps" or "spral".

# Labels of former routes, by init_fac:
# {-0.5: "North coast", 0.: "Ortho cst speed", 0.75: "North offshore", 3.: "South"}

#%% AN EXPERIMENT, TO FINISH

# Interpolating a forecast with modeling.InterpolatedModel rather than with add_interpolator.
# It does not work as it is: the call at the end fails.
#
# ds = ATMOS["ifs"].data
# interp = InterpolatedModel(
#     x_data_coordinates={
#         "valid_time": ds["valid_time"],
#         "latitude": ds["latitude"],
#         "longitude": ds["longitude"],
#     },
#     y_data_structured=ds["u10"].data,
#     method="linear", # or "bspline"
#     # fill_value=0.
# )
# n = 100
# clat, clon = route_ortho(np.linspace(0, 1, n))
# ctim = np.linspace(etd, eta, n)
# opti = Opti()
# interp({
#     "valid_time": ctim, # or opti.parameter(ctim)
#     "latitude": clat,
#     "longitude": clon,
# })

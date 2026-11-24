# User guide

The reference of Architeuthis: data sources, reports, figures, exclusion zones and the viewer. For installation and a first routing, see the [README](../README.md).

- [Data sources](#data-sources)
- [Keeping and reusing results](#keeping-and-reusing-results)
- [Plotting](#plotting)
- [Exclusion zones](#exclusion-zones)
- [Sharing routes](#sharing-routes)

## Data sources

[`examples/`](../examples/README.md) has one script per use, each with its settings at the top, and a skeleton of a routing script. Start with `examples/simple_routing.py`.

Each source is built explicitly with its class, then downloaded with `load_data`, and each variable that the routing queries is registered with `add_interpolator`. Dimensions must be given in the order of the array.

```python
from architeuthis.forecast import CopernicusForecast, DeterministicHerbieForecast, Topography
from architeuthis.vessel import Vessel

domain = dict(min_lon=-70., max_lon=5., min_lat=30., max_lat=60.)

atmosphere = DeterministicHerbieForecast("wind", model="ifs", product="oper", regex=r":10[u|v]:", fxx=steps, date=date, **domain)
atmosphere.load_data()
atmosphere.data["u10"] = atmosphere.data["u10"] * 1.2  # a correction of the wind speed, if you want one
atmosphere.data["v10"] = atmosphere.data["v10"] * 1.2
atmosphere.add_interpolator("u10", "valid_time", "latitude", "longitude")
atmosphere.add_interpolator("v10", "valid_time", "latitude", "longitude")

wave = DeterministicHerbieForecast("wave", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=steps, date=date, **domain)
wave.load_data()
wave.add_wave_components()  # the direction is interpolated through its components
wave.add_interpolator("swh", "valid_time", "latitude", "longitude")
wave.add_interpolator("uw", "valid_time", "latitude", "longitude")
wave.add_interpolator("vw", "valid_time", "latitude", "longitude")

current = CopernicusForecast("current", dataset="cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", variables=["uo", "vo"], date=date, **domain)
current.load_data()
current.add_interpolator("uo", "valid_time", "latitude", "longitude")
current.add_interpolator("vo", "valid_time", "latitude", "longitude")

topography = Topography("topography", exclusion_zones=zones, **domain)
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

vessel = Vessel("vessel", filepath="polar_eff45.nc", sfoc=220., hotel_load=194., max_power=4100.)
vessel.load_data()
for key in ("bhp", "max_bhp", "sails_contribution"):
    vessel.add_interpolator(key, "stw", "tws", "twa", "hs", "wa", method="linear")
```

| Class | Gives |
| --- | --- |
| `forecast.DeterministicHerbieForecast` | A deterministic forecast through Herbie: IFS, GFS and their wave models, chosen with `model`, `product` and `regex`. No account. |
| `forecast.EnsembleHerbieForecast` | The members of an ensemble, IFS for example. `add_interpolator` takes `var_dim, time_dim, member_dim, latitude_dim, longitude_dim`. No account. |
| `forecast.HRDPSForecast` | The 10 m wind of HRDPS continental, regridded on a regular grid, the latest run by default. Its wind direction is not reliable yet: the components are relative to the rotated grid of the model and are not rotated, about 45° off around Saint-Pierre-et-Miquelon. |
| `forecast.CopernicusForecast` | Currents and other products of Copernicus Marine. Needs an account, `CMEMS_USER` and `CMEMS_PWD`. |
| `forecast.CDSForecast` | ERA5 reanalysis. Needs an account, `CDS_API_KEY`. |
| `satellite.ASCATData` | ASCAT winds over a period and a box, to check forecasts against them: from EUMETSAT, else from Copernicus Marine. See [Satellite observations](#satellite-observations). |
| `satellite.GeostationaryImagery` | Cloud images every 10 min, Meteosat and GOES-East joined into one layer, in the infrared and the visible. No account. See [Satellite observations](#satellite-observations). |
| `forecast.Topography` | The signed distance to land and to your exclusion zones. It needs only its box, and `exclusion_zones` if you have some. |
| `vessel.Vessel` | A vessel, from its polar file, from functions (see [Polars as functions](#polars-as-functions)) or from constants. The routing only needs its consumption (see [Consumption](#consumption)). `label` comes from the file name by default, `eff45` for `..._eff45.nc`, or is the name without a file. |

The environment may be incomplete. `atmosphere`, `wave` and `current` are optional arguments of `RoutingAnalysis`, None by default, and each one left out is a calm source whose routing fields are zero: no wind (`u10`, `v10`), a flat sea (`swh`, `uw`, `vw`) or no current (`uo`, `vo`). `forecast.calm_forecast(source)` builds it: a `Forecast` without data whose models are these fields, functions of `valid_time`, `latitude` and `longitude` that return zeros independent of the query, so the routing takes no derivative of the undefined direction of a zero wind or sea. The time grid comes from the first source with data, the atmosphere normally, or is every 3 hours (`core.DEFAULT_TIME_STEP`) without any. The topography is required.

```python
analysis = RoutingAnalysis("analysis", vessel, voyage, atmosphere, topography=topography)  # no waves, no current
```

`examples/passage_planning.py` and `examples/function_polar_routing.py` route without current, and `examples/wind_only_routing.py` and `examples/vessel_definitions.py` with the wind only.

The wave direction is not interpolated itself, because it jumps from 360 to 0 deg. `wave.add_wave_components()` adds `uw = -swh**2 * sin(mwd)` and `vw = -swh**2 * cos(mwd)` to the data, the components of where the waves go weighted by their energy, and the routing takes the direction back from them, as for the wind. The weight lets the larger seas, not calm cells or land, set the direction between grid points. `swh` is still interpolated on its own for the height. For GFS, whose direction is `dirpw`, call `add_wave_components(mwd_dim="dirpw")`. The routing needs `swh`, `uw` and `vw`, and reports `mwd` as before.

Once registered, a variable is read by calling its source with a dict. The keys are standard names, whatever the names of the coordinates in the data: `valid_time`, `latitude` and `longitude` for forecasts, plus `member` for an ensemble, `latitude` and `longitude` for the topography, and `stw`, `tws`, `twa`, `hs` and `wa` for a vessel. `input_names(var_key)` gives them. Values are floats or arrays, NumPy or CasADi, broadcast against each other, and the result is a column.

```python
u10 = atmosphere("u10", {"valid_time": t, "latitude": lats, "longitude": lons})
z = topography("z", {"latitude": lats, "longitude": lons})
bhp = vessel("bhp", {"stw": 10., "tws": 15., "twa": 60., "hs": 2., "wa": 30.})
```

Keys that a variable does not take are ignored, so one query can serve several variables.

`add_interpolator` takes `method="linear"` (the default), `"bspline"`, smooth and suited to optimization, or `"nearest"`.

### Polars as functions

A table is one kind of model. `add_function(var_key, function, inputs, args=None, output=None)` registers a function instead: it is called as `function(x, **args)`, where `x` is a dict of its `inputs`, and `args` holds fixed arguments such as fitted parameters. Written with `architeuthis.numpy`, without `if` on values, it takes CasADi inputs and the routing differentiates through it. `output` picks the value when the function returns more: a key of a dict, a key of the dict of a `(value, components)` tuple, an index, or a function of the result. `add_model` registers any other object that is called with a dict and has an `input_names()` method.

A vessel defined by semi-empirical functions needs no polar file:

```python
from my_polars import propulsion_power, total_power, parameters

inputs = ["stw", "tws", "twa", "swh", "mwa", "mwp", "water_temperature"]

vessel = Vessel("vessel", sfoc=220., max_power=4100.)  # no filepath, no load_data
vessel.add_function("bhp", propulsion_power, inputs, args={"p": parameters})
vessel.add_function("max_bhp", total_power, inputs, args={"p": parameters})
vessel.add_function(
    "sails_contribution",
    propulsion_power,
    inputs,
    args={"p": parameters, "return_components": True},
    output=lambda result: -result[1]["aero_sails"],
)
```

The routing gives each vessel model the inputs it names. It computes `stw`, `sog`, `tws`, `twd`, `twa`, `hs` (or `swh`), `wa` (or `mwa`), `aws` and `awa`, angles relative to the COG in absolute value. The wind at another height is computed the same way from its components: an input `tws100`, `twd100`, `twa100`, `aws100` or `awa100` makes the routing read `u100` and `v100` (m/s) from the forecasts, so `atmosphere.add_interpolator("u100", ...)` and `"v100"` are all it takes; any height works. Any other input is a forecast variable, read at the middle of each segment from the first of `atmosphere`, `wave` and `current` that has a model with that key, so register it there under the name the vessel uses. A conversion is a function of the forecast itself:

```python
wave.add_interpolator("mwp", "valid_time", "latitude", "longitude")
current.add_interpolator("thetao", "valid_time", "latitude", "longitude", var_key="water_temperature")
atmosphere.add_interpolator("t2m", "valid_time", "latitude", "longitude")
atmosphere.add_function(
    "air_temperature",
    lambda x: atmosphere("t2m", x) - 273.15,
    inputs=["valid_time", "latitude", "longitude"],
)
```

A Herbie forecast may mix fields at different levels in one download, such as the IFS 10 m wind and 2 m temperature with `regex=r":(?:10[uv]|2t):"`.

`examples/function_polar_routing.py` routes a voyage with a dummy polar of this kind, which depends on `stw`, `tws`, `twa`, `swh`, `mwa` and the air temperature of IFS. It needs no polar file and no credentials.

Each vessel model is evaluated separately, so a function that computes all components is computed once per model the routing uses when the problem is built.

### Consumption

The objective is the fuel, in tonnes: the integral over the passage of the consumption in L/h, at the middle of each segment, times the fuel density in kg/L. Consumptions are volumes, in L/h, in `ctx`, the report, the tooltips and the figures; only the fuel of the voyage, `fuel`, is a mass, in tonnes. An `hourly_consumption` table or function gives litres per hour. The routing takes it from the first of these vessel models; the others, such as `max_bhp` or `sails_contribution`, are computed only when `variables` lists them.

| Model | Consumption, L/h | Report entries |
| --- | --- | --- |
| `hourly_consumption`, L/h | the model itself, a table or function in litres per hour | `hourly_consumption` |
| `total_power`, kW: propulsion and hotel | `total_power * sfoc / 1e3 / fuel_density` | `total_power`, `sfoc`, `hourly_consumption` |
| `bhp`, kW: propulsion | `(bhp + hotel_load) * sfoc / 1e3 / fuel_density` | `bhp`, `hotel_load`, `total_power`, `sfoc`, `hourly_consumption` |

Each model is a table, a function or a constant: `vessel.add_constant("bhp", 1500.)` registers a model without input. `hotel_load` (kW) and `sfoc` (g/kWh) are given to `Vessel` as numbers or as functions of the power, the brake power for `hotel_load` and the total power for `sfoc`. A model of the same key takes precedence, and may name `bhp`, `hotel_load` or `total_power` among its inputs, so an sfoc curve of the engine load is a table or a function of `total_power`:

```python
vessel = Vessel("vessel", hotel_load=180., max_power=4100.)
vessel.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa")
vessel.add_function("sfoc", lambda x: 175. + 2e-6 * (x["total_power"] - 3000.)**2, ["total_power"])
```

The fuel density, in kg/L, is `Vessel(fuel_density=...)`, from the bunker delivery note for example, else that of `fuel_type`, a key of `fuels.FUELS`, an alias of `fuels.FUEL_ALIASES` or a `fuels.Fuel` of your own: marine diesel oil at 0.85 kg/L by default. The passage plan metadata records both.

```python
vessel = Vessel("vessel", fuel_type="hfo", sfoc=180., hotel_load=180., max_power=4100.)  # 0.985 kg/L
vessel = Vessel("vessel", fuel_type="hfo", fuel_density=0.991, ...)                     # measured
vessel.fuel.co2(report["fuel"])            # t of CO2, tank to wake
vessel.fuel.ghg(report["fuel"])            # t of CO2 equivalent, well to wake (FuelEU Maritime)
```

| Key | Fuel | Density, kg/L | LCV, MJ/kg | CO2, g/g | Well to wake, gCO2e/MJ |
| --- | --- | --- | --- | --- | --- |
| `mdo` | Marine diesel oil (ISO 8217 DMB) | 0.85 | 42.7 | 3.206 | 90.8 |
| `mgo` | Marine gas oil (ISO 8217 DMA) | 0.85 | 42.7 | 3.206 | 90.8 |
| `lfo` | Light fuel oil (ISO 8217 RMA-RMD) | 0.93 | 41 | 3.151 | 91.4 |
| `hfo` | Heavy fuel oil (ISO 8217 RME-RMK) | 0.985 | 40.5 | 3.114 | 91.7 |
| `vlsfo` | Very low sulphur fuel oil, 0.5 % S (residual) | 0.94 | 40.5 | 3.114 | 91.7 |
| `lng` | LNG, Otto dual fuel medium speed engine | 0.45 | 49.1 | 2.75 | 89.2 |
| `lng_otto_slow` | LNG, Otto dual fuel slow speed engine | 0.45 | 49.1 | 2.75 | 82.9 |
| `lng_diesel` | LNG, diesel dual fuel slow speed engine | 0.45 | 49.1 | 2.75 | 76.1 |
| `lng_lbsi` | LNG, lean burn spark ignited engine | 0.45 | 49.1 | 2.75 | 86.9 |
| `lpg_propane` | LPG, propane | 0.51 | 46 | 3 | 73.0 |
| `lpg_butane` | LPG, butane | 0.58 | 46 | 3.03 | 73.7 |
| `methanol` | Methanol from natural gas | 0.792 | 19.9 | 1.375 | 100.4 |
| `ethanol` | Ethanol | 0.789 | 26.8 | 1.913 | – |
| `ammonia` | Ammonia from natural gas, liquid at -33 deg C | 0.682 | 18.6 | 0 | 121.0 |
| `hydrogen` | Hydrogen from natural gas, liquid at -253 deg C | 0.071 | 120 | 0 | 132.0 |
| `fame` | Biodiesel, FAME (EN 14214) | 0.88 | 37.2 | 2.834 | – |
| `hvo` | Hydrotreated vegetable oil (EN 15940) | 0.78 | 44 | 3.115 | – |
| `diesel` | Road diesel (EN 590) | 0.835 | 43 | 3.186 | – |
| `unleaded` | Unleaded petrol (EN 228) | 0.745 | 44.3 | 3.07 | – |

Factors of marine fuels are the default values of FuelEU Maritime (Regulation (EU) 2023/1805, Annex II, with GWP 25 for CH4 and 298 for N2O), and of road fuels those of the IPCC 2006 guidelines. A `Fuel` also has `cf_ch4`, `cf_n2o` and `methane_slip` (LNG by engine type), `wtt`, `ttw_intensity` and `wtw_intensity`, `energy_density` (MJ/L) and `biogenic`: FuelEU counts the combustion CO2 of sustainable biofuels as zero, and the well to tank of biofuels and road fuels, which depends on their production, is left as None. Densities are typical at 15 deg C (liquid for the gases); that of a delivery is on its bunker note. Check the factors against the regulation in force before any regulatory use.

`examples/vessel_definitions.py` compares five definitions of one vessel on a short-sea leg, without polar file or credentials: the brake power as a function or as a table, an sfoc curve of the total power, the total power, and the hourly consumption.

`vessel.consumption(query)` gives these quantities for a query, and `vessel.consumption_model` the model it uses. Without any of the three models, the routing raises an error that says so. Without `sfoc` when it is needed, it is still 0 g/kWh until 0.4.0, a zero objective, with a `DeprecationWarning`; from 0.4.0 this is an error too. The entries of the table are in the report and in `ctx`, so a constraint can limit the consumption or the total power. `sfc`, the former name of `sfoc`, still works with a `DeprecationWarning` until 0.4.0.

`max_power`, in kW, is the power limit of the default constraints: `max_bhp` when `variables` lists it, else `bhp`, else `total_power` stays below it. `max_power=None` leaves the power free. Left out, it is still 1e12 kW until 0.4.0, with a `DeprecationWarning`, and None from 0.4.0.

Until 0.4.0, `max_bhp` and `sails_contribution` are still computed when the vessel has these models and `variables` does not list them, with a `DeprecationWarning`, so that the default constraints and existing scripts work as before. List them to keep them from 0.4.0.

### Additional variables

The routing computes only what the objective and the vessel models need. `variables` asks for more quantities, which nothing has to use: they are computed at the middle of each segment, handed to the constraints in `ctx` and stored in the report under their name, so they can be limited, tabulated and plotted like `tws` or `swh`. The wind gust and the wave slope are typical: they do not enter the polar, but they measure comfort and safety.

```python
wave.add_interpolator("mwp", "valid_time", "latitude", "longitude")
wave.add_function(
    "slope",
    lambda x: wave("swh", x) / np.softmax(wave("mwp", x), 1., softness=0.1),
    inputs=["valid_time", "latitude", "longitude"],
)

analysis = RoutingAnalysis(
    "analysis", vessel, voyage, atmosphere, wave, current, topography,
    variables=[
        "max_bhp",                                                # a vessel model, kW
        "gust",                                                   # tws_gust and aws_gust, kt
        "slope",                                                  # read from the wave forecast
        {"gust_excess": lambda ctx: ctx["tws_gust"] - ctx["tws"]},
    ],
    constraints=lambda ctx: [
        ctx["max_bhp"] < ctx["vessel"].max_power,
        ctx["z"] < 0.,
        ctx["tws_gust"] < 45.,                                    # no gust over 45 kt
        ctx["gust_excess"] < 15.,                                 # nor 15 kt above the mean wind
        ctx["slope"] < 0.5,
    ],
)
report = analysis.run()
report.table(["tws", "tws_gust", "slope"])
```

`variables` is a name, a list of names, or a dict of names and specifications; a list may also hold such dicts. A name alone is its own specification. A specification is:

| Specification | Gives | Units |
| --- | --- | --- |
| `"gust"` | `tws_gust` and `aws_gust`, below | kt |
| a model key, such as `"slope"` or `"pres"` | the model of the first of `atmosphere`, `wave`, `current` and `vessel` that has this key | those of the model |
| a model key with its source, such as `"wave.slope"` or `"vessel.leeway"` | the model of that source; in a list, the variable is named without the prefix, `slope` | those of the model |
| `"tws_gust"` | the atmospheric model `gust` (m/s) converted to kt, or `tws * GUST_DEFAULT_RATIO` (1.23) when there is none | kt |
| `"aws_gust"` | the apparent wind of `tws_gust` | kt |
| a model key under another name, such as `{"gust_ms": "atmosphere.gust"}` | the model itself, the gust in m/s here | those of the model |
| `"tws100"`, `"twd100"`, `"twa100"`, `"aws100"`, `"awa100"`, at any height | the wind at that height from `u100` and `v100`, angles signed as `twa` | kt, deg |
| a routing quantity, such as `"tws"` | a copy of it, under another name in a dict | as reported |
| a callable `ctx -> expression` | any function of the quantities of the passage and of the variables listed before it; `ctx["vessel"]` is the vessel | yours |

Forecasts are queried at the time and position of each segment, with the ensemble member of the analysis, and vessel models with the inputs they name, found as for the polars. A model of a variable may thus be an interpolator or a function, of any data object. Write functions with `architeuthis.numpy`, and keep them smooth when a constraint uses them: the period above is kept away from zero, its value on land and past the forecast horizon.

`run(variables=...)` and `evaluate(variables=...)` add variables for one run or one evaluation to those of the analysis. `options={"include_gusts": ...}` is deprecated, with a `DeprecationWarning`, and will be removed in 0.4.0: list `"gust"` instead. Until then, an analysis without `options` still computes the gusts, and `options={}` leaves them out unless they are listed; from 0.4.0, they are computed only when listed. A variable cannot take the name of a routing quantity or of a report entry such as `status`, and an unknown key raises a `KeyError` that names it. The variables are recorded in the metadata of the passage plan, callables by their name.

`examples/function_polar_routing.py` computes the IFS gusts, the wave slope and the wind at 100 m this way.

### The sky along a route

`architeuthis.sky` describes the clouds an observer would see from deck, from nine fields of IFS or GFS: the total, low, middle and high cloud covers, the CAPE, the precipitation rate, the 2 m temperature and dewpoint, and the temperature at 700 hPa. It tells apart the ten cloud genera of the WMO International Cloud Atlas, whose table is `architeuthis/data/cloud_genera.json`. It works on NumPy values and stands apart from the routing for now.

```python
from architeuthis import sky

forecast = DeterministicHerbieForecast("sky", model="gfs", product="pgrb2.0p25", regex=sky.GFS_SKY_REGEX, fxx=range(3, 121, 3), date=forecast_date, **domain)
forecast.load_data()
sky.add_sky_models(forecast)                       # names and units of the model > keys and units of sky

fields = sky.sample(forecast, valid_time, latitude, longitude)
diagnosis = sky.diagnose(fields)
print(sky.describe(fields | diagnosis))           # ["6/8 · Sc 600 m · As · light rain", ...]
```

| Name | Does |
| --- | --- |
| `IFS_SKY_REGEX`, `GFS_SKY_REGEX` | Select the nine fields with Herbie. For GFS, only the instantaneous covers and rate, not the averages of the same names; GFS has no middle and high covers at step 0, so start at 3 h. |
| `add_sky_models(forecast, model=None)` | Registers the fields under the keys of `SKY_VARIABLES`, in 0-1 covers, J/kg, mm/h and K, whatever their names and units in the model (`SKY_FIELDS`). |
| `sample(forecast, valid_time, latitude, longitude)` | The nine fields at these points, as NumPy arrays. |
| `diagnose(fields, thresholds=None)` | Per point: `cloud_oktas` (9 for fog), `cloud_base` in m, one genus per étage in `cloud_low`, `cloud_middle` and `cloud_high` (index in `load_genera()["genera"]`, `NONE` or `HIDDEN`), every genus present in the column in `cloud_low_genera`, `cloud_middle_genera` and `cloud_high_genera` (bit masks, whether hidden from deck or not), `fog` and the lower-tropospheric `stability` in K. |
| `describe(sky, thresholds=None)` | One line per point: cover, low genera and their base, middle and high genera seen from deck, several genera of an étage joined by "+" (`Cb+Cu`), precipitation. |
| `load_genera()`, `genus_index`, `genus_abbreviation` | The table of genera, and the codes of `diagnose`. |
| `genera_present(mask, main=None)` | The genera of a bit mask of `diagnose`, the main one first. |
| `draw(sky, valid_time, **kwargs)` | The meteogram of `plot_sky`, described with the figures below. |

The rules take, in each étage, the first genus that applies. Low: Cb with a strong CAPE and precipitation rate, St with a low cover over air near its dewpoint, Cu with a broken cover in unstable air, else Sc. Middle: Ns with thick middle and low covers and steady rain, As with a thick middle cover, else Ac. High: Cs with a wide cover, else Ci. Other genera present beside the main one are kept: Cu around a Cb or beside Sc, Sc beside St, Ac beside As, Ci beside Cs or from the anvil of a Cb. An étage is `HIDDEN` where the étages below leave at most `visible_cover` (10%) of the sky open, coded "/" as in the WMO codes. The cloud base is the condensation level, 125 m per kelvin of dewpoint spread. Cirrocumulus would need the upper air and is reported as Cirrus. The thresholds, in `THRESHOLDS`, are first values that have not been calibrated against observations: replace some with `thresholds={...}`.

`examples/sky_along_route.py` puts the skies of IFS and GFS side by side along a great circle.

### Satellite observations

`architeuthis.satellite` downloads what satellites saw, to judge a forecast after the fact or to show the clouds on a map. It stands apart from the routing: these are observations, not forecasts, and they have no interpolators.

| Class | Gives | Account |
| --- | --- | --- |
| `ASCATData` | ASCAT winds, from the first source of `sources` that works | Either below |
| `EUMETSATASCATData` | ASCAT winds of the OSI SAF at 12.5 km along the swaths, a couple of hours after the pass | EUMETSAT: `EUMDAC_KEY`, `EUMDAC_SECRET` |
| `CopernicusASCATData` | The same swaths on a regular grid, one file a day, about a day behind | Copernicus Marine: `CMEMS_USER`, `CMEMS_PWD` |
| `PoseidonData` | Sentinel-6 Poseidon-4 altimeter winds and waves along the track, as delivered | EUMETSAT |
| `GeostationaryImagery` | One cloud layer from several geostationary satellites | None |
| `EUMETViewData`, `GIBSData` | The images of one satellite: Meteosat from EUMETView, GOES and Himawari from NASA GIBS | None |

The [README](../README.md#-credentials-and-settings) explains how to get each credential. Every class takes `name`, `start`, `end`, `min_lon`, `max_lon`, `min_lat`, `max_lat` and `verbose`, and downloads with `load_data`.

#### ASCAT winds

```python
from architeuthis.satellite import ASCATData, CopernicusASCATData

ascat = ASCATData("ascat", start, end, **domain)                    # EUMETSAT, else Copernicus Marine
ascat = ASCATData("ascat", start, end, sources="cmems", **domain)   # Copernicus Marine only
ascat.load_data()
ascat.source                                                         # the source used: "eumetsat" or "cmems"

cmems = CopernicusASCATData("ascat", start, end, satellites=("metopc",), orbits=("asc",), resolution=0.25, **domain)
```

`ASCATData` tries its sources in order, with a ⚠️ status for each one that fails (missing credentials, server error, no pass in the period). Whatever the source, `data` holds the same variables, on swath dimensions for EUMETSAT and on `swath, day, latitude, longitude` for Copernicus Marine:

| Variable | Meaning |
| --- | --- |
| `lat`, `lon` | Position, in degrees, longitudes in [-180, 180) |
| `time`, `valid_time` | Measurement time, as datetime64 and as epoch seconds |
| `wind_speed` | 10 m equivalent neutral wind, m/s |
| `wind_dir` | Where the wind **goes**, in degrees: add 180 to compare it with a forecast or a weather report |

Measurements outside the box are NaN. `CopernicusASCATData` also takes the Metop `satellites` (`"metopb"`, `"metopc"`), the `orbits` (`"asc"`, `"des"`) and the grid `resolution` (0.125 or 0.25 deg). Only the products crossing the box are downloaded, once: EUMETSAT products are kept in `~/data/eumetsat/`, Copernicus Marine subsets in `~/data/cmems/`. `examples/ascat_sources.py` compares both sources on the passes they share, and `examples/comparison_ascat_models.py` compares ASCAT with the models.

#### Cloud images

```python
from architeuthis.satellite import GeostationaryImagery

clouds = GeostationaryImagery(
    "clouds", start, end, min_lon=-75., max_lon=5., min_lat=35., max_lat=60.,
    channels=["ir", "visible"],     # what to download
    resolution=0.05,                # grid step, deg: sets the download time
    limb_correction=True,           # make up for the oblique views
)
clouds.load_data()

clouds.times()                                       # UTC times of the images
rgba = clouds.image(-1, "ir", colormap="blue")       # the latest image, coloured, north up
plt.imshow(rgba, extent=clouds.extent())
```

Two servers render the images, without account: [EUMETView](https://view.eumetsat.int/) for Meteosat at 0 deg (`EUMETViewData`) and [NASA GIBS](https://nasa-gibs.github.io/gibs-api-docs/) for GOES-East at 75.2 W (`GIBSData`). Architeuthis turns their colours back into physical values, then `GeostationaryImagery` takes each pixel from the satellite that sees it most directly, blended over a few degrees along the seam. A source that fails is left out with a ⚠️ status, and the other fills in where it can.

**Channels** are chosen like the variables of a forecast, and each gives one quantity in `data`, on `valid_time`, `latitude` and `longitude`:

| Channel | Quantity | When |
| --- | --- | --- |
| `"ir"` (default) | `bt`, brightness temperature in K: the cloud tops are cold | Day and night |
| `"visible"` | `brightness`, from 0 (black) to 1 (white). GOES is matched to Meteosat along the seam, image by image (`gain` and `offset` in `data`), since the brightness of a scene changes with the sun | By day |

**Main options**:

| Argument | Default | Meaning |
| --- | --- | --- |
| `resolution` | 0.05 | Grid step in degrees. It sets the size of each requested image, hence the download time: about a second for 1600 x 500 pixels, four images at a time. 0.02 shows all the detail of the infrared and 0.01 of the visible (`DETAIL_RESOLUTIONS`), best on a small box. |
| `native_resolution` | `"finest"` | Server layer, where a server has several: `"finest"` (MTG FCI on EUMETView, every 10 min), `"coarsest"` or `"3km"` (MSG SEVIRI, every 15 min), or one per channel, `{"ir": "3km"}`. |
| `time_step` | `None` | Keep only the times on multiples of a step, such as `"30min"`; None for every image. |
| `complete` | `True` | Keep only the times every satellite has, so that no image misses a part; False for the times of any. GIBS is about an hour behind EUMETView, so the latest complete image is about an hour old. |
| `limb_correction` | `False` | Each satellite reads the infrared colder towards the edge of its disk, about 2 K at a zenith angle of 50 deg, 7 K at 70 and 12 K at 80. True adds `satellite.limb_cooling(zenith)`, so that Meteosat and GOES-East agree within about 3 K across the North Atlantic. |
| `match` | `None` | Match the levels of the sources along the seam; None for the visible only. |
| `seam_width` | 2 | Width of the blending along the seams, in degrees of viewing angle. |
| `sources` | `None` | `WMSImageryData` objects to join, None for EUMETView and GIBS. `GIBSData(wms_layers={"ir": ...})` takes GOES-West or Himawari layers. |

**Drawing.** How the images look is chosen when drawing, never when downloading. `image(time, channel, colormap=...)` returns an RGBA array, first row north, ready for `imshow` or a map overlay:

| Argument | Meaning |
| --- | --- |
| `time` | Index of the image, or a time (the nearest image). |
| `colormap` | A colour scale of Windy: `"infra"` (Infra+, default of `"ir"`) or `"blue"` (white clouds over a transparent clear sky) for the infrared, `"visible"` for the visible. |
| `transparent_above`, `transparent_below` | Fade out the pixels warmer (the clear sky of an infrared layer, 275 K say) or darker (the sea of a visible layer) than a value, over `fade`. |
| `box`, `scale`, `order` | Draw only `(min_lon, max_lon, min_lat, max_lat)`, each pixel interpolated into `scale` x `scale` (`order=1` bilinear, `3` bicubic) before colouring, so the steps of the colour scale stay sharp. `extent(box)` gives where it lies, `[west, east, south, north]`. |

`bounds` gives the corners as Leaflet takes them, and `toolbox.windy_colormaps.get_satellite_cmap(colormap)` the colormap and norm for a colour bar. `EUMETViewData` and `GIBSData` take the same arguments for one satellite each.

**Files** are managed as those of the forecasts: nothing is downloaded twice. Each image is a PNG in `~/data/wms/<host>/<layer>/<box>/`, and the times a server listed, with the periods they cover, are kept in `<layer>/times.json`, so loading a period again asks the server nothing. An image still empty 3 hours after its time (`EMPTY_FINAL_AFTER`) is recorded and not asked again; a more recent one may not be produced yet and is asked again next time. Offline, the images of the period on disk are used, with a ⚠️ status.

`examples/cloud_imagery.py` loads the last hours over the North Atlantic, checks that both satellites agree, and draws each source, the joined layer, the three colour scales, a smoothed zoom, the clouds over a map and an animation.

### Credentials and the data folder

The [README](../README.md#-credentials-and-settings) explains how to get each credential and save it once. `architeuthis.credentials` holds the functions behind `python -m architeuthis.credentials`:

| Function | Does |
| --- | --- |
| `save_credential(name, value=None)` | Stores a credential in the credential store of the operating system, through `keyring`. Without `value`, asks for it, hidden when it is secret. |
| `get_credential(name)` | Its value, from its environment variables first, then from the credential store, or `None`. Read when called, never at import. |
| `credential_sources()` | Where each credential is found, without its value. |
| `delete_credential(name)` | Removes it from the credential store, and says whether it was there. |
| `require_credentials(*names, provider, fallback_files=())` | The values a provider needs, or a ⚠️ status and a `MissingCredentialError` naming what is missing. |

`CREDENTIALS` lists the names, `CDS_API_KEY`, `CMEMS_USER`, `CMEMS_PWD`, `EUMDAC_KEY` and `EUMDAC_SECRET`, with the environment variables read for each. The data sources read them when they download, and keep none on the object. A data source cannot be given credentials as arguments, so that they stay out of scripts.

Downloads, libraries and reports are kept in `~/data/`. Set `ARCHITEUTHIS_HOME` before importing Architeuthis to keep them elsewhere, as the [README](../README.md#-the-data-folder) explains.

## Keeping and reusing results

`RoutingAnalysis.run` and `evaluate` return a `RoutingReport`, a dict with the same entries as before plus a few helpers. A `ReportCollection` is a list of reports that can be selected, tabulated, saved and reloaded.

```python
from architeuthis.report import ReportCollection

reports = ReportCollection()
reports.append(analysis.run(tags={"model": "ifs", "init_fac": 0.}))

reports.save()                                  # ~/data/routes/output_<today>.json, displayed by ui.py
reports.share(forecasts={"IFS": [atmosphere, wave]})  # one HTML file to send aboard
reports = ReportCollection.latest()             # the most recent file of ~/data/routes/

selected = reports.select(vessel="eff45", solve=1)
selected = reports.select(lambda r: r["fuel"] < 100., model="ifs")

selected.table()                                # routes against time, as a DataFrame
selected.frame()                                # one row per report
selected.summary()                              # the key figures of each report, one row per report
selected.quantiles("tws")                       # {quantile: values at each segment}
selected.to_gpx()                               # one GPX file per report
```

`tags` are entries added to the report. By default a report has `solve` (0 or 1), `model` (the atmospheric model), `vessel` (`Vessel.label`, such as `eff45`) and `member`. `run` also records `init_fac`, the deviation factor of the route. `summary()` gives `etd`, `eta`, `model`, `vessel`, `member`, `init_fac`, `solve`, `status`, `dist`, `extra_dist_%`, `stw`, `sog`, `fuel`, `fuel_per_day` and `max_z`, and a slice of a collection is a collection.

## Plotting

The figures are in `architeuthis.toolbox.plot_utils`. They take reports as returned by `run` and `evaluate`, or reloaded from a file, and plain dicts with the same entries work too.

These arguments mean the same in every function:

| Argument | Default | Meaning |
| --- | --- | --- |
| `save_as` | `None` | File to write. Its extension gives the format, and a file name without extension is written as PDF. |
| `show` | `True` | Whether to call `plt.show()`. Pass `False` in a GUI, or to save pages in a loop and close them with `plt.close(fig)`. |

Every function returns its figure, except `plot_fuel_vs_etd`, which returns a list of figures. The figures have the Architeuthis style whatever the current matplotlib settings, and they leave these settings unchanged.

### One route on an A4 page: `plot_report`

```python
plot_report(report, save_as=None, show=True, figsize=A4_PORTRAIT, dpi=300, ylim=None)
```

Six stacked panels share a time axis in UTC, which runs from the first to the last node of `tim`. Values are per segment and drawn as steps centered on `ctim`.

| Position | Panel name | Report entries | Content | Default vertical limits |
| --- | --- | --- | --- | --- |
| 1 | `sog` | `sog` | Speed over ground, kt | Automatic |
| 2 | `sails` | `sails_contribution` | Sails contribution, %. Without it, the panel says so | 0 to 100 |
| 3 | `bhp` | `bhp`, `max_bhp` | Average BHP, kW. With `max_bhp`, load fluctuations are dashed lines and a band at average ± (max − average). Without `bhp`, `total_power` (kW), else `hourly_consumption` (L/h) | From 0 |
| 4 | `swh` | `swh` | Significant wave height, m | From 0 |
| 5 | `tws` | `tws`, `tws_gust` | True wind, kt: average, and gust as a dashed line with a band | From 0 |
| 6 | `aws` | `aws`, `aws_gust` | Apparent wind, kt: average, and gust as a dashed line with a band | From 0 |

The gust lines are left out when the report has no gust, which happens with `RoutingAnalysis(..., options={})` unless `variables` lists `"gust"`. Likewise, `sails_contribution` and `max_bhp` are in the report only when `variables` lists them (or, until 0.4.0, when the vessel has them).

| Argument | Default | Meaning |
| --- | --- | --- |
| `report` | | The report to draw. |
| `save_as` | `None` | File to write. The page size is kept exactly, so a PDF is a true A4 page. |
| `show` | `True` | Whether to call `plt.show()`. |
| `figsize` | `A4_PORTRAIT`, (8.27, 11.69) | Page size in inches. |
| `dpi` | 300 | Resolution in dots per inch. |
| `ylim` | `None` | Vertical limits by panel name, replacing the defaults above. An unknown name raises `KeyError`. |

`fig.axes` holds the panels in the order above, and `REPORT_PANELS` gives their names, so a page can be customized after it is drawn. `report.plot(...)` is the same function.

```python
from architeuthis.toolbox.plot_utils import REPORT_PANELS, plot_report

# Each selected report, as in the last section of examples/simple_routing.py
for report in reports.select(solve=1):
    plot_report(report)

# A PDF for each report, without displaying them
for i, report in enumerate(reports):
    fig = plot_report(report, save_as=f"report_{i}.pdf", show=False)
    plt.close(fig)

# Fixed scales, to compare pages, and a shorter page
plot_report(report, ylim={"sog": (6., 13.), "bhp": (0., 3084.)}, figsize=(8.27, 10))

# Further customization
fig = plot_report(report, show=False)
fig.axes[REPORT_PANELS.index("sog")].axhline(10., color="red")
fig.savefig("report.png")
```

### Routes on a map: `draw` and `plot_route`

```python
draw(reports, barbs=True, sails_threshold=None, ax=None, save_as=None, show=True)
plot_route(lon, lat, clon, clat, tws, twd, barbs, sails_contribution=None, sails_threshold=1.0, ax=None, save_as=None, show=True)
```

`draw` shows several reports on a map, one color each, over the great circle of the first report in grey. `plot_route` is the same map from arrays, one per route, for routes that are not in a report.

| Argument | Default | Meaning |
| --- | --- | --- |
| `reports` | | The reports to draw. Entries used: `lat`, `lon`, `clat`, `clon`, `tws`, `twd`. |
| `barbs` | `True` | Whether to draw wind barbs at segment centers. Required for `plot_route`. |
| `sails_threshold` | `None` | If given, a dot marks the segments whose `sails_contribution`, in %, is above this value, instead of a dot at every node, when every report has `sails_contribution`. For `plot_route` it applies when `sails_contribution` is given, and defaults to 1. |
| `ax` | `None` | Cartopy axes to draw in, to combine maps on a figure. By default the current figure is cleared. |

Cartopy downloads the Natural Earth coastlines the first time it draws a map.

```python
draw(reports.select(solve=1), sails_threshold=10.)

fig, (left, right) = plt.subplots(1, 2, subplot_kw={"projection": ccrs.PlateCarree()})
draw(reports.select(model="ifs"), ax=left, show=False)
draw(reports.select(model="gfs"), ax=right, barbs=False)
```

To check the reference routes of a voyage before routing, `plot_route_set(route_set, n=50, ax=None, save_as=None, show=True)` draws a `RouteSet` on a map: ortho in solid black, minus in dashed red and plus in dashed green, each with `n` points.

### Comparing routes: `plot_variable` and `plot_power_and_weather`

```python
plot_variable(reports, variable, unit="", labels=None, ylim=(0.0, None), legend=False, figsize=(12, 6), dpi=300, save_as=None, show=True)
plot_power_and_weather(reports, labels=None, max_bhp=False, figsize=(12, 10), dpi=300, save_as=None, show=True)
```

Both draw per-segment quantities against time, as steps, with one viridis color per report. `plot_variable` draws one quantity. `plot_power_and_weather` draws `bhp`, `swh` and `tws` on three panels, and `max_bhp=True` adds `max_bhp` as dashed lines on the top panel, for the reports that have it.

`labels` gives the legend text by `init_fac`, so reports need this entry. Without a label, the text is `Route <init_fac>`.

```python
sides = {-1.: "North", 0.: "Ortho", 1.: "South"}
plot_variable(reports, "sog", unit="kts", labels=sides, legend=True, ylim=(6., 16.))
plot_power_and_weather(reports, labels=sides, max_bhp=True, save_as="comparison.pdf")
```

### Several runs: spreads and sweeps

| Function | Figure | Report entries |
| --- | --- | --- |
| `plot_quantiles(reports, variable, unit="", prefix="", title=None, ylim=None, daily_ticks=False, figsize=(10, 4), save_as=None, show=True)` | Meteogram of reports on the same time grid: bands between the quantiles 1-99 %, 5-95 % and 25-75 %, and the median. `prefix` goes before the band labels. `daily_ticks` marks every day. | `ctim`, `variable` |
| `plot_fuel_quantiles(reports, daily=False, converged_only=True, figsize=(8, 4), save_as=None, show=True)` | The same bands for the fuel against ETA. `daily` shows tons per day of transit. `converged_only` leaves out the reports with a `status` other than 1. | `eta`, `fuel`, `transit_time`, `status` |
| `plot_convergence(reports, figsize=(8, 4), save_as=None, show=True)` | Share of the reports with `status` 1 for each ETA, in %: the probability that this ETA is possible, when reports are ensemble members. | `eta`, `status` |
| `plot_fuel_distribution(groups, horizontal=False, figsize=(8, 3), save_as=None, show=True)` | Violins with box plots, one per group. `groups` gives reports by label, and `horizontal` lays them on their side. | `fuel` |
| `plot_ensemble_along_route(report, atmosphere, wave, ylim=None, figsize=(10, 8), save_as=None, show=True)` | One route, whatever the member it was optimized for, on three panels: BHP with load fluctuations, then SWH and TWS with their quantile bands over the members. `atmosphere` and `wave` are ensemble forecasts with the `u10`, `v10` and `swh` interpolators. `ylim` gives limits by panel: `bhp`, `swh` or `tws`. | `ctim`, `tim`, `clat`, `clon`, `bhp`, `max_bhp` |
| `plot_fuel_vs_etd(reports, models_colors=None, ylim=None, figsize=(10, 3.5), show=True)` | Fuel against ETD, one figure per vessel: one color per model, crosses for `solve` 0 and dots for `solve` 1. `models_colors` gives a color by model, and the default `ylim` is rounded to 2 t around the points. Returns a list of figures. | `solve`, `vessel`, `model`, `etd`, `fuel` |

```python
plot_quantiles(reports, "tws", unit="kts", prefix="IFS ensemble ", title="True wind", daily_ticks=True)
plot_fuel_quantiles(reports, daily=True)
plot_fuel_distribution({"Eff. 45%": reports.select(vessel="eff45"), "Eff. 60%": reports.select(vessel="eff60")})
```

### The sky as a meteogram: `plot_sky`

```python
plot_sky(sky, valid_time, style="cells", title=None, labels=True, latitude=None, longitude=None, figsize=(12, 6), dpi=300, save_as=None, show=True)
```

Draws the result of `architeuthis.sky` over the air column against time, as a meteogram, in one of two styles (`SKY_STYLES`). `sky.draw(sky, valid_time, ...)` is the same figure. Both styles show every genus present in the column, from the bit masks of `diagnose`, and have the precipitation rate in mm/h in a bottom panel, blue for rain and light blue for snow; without `prate` in `sky`, there is no bottom panel.

- `style="cells"`, the table of the sky: one row per étage, of equal heights, the low one to scale, 0 to 2 km, the middle and high ones schematic (`SKY_ETAGE_ROWS`). Each row is shaded by its cover, white to dark grey, and holds the genera of each column, stacked with the main one on top and colored by their form (cumuliform, stratocumuliform, stratiform, cirriform), or "/" where the clouds below hide the étage from deck. A frame marks the genera that rise through the three étages, even hidden: a Cb from its cloud base, a Ns from the middle étage. Dashes give the cloud base, dots the fog, and the oktas run along the top.
- `style="smooth"`, the picture of the sky, as in a weather app: the clouds are painted after their genus over a blue sky, in a column on a continuous height scale, to scale up to 2 km and compressed above. Cu are separate domes with flat bases, taller with the CAPE; Cb towers with an anvil, lightning and rain under them; Sc and Ac broken into rolls where their cover is; St, As and Ns layers, Ns with a ragged base; Cs a veil and Ci hooked strokes. Rain streaks or snow fall under the columns that have clouds, fog rises from the sea, and the cover is given along the top by WMO sky cover symbols, crossed for a sky hidden by fog. Each genus is tagged once per stretch of the route, at its height, again on long stretches. With `latitude` and `longitude`, the nights are darker, after `sun_elevation`.

| Argument | Default | Meaning |
| --- | --- | --- |
| `sky` | | The fields of `SKY_VARIABLES` and the result of `diagnose`, merged with `fields \| diagnose(fields)`. |
| `valid_time` | | Time of each point, in epoch seconds. Each column runs halfway to its neighbours. |
| `style` | `"cells"` | `"cells"` or `"smooth"`. |
| `labels` | `True` | Whether to write the genera, and the oktas of `"cells"`, which crowd on long routes. |
| `latitude`, `longitude` | `None` | Position of each point, to shade the nights in `"smooth"`. |

```python
fields = sky.sample(forecast, valid_time, latitude, longitude)
columns = fields | sky.diagnose(fields)
sky.draw(columns, valid_time, title="Brest to the Azores, GFS")
sky.draw(columns, valid_time, style="smooth", latitude=latitude, longitude=longitude)
```

### Helpers for your own figures

| Helper | Use |
| --- | --- |
| `get_steps(report, quantity)` | Times and values of a per-segment quantity, to draw it as steps: `plt.plot(*get_steps(report, "bhp"))`. Also `report.steps(quantity)`. |
| `add_map_background(ax)` | Land, ocean, coastline and gridlines of the maps above, on cartopy axes. Returns the gridlines. |
| `set_plot_style()` | Applies the Architeuthis style to every figure from now on, for scripts that draw their own figures. Importing `plot_utils` no longer does this. |
| `plot_style()` | The same style inside a `with` block only. |
| `A4_PORTRAIT`, `REPORT_PANELS` | The A4 page size in inches, and the panel names of `plot_report`. |
| `sun_elevation(seconds, latitude, longitude)` | Elevation of the Sun in degrees, within a few tenths, as the smooth sky uses it for the nights. |

## Exclusion zones

An `ExclusionZone` is a named `[lat, lon]` polygon that routes stay out of, with what the UI needs to show it. It reads like its list of points, and plain lists are still accepted wherever a zone is.

```python
from architeuthis.exclusion import ExclusionZone, ExclusionZoneLibrary, iceberg_zone
from architeuthis.forecast import Topography

zone = ExclusionZone(
    "safety",
    [[49.2, -65.9], [49.2, -64.9], [48.0, -64.5]],
    label="Safety margin",      # text on the map and in the layers control, `name` by default
    color="#ff8c00",
    visible=True,               # shown when the UI opens
)

library = ExclusionZoneLibrary()         # ~/data/exclusion_zones/
library.save(zone)
library.load("safety")
list(library)                            # every stored zone

topography = Topography("topo", exclusion_zones=[zone, iceberg_zone()], **domain)
```

The zones of a routing are yours: the package holds no geographic zone, and `examples/simple_routing.py` shows some written as plain lists. `iceberg_zone()` gives the latest IIP iceberg limit. The bulletin is downloaded when it is first needed in a session, not at import, and `architeuthis.icebergs.refresh()` fetches it again. If the server cannot be reached, the last downloaded bulletin is used. If there is none, the zone is empty and the routing runs without the iceberg limit, with a warning.

`ExclusionZone.from_geojson(path, feature_id)` reads a polygon from a GeoJSON file. `visible` only concerns the display: a hidden zone still applies to the routing.

## Sharing routes

The routes, the forecasts of the voyage and the exclusion zones go aboard as one HTML file. It opens in any browser, without a server or a connection, on a 3D globe with a timeline and a layers panel: send it by email, or copy it to the ship.

```python
from architeuthis.report import ReportCollection

reports = ReportCollection.latest()
reports.share(
    forecasts={"IFS": [atmosphere, wave], "GFS": [gfs_atmosphere, gfs_wave]},
    routes=[1, 3],                          # indices of the reports, all by default
    variables=["sog", "tws", "twa", "swh"],   # shown on the routes, in this order
    zones=[iceberg_zone(), zone],
    title="Saint-Nazaire to Baltimore",
    note="Expect the low to cross the route on Saturday: keep north.",
)                                           # ~/data/shared/saint-nazaire-to-baltimore_<time>.html
```

`ReportCollection.share(path=None, **options)` calls `architeuthis.dux.share.share_routes(reports, path=None, library="inline", verbose=True, **options)`, which returns the path of the file. Its options are those of `build_scene`:

| Option | Default | Meaning |
| --- | --- | --- |
| `forecasts` | `None` | Layers by label. Each value is a `Forecast`, an `xarray.Dataset` or a list of them, the others interpolated on the grid of the first. The built-in layers read `u10` and `v10` (or `si10` and `wdir10`), `gust` (or `i10fg`, `fg10`), `msl` (or `prmsl`), `swh` with `mwd` (or `dirpw`), `uo` and `vo`. `share.FIELDS` knows the wave period (`mwp`, `mp2`, `pp1d`, `perpw`), from which the wave slope is computed, the temperature (`t2m`, in °C), the CAPE (`mucape`, `cape`), the precipitation rate (`tprate`, `prate`, in mm/h) and type (`ptype`, in categories), each with its colour scale and arrows. Any other field of time and position, and any `add_function` model of time and position of a `Forecast`, is a layer of its own, in its units, on a scale of its values. `share.forecast_fields(forecasts)` lists the layers. |
| `routes` | all | Indices of the reports to share. A route keeps the colour of its index. |
| `variables` | `share.DEFAULT_VARIABLES` that the reports have | Entries shown when hovering a route: any array of the report along the route (`segment_variables`), per segment, per node or sampled between nodes, as the topography `z`, shown by its largest value on each segment (`segment_values`). `share.variable_info` gives their label, unit and description, from `share.VARIABLES` or the name. |
| `labels` | `route_label` | One name per report, by default from its tags: `IFS eff60`, `GFS eff45 m3 (baseline)`. |
| `zones` | `()` | `ExclusionZone` objects or `[lat, lon]` lists. An empty one, such as the iceberg limit without a bulletin, is listed as unavailable. |
| `overlays` | `()` | Images drawn over the globe: dicts with `label`, `url` (an address or `share.png_data_uri(content)`), `bounds` (`[[lat, lon], [lat, lon]]`), `visible`, `opacity` and `time`, the valid time of a chart (epoch seconds or a date, naive dates in UTC). Showing a chart with a time brings the page to that time. |
| `comments` | `None` | The analyst's notes on the routes, by report index: `{index: {"description": text, "points": {segment: text}}}`, or just the description as a text. A segment is an index of `ctim`. A report's own `description` entry is used when none is given. |
| `title`, `note` | today's date, `""` | Shown at the top of the page; the note is the analyst's message to the crew. |
| `member` | first | Ensemble member of the forecasts. |
| `fields` | all | Layers of the forecasts to put in the file, such as `["wind", "waves", "period"]`. A layer brings the fields of its arrows: wave arrows with the period. |
| `settings` | `None` | Initial choices of the page: `theme` (`"dark"`, the default, or `"light"`), and for `ui.py` the routes, sources, overlays and tooltip variables shown. |
| `resolution`, `margin`, `time_margin` | 0.5 deg, 10 deg, 12 h | Grid of the forecast frames, and the forecast kept around the routes and before and after them. |

```python
reports.share(
    comments={
        1: {
            "description": "Northern option: shorter, but meets the low on Saturday.",
            "points": {12: "Slow down here to let the front pass ahead."},
        },
    },
    settings={"theme": "light"},
)
```

The forecasts are kept around the routes only, and their fake final steps are left out. Each frame is a PNG of 8-bit values, so that a crossing with two models over a week weighs about 3 to 5 MB. Speeds are in knots and pressures in hPa. `library="inline"` puts MapLibre GL JS in the file, downloaded once to `~/data/viewer/`; when it cannot be downloaded, the file loads it from a CDN, and then needs a connection when it is opened, with a ⚠️ status. `library="cdn"` does that on purpose, for a lighter file. `build_scene` and `viewer_html(scene, library)` give the content and the page without writing a file.

In the page:

- **Timeline**: play and pause, steps, a speed from 1 to 24 h of forecast per second, the frames of each source, and the schedule of each route, routes of the same schedule grouped in one bar, with a dot where the analyst commented on the route. Charts with a valid time have a lane of their own: clicking one shows it at its time. Click or drag anywhere on it; *Now* goes to the current time.
- **Globe**: the boats move along their routes. Hovering a boat shows the description of its route; hovering a point of a route shows its time, the analyst's comment there, marked by a bubble and tinted in the colour of the route, and the chosen variables in two columns, pairs such as TWS and TWA, AWS and AWA or SOG and COG on one row, each gust alone under its speed; hovering the sea shows the position and the fields of the file, with the direction of wind, waves and current.
- **Weather picker** (the target button under the zoom, or `P`): a dot to drag anywhere, or to move by clicking the map, with a line up to a card telling, as the time changes, the position, the model and time, the wind with its direction and gusts, the waves with their direction, the pressure, and the field shown when it is another one.
- **Glyphs**: wind barbs and wave and current arrows take the colour of the field under them, made vivid, and sit on a fixed lattice that only the zoom changes. A wave glyph points where the waves go: a solid head for each 4 m and a thin chevron, smaller and touching the last head, for each metre left, so that 3 m is three chevrons, 4 m one head and 9 m two heads and a chevron; a dot is a sea under half a metre.
- **Layers** (the button left of the title, or `L`): source, field (wind, gusts, waves, current, pressure and any other field of the file), the arrows drawn over it (those of the field at first: wind barbs over the gusts, wave arrows over the period and slope), each with the colour of the field under it, isobars every 2 or 4 hPa (4 at first) with or without their pressure labels, the highs and lows marked H and L with their pressure (the lowest or highest point within 6 deg, at least 1.5 hPa below or above the edge of that disc), and opacity (100 % at first); each route with its fuel, distance and description, and a badge when it did not converge or touches land or a zone (`max_z` > 0); the exclusion zones; the land of the file, offline (OpenStreetMap is disabled for now), OpenSeaMap sea marks, online, shown from zoom 7 with traffic separation schemes and restricted areas, latitude and longitude lines and the overlays.
- **Theme** (the sun or moon button, or `T`): a dark or a light map, the panels and the land; the weather, its colour scales, glyphs and isobars, is drawn the same in both. The offline land is drawn flat over the weather, with a thin, faint coastline shaded on the sea side, from Natural Earth 1:10m: simplified at 0.05 deg on the globe and at about 500 m from zoom 5.
- **Keys**: space plays, the arrows step, Shift and the arrows jump a day, `Esc` closes a tooltip. The choices of the layers, the theme and the picker are kept when the page is reloaded.

### The analyst's page: `dux/ui.py`

```bash
python -m architeuthis.dux.ui
```

`ui.py` needs the `dux` extra (`pip install "architeuthis[dux]"`) and serves on port 8052. It opens on the most recently modified file of `~/data/routes/`, so `reports.save()` is all it takes for the latest routes to appear, and the others can be chosen from a list. The page shows the share file as the crew will see it, and beside it what goes into it: the routes (optimized ones, `solve` 1, ticked at first) each with its name, its label at first, edited in place by clicking it, and a description for the crew, the variables of the route tooltips, the models and the fields shared, chosen in a list like the variables (all at first), the NOAA surface analysis, a title and a note. Clicking a point of a route in the preview opens a box to comment on it, to tell the crew what to expect or do there; `Ctrl+Enter` saves it, and clicking it again edits or deletes it. *Light map* switches the theme of the page and of the file. Each change shows at once in the preview, and *Download the share file* writes it. Comments belong to the routes of a file: choosing another file starts without any.

The models, their fields and the domain are set at the top of the script (`PRODUCT`, `MODELS`, `ATMOSPHERE_FIELDS`, `WAVE_FIELDS`, `minimum_longitude`...), and every start downloads the forecasts: by default wind, gusts, pressure, CAPE and, for IFS, precipitation type, and waves with their period; precipitation rate and temperature are a line away. `GRIB_SEARCH` translates each field into the GRIB search of each model (`ifs`, `gfs`, `gfs_wave`), and a field a model lacks is left out with a warning. Any field added there can be shared. The iceberg limit and the zones of `~/data/exclusion_zones/` are always shared, whether or not a routing used them: the iceberg limit is shown at first, and the other zones are hidden at first, whatever their `visible`, and can be shown in the layers.

The NOAA chart is always shared, hidden when the file opens unless its box is ticked, and the crew shows or hides it in the layers; showing or hiding it in the preview ticks or unticks the box. It gives its valid time only in its picture. `ui.py` takes it as the last synoptic hour (00, 06, 12 or 18 UTC) at least 1.5 h before the chart's `Last-Modified` date, as it is published about 2 hours after its time; the label of the option shows it. Showing the chart brings the preview to that time.

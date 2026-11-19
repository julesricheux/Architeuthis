# User guide

The reference of Architeuthis: data sources, reports, figures, exclusion zones and the viewer. For installation and a first routing, see the [README](../README.md).

- [Data sources](#data-sources)
- [Keeping and reusing results](#keeping-and-reusing-results)
- [Plotting](#plotting)
- [Exclusion zones](#exclusion-zones)
- [Displaying routes: `ui.py`](#displaying-routes-uipy)

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
| `satellite.ASCATData` | ASCAT winds over a period and a box, to validate forecasts: from EUMETSAT (`EUMDAC_KEY`, `EUMDAC_SECRET`), the latest swaths, else from Copernicus Marine (`CMEMS_USER`, `CMEMS_PWD`), daily gridded swaths about a day behind. `sources="cmems"` uses Copernicus Marine only, and `source` tells which one was used. The variables are the same either way: `lat`, `lon`, `time`, `valid_time`, `wind_speed` in m/s and `wind_dir`, where the wind goes to, in degrees. `EUMETSATASCATData` and `CopernicusASCATData` are the two sources. |
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

The objective is the fuel, in tonnes: the integral over the passage of the consumption in kg/h, at the middle of each segment. The routing takes it from the first of these vessel models; the others, such as `max_bhp` or `sails_contribution`, are computed only when `variables` lists them.

| Model | Consumption, kg/h | Report entries |
| --- | --- | --- |
| `hourly_consumption`, kg/h | the model itself | `hourly_consumption` |
| `total_power`, kW: propulsion and hotel | `total_power * sfoc / 1e3` | `total_power`, `sfoc`, `hourly_consumption` |
| `bhp`, kW: propulsion | `(bhp + hotel_load) * sfoc / 1e3` | `bhp`, `hotel_load`, `total_power`, `sfoc`, `hourly_consumption` |

Each model is a table, a function or a constant: `vessel.add_constant("bhp", 1500.)` registers a model without input. `hotel_load` (kW) and `sfoc` (g/kWh) are given to `Vessel` as numbers or as functions of the power, the brake power for `hotel_load` and the total power for `sfoc`. A model of the same key takes precedence, and may name `bhp`, `hotel_load` or `total_power` among its inputs, so an sfoc curve of the engine load is a table or a function of `total_power`:

```python
vessel = Vessel("vessel", hotel_load=180., max_power=4100.)
vessel.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa")
vessel.add_function("sfoc", lambda x: 175. + 2e-6 * (x["total_power"] - 3000.)**2, ["total_power"])
```

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
| 3 | `bhp` | `bhp`, `max_bhp` | Average BHP, kW. With `max_bhp`, load fluctuations are dashed lines and a band at average ± (max − average). Without `bhp`, `total_power` (kW), else `hourly_consumption` (kg/h) | From 0 |
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

## Displaying routes: `ui.py`

```bash
cd architeuthis
python ui.py
```

`ui.py` serves on port 8052 and must be started from the `architeuthis/` folder. It displays the most recently modified file of `~/data/routes/`, so `reports.save()` is all it takes for the latest routes to appear at its next start. Each report needs the entries `model`, `vessel`, `member`, `init_fac`, `solve` and `fuel`, and optimized routes (`solve` 1) are shown when the page opens.

The iceberg limit and the zones of `~/data/exclusion_zones/` are drawn with their label on the map, whether or not a routing used them. Each one can be hidden in the layers control at the top right of the map. The iceberg limit is listed as `Iceberg limit (unavailable)` when no bulletin could be obtained, so that it is not taken for a limit far from the route.

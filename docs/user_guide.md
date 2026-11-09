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
wave.add_interpolator("swh", "valid_time", "latitude", "longitude")
wave.add_interpolator("mwd", "valid_time", "latitude", "longitude")

current = CopernicusForecast("current", dataset="cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", variables=["uo", "vo"], date=date, **domain)
current.load_data()
current.add_interpolator("uo", "valid_time", "latitude", "longitude")
current.add_interpolator("vo", "valid_time", "latitude", "longitude")

topography = Topography("topography", exclusion_zones=zones, **domain)
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

vessel = Vessel("vessel", filepath="polar_eff45.nc", sfc=220., hotel_load=194., max_power=4100.)
vessel.load_data()
for key in ("bhp", "max_bhp", "sails_contribution"):
    vessel.add_interpolator(key, "stw", "tws", "twa", "hs", "wa", method="linear")
```

| Class | Gives |
| --- | --- |
| `forecast.DeterministicHerbieForecast` | A deterministic forecast through Herbie: IFS, GFS and their wave models, chosen with `model`, `product` and `regex`. No account. |
| `forecast.EnsembleHerbieForecast` | The members of an ensemble, IFS for example. `add_interpolator` takes `var_dim, time_dim, member_dim, latitude_dim, longitude_dim`. No account. |
| `forecast.HRDPSForecast` | The 10 m wind of HRDPS continental, regridded on a regular grid, the latest run by default. Its wind direction is not reliable yet: the components are relative to the rotated grid of the model and are not rotated, about 45° off around Saint-Pierre-et-Miquelon. |
| `forecast.CopernicusForecast` | Currents and other products of Copernicus Marine. Needs an account. |
| `forecast.CDSForecast` | ERA5 reanalysis. Needs an account. |
| `forecast.Topography` | The signed distance to land and to your exclusion zones. It needs only its box, and `exclusion_zones` if you have some. |
| `vessel.Vessel` | A vessel, from its polar file. `sfc` must be given for a routing, because the objective is zero without it. `label` comes from the file name by default: `eff45` for `..._eff45.nc`. |

To route without a current provider, fill a `Forecast` with zeros on the grid of the wind, as `examples/passage_planning.py` does.

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
| 2 | `sails` | `sails_contribution` | Sails contribution, % | 0 to 100 |
| 3 | `bhp` | `avg_bhp`, `max_bhp` | Average BHP, kW. Load fluctuations are dashed lines and a band at average ± (max − average) | From 0 |
| 4 | `swh` | `swh` | Significant wave height, m | From 0 |
| 5 | `tws` | `tws`, `tws_gust` | True wind, kt: average, and gust as a dashed line with a band | From 0 |
| 6 | `aws` | `aws`, `aws_gust` | Apparent wind, kt: average, and gust as a dashed line with a band | From 0 |

The gust lines are left out when the report has no gust, which happens with `RoutingAnalysis(..., options={})`.

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
| `sails_threshold` | `None` | If given, a dot marks the segments whose `sails_contribution`, in %, is above this value, instead of a dot at every node. For `plot_route` it applies when `sails_contribution` is given, and defaults to 1. |
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

Both draw per-segment quantities against time, as steps, with one viridis color per report. `plot_variable` draws one quantity. `plot_power_and_weather` draws `avg_bhp`, `swh` and `tws` on three panels, and `max_bhp=True` adds `max_bhp` as dashed lines on the top panel.

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
| `plot_ensemble_along_route(report, atmosphere, wave, ylim=None, figsize=(10, 8), save_as=None, show=True)` | One route, whatever the member it was optimized for, on three panels: BHP with load fluctuations, then SWH and TWS with their quantile bands over the members. `atmosphere` and `wave` are ensemble forecasts with the `u10`, `v10` and `swh` interpolators. `ylim` gives limits by panel: `bhp`, `swh` or `tws`. | `ctim`, `tim`, `clat`, `clon`, `avg_bhp`, `max_bhp` |
| `plot_fuel_vs_etd(reports, models_colors=None, ylim=None, figsize=(10, 3.5), show=True)` | Fuel against ETD, one figure per vessel: one color per model, crosses for `solve` 0 and dots for `solve` 1. `models_colors` gives a color by model, and the default `ylim` is rounded to 2 t around the points. Returns a list of figures. | `solve`, `vessel`, `model`, `etd`, `fuel` |

```python
plot_quantiles(reports, "tws", unit="kts", prefix="IFS ensemble ", title="True wind", daily_ticks=True)
plot_fuel_quantiles(reports, daily=True)
plot_fuel_distribution({"Eff. 45%": reports.select(vessel="eff45"), "Eff. 60%": reports.select(vessel="eff60")})
```

### Helpers for your own figures

| Helper | Use |
| --- | --- |
| `get_steps(report, quantity)` | Times and values of a per-segment quantity, to draw it as steps: `plt.plot(*get_steps(report, "avg_bhp"))`. Also `report.steps(quantity)`. |
| `add_map_background(ax)` | Land, ocean, coastline and gridlines of the maps above, on cartopy axes. Returns the gridlines. |
| `set_plot_style()` | Applies the Architeuthis style to every figure from now on, for scripts that draw their own figures. Importing `plot_utils` no longer does this. |
| `plot_style()` | The same style inside a `with` block only. |
| `A4_PORTRAIT`, `REPORT_PANELS` | The A4 page size in inches, and the panel names of `plot_report`. |

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

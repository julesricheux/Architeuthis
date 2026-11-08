# Architeuthis 🦑🗺️

[![Downloads](https://static.pepy.tech/badge/architeuthis)](https://pepy.tech/projects/architeuthis)
[![Tests](https://github.com/julesricheux/Architeuthis/actions/workflows/tests.yml/badge.svg?branch=develop)](https://github.com/julesricheux/Architeuthis/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/architeuthis.svg)](https://pypi.org/project/architeuthis/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

An open-source marine weather and decision-making framework for hybrid sailing ships. It couples mesh-free, fully differentiable methods in a unified optimization environment to compute optimal routes under real-world constraints.

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
selected.quantiles("tws")                       # {quantile: values at each segment}
selected.to_gpx()                               # one GPX file per report
```

`tags` are entries added to the report. By default a report has `solve` (0 or 1), `model` (the atmospheric model), `vessel` (`Vessel.label`, such as `eff45`) and `member`. The UI also needs `init_fac`, the deviation factor of the route, which the scripts give as a tag.

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
| `plot_fuel_distribution(groups, figsize=(8, 3), save_as=None, show=True)` | Violins with box plots, one per group. `groups` gives reports by label. | `fuel` |
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
from architeuthis.exclusion import ExclusionZone, ExclusionZoneLibrary, default_exclusion_zones
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

topography = Topography("topo", exclusion_zones=default_exclusion_zones() + [zone], **domain)
```

`default_exclusion_zones()` gives North America, Brittany and the latest IIP iceberg limit, in this order. The bulletin is downloaded when it is first needed in a session, not at import, and `architeuthis.icebergs.refresh()` fetches it again. If the server cannot be reached, the last downloaded bulletin is used. If there is none, the zone is empty and the routing runs without the iceberg limit, with a warning.

`ExclusionZone.from_geojson(path, feature_id)` reads a polygon from a GeoJSON file. `visible` only concerns the display: a hidden zone still applies to the routing.

## Displaying routes: `ui.py`

```bash
cd architeuthis
python ui.py
```

`ui.py` serves on port 8052 and must be started from the `architeuthis/` folder. It displays the most recently modified file of `~/data/routes/`, so `reports.save()` is all it takes for the latest routes to appear at its next start. Each report needs the entries `model`, `vessel`, `member`, `init_fac`, `solve` and `fuel`, and optimized routes (`solve` 1) are shown when the page opens.

The default exclusion zones and those of `~/data/exclusion_zones/` are drawn with their label on the map, whether or not a routing used them. Each one can be hidden in the layers control at the top right of the map. The iceberg limit is listed as `Iceberg limit (unavailable)` when no bulletin could be obtained, so that it is not taken for a limit far from the route.

## Running the tests

The tests need no network access or credentials:

```bash
python -m pip install -e ".[test]"
python -m pytest
```


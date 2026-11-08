# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog https://keepachangelog.com
and this project follows Semantic Versioning https://semver.org

---

## [Unrealeased v0.0.0] - 2025-12-16

### First steps
- Vessel data reading, forecast downloading, short-term weather routing in one file

---

## [Unrealeased v0.1.0] - 2026-01-19

### Added
- Common module with abstract classes ArchiteuthisObject, ArchiteuthisData, ArchiteuthisSpatialData
- Forecast module with classes Forecast, Topography, and inherited, for both fixed, deterministic and ensemble envrionmental data.
- Vessel module with class Vessel.
- Environment module with class Environment, still to be implemented.
- Core module with class RoutingAnalysis.
- Dynamic routes visualisation through a Dash GUI.

---

## [Unrealeased v0.1.1] - 2026-02-09

### Added
- Satellite module with classes ArchiteuthisSatelliteData and inherited, for satellite data download.
- Example for ASCAT to model comparison.

---

## [Unrealeased v0.1.2] - 2026-02-09

### Added

- Exclusion zones definition.
- Icebergs module, including IIP iceberg zone automatic retrieval.

---

## v0.1.3 - 2026-03-02

### Added
- Proper numpy and optimization modules, retrieved from [AeroSandbox](https://peterdsharpe.github.io/AeroSandbox/) by [Peter Sharpe](https://peterdsharpe.github.io) (<pds [at] mit [dot] edu>)

### Fixed
- Fixed overall package concatenation.

---

### v0.1.4dev

- HRDPS grid formatting.

---

### Unreleased

- `Route` (new `route` module): waypoints with per-segment divergence and spread, legs, distance, reversal and restart from a position at sea (`from_position`). Routes are saved as JSON and kept in a `RouteLibrary` (`~/data/route_library/`).
- `voyage` module: `Schedule` converts dates to epoch seconds, `Voyage` takes a `route` (departure and arrival still work) and restarts with `from_position` at the same ETA. `Leg`, `Schedule` and `Voyage` remain importable from `core`.
- `PassagePlan` and `PassagePlanLibrary` (`~/data/passage_plans/`): timed positions of a routing with their route, schedule and metadata. `RoutingAnalysis.run` stores `report` and `passage_plan`.
- `RoutingAnalysis.evaluate(plan)`: open-loop evaluation of fixed positions with another vessel or forecast, reporting constraint violations.
- Example `examples/passage_planning.py`.
- `architeuthis.icebergs` no longer fails at import when the IIP server is unreachable: it uses the last downloaded bulletin and shapefiles, or none, with a warning. `Topography` ignores empty exclusion zones.
- A `Route` is callable like the former `poly_deviated_route` functions (`route(s)` is `route.ortho(s)`).
- Tests moved to a top-level `tests/` folder, configured in `pyproject.toml` and isolated from the network, credentials and home directory.
- New tests for the domain code, including end-to-end routing on synthetic data.
- GitHub Actions workflow running the tests on every push.
- `Opti` and `OptiSol` exported from the top-level package.
- Declared missing dependencies in `pyproject.toml`, `requirements.txt` and `environment.yaml`.
- `exclusion` module: `ExclusionZone` (polygon, label, color, displayed outline, initial visibility) and `ExclusionZoneLibrary` (`~/data/exclusion_zones/`). `Topography` accepts zones and plain lists of points. `core.exclusion_zones` is still available.
- `ui.py` writes the label of each exclusion zone on the map and each zone can be hidden in the layers control, including those of the library. An iceberg limit without data is listed as unavailable.
- `report` module: `RoutingReport`, the dict returned by `run` and `evaluate`, and `ReportCollection` to select, tabulate, export to GPX, save and reload reports. The JSON format is unchanged and `ui.py` reads the files as before.
- `plot_utils.plot_report`, the A4 page of `examples/simple_routing.py`, documented in the README. Its output is pixel-identical to the former function. Also `draw`, `get_steps`, `plot_variable`, `plot_power_and_weather`, `plot_quantiles`, `plot_fuel_quantiles`, `plot_convergence`, `plot_fuel_distribution` and `plot_fuel_vs_etd`. `plot_route` takes `ax`, `save_as` and `show`.
- `presets` module: ready-made atmosphere, wave, ensemble, current and topography sources. `common.Domain`: a longitude and latitude box for `**domain`.
- `route.RouteSet` and `RouteSetLibrary` (`~/data/route_sets/`): the ortho, minus and plus routes of a voyage, reversed and restarted together. `Voyage.from_routes` builds a voyage from them.
- `Vessel.label`, taken from the polar file name by default, and `Vessel.add_interpolators`.
- `RoutingAnalysis.run` takes `tags`, entries added to the report, and `callback`, called at each iteration. Reports have `solve`, `model`, `vessel` and `member` by default.
- `common.status` and `set_status_sink`: messages can be sent to a GUI instead of being printed.
- Examples rewritten around these additions, with their settings at the top and one line per figure, and `examples/README.md` as an index with a skeleton of a routing script. Compared with the former scripts on synthetic data, the results are the same except for the real gust in `passage_planning` and `ifs_route_tested_with_gfs`, and the reference distance and `model` tag of `short_term_routing`. `examples/reference_data.py` keeps what the former commented-out lines held: positions, past schedules, polars, fits and constraint variants.
- `forecast.HRDPSForecast` and `presets.hrdps_atmosphere`: the HRDPS regridding of `examples/short_term_routing.py`, now reusable. Its wind direction is not reliable yet: the components are relative to the rotated grid and are not rotated.
- `presets.vessel` and `presets.calm_current`.
- `RoutingReport.summary` and `ReportCollection.summary`: the key figures of reports. A slice of a `ReportCollection` is a `ReportCollection`.
- `plot_utils.plot_route_set` and `plot_ensemble_along_route`. `plot_fuel_distribution` takes `horizontal`.
- Tests running every example from start to finish on synthetic data (`tests/domain/test_examples.py`).
- New README for engineers who route motor and hybrid vessels, with credits and license. The reference of the former README moved word for word to `docs/user_guide.md`.

### Changed
- Importing Architeuthis has no side effect: no network access, logging setup or file writing. The iceberg limit is fetched on first use, logging is set up by `load_data` (`common.setup_logging`) and `~/.cdsapirc` is written before a CDS download (`common.ensure_cdsapirc`). Importing `plot_utils` no longer changes the matplotlib style: call `set_plot_style()` for your own figures.
- The JSON codec moved to `toolbox/json_utils.py`, so that reports do not need Dash. `wrappers/json_wrapper.py` still exports it.

### Fixed
- `python ui.py` failed at import in a terminal, because `architeuthis/numpy` hid numpy. `ui.py` now removes its own folder from the path.
- `ui.py` crashed at the first raster or contour with a GUI matplotlib backend, the default in a terminal, and its reloader then restarted it in a loop. It now uses Agg.
- `save_gpx` read epoch seconds as nanoseconds, which dated every point in 1970.
- `~/.cdsapirc` is no longer written with `key: None`.
- `EnsembleHerbieForecast.add_interpolator` argument names now match their position: `var_dim, time_dim, member_dim, latitude_dim, longitude_dim`. The positional order is unchanged.
- `RoutingAnalysis` no longer shares its default `options` dict between instances.
- `pyproject.toml` declared the MIT license, while the project is distributed under GPL v3 as in `LICENSE`.
- The latest HRDPS run could not be found, because `HerbieLatest` only looks on AWS and NOMADS by default. `HRDPSForecast` looks on the MSC Datamart.
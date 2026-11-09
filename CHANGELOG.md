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

## [Unrealeased v0.1.3] - 2026-03-02

### Added
- Proper numpy and optimization modules, retrieved from [AeroSandbox](https://peterdsharpe.github.io/AeroSandbox/) by [Peter Sharpe](https://peterdsharpe.github.io) (<pds [at] mit [dot] edu>)

### Fixed
- Fixed overall package concatenation.

---

## [Unrealeased v0.1.4] - 2026-11-06

### Added
- HRDPS grid formatting.
- Context dictionary formulation for custom constraints.
- RoutingAnalysis options.
- Gusts evaluation and constraints.

---

## v0.2.0 - 2026-11-09

### Added
- Route module with classes Route, Leg, RouteSet and their libraries: reversal, restart at sea, JSON storage.
- Voyage module with classes Schedule, Voyage, PassagePlan and PassagePlanLibrary.
- Exclusion module with classes ExclusionZone and ExclusionZoneLibrary; zone labels and toggles in the UI.
- Report module with classes RoutingReport and ReportCollection: summaries, tables, GPX and JSON export.
- RoutingAnalysis.evaluate for open-loop evaluation of fixed positions with reported violations.
- RoutingAnalysis.run tags and iteration callback; it now stores `report` and `passage_plan`.
- New plot_utils figures, including plot_report, and `ax`, `save_as` and `show` options in plot_route.
- HRDPSForecast class, with wind direction not yet reliable (components not rotated from the grid).
- Vessel.label and Vessel.add_interpolators.
- common.status and set_status_sink to send messages to a GUI.
- Top-level Opti and OptiSol exports, and missing dependencies declared.
- Offline test suite in `tests/`, covering domain code, end-to-end routing and every example, with GitHub Actions on every push.
- Passage planning example and examples index.
- New README with credentials tutorials; former reference moved to `docs/user_guide.md`.

### Changed
- Import has no side effect: iceberg limit fetched on first use, logging and `~/.cdsapirc` set up when needed, plot style applied by set_plot_style.
- IIP server failures fall back to the last downloads or to no zone, with a warning; Topography ignores empty zones.
- Examples restored to their settings before the refactoring, with schedules following the latest forecasts.
- Docstrings follow a single layout outside vendored code.
- JSON codec moved to `toolbox/json_utils.py`.

### Removed
- Presets module and common.Domain: data sources are built explicitly.
- Geographic zones from the package, except iceberg_zone: zones, waypoints and legs belong to the user.
- `examples/reference_data.py`, its content back in the examples as comments.

### Fixed
- `python ui.py` import failure, and its crash and restart loop with GUI matplotlib backends.
- save_gpx dating every point in 1970.
- `~/.cdsapirc` written with `key: None`.
- EnsembleHerbieForecast.add_interpolator argument names not matching their position.
- RoutingAnalysis default options shared between instances.
- MIT license declared in `pyproject.toml` instead of GPL v3.
- Latest HRDPS run not found: HRDPSForecast now looks on the MSC Datamart.
- `pyproject.toml` declared the MIT license, while the project is distributed under GPL v3 as in `LICENSE`.
- The latest HRDPS run could not be found, because `HerbieLatest` only looks on AWS and NOMADS by default. `HRDPSForecast` looks on the MSC Datamart.
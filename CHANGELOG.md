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
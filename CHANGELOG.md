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
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

---

## v0.3.0 - 2026-11-17

### Fixed
- The UI showed only an error with dash-mantine-components 3, which needs React 19. The app requires Dash 4.5 and DMC 3, and `ui.py` selects React 19.
- `RoutingAnalysis.run(solve=False)` no longer calls IPOPT, whose empty problem crashed the kernel with `spral` on Windows. The baseline is evaluated directly.
- B-spline interpolators on 2-point axes (degree 1) broke the CasADi Hessian, so solves failed. These axes are now raised to the requested degree, with the same values.
- `DeterministicHerbieForecast` could not read fields at different heights in one download, such as the IFS 10 m wind with the 2 m temperature: cfgrib skipped `t2m` and the files failed to concatenate on `heightAboveGround`. Each file is now read level by level (`forecast.open_grib`) and merged, without cfgrib index files, which Herbie's rewritten subsets made incompatible and which logged a warning per file at each read.
- The UI failed to open reports without a `member` entry: `json_wrapper.route_to_geojson` takes member 0 by default.

### Security
- Credentials can be saved once, encrypted in the credential store of the operating system (Windows Credential Manager, macOS Keychain, Secret Service), with `python -m architeuthis.credentials set` or `credentials.save_credential`. Environment variables still work and take precedence.
- The CDS key is given to `cdsapi.Client` directly and never written to `~/.cdsapirc` in plain text. A `~/.cdsapirc` of the user is still read when no key is found.
- Data sources no longer keep credentials as attributes: they are read when downloading.

### Added
- `credentials` module: `save_credential`, `get_credential`, `credential_sources`, `delete_credential`, `require_credentials` and the `python -m architeuthis.credentials` command (`set`, `status`, `delete`).
- `EUMDAC_KEY` and `EUMDAC_SECRET`, the new names of `EUMDAC_USER` and `EUMDAC_PWD`, which are still read.
- The variables of the provider clients are read too: `CDSAPI_KEY`, `COPERNICUSMARINE_SERVICE_USERNAME`, `COPERNICUSMARINE_SERVICE_PASSWORD`.
- `ARCHITEUTHIS_HOME` moves the data folder, `~/data/` by default.
- `keyring` dependency.
- `modeling.HybridInterpolatedModel`, a SurrogateModel called like InterpolatedModel whose NumPy and CasADi evaluators are built once from the same data and give the same values.
- `input_names(var_key)` on data objects, and the `coord_keys` argument of `add_interpolator`.
- Data objects hold general models, not only lookup tables: `add_function(var_key, function, inputs, args, output)` registers a function of a dict of inputs and of fixed arguments, such as a semi-empirical polar with fitted parameters, and `add_model` any object called like a table. `common.FunctionModel` wraps the functions; `output` picks a part of their result, such as a component of a `(value, components)` tuple.
- A `Vessel` without a polar file: `filepath` is optional, for vessels whose polars are functions.
- `examples/function_polar_routing.py`: a routing with a dummy function-based polar, without a polar file, whose sails take the wind averaged between 10 m and 100 m and the IFS air temperature.
- Vessel models can take more inputs than the polar axes: `sog`, `swh`, `mwa`, `aws`, `awa`, `twd`, and any forecast variable, such as a water temperature or a wave period, which `RoutingAnalysis` reads from the first of `atmosphere`, `wave` and `current` that has a model of it. The wind at any other height, such as `tws100`, `twd100`, `twa100`, `aws100` and `awa100`, is computed relative to the vessel from the forecast variables `u100` and `v100`, as the 10 m wind is.

### Changed
- Credentials are read when a download needs them rather than at import, so a variable set during a session is used.
- A missing credential stops the download at once, with a ⚠️ status and a `MissingCredentialError` naming it and the command that saves it. The startup log no longer lists missing credentials.
- The version is written only in `architeuthis/__init__.py`: `pyproject.toml` reads it (`dynamic`), and so does the release check of the tag.
- `common._USER` renamed `common._USER_HOME`, as it holds the home directory.
- README rewritten to be shorter, around the two ways of modelling a vessel (polar table or functions) and the inputs the routing provides on its own.
- `add_interpolator` builds a HybridInterpolatedModel instead of a CasADi interpolant: B-spline tables are built hundreds of times faster, with the same values, and numeric queries are computed with NumPy.
- `HybridInterpolatedModel` extrapolates by default (`fill_value=None`), where InterpolatedModel returns NaN.
- The wave direction is interpolated through its east and north components weighted by the wave energy, `uw` and `vw`, added by the new `Forecast.add_wave_components`, instead of `mwd`, whose jump from 360 to 0 deg made the routing unstable. RoutingAnalysis needs the wave interpolators `swh`, `uw` and `vw`; reports still give `mwd`.
- Data objects are queried with dicts keyed by standard names (`valid_time`, `member`, `latitude`, `longitude`; `stw`, `tws`, `twa`, `hs`, `wa`), whatever the names in the data. Arrays of shape (n_queries, n_dims) are still accepted.
- The models of a data object are in `models`; `interpolators` is the same dict, kept for compatibility, and `remove_model` is the new name of `remove_interpolator`, which still works. Queries may hold keys that a model does not take, which are ignored, and a missing input raises a `KeyError` naming it.

### Removed
- `common.ensure_cdsapirc`, `common.file_path` and the credential constants of `common` (`_CDS_API_KEY`, `_CMEMS_USER`, `_CMEMS_PWD`, `_EUMDAC_USER`, `_EUMDAC_PWD`, `_EUMDAC_CREDENTIALS`).

---

## v0.3.1 - 2026-11-18

### Added
- Additional variables: `RoutingAnalysis(variables=...)`, and `run(variables=...)` and `evaluate(variables=...)` for one run, compute quantities that the objective and the vessel models do not need, at the middle of each segment, and put them in the constraint context `ctx` and in the report. A variable is a model key of the atmosphere, wave, current or vessel (`"gust"`, `"slope"`, or `"wave.slope"` to name the source), a derived quantity (`tws_gust` and `aws_gust` in kt, from the forecast `gust` or the standard ratio; the wind at any height, such as `tws100`), a routing quantity, or a callable of `ctx`. For example, gust thresholds and a wave slope (`swh / mwp`) can be constrained and reported. `core.normalize_variables` reads the accepted forms, and the variables are recorded in the passage plan metadata.
- `examples/function_polar_routing.py` downloads the IFS 10 m gust and mean wave period, and reports the gusts, the wave slope, the wind at 100 m and the air temperature as additional variables.
- `architeuthis/data/cloud_genera.json`: the ten cloud genera of the WMO International Cloud Atlas (Table 2), with their abbreviation, étage and the étages they reach, form, composition, precipitation (character, intensity and forms), species, varieties, supplementary features, accessory clouds, mother clouds, appearance and significance at sea, plus the heights of the three étages. It is the reference for describing the sky along a route.
- `architeuthis.sky` diagnoses the clouds from nine fields of IFS or GFS: total, low, middle and high cloud covers, CAPE, precipitation rate, 2 m temperature and dewpoint, temperature at 700 hPa. `IFS_SKY_REGEX` and `GFS_SKY_REGEX` download them, `add_sky_models` registers them in common keys and units, `sample` reads them along a route, `diagnose` gives the cover in oktas, the cloud base, fog, and one genus per étage as seen from deck, and `describe` writes one line per point for the crew. It stands apart from the routing for now, and its thresholds are not calibrated yet.
- `examples/sky_along_route.py` compares the skies of IFS and GFS along a great circle, as a table and as meteograms.
- `plot_utils.plot_sky`, also `sky.draw`: the sky along a route as a meteogram, in two styles. `"cells"` has one row per étage shaded by its cover, the genera of each column stacked and colored by their form, "/" where hidden, a frame for the Cb and Ns that rise through every étage, the cloud base, fog and the oktas. `"smooth"` paints the clouds after their genus over a day or night sky (Cu domes, Cb towers with anvil and lightning, rolls of Sc and Ac, layers, Ci strokes), with rain or snow under them, fog, WMO sky cover symbols and a tag per genus where it is. Both have the precipitation rate below. `plot_utils.sun_elevation` gives the elevation of the Sun.
- `sky.diagnose` also gives every genus present per étage, as bit masks read by `sky.genera_present`, and `describe` joins them (`Cb+Cu`).

### Changed
- `variables=["gust"]` computes the true and apparent wind gusts, `tws_gust` and `aws_gust`, in kt. The gust model itself is reached under another name, as in `{"gust_ms": "atmosphere.gust"}`.

### Deprecated
- `RoutingAnalysis(options={"include_gusts": ...})` raises a `DeprecationWarning` and will be removed in 0.4.0: give `variables=["gust"]`. Until then, an analysis without `options` still computes the gusts; from 0.4.0, they are computed only when `"gust"` is in the variables.

### Fixed
- Reading Herbie GRIB files flooded the console with xarray `FutureWarning`s about the default of `compat`, for example with the IFS 10 m gust next to the 10 m wind. `cfgrib.open_datasets` groups fields through merges that rely on the current default, `"no_conflicts"`: `forecast.open_grib` now pins it during the read and silences that warning there only, so the grouping stays the same when xarray changes the default.
- `save_credential` seemed to have no effect when an environment variable of the same credential was set, such as `CMEMS_PWD` or `COPERNICUSMARINE_SERVICE_PASSWORD` from before 0.3.0: that variable kept being read first. Saving now removes these variables from the current session and names them in a ⚠️ status, so the saved value is used at once. It also reads the value back from the credential store and raises an error if the save did not take.
- `plot_fuel_quantiles` raised a `KeyError` when no report had converged (with `converged_only=True`): it now draws empty axes.
- The example tests no longer depend on the settings of the examples: any variable a script reads is added to the synthetic data, and the checks of `simple_routing.py` hold whatever its models, vessels and runs.

---

## [Unreleased]

### Added
- A routing analysis runs without a complete environment: `atmosphere`, `wave` and `current` are optional arguments of `RoutingAnalysis`, None by default, and each one left out is a calm source whose fields are zero, a calm wind (`u10`, `v10`), a flat sea (`swh`, `uw`, `vw`) or no current (`uo`, `vo`). `forecast.calm_forecast(source)` builds these sources, `Forecast` objects without data whose models are zero functions of the time and position, and `forecast.ENVIRONMENT_FIELDS` lists their fields. The time grid comes from the first source with data, or is every 3 hours (`core.DEFAULT_TIME_STEP`) without any. The topography is still required, now checked with a `TypeError` since it has a default of None.
- The vessel consumption has three formulations, and the routing only needs one of them, the first that the vessel has: `hourly_consumption` (kg/h), `total_power` (kW, propulsion and hotel) burnt at `sfoc`, or `bhp` plus `hotel_load` burnt at `sfoc`. Each is a table, a function or a constant. `Vessel.consumption(query)` computes them, `Vessel.consumption_model`, `consumption_keys()` and `consumption_quantities()` describe them, and `vessel.CONSUMPTION_KEYS` lists the three models.
- `hotel_load` and `sfoc` can be vessel models, which take precedence over the numbers or functions given to `Vessel` and can take `bhp`, `hotel_load` or `total_power` as inputs: an sfoc curve of the engine load, for example. Any vessel model listed in `variables` can take them too.
- `examples/vessel_definitions.py` compares the ways of defining the consumption of a vessel on a short-sea leg, with IFS wind and a calm sea, without polar file or credentials.
- `add_constant(var_key, value)` registers a constant model without input on any data object, a constant brake power or hotel load for example.
- Reports hold the consumption quantities of the formulation: `hourly_consumption` always, and `bhp`, `hotel_load`, `total_power` and `sfoc` when the formulation computes them. They are in `ctx` for the constraints.
- `plot_report` draws `total_power`, else `hourly_consumption`, on its power panel when the report has no `bhp`, and says so on the sails panel when the report has no `sails_contribution`.
- ASCAT winds from Copernicus Marine: `satellite.CopernicusASCATData` reads the daily gridded swaths of Metop-B and -C (WIND_GLO_PHY_L3_NRT_012_002, 0.125 or 0.25 deg, ascending and descending orbits), subset by the server, with the CMEMS credentials. `satellite.CopernicusSatelliteData` reads any other Copernicus Marine observation dataset.
- `architeuthis.copernicus` holds what forecasts and satellite data share for Copernicus Marine: the `CopernicusMarineData` mixin, whose `_subset` downloads a subset with the credentials, and `copernicusmarine_credentials_file()`.

### Changed
- casadi is required from 3.7 (`casadi>=3.7` in `pyproject.toml`, `environment.yaml` and `requirements.txt`). 3.7 and 3.8 are both supported.
- `verbose` now controls the information messages of every object (📦 reading, ⬇️ downloading, ➕ added, ➖ removed, 🟦 already there, the routing banner...): `verbose=False` silences them through the new `ArchiteuthisObject.info`. Warnings (⚠️) and errors (💔) are still always reported, including the ⚠️ of `Topography` about a skipped exclusion zone, formerly hidden by `verbose=False`. `ReportCollection.save` takes `verbose` too.
- `max_bhp` and `sails_contribution` are no longer required: a vessel needs only a consumption model, and they are computed and reported when listed in `variables`, as any other vessel model: `RoutingAnalysis(..., variables=["max_bhp", "sails_contribution"])`. The examples and the quick start list them.
- The default constraints limit `max_bhp` when it is in the variables, else `bhp`, else `total_power`, to `max_power`, and only if it is not None. `Vessel(max_power=None)` gives no power limit.
- `examples/wind_only_routing.py` routes with the IFS wind alone and a dummy function polar, the waves and the current left out.
- `passage_planning.py`, `function_polar_routing.py` and `vessel_definitions.py` leave out the current (and the waves for the last one) instead of filling a forecast with zeros.
- The fuel is computed as `sum(hourly_consumption * dt) / 1e3`, which gives the same value as before for a `bhp` model.
- The brake power is `bhp` in reports, in `ctx` and in the default table columns, the key of its vessel model, instead of `avg_bhp`. The y label of `plot_power_and_weather` is `BHP / kW`. Saved reports with `avg_bhp` are read with `bhp`.
- The examples follow the new vessel definition: the sfoc and hotel load curves are vessel models of `total_power` and `bhp` (active in `ensemble_routing.py`, as commented alternatives in `simple_routing.py` and `long_term_routing.py`), `function_polar_routing.py` shows the other consumption formulations as commented alternatives, and the unused `columns` lists are gone.
- `plot_power_and_weather(max_bhp=True)`, `plot_ensemble_along_route`, `draw(sails_threshold=...)` and the tooltips of the UI map skip `max_bhp` and `sails_contribution` when a report has none.
- `satellite.ASCATData` takes its winds from the first source of `sources` that works, by default EUMETSAT then Copernicus Marine, with a ⚠️ status for each one that fails, and tells which in `source`. `sources="cmems"` uses Copernicus Marine only. The former class, reading EUMETSAT only, is `satellite.EUMETSATASCATData`. Both sources give `lat`, `lon`, `time`, `valid_time`, `wind_speed` and `wind_dir`, on swath dimensions for EUMETSAT and on `swath, day, latitude, longitude` for Copernicus Marine.
- `EUMETSATData` downloads only the products crossing its domain (`bbox` of the search), 3 instead of 14 orbits for the Bay of Biscay over 12 hours, and raises `FileNotFoundError` when there is none.
- `CopernicusForecast` inherits its download from `copernicus.CopernicusMarineData`, unchanged.

### Deprecated
- `Vessel(sfc=...)` and `Vessel.sfc` raise a `DeprecationWarning` and will be removed in 0.4.0: use `sfoc`, the specific fuel oil consumption in g/kWh.
- A vessel with `max_bhp` or `sails_contribution` models still has them computed when `variables` does not list them, so that the default constraints and existing scripts work as before, with a `DeprecationWarning`. From 0.4.0, they are computed only when listed.
- `Vessel` without `max_power` still has 1e12 kW, with a `DeprecationWarning`. From 0.4.0, the default is None, no power limit.
- A `bhp` or `total_power` model without `sfoc` still burns at 0 g/kWh, a zero objective, with a `DeprecationWarning`. From 0.4.0, it raises an error.
- `report["avg_bhp"]`, `ctx["avg_bhp"]`, `report.get("avg_bhp")` and `"avg_bhp" in report` still give the brake power, with a `DeprecationWarning`: use `bhp`.

### Fixed
- `requirements.txt` still pinned `dash==3.2.0`, unsupported since 0.3, and lacked `keyring`: it now asks for `dash==4.5.0` and `dash-mantine-components>=3,<4`, as `environment.yaml`, and `keyring`.
- With casadi 3.8, a vessel table optimized without wave or atmospheric forecast failed with a CasADi reshape error: the calm fields were DM zeros, which NumPy functions turn into NumPy columns from casadi 3.8, broadcast to a square by the table query. They are MX zeros for a symbolic query.
- The cache of `EUMETSATData` never worked: each run downloaded every product again, truncating the file it tested, and products already downloaded were left out of `path`. They are now downloaded once, through a `.part` file, and always read.
- `WAVE_COMPONENTS_OFFSET` is back to 1e-2 m² from 0: the wave direction had no gradient where the wave components vanish (a calm sea, land cells, the steps past the forecast horizon), so IPOPT stopped at its first iteration with `Invalid_Number_Detected` for any vessel model taking `hs` or `wa`, such as a polar table.

---

## v0.4.0 - Planned

### Removed
- `RoutingAnalysis(options={"include_gusts": ...})`, deprecated since 0.3.1: give `variables=["gust"]`. An analysis then computes `tws_gust` and `aws_gust` only when `"gust"` is in its variables, no longer by default.
- `Vessel(sfc=...)` and `Vessel.sfc`, deprecated in favour of `sfoc`.
- The former report and `ctx` name `avg_bhp` of the brake power, deprecated in favour of `bhp`. Saved reports with `avg_bhp` are still read with `bhp`.

### Changed
- Vessel models other than the consumption, `max_bhp` and `sails_contribution` included, are computed only when listed in `variables`.
- `Vessel(max_power=...)` defaults to None, no power limit, instead of 1e12 kW.
- A `bhp` or `total_power` model without `sfoc` raises an error instead of burning at 0 g/kWh.

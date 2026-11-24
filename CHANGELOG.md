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

## v0.3.2 - 2026-11-20

### Added
- A routing analysis runs without a complete environment: `atmosphere`, `wave` and `current` are optional arguments of `RoutingAnalysis`, None by default, and each one left out is a calm source whose fields are zero, a calm wind (`u10`, `v10`), a flat sea (`swh`, `uw`, `vw`) or no current (`uo`, `vo`). `forecast.calm_forecast(source)` builds these sources, `Forecast` objects without data whose models are zero functions of the time and position, and `forecast.ENVIRONMENT_FIELDS` lists their fields. The time grid comes from the first source with data, or is every 3 hours (`core.DEFAULT_TIME_STEP`) without any. The topography is still required, now checked with a `TypeError` since it has a default of None.
- The vessel consumption has three formulations, and the routing only needs one of them, the first that the vessel has: `hourly_consumption` (kg/h), `total_power` (kW, propulsion and hotel) burnt at `sfoc`, or `bhp` plus `hotel_load` burnt at `sfoc`. Each is a table, a function or a constant. `Vessel.consumption(query)` computes them, `Vessel.consumption_model`, `consumption_keys()` and `consumption_quantities()` describe them, and `vessel.CONSUMPTION_KEYS` lists the three models.
- `hotel_load` and `sfoc` can be vessel models, which take precedence over the numbers or functions given to `Vessel` and can take `bhp`, `hotel_load` or `total_power` as inputs: an sfoc curve of the engine load, for example. Any vessel model listed in `variables` can take them too.
- `examples/vessel_definitions.py` compares the ways of defining the consumption of a vessel on a short-sea leg, with IFS wind and a calm sea, without polar file or credentials.
- `add_constant(var_key, value)` registers a constant model without input on any data object, a constant brake power or hotel load for example.
- Reports hold the consumption quantities of the formulation: `hourly_consumption` always, and `bhp`, `hotel_load`, `total_power` and `sfoc` when the formulation computes them. They are in `ctx` for the constraints.
- `plot_report` draws `total_power`, else `hourly_consumption`, on its power panel when the report has no `bhp`, and says so on the sails panel when the report has no `sails_contribution`.
- ASCAT winds from Copernicus Marine: `satellite.CopernicusASCATData` reads the daily gridded swaths of Metop-B and -C (WIND_GLO_PHY_L3_NRT_012_002, 0.125 or 0.25 deg, ascending and descending orbits), subset by the server, with the CMEMS credentials. `satellite.CopernicusSatelliteData` reads any other Copernicus Marine observation dataset.
- `examples/ascat_sources.py` downloads ASCAT winds through `ASCATData`, with its fallback and with Copernicus Marine only, then through each source class with its options, and compares both sources on the passes they share (on the Bay of Biscay, no bias and 0.27 m/s RMS difference).
- `architeuthis.copernicus` holds what forecasts and satellite data share for Copernicus Marine: the `CopernicusMarineData` mixin, whose `_subset` downloads a subset with the credentials, and `copernicusmarine_credentials_file()`.
- Geostationary cloud imagery, without account, whose channels are chosen as the variables of a forecast, with `channels` (`satellite.IMAGERY_CHANNELS`): `"ir"` (infrared, day and night) and `"visible"` (by day), the only single channels that both servers give. `satellite.EUMETViewData` (Meteosat from EUMETView: MTG FCI HRFI IR 10.5 um at 1 km and VIS 0.6 um at 0.5 km, or MSG SEVIRI at 3 km) and `satellite.GIBSData` (GOES-East ABI bands 13 and 2 from NASA GIBS, or GOES-West and Himawari layers through `wms_layers`), both `WMSImageryData`, download the server layer of each channel over a box, a period and a resolution, every 10 min, at the times every channel has, cached in `~/data/wms/`. `native_resolution` chooses the server layer where a server has several for a channel (`"finest"` by default, `"coarsest"`, `"3km"`..., or one per channel, `satellite.native_layers`); `resolution` sets the size of the requested images, hence the download time (about 1 s an image of 1600 x 500 pixels, four at a time); `DETAIL_RESOLUTIONS` gives the grid that shows all the detail of the finest layers. Images larger than `wms_utils.MAX_SIZE` (4096 pixels) are requested in tiles that join on the pixel grid (`wms_utils.get_map_array`). Their colours are turned back into a common scale: brightness temperatures (`bt`, in K) for the infrared, with a calibrated grey ramp for EUMETView and the published colormap for GIBS, both agreeing within 1.6 K (median) over the Atlantic; a brightness from 0 to 1 (`brightness`) for the visible.
- `satellite.GeostationaryImagery` joins several of them into one continuous layer: each pixel from the satellite that sees it the most directly, blended over a few degrees along the seam, a failing source left out with a ⚠️ status. In the visible, where the brightness of a scene depends on the angles of the sun and the satellite, the levels of the other sources are matched to the first along the seam, image by image (`gain`, `offset`). `image(time, channel, colormap=...)` draws a channel with a colour scale of Windy chosen when drawing, by default that of the channel (`IMAGERY_COLORMAPS`), clear sky or dark sea optionally transparent, ready for a map layer; `bounds` gives its corners. `image(box=..., scale=4)` draws a part of the domain with each pixel interpolated into 4 x 4 (`image_utils.rescale`, bilinear by default, `order=3` bicubic): the values are interpolated before being coloured, so the steps of a colour scale stay sharp; `extent(box)` places it.
- Satellite imagery: files are managed as those of the forecasts: nothing on disk is downloaded again. Each image is a PNG in `~/data/wms/<host>/<layer>/<box>/`, opened rather than downloaded when it is there; the times a server listed for a layer, and the periods they cover, are kept in `<layer>/times.json`, so that loading a period again asks the server nothing (💾 statuses). An image still empty `satellite.EMPTY_FINAL_AFTER` (3 h) after its time is recorded there and not asked again, whereas a more recent one may not be produced yet and is asked again by a later run. If a server cannot be reached, the images of the period on disk are used, with a ⚠️ status. The GIBS colormaps are kept in `<host>/colormaps/`.
- Infrared limb correction: each geostationary satellite reads colder towards the limb of its disk (more atmosphere, the sides of the clouds), Meteosat in the west of the North Atlantic and GOES-East in the east, up to 15 K from each other. `limb_correction=True` (`EUMETViewData`, `GIBSData`, `GeostationaryImagery`, off by default) adds `satellite.limb_cooling(zenith)`, `LIMB_COOLING` (18.4 K) times (zenith / 90)^4, one law for both satellites fitted on their overlap: they then agree within about 3 K over 75 W - 5 E. `geo_utils.geostationary_zenith` gives the zenith angle of the satellite. `examples/cloud_imagery.py` uses it.
- `toolbox.windy_colormaps.get_satellite_cmap(name, quantity=None)`, beside the wind and wave colormaps, gives the colormap and norm of each satellite colour scale (`SATELLITE_STOPS`, the quantity each draws in `SATELLITE_QUANTITIES`): for the brightness temperature, `"infra"` the legend of Windy's Infra+ (grey to white at 240 K, then coloured cloud tops from blue to dark red at 182 K) and `"blue"` Windy's Blue as estimated by eye (clear sky transparent at 290 K, translucent white at 270 K, opaque white at 250 K, darker to dark grey at 190 K); for the brightness, `"visible"` black to white. `image_utils.values_to_rgba` keeps the alpha of a colormap.
- `toolbox.wms_utils`: WMS requests (capabilities, time extent and times of a layer, maps), the times of a GIBS layer from DescribeDomains and the GIBS colormaps. `toolbox.image_utils`: PNG decoding and encoding, palette inversion (including palettes that repeat colours), smooth resizing that keeps NaN in place, values drawn on a colour scale, matching of levels by quantiles, smooth blending weights and blending, animated GIFs. `toolbox.geo_utils.central_angle`.
- `examples/cloud_imagery.py` loads the last hours of infrared and the visible around the latest midday over the North Atlantic, checks both satellites on their overlap, and draws each source, the combined layer, the share of each satellite, the three colour scales at the same time, a zoom on Saint-Pierre-et-Miquelon downloaded at 0.01 deg and drawn 4 times finer, the clouds in Windy Blue over a map and an animation.

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
- README: a Satellite Observations section, a credentials table by provider that lists the sources needing no account, and step-by-step tutorials for Copernicus Marine (currents and ASCAT), the Climate Data Store and EUMETSAT. The user guide documents the satellite classes in a section of their own, and the examples index groups the scripts by what they need.

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

## Unreleased

### Added
- `architeuthis.fuels`: `FUELS`, the fuel types (MDO, MGO, LFO, HFO, VLSFO, LNG by engine type, LPG, methanol, ethanol, ammonia, hydrogen, FAME, HVO, road diesel, unleaded petrol) with their density, lower heating value, CO2, CH4 and N2O factors, methane slip and well-to-tank intensity (FuelEU Maritime defaults, IPCC for road fuels), their tank-to-wake and well-to-wake intensities, and `co2(fuel)` and `ghg(fuel)` of a voyage; `get_fuel` finds them by key or alias (`FUEL_ALIASES`).
- Routes can be shared aboard as one HTML file (#10): `ReportCollection.share(path=None, **options)` and `dux.share.share_routes` write the chosen routes, the forecasts around them and the exclusion zones in a page that opens in any browser, offline, on a 3D globe drawn by MapLibre GL JS 5 (downloaded once to `~/data/viewer/` and put in each file, from a CDN when it cannot be downloaded). Files go to `~/data/shared/` by default, and weigh a few MB for a week with two models.
- The page has a timeline (play, steps, speed, the frames of each source and the schedule of each route, routes of the same schedule grouped), a layers panel (source, wind, gusts, waves, current or pressure, wind barbs or arrows, isobars, opacity, routes with their fuel, distance and warnings, exclusion zones, an offline land map (OpenStreetMap disabled for now), OpenSeaMap sea marks, from zoom 7 rather than 9, latitude and longitude lines, overlays), boats moving along their routes, tooltips with the variables the analyst chose, a readout of the weather under the cursor, a note to the crew and keyboard shortcuts.
- `dux.share.build_scene` gives the content of a page as JSON-ready data and `share.viewer_html` the page; `route_label`, `route_labels`, `segment_variables`, `segment_values`, `variable_info` and `default_variables` name routes and list their variables: every array of a report along the route, per node or sampled between nodes too, such as the topography `z`, shown by its worst point of each segment. Forecasts are read from `u10`/`v10` or `si10`/`wdir10`, `gust`, `msl` or `prmsl`, `swh` with `mwd` or `dirpw`, and `uo`/`vo`, as `Forecast` objects or datasets, and stored as 8-bit PNG frames around the routes.
- `architeuthis/dux/data/land.json` and `land_detail.json`, the land of the offline page from Natural Earth 1:10m (public domain), built by `tools/make_land.py`: simplified at 0.05 deg for the globe and at 0.005 deg (about 500 m) from zoom 5, read once the page is shown so that it opens as fast.
- `architeuthis.dux` (display and user experience) holds the graphical reporting and sharing tools: `share`, `ui`, the viewer page and the former Leaflet wrappers. Its Dash dependencies are the `dux` extra, `pip install "architeuthis[dux]"`, so that `pip install architeuthis` gives the routing, the data sources, the reports and the figures without Dash or Flask. Importing a page without them raises `dux.MissingExtraError` (an `ImportError`) with that command.
- The analyst names and describes each route and comments on points of it, which the crew reads on the globe and the timeline: `build_scene(labels=..., comments=...)`, and in `ui.py` the name of each route, edited in place, a description box per route and a click on the preview.
- Any field of a forecast can be shared and shown, besides wind, gusts, waves, current and pressure (#10): `share.FIELDS` gives, on the colour scales of `windy_colormaps.FIELD_COLORMAPS` and `PRECIPITATION_TYPES` (with `get_field_cmap`), the wave period and the wave slope computed from it, shown with wave arrows, the temperature, the CAPE and the precipitation rate and type (in categories), any other field is shown in its units on a scale of its values, and so are the `add_function` models of a `Forecast`. `build_scene(fields=...)` and a list of `ui.py`, like that of the tooltip variables, choose them, `forecast_fields` lists them, and the page chooses the arrows drawn over a field, which take its colour. `ui.py` downloads the gusts, the CAPE, the IFS precipitation type and the wave period, chosen at the top of the script in `ATMOSPHERE_FIELDS` and `WAVE_FIELDS` and translated for each model by `GRIB_SEARCH`.
- The fields of a source in a compact list, one per row with an icon of the field (wind, gusts, waves, current, pressure, period, slope, temperature, dew point, CAPE, precipitation and its type, cloud covers by étage, a mesh for any other), switched with the up and down keys, the other weather choices in labelled rows under it, a weather picker to drag on the globe (`P`), a dot with a line up to the side of its card telling the position, model, wind and gusts, waves, pressure and the field shown, a light and a dark theme (`T`, `settings={"theme": ...}`), isobars every 2 or 4 hPa, with or without their pressure labels, highs and lows marked H and L with their pressure, and charts at their valid time: an overlay with a `time` brings the page to it when shown, and has its mark on the timeline.
- The highs and lows (H, L with their pressure) are found in each forecast frame and move smoothly along the timeline, every 15 min as the fields: each is paired with the nearest system of its kind in the next frame, within the way a system goes at 60 kt (`CENTRE_SPEED`), its position, at the bottom of a parabola between the points of the grid, and pressure interpolated in time; a system without a pair fades out, a new one fades in.
- A panel of plots beside the globe (`G`), for the crew to follow a route and compare it with what they see aboard: SOG and STW, sails, hotel load and propulsion power stacked from zero with the fluctuation of the power dashed in the colour of the total, true and apparent wind with their gusts, waves, pressure along the route and the clouds painted as `plot_sky` draws them, each axis fitted to its values (from zero for power, wind and waves, 0 to 100 % for the sails), drawn at twice the pixels of the screen at least with thin lines and short dashes, with a line at the time of the timeline, the values at that time, and the time moved by a click or drag on a plot. The route of the plots is chosen at their top or by a click on the globe or in the list of routes, where it is marked. The plots and the panel of the layers are resized by dragging their inner edge (a double click gives back their first width), and their widths are kept on reload. Routes keep the entries of `share.PLOT_VARIABLES` for it, their pressure (`PRESSURE_NAMES`, `route_pressure`) and their sky (`route_sky`, `SKY_ENTRIES`), diagnosed from the nine fields of `sky.SKY_VARIABLES`, all read from the routing report and never from the forecasts of the file: a routing lists them in its `variables`.
- `"clouds"` in the routing `variables` (`core.CLOUDS_VARIABLE`) keeps the sky of the passage in the report: the nine fields of `sky.SKY_VARIABLES` from the atmosphere, registered by `sky.add_sky_models` on an IFS or GFS atmosphere that has their data and no sky model yet (else a `KeyError` names the fields missing). `sky.from_report(report)` reads them back with their `diagnose`, for `plot_sky` and `describe`, and the share file draws them in its cloud plot.

### Changed
- Consumptions are volumes, in L/h: an `hourly_consumption` table or function gives litres per hour, the mass burnt at `sfoc` is divided by the fuel density, and the fuel of the voyage, still in tonnes, is the volume times the density. The density is the new `Vessel(fuel_density=...)`, in kg/L, else that of the new `Vessel(fuel_type=...)`, marine diesel oil ("mdo", 0.85 kg/L) by default; the passage plan metadata records both. Reports, tooltips and figures give `hourly_consumption` in L/h. An `hourly_consumption` model written in kg/h should be divided by the density.
- `ui.py` is now the analyst's page for sharing: beside a live preview of the file, it chooses the report file of `~/data/routes/`, the routes, the variables of the route tooltips, the models, the NOAA surface analysis, a title and a note, and downloads the file. It runs from anywhere with `python -m architeuthis.dux.ui`, without debug mode, and writes nothing to the working directory. The globe replaces the Mercator map. Only the iceberg limit is ticked at first, the zones of the library being unticked, and the file holds only the zones ticked in the preview, all shown when it opens (`ticked_zones`, sent by the page as `"architeuthis:zones"`), and the NOAA analysis comes with its valid time, estimated from the date of the chart: it is always shared, hidden at first, and its box follows each toggle of the chart in the preview.
- The page is flat: panels, labels and glyphs have no outline or shadow, except the thin white outline of the routes. The sea is dark grey, the land flat over the weather with a thin, faint coastline shaded on the sea side, and wind barbs and wave and current arrows take the vivid colour of the field under them, on a lattice that panning and rotating the globe leave in place, in both themes alike, as the isobars. Wave glyphs tell the height: a head for each 4 m, a chevron of the same proportions for each metre left. The points of the routes are 1.3 times their first size (`ROUTE_POINT_SCALE` at the top of `viewer.js`), and the latitude and longitude lines stronger. Routes follow the great circles between their nodes, with their points halfway along them and the boats moving along them, rather than straight lines in latitude and longitude.

### Deprecated
- `architeuthis.wrappers.json_wrapper` and `architeuthis.wrappers.leaflet_wrapper`, moved to `architeuthis.dux`: the former names warn (`DeprecationWarning`) and give the new modules until 0.4.0.

### Removed
- The `app` extra, replaced by `dux`: `pip install "architeuthis[dux]"`.
- The Leaflet map of `ui.py`, its forecast raster, arrow and contour routes, its EUMETSAT animation, and the tracked `assets/noaa_overlay.png` that it overwrote at each start. `leaflet_wrapper` and `json_wrapper` stay, in `architeuthis.dux`, with the `assets/` folder; a stray copy of `dashExtensions_default.js` in `toolbox/assets/` is gone.

### Fixed
- On a phone, the time of the share page's timeline no longer widens the page: its distance to now is left out and the time shortened.
- The GFS wind of `ui.py` also matched the 10 mb level (`(?:U|V)GRD:10 m`): it reads `10 m above ground` only.
- `examples/simple_routing.py` stopped at its fuel distribution figure since its polars became `eff1` and `eff90`: its figures still selected `eff45` and `eff60`, now they take the vessels that were routed. `plot_fuel_distribution` names an empty group (`ValueError`) instead of failing inside matplotlib.

---

## v0.4.0 - Planned

### Removed
- `RoutingAnalysis(options={"include_gusts": ...})`, deprecated since 0.3.1: give `variables=["gust"]`. An analysis then computes `tws_gust` and `aws_gust` only when `"gust"` is in its variables, no longer by default.
- `Vessel(sfc=...)` and `Vessel.sfc`, deprecated in favour of `sfoc`.
- The former report and `ctx` name `avg_bhp` of the brake power, deprecated in favour of `bhp`. Saved reports with `avg_bhp` are still read with `bhp`.
- `architeuthis.wrappers.json_wrapper` and `architeuthis.wrappers.leaflet_wrapper`, deprecated in favour of `architeuthis.dux.json_wrapper` and `architeuthis.dux.leaflet_wrapper`.

### Changed
- Vessel models other than the consumption, `max_bhp` and `sails_contribution` included, are computed only when listed in `variables`.
- `Vessel(max_power=...)` defaults to None, no power limit, instead of 1e12 kW.
- A `bhp` or `total_power` model without `sfoc` raises an error instead of burning at 0 g/kWh.

# Architeuthis

Open-source marine weather and decision-making framework for hybrid sailing ships. It couples mesh-free, fully differentiable methods in a unified optimization environment to compute optimal routes under real-world constraints.

"Mesh-free" means routes are not searched on a graph: waypoints are continuous decision variables in a single nonlinear program (NLP). Weather, bathymetry and vessel polars are differentiable lookup tables queried at those waypoints. CasADi differentiates through everything and IPOPT solves it.

## Conventions

- **Unified math:** use `import architeuthis.numpy as np` in anything that may run symbolically.
- **Differentiable first:** no branching on values that may be symbolic, and prefer smooth formulations. Use `np.where`, `np.softmax`, `np.softmin`, `np.blend` and `np.sigmoid` rather than `if`, boolean masks or in-place assignment.
- **Object model:** domain objects inherit from `ArchiteuthisObject` (`common.py`), which takes `name` and `verbose`. Data-backed objects inherit from `ArchiteuthisData` or `ArchiteuthisSpatialData`. Analyses inherit from `ArchiteuthisAnalysis` (`core.py`).
- **Naming:** PEP8 with descriptive names. Use keyword arguments unless self-explanatory, and one parameter per line in long signatures and calls.
- **Maritime abbreviations** are the accepted exception to descriptive names; see the glossary below.
- **Docstrings:** PEP 8 and PEP 257, as in AeroSandbox: `"""` alone on its first and last lines, a one-line summary, then Google-style `Args:`, `Returns:` and `Example:` sections, all within 72 columns. Every public module, class, function and method has one; `__init__` is exempt when its class has one, which then holds `Args:`. A module's description goes above its `Created on` header. `tests/domain/test_docstrings.py` checks all this, outside `numpy/`, `optimization/` and `modeling/`.
- **Console output:** user-facing status goes through `common.status` with the existing emoji vocabulary (📦 ✅ ⬇️ ➕ ➖ 🟦 💔 ⚠️). It prints by default, and `set_status_sink` sends it elsewhere, to a GUI for example. Objects send information (📦 ✅ ⬇️ ➕ ➖ 🟦...) through `self.info`, which calls `status` only if `self.verbose`; warnings (⚠️) and errors (💔) call `status` directly, whatever `verbose`.
- **No side effect at import:** no network access, logging setup or file writing when a module is imported. Fetch on first use, as `icebergs` does.
- **Project docs:** `README.md` is the short presentation for users, `docs/user_guide.md` the reference of the public API. Record notable changes in `CHANGELOG.md` (Keep a Changelog, SemVer) and planned work in `ROADMAP.md`.
- **License:** the project is GPL v3 (`LICENSE`, `pyproject.toml`, README). The vendored code keeps its MIT license.
- **Vendored code:** `numpy/`, `optimization/` and `modeling/` are adapted from [AeroSandbox](https://github.com/peterdsharpe/AeroSandbox) 4.2.9 (MIT). Keep the attribution headers and make domain changes outside these packages where possible. Docstrings there still say `asb.`.

## Environment and commands

Python >= 3.11, developed on 3.13 with conda (`environment.yaml` creates `py313-architeuthis`). casadi >= 3.7 in `pyproject.toml`, `environment.yaml` and `requirements.txt`: the suite passes on 3.7.2 and 3.8.2. Line endings are LF for `.py`, `.md` and `.txt`.

The package does not need installing for development: **run everything from the repository root** using `python -m ...`. `pip install -e ".[test]"` is the alternative, and it is what CI does.

```bash
conda env create -f environment.yaml
```

```bash
python -m pytest
```

A single test: `python -m pytest tests/optimization/test_opti_rosenbrock.py::test_2D_rosenbrock`. Only the end-to-end routing tests: `python -m pytest -m integration`. The suite takes under a minute and needs no network or credentials. There is no linter or formatter configuration.

Credentials are handled by `architeuthis/credentials.py`, and each is only needed for its provider: `CDS_API_KEY`, `CMEMS_USER`, `CMEMS_PWD`, `EUMDAC_KEY`, `EUMDAC_SECRET` (`CREDENTIALS`). Users save them once with `python -m architeuthis.credentials set NAME...`, which stores them in the OS credential store through `keyring` (service `architeuthis`), reads them back, and removes from `os.environ` the variables of that credential, which would otherwise hide the saved value (⚠️ status naming them, never the value). They are read when a download needs them, never at import: environment variables first (the names above, then aliases: `CDSAPI_KEY`, `COPERNICUSMARINE_SERVICE_USERNAME`/`_PASSWORD`, the former `EUMDAC_USER`/`EUMDAC_PWD`), then the store. Data sources call `require_credentials` in their download hook and keep no secret on the object; a missing one raises `MissingCredentialError` after a ⚠️ status. Herbie sources (IFS, GFS, HRDPS) need none. The README has a tutorial per provider. Never write a real value in a tracked file, including in a comment.

Downloads are cached under `~/data/` (`common._HOME`, moved by `ARCHITEUTHIS_HOME`, read at import) in `topo/`, `cmems/`, `cds/`, `eumetsat/`, `wms/` (imagery PNGs, by host, layer and box, with a `times.json` index per layer), `iip/` and `viewer/` (MapLibre GL JS, put in share files). `share_routes` writes to `shared/`. `RouteLibrary`, `RouteSetLibrary`, `PassagePlanLibrary` and `ExclusionZoneLibrary` store JSON in `route_library/`, `route_sets/`, `passage_plans/` and `exclusion_zones/`. `dux/ui.py` reads route reports from `routes/`, a different format, written by `ReportCollection.save`. Vessel polars are NetCDF files that are not in the repository.

Development is Spyder-based: scripts use `#%%` cells and many modules have a `__main__` block used as a manual check.

Branches: work on `develop`, PRs target `main`.

The version is written only in `architeuthis/__init__.py` (`__version__`, a literal): `pyproject.toml` declares it `dynamic` and setuptools reads it with `attr`, and `publish.yml` compares the tag with it through `ast`. Only the `architeuthis/` package is published.

Extras: `pip install architeuthis` is the routing, data sources, reports and figures; `architeuthis[dux]` adds Dash, Flask and the other dependencies of `architeuthis.dux` (it replaced `[app]`); `test` includes `dux`. A later `[full]` will add the desktop app. A new dependency of the display tools goes in `dux`, never in `dependencies`, and every `dux` module importing one wraps it in `with require_extra():`. `test_packaging.py` and `test_import_side_effects.py` check that the core imports without them.

## Architecture

```text
architeuthis.numpy         NumPy/CasADi unified math (AeroSandbox)
architeuthis.optimization  Opti (cas.Opti subclass), OptiSol (AeroSandbox)
architeuthis.modeling      Fitted/interpolated models, black_box (AeroSandbox)
        |
common.py      ArchiteuthisObject > ArchiteuthisData > ArchiteuthisSpatialData
        |       load_data() pipeline, add_interpolator(), __call__(), _HOME, status
credentials.py save/get/delete/require credentials: environment, then OS store (keyring)
copernicus.py  CopernicusMarineData mixin (subset + credentials), shared by CopernicusForecast and satellite
        +-- vessel.py     Vessel: models (NetCDF, functions, constants), consumption + hotel_load, sfoc, max_power
        +-- forecast.py   Topography; Forecast > Herbie (deterministic, HRDPS, ensemble),
        |                 Copernicus (CMEMS), CDS (ERA5); calm_forecast (zero fields)
        +-- satellite.py  EUMETSATData > EUMETSATASCATData, PoseidonData; CopernicusSatelliteData >
        |                 CopernicusASCATData; ASCATData: first of EUMETSAT, CMEMS that works (validation);
        |                 SatelliteImagery > WMSImageryData > EUMETViewData, GIBSData; channels "ir"
        |                 (bt, K) and "visible" (brightness 0-1) chosen like forecast variables, colour
        |                 scale chosen in image(); GeostationaryImagery: sources joined into one layer
        |
icebergs.py    IIP iceberg limit, fetched on first use: berg_zone polygon, berg_geojson
        |
route.py       Waypoint, Leg, Route (waypoints + divergences + spread), RouteSet, RouteLibrary
voyage.py      Schedule, Voyage (Route + Schedule), PassagePlan, PassagePlanLibrary
exclusion.py   ExclusionZone, ExclusionZoneLibrary, iceberg_zone (the zones themselves belong to the user)
sky.py         cloud genera per étage, cover, base and one line per point from 9 IFS/GFS fields (NumPy only, standalone)
report.py      RoutingReport (dict), ReportCollection (list): tables, GPX, JSON storage, share
        |       all offline: they do not import core
core.py        RoutingAnalysis (run, evaluate); re-exports the above
        |
dux/           display and user experience, Dash in the `dux` extra; nothing above imports it
               (only ReportCollection.share, lazily). __init__: require_extra, MissingExtraError
  share.py       one self-contained HTML file of routes, forecasts, zones and the analyst's comments:
        |         build_scene (JSON-ready dict), viewer_html, share_routes, ReportCollection.share;
        |         MapLibre cached in ~/data/viewer/; needs no extra
  ui.py          Dash page of the analyst: choices beside a live preview (iframe) of the share file
  json_wrapper, leaflet_wrapper   GeoJSON and zone layers of the former Leaflet map
  data/          land.json and land_detail.json (land rings of the offline globe, from zoom 5, built by
                 tools/make_land.py from Natural Earth 1:10m), viewer/ (viewer.html, .css, .js: the page of share.py)
  assets/        style and icons of the former Leaflet map

toolbox/       geo_utils (route geometry, central_angle), windy_colormaps (wind, waves, satellite colour scales), plot_utils (figures, documented in docs/user_guide.md),
               json_utils (report JSON codec), wms_utils (WMS requests, tiled maps, GIBS times and colormaps),
               image_utils (PNG, palette inversion, smooth rescaling, colour scales, quantile matching, blending, GIF),
               inspect_tools, string_formatting...
data/          package data: cloud_genera.json (the 10 WMO genera, étages, precipitation)
wrappers/      legacy provider wrappers; json_wrapper and leaflet_wrapper are deprecated aliases of dux
examples/      simple_routing, long_term_routing, ensemble_routing, post_leg_rewind,
               passage_planning, ifs_route_tested_with_gfs, short_term_routing, comparison_ascat_models,
               function_polar_routing, sky_along_route, vessel_definitions, wind_only_routing,
               ascat_sources, cloud_imagery;
               they define their own sources and zones, and keep past settings as commented lines
tests/         numpy, optimization, modeling (AeroSandbox), domain (Architeuthis)
```

Stubs that are not functional yet: `environment.Environment` (also has a broken bare import), `ECMWFForecast`, `AtmosphericForecast`, `OceanographicForecast`. `architeuthis/__init__.py` exports only `Opti` and `OptiSol`, so import everything else from submodules.

### Data pipeline

`ArchiteuthisData.load_data()` is a template method: `_locate_data` > `_download_data` > `_read_data` > `_convert_data` > `_extend_data`. A new data source overrides these hooks and must normalize to:

- **Longitude** in [-180, 180) and sorted coordinates.
- **Time** as a float epoch-seconds coordinate named `valid_time`.
- **Dimension order** matching the `coord_dims` passed to `add_interpolator`.

Each data object holds **models** in `models` (`interpolators` is the same dict, the former name), keyed by `var_key`. A model is any object called with a dict of inputs and having `input_names()`, registered with `add_model`. A table is one kind: `add_function(var_key, function, inputs, args, output)` wraps `function(x, **args)` into a `common.FunctionModel`, for semi-empirical polars with fitted parameters for example (`Vessel` then needs no `filepath`); `output` picks a key, index or function of a result such as `(value, components)`. `__call__` passes each model only its own inputs, so a query may hold more keys.

`add_interpolator` builds a `HybridInterpolatedModel` (`modeling/hybrid_interpolation.py`) from the array, registered through `add_model`. Its NumPy and CasADi evaluators are built once from the same data: SciPy fits the B-spline coefficients, much faster than `casadi.interpolant(..., "bspline")`. Know these behaviours:

- Dimensions are **positional**: the array is squeezed and sliced, so array dimension order must equal `coord_dims` order. The names only select coordinates.
- **Query keys are standard names**, whatever the names in the data: `valid_time, latitude, longitude` for forecasts, plus `member` for `EnsembleHerbieForecast`, `latitude, longitude` for `Topography`, and `stw, tws, twa, hs, wa` for `Vessel` (`common.FORECAST_KEYS` and the like, passed as `coord_keys`). `obj.input_names(var_key)` gives them.
- Outside the grid, `fill_value=None`: "linear" extrapolates, "bspline" keeps the boundary value. "nearest" takes no symbolic query.
- **NaN becomes 0**, so land currents and missing values read as calm conditions.
- Herbie and Copernicus forecasts append two fake time steps (+1e6 s, +1e7 s) filled with 0, so fields fade to zero past the horizon rather than failing. `RoutingAnalysis.check_valid_time` assumes this by treating `valid_time[-3]` as the last real step; `CDSForecast` does not pad, so the check is off by two steps there.
- Calling `obj(var_key, X)` takes a dict keyed by those names, whose values (NumPy or CasADi, scalars or columns) are broadcast, as in `core._passage`. An array of shape `(n_queries, n_dims)` with columns in key order still works. It returns a CasADi column, a DM for numeric queries, which are computed with NumPy.

`Topography` computes `distance_to_iso0`, normally registered with `var_key="z"`: a signed distance to the navigable boundary in **nautical miles**, positive on land or inside exclusion zones and negative at sea. `depth_offset` treats shallow water as land and `z_margin` adds clearance. Its coordinates are `lat` and `lon` (ETOPO 2022), unlike the `latitude` and `longitude` of forecasts. Exclusion zones are `ExclusionZone` objects or plain `[lat, lon]` lists, rasterized into this field; the caller defines them and passes them to `Topography`. The package holds no zone or waypoint of its own: only `iceberg_zone()`, which comes from the IIP bulletin.

### Routing problem (`RoutingAnalysis.run`)

- **Objective:** minimize total fuel, `sum(hourly_consumption * dt) * vessel.density / 1e3` in tonnes. `Vessel.consumption` gives the consumption in **L/h** from the first model of `CONSUMPTION_KEYS` that the vessel has: `hourly_consumption` (a table or function in L/h); `total_power * sfoc / 1e3 / density`; or `(bhp + hotel_load) * sfoc / 1e3 / density`. `density` is the fuel density in kg/L, `FUEL_DENSITY` (0.83) by default: consumptions are volumes everywhere, only `fuel` is a mass. `hotel_load` and `sfoc` are models of that key if any, else the constructor values (numbers, or functions of the brake and total power). Each step adds its result to the query, so later models can take `bhp`, `hotel_load` or `total_power` as inputs. The quantities of the formulation go into `ctx` and the report under the keys of their models (`bhp` for the brake power; `avg_bhp` is its former name, still read through `report.RENAMED_ENTRIES` with a warning until 0.4.0), and constants are repeated per segment (`_column`).
- **Fixed:** ETD, ETA, departure and arrival, so the schedule is a hard requirement and speed is an outcome (`sog = distance / dt`).
- **Environment:** `atmosphere`, `wave` and `current` default to None, and `RoutingAnalysis.__init__` replaces each None by `forecast.calm_forecast(source)`: a `Forecast` with `data = None` whose `ENVIRONMENT_FIELDS` are `add_function` models returning zeros that do not depend on the query, so that `arctan2` of the zero wind or sea has no derivative to take: `MX` zeros for a symbolic query, because from casadi 3.8 NumPy functions turn `DM` into NumPy columns, which a polar table query then broadcasts to an n x n square (CI failure), `DM` for a numeric one. So `self.atmosphere` and the others are never None; code needing data uses `_forecasts()`, the ones with data. `topography` defaults to None only because it comes after them, and None raises `TypeError`.
- **Time grid:** comes from the first forecast with data (`_forecasts()`), the atmosphere normally, else every `DEFAULT_TIME_STEP` (3 h). Segment centers (`ctim`) are the `valid_time` values strictly between ETD and ETA, and nodes (`tim`) are ETD, their midpoints and ETA. `skip_tim` thins them.
- **Decision variables:** `vlat` and `vlon`, offsets of interior nodes from a reference route. With `vary_fac=True`, also `deviation_fac`, which blends `Voyage.route_minus`, `route_ortho` and `route_plus` (-1, 0, +1).
- **Evaluation:** weather is sampled at segment midpoints, topography at nodes resampled with `n=3`, and the vessel with a query of `stw, tws, |twa|, hs, |wa|` plus `sog, swh, |mwa|, aws, |awa|, twd`, from which each model takes its inputs. An input matching `(tws|twd|twa|aws|awa)<height>` (`_WIND_AT_HEIGHT`, `twa100` for example) is computed by `_wind_at_height` from the forecast variables `u<height>` and `v<height>`, with the formulas of the 10 m wind. Any other vessel input is a forecast variable, read by `_forecast_variable` from the first of `atmosphere`, `wave`, `current` with a model of that key, else `KeyError`.
- **Constraints:** a callable `ctx -> list` or a plain list, given to the constructor or to `run`. `ctx` exposes the symbolic quantities plus `vessel` and `opti`. The default is `z < 0` and, if `vessel.max_power` is not None, the first of `max_bhp` (only there when listed in `variables`), `bhp`, `total_power` (`POWER_LIMITED_QUANTITIES`) below it.
- **Additional variables:** `variables` (constructor, plus `run`/`evaluate`, which add to it) asks for quantities the objective does not need, computed at segment midpoints by `_passage`, put in `ctx` and in the report. `normalize_variables` turns a name, a list or a dict into `{name: specification}`. A specification is a model key, looked up in `VARIABLE_SOURCES` (`atmosphere`, `wave`, `current`, `vessel`) unless prefixed (`"wave.slope"`, a list entry then named `slope`), in the units of the model; a derived quantity of `_derived_variable` (`tws_gust`, `aws_gust`, wind at a height with signed angles); a routing quantity; or a callable `ctx -> expression` seeing the variables before it. `"gust"` (`GUST_VARIABLE`) is expanded by `normalize_variables` into `tws_gust` and `aws_gust`; the raw gust model needs another name (`{"gust_ms": "atmosphere.gust"}`). `options["include_gusts"]` is deprecated (`DeprecationWarning` at construction when given, removal in 0.4.0); until then the default options still prepend `tws_gust` and `aws_gust` (`_variables`). Names of routing quantities and of `_RESERVED_NAMES` are refused. The plan metadata records them (`_describe_variables`).
- **`solve=False`:** evaluates the reference route without optimizing it, giving a baseline for comparison.
- **Shared model:** `_passage(tim, ctim, lat, lon, ...)` builds every symbolic quantity; `run` feeds it Opti variables and `evaluate` plain MX symbols. Change the physics there only.
- **Results:** `run` also sets `analysis.report` and `analysis.passage_plan` (a `PassagePlan` named `<route>_<etd>Z`, with `describe()` metadata).
- **Tags:** `run(tags=...)` and `evaluate(tags=...)` add entries to the report. By default it has `solve` (int), `model`, `vessel` (`Vessel.label`) and `member`.
- **Callback:** `run(callback=...)` is called at each IPOPT iteration, with the iteration number.
- **Open loop:** `evaluate(plan)` computes the same report for fixed positions with another vessel, forecast or member, through a `ca.Function` and without IPOPT. Constraints are only measured: `max_constraint_violation` and `constraint_violations`, with `ctx["opti"] = None`. `status` is 0.
- **Output:** `run` returns a `RoutingReport`, a dict of numeric arrays and scalars, with the tags above and the additional variables.

Required interpolator keys:

| Object | Keys | Units |
| --- | --- | --- |
| `atmosphere` | `u10`, `v10`, optional `gust` for `tws_gust` and `aws_gust` (otherwise `tws * GUST_DEFAULT_RATIO`) | m/s, converted to kt |
| `wave` | `swh`, `uw`, `vw` (from `Forecast.add_wave_components`) | m, m² |
| `current` | `uo`, `vo` | m/s, converted to kt |
| `topography` | `z` | nm |
| `vessel` | one of `hourly_consumption`, `total_power` (with `sfoc`), `bhp` (with `hotel_load`, `sfoc`); optional models such as `max_bhp`, `sails_contribution` only when listed in `variables`; tables on axes `stw, tws, twa, hs, wa`, functions on any inputs, constants | L/h, kW; kt, kt, deg, m, deg |

The wave direction is interpolated through `uw = -swh**2 * sin(mwd)` and `vw = -swh**2 * cos(mwd)`, which `Forecast.add_wave_components` adds to the data (`mwd_dim="dirpw"` for GFS), because `mwd` itself jumps from 360 to 0 deg. `_passage` takes `mwd = arctan2(uw, vw + WAVE_COMPONENTS_OFFSET) + 180`: the energy weight lets large seas rather than calm or land cells (0 after NaN) set the direction, and the offset (`common`, 1e-2 m²) keeps `arctan2` differentiable where both components vanish. `swh` stays a separate interpolator, because the norm of interpolated components underestimates it where directions differ, and `sqrt` is not differentiable at 0. Reports still give `mwd`.

Modelling choices to preserve or change deliberately: wind and wave angles are relative to COG, apparent wind uses SOG rather than STW, and leeway is not modelled.

### Glossary and units

Speeds in knots, distances in nautical miles, angles in degrees, time in float epoch seconds, power in kW. Positions are always `[lat, lon]`, latitude first. A `c` prefix (`clat`, `ctim`) marks a segment center.

| Term | Meaning | Term | Meaning |
| --- | --- | --- | --- |
| `stw`, `sog` | speed through water, over ground | `swh`, `hs` | significant wave height |
| `cog`, `ctw` | course over ground, through water | `mwd`, `mwa` | mean wave direction, angle |
| `tws`, `twd`, `twa` | true wind speed, direction, angle | `cs`, `cd` | current speed, direction (going to) |
| `aws`, `awa` | apparent wind speed, angle | `bhp`, `sfoc` | brake power, specific fuel oil consumption (g/kWh) |
| `etd`, `eta` | departure, arrival time | `f00`, `fxx` | forecast base time, lead times |

## Pitfalls

**Import side effects**

- Importing the package has none, and `tests/domain/test_import_side_effects.py` checks it. `load_data` calls `common.setup_logging`, which leaves logging alone if the application has configured it, and nothing reads credentials or imports `keyring` at import.
- `architeuthis.icebergs` fetches the IIP bulletin and shapefiles on first use of `berg_zone`, `polygon` or `berg_geojson` (module `__getattr__`, connect timeout 10 s), once per session unless `refresh()` is called. Calling `exclusion.iceberg_zone()` or reading `core.berg_zone` counts as a use, so these can take time. Offline, it falls back to the last downloads in `~/data/iip/` (`IcebergBulletin.txt`, shapefiles), else to an empty `berg_zone` and GeoJSON, with a warning. `Topography` skips exclusion zones with fewer than 3 points, so routing then runs **without the iceberg limit**.
- `architeuthis/dux/ui.py` is a script, not a library: importing it downloads forecasts and the NOAA chart and needs a report JSON in `~/data/routes/`. Run it with `python -m architeuthis.dux.ui` from the repository root (or `python ui.py` from `architeuthis/dux/`); it serves on port 8052 without debug mode, reads no asset (`assets_ignore`) and writes nothing to the working directory. Another instance may hold that port: a check through `runpy` can use another `run_name` and call `app.run(port=...)` itself. Its first lines remove `architeuthis/dux/` and `architeuthis/` from `sys.path`, where `architeuthis/numpy` would hide numpy, and put the repository root first, and it selects the Agg backend, because a GUI backend kills the process from a server thread. So when checking the UI, do not set `MPLBACKEND`, which is not what a user has. Any restart downloads the forecasts again: to check it in a browser, run it through `runpy` with `DeterministicHerbieForecast.load_data` replaced by synthetic fields.
- The preview of `ui.py` is the share page itself at `/viewer?file=&member=`, built once per file and member with every route and variable (`preview_scene`). The choices reach it by `postMessage`: a clientside callback sends `{type: "architeuthis:settings", settings: {routes, sources, overlays, overlaysShown, fields, hover, title, note, theme, editable, labels, descriptions, comments}}`, and the page sends `"architeuthis:ready"` when it loads, answered with the current choices. With `editable`, clicking a route point opens a comment editor, and the page sends every comment back (`{type: "architeuthis:comments", comments: {"r<index>": {"<segment>": text}}}`), which the bridge puts in the `route-comments` Store with `dash_clientside.set_props`; its theme button sends `"architeuthis:theme"`, which sets `theme-switch`, and each toggle of a chart sends `"architeuthis:overlays"` (`{o<index>: shown}`), which sets `noaa-check`: the NOAA chart is always shared, `visible` as that box. Only the download builds a scene with the chosen routes, names (`route_names`), variables, models and comments (`route_notes`). `scene["settings"]` holds the initial choices, None meaning all, and `theme`. `ui.py` hides every library zone at first (`shared_zones`, on copies) and dates the NOAA chart from its `Last-Modified` header (`analysis_time`), which the tests' `Answer` provides.
- `share.py` and the page agree on the scene format (`version` 1): routes with `id` `r<index>` (colour of the index, kept when others are left out), a `description` and `comments` (`[{k, text}]`, `k` an index of `ctim`), sources with `times`, `layers`, a regular `grid` (`lat0`, `dlat`, `nlat`, `lon0`...) and `packs` of three quantities per RGB PNG (rows south to north, 255 = missing, value = `offset + scale * byte`, `categorical` quantities exact and never blended), `layers` describing each layer (`quantity` or `vector`, `colormap` or `categories`, `floor`, `digits`, `arrows`: `wind`, `waves`, `current` or None; a layer other than the built-in ones is the quantity of its name), overlays with their `time` (epoch seconds or None), zone outlines and land in `[lon, lat]`. Change both sides together. The page uses no build step: plain JavaScript in `dux/data/viewer/viewer.js`, the scene in a `<script type="application/json">` with `</` escaped. There is no JavaScript test runner (no Node): check the page in a browser.
- The land has two levels, `scene["land"]` (0.05 deg) and its `detail` (0.005 deg): the page draws the first, then once idle (`loadLandDetail`) decodes the second into the `-detail` twins of the land and coast layers, drawn from `DETAIL_ZOOM` (5), and limits the coarse ones below it, so the detail never delays the opening.
- In the page, the land is filled over the weather raster and the sea-side coast shade, lines of growing width with a positive `line-offset` on rings turned so that the sea is on their right (`coastData`, cut along the antimeridian and the south edge of Antarctica): without the land on top, the offset lines show spikes inland at sharp corners. Arrows sit on a geographic lattice (`latticeSpacing`), rows from the equator and columns from the prime meridian spaced by the cosine of their row, values interpolated from the grid, so only the zoom (by half levels) moves them. Glyph images are drawn on canvases with ids holding the theme and colour, flat, without outline; only routes, boats and comment bubbles have a white outline. Colours of the panels are CSS variables of `:root` and `:root[data-theme="light"]`, and map colours are `THEMES`; the weather (raster, glyphs, isobars) never depends on the theme (`GLYPH_LIGHTNESS`, `ISOBAR_COLOR`).
- `ui.py` needs Dash >= 4.5 and Dash Mantine Components 3, which needs React 19: right after importing Dash it calls `dash._dash_renderer._set_react_version("19.2.4")`, a private function, because Dash still loads React 18 by default. Without it the page shows only "requires React 19".

**Symbolic code**

- `architeuthis.numpy` begins with `from numpy import *`, so any function it does not override is plain NumPy and can fail or misbehave on CasADi types. Check the overrides when using a less common function.
- `toolbox/geo_utils.py` is mixed. `distances`, `headings`, `midpoints` and `resample_coordinates` work symbolically. `poly_deviated_route`, `deviated_gc_segment` and `great_circle_route` are numeric only and may only build reference routes before optimization.
- `core.py` itself uses non-smooth `np.mod`, `np.abs`, `np.fmax` and `np.fmin`. This is existing behaviour, not a pattern to extend.
- casadi 3.8 raises a `FutureWarning` when a NumPy function receives a casadi value (`core.py` at `np.fmax`, `geo_utils.distances` and `headings`, and parts of `numpy/` and `Opti.variable`). This works through casadi's legacy behaviour, which a later release may change.
- `headings` is a local flat approximation and nothing unwraps longitude, so routes crossing the antimeridian are unsupported.

**Figures**

- `plot_utils` figures are built inside `plot_style()` and end with `_finish`, which saves, shows and calls `_fix_style`. Matplotlib reads several settings when it draws (ticks and their number, fonts, `C0`-style colors), which may be after the block in Spyder or a GUI. So use `to_rgba("C0")` rather than `"C0"` in these figures, and keep `_finish` inside the block.
- `plot_utils.plot_routing_report` is the former figure and is left as it was.
- Cartopy downloads Natural Earth when it draws a map, so tests build maps but never render them.

**Solver**

- `DEFAULT_SOLVER_OPTIONS` uses `linear_solver: spral`. With casadi 3.7.2 on Windows, `run(solve=False)` with these defaults crashes the process with an access violation; casadi 3.8.2 does not. Pass `linear_solver: mumps` for baselines, as `examples/short_term_routing.py` does.
- `acceptable_tol` is `1e9` and `Solved_To_Acceptable_Level` counts as solved, so `status == 1` is weak evidence of optimality. The solve uses `behavior_on_failure="return_last"`, so failures return a possibly infeasible route with `status == 2`. Check `status` and `max(z)`.

**API traps**

- `Schedule` and `Voyage` convert dates with `common.to_timestamp`; naive dates are UTC, so give local times with a timezone.
- Divergence and spread signs are relative to the travel direction: `Route.reversed()` negates divergences, so the reverse route's `plus` is the forward `minus`.
- `Route.from_position` restarts with a straight first segment. `Voyage.from_position` cannot restart `route_minus`/`route_plus` given as functions and falls back to the spread paths; pass Routes to keep them.
- `Vessel.hotel_load` and `Vessel.sfoc` are wrapped into callables, while `Vessel.max_power` stays a raw value. `sfoc` defaults to None, and the `bhp` and `total_power` formulations then burn at 0 with a `DeprecationWarning` (`ValueError` from 0.4.0). `max_power` left out is 1e12 kW with a `DeprecationWarning` (sentinel `_UNSET`; None from 0.4.0); `max_power=None` gives no power constraint. A huge value such as 1e12 kW is a slack that can send IPOPT's adaptive barrier off and the route diverging, so give a realistic value or none. `sfc` is the deprecated name of `sfoc` (warning, removal in 0.4.0).
- Only the consumption models are meant to be evaluated by default: a constraint on `ctx["max_bhp"]` or a figure of `sails_contribution` should list them in `variables`. Until 0.4.0, `_variables` still adds the `IMPLICIT_VESSEL_VARIABLES` that the vessel has and nobody listed, with a `DeprecationWarning`; from 0.4.0, a missing one is a `KeyError`. The plots and `json_wrapper` skip them when absent.
- `EnsembleHerbieForecast.add_interpolator` takes `var_dim, time_dim, member_dim, latitude_dim, longitude_dim`, which must be the order of the array.
- `json_wrapper.route_to_geojson` also needs `init_fac`, which `run` records but `evaluate` does not; `share.route_label` uses it only when present. `ReportCollection.save` writes to `~/data/routes/` by default.
- `DeterministicHerbieForecast` reads each GRIB file with `forecast.open_grib` (`cfgrib.open_datasets`, one hypercube per level, merged without their scalar level coordinates), so one `regex` may mix levels, such as the IFS 10 m wind and 2 m temperature. Plain `xr.open_dataset(engine="cfgrib")` would skip `t2m` and the concatenation fail on `heightAboveGround`. cfgrib groups fields by merging them with xarray's default `compat`, catching the merges that fail: `_cfgrib_merge_defaults` pins the current default (`"no_conflicts"`, about to become `"override"`) and silences its `FutureWarning` around that call. A test turning warnings into errors cannot see them there, since cfgrib swallows the exception: record them instead. Two variables of the same name at two levels would collide; cfgrib names them apart (`u10`, `u100`).
- `HRDPSForecast` wind speeds are right but its directions are not: the files have `uvRelativeToGrid` = 1 and the components are not rotated from the rotated grid, about 45 deg off around Saint-Pierre-et-Miquelon compared with GFS. `HerbieLatest` only looks on `aws` and `nomads` by default, so a model elsewhere needs `priority`.
- `EUMDAC_KEY` and `EUMDAC_SECRET` hold the EUMETSAT Consumer Key and Secret, not a login. When neither CMEMS credential is found, `CopernicusForecast` passes `None` to the toolbox only if the `copernicusmarine login` file exists (`COPERNICUSMARINE_CREDENTIALS_DIRECTORY` or `~/.copernicusmarine/`), else it raises; likewise `CDSForecast` falls back to `cdsapi.Client()` only if `CDSAPI_RC` or `~/.cdsapirc` exists. Architeuthis never writes `~/.cdsapirc` any more. Without a credential store (Linux server), `keyring` errors are treated as "not found", so environment variables still work.
- `copernicusmarine` takes naive dates as **local** times, not UTC. `CopernicusSatelliteData` passes UTC-aware timestamps; `CopernicusForecast` passes `date` and `end` as given. Its `"strict-inside"` selection refuses a period past the end of a dataset, so satellite data uses `"inside"`, which clips. Importing `copernicusmarine` takes about 3 s, which is why `architeuthis/copernicus.py` exists rather than this code living in `common.py`; mock it with `patch("architeuthis.copernicus.copernicusmarine.subset")`.
- `ASCATData` is not an `EUMETSATData`: it builds an `EUMETSATASCATData` or a `CopernicusASCATData` per source in `load_data` and keeps the data of the first that loads, catching any exception of the others. ASCAT `wind_dir` is where the wind goes, unlike the meteorological convention of the models.
- Imagery servers send rendered PNGs, which `WMSImageryData` turns back into brightness temperatures (`bt`, K) with the palette of the layer. EUMETView's grey ramp is calibrated in `EUMETVIEW_CALIBRATIONS`, fitted once against FCI L1c data (SEVIRI against that FCI); another layer needs its own fit. The GIBS IR colormap draws 195-203 K in the greys of 261-328 K: `GIBSData.secondary["ir"]` marks those entries and `image_utils.invert_palette` reads such pixels from their neighbours (`tolerance` 3, a wider one makes most mid-grey sea ambiguous and turns it cold). A grey nearer a secondary entry than any main one is also weighed by its neighbours, in a window 4 times wider when the first holds no unambiguous pixel: GIBS's grey 155 is exactly a 196.5 K entry between 270.8 K and 270.3 K, and read alone it drew cold streaks across warm sea. `uniform_filter` gives about 1e-16 rather than 0 for an empty window, so test counts against half a pixel. Past about 70 deg from GOES-East (east of 5 W), GIBS reads cold; `GeostationaryImagery` gives Meteosat all the weight there. Both palettes are right: where both satellites see at the same zenith angle they agree within 1-2 K at any temperature (GOES 10.3 um about 1 K warmer). The east-west differences, up to 15 K, are limb cooling, symmetric for both: `limb_correction` adds `limb_cooling`, fitted on their overlap (`LIMB_COOLING`), and leaves parallax and the visible alone. A temperature-dependent law fits better but over-corrects cold tops (their side seen near the limb), and about 12 % of GIBS pixels blend colours off its palette (interpolated rendering, even in its native tiles): reading them between two palette entries was tried and was no better.
- The WMS capabilities of GIBS may lag by an hour or more, depending on the server answering: `GIBSData` takes its times from DescribeDomains (`wms_utils.gibs_time_domain`), falling back on the capabilities. An entirely transparent image (not produced yet) is left out with a ⚠️ status and not cached. GIBS is about an hour behind EUMETView, so `GeostationaryImagery` (all sources' times by default) ends about an hour ago. Imagery files are never downloaded twice: `WMSImageryData._times` answers a period inside a `covered` interval of `<layer>/times.json` without asking the server, records after each answer the period up to the last time listed (later times may still come), and offline falls back on the PNGs on disk (`RequestException` only). An empty image is not cached; past `EMPTY_FINAL_AFTER` it is recorded under `empty` for its box and left out by `_locate_data`.
- Visible imagery has no published calibration on either server: both are read as grey level / 255 (`brightness`), and their relation changes through the day with the sun and viewing angles (GOES-to-Meteosat factor 0.74 at 11 UTC, 0.93 at 13 UTC on 2026-11-19), so `GeostationaryImagery` matches them per image along the seam (`match`, on for the visible only) rather than with a constant. A night image (reference spread under 0.02) is not matched. `windy_colormaps.SATELLITE_STOPS["infra"]` reproduces Windy's Infra+ legend; "blue" is Windy's Blue estimated by eye, whose definition is not published, and carries its own alpha (clear sky transparent above 290 K), which `values_to_rgba` keeps.
- Imagery channels (`IMAGERY_CHANNELS`) are what is downloaded: each maps to one server layer per source (`wms_layers`) and one quantity in `data`. Colour scales are a drawing option, never a channel: they live in `windy_colormaps` (`SATELLITE_STOPS`, with the quantity each draws in `SATELLITE_QUANTITIES`), and `image(time, channel, colormap=...)` refuses a scale of another quantity; `IMAGERY_COLORMAPS` gives each channel its default. Only "ir" and "visible" exist on both EUMETView and GIBS (water vapour on MSG only, the rest colour composites). A source with several channels keeps the times every channel has, and stores its pixels as `rgba_<channel>` in `output_path/<server layer>/<box>/`. Two resolutions are distinct: `resolution` is the grid, which sets the size of the requested images and so the download time (the reason to use these servers is speed), and `native_resolution` picks among the server layers of a channel (`EUMETVIEW_LAYERS`, `GIBS_LAYERS`, by native resolution, finest first), which barely changes the time. Images are fetched `DOWNLOAD_WORKERS` at a time, in tiles above `wms_utils.MAX_SIZE`, converted and composited image by image to keep the memory low; `image(scale=...)` smooths for display. `GeostationaryImagery.data["gain"]` and `["offset"]` are on (channel, source, valid_time).
- `core.berg_zone` and `icebergs.berg_zone` are computed when they are read (module `__getattr__`), so `from architeuthis.icebergs import berg_zone` fetches the iceberg limit at that line.

## Testing

Tests live in `tests/`, configured in `pyproject.toml`. `.github/workflows/tests.yml` runs them with coverage on every push, on Ubuntu (Python 3.11 to 3.13) and Windows (3.13). `publish.yml` releases to PyPI from `v*` tags and does not depend on the tests.

CI installs the latest dependencies, so it can differ from a local environment. In particular, casadi 3.7 and 3.8 do not always converge the same way, so keep test objectives reasonably well conditioned.

- **`tests/numpy`, `tests/optimization`, `tests/modeling`:** vendored from AeroSandbox, including the `import architeuthis as asb` style.
- **`tests/domain`:** Architeuthis code. `test_route.py` covers routes, voyages and passage plans offline. `test_routing.py` runs `RoutingAnalysis.run` and `evaluate` end to end, marked `integration`. `test_plots.py` draws every figure from real reports with Agg. `test_ui.py` runs the real `ui.py` without its server, with forecasts and downloads replaced, and calls its callbacks. `test_share.py` builds scenes from synthetic forecasts and reads the frames back from their PNGs. `test_examples.py` runs every example and the quick start of the README from start to finish on synthetic data, so a new example must be added to its `WINDOWS`. `test_readme.py` checks the README and its links, and `test_plots.py` checks that `docs/user_guide.md` gives the signature of each figure. `test_import_side_effects.py` checks imports in a new interpreter with the network cut off. `test_satellite.py` covers the ASCAT sources and their fallback with a mocked Data Store and toolbox, and the imagery with synthetic PNGs, replaced `wms_utils` requests and sources whose `load_data` gives a `bt` directly. `test_examples.py` replaces `WMSImageryData.load_data`, runs `cloud_imagery.py` at 1 deg and makes `Figure.savefig` a no-op, since a saved map would download Natural Earth. `test_credentials.py` covers the credential lookup, the store and the command line, and `test_packaging.py` the single source of the version. Download tests set credentials with `monkeypatch.setenv`.
- **Expected failure:** `test_black_box_nonsmooth_function` is `xfail` because IPOPT can fail on the kink of `abs()`.

Rules for new tests:

- **Stay offline.** `tests/conftest.py` points `HOME` at a temporary folder, removes credentials and their aliases and `ARCHITEUTHIS_HOME`, selects the null `keyring` backend through `PYTHON_KEYRING_BACKEND` so the real credential store is never touched (`test_credentials.py` installs one in memory), and replaces `architeuthis.icebergs` with a stub. Mock providers with `patch("architeuthis.forecast.<name>")`, or `load_data` as `test_examples.py` does.
- **Use synthetic data.** The fixtures in `tests/domain/conftest.py` provide forecasts, topographies, a vessel and real reports (`baseline_report`, `optimized_report`, `routing`): assign a dataset to `.data`, skip `load_data()`, then call `add_interpolator`. The reports are shared, so copy them to change them. The `routing` fixture lists `max_bhp` and `sails_contribution` in `variables` unless `analysis_options` gives its own.
- **Pass `linear_solver: mumps`** in routing tests, because of the `spral` crash described under Pitfalls.
- **Keep the checkout clean.** Importing `dux/json_wrapper.py` writes `assets/dashExtensions_default.js` to the working directory, so import it from a temporary folder, as `tests/domain/test_toolbox.py` does. Tests of `share.py` point `share.VIEWER_DIRECTORY` at a temporary folder, so that MapLibre is never downloaded.
- **Do not change `--tb=native`.** Other traceback styles parse `casadi.py`, which raises `MemoryError` and aborts the session.

Not covered: the real IIP server (`test_icebergs.py` replaces `requests.get`), `ui.py` with real forecasts, the JavaScript of the share page (only checked by hand in a browser), the rendering of cartopy maps, the real EUMETSAT, Copernicus Marine, EUMETView and GIBS servers for `satellite.py`, the real credential stores of each OS (only checked by hand on Windows), and the default `spral` solver options.

## Deprecations

To remove in **0.4.0**, with an entry under "Removed" in `CHANGELOG.md`:

- `architeuthis/wrappers/json_wrapper.py` and `leaflet_wrapper.py`, aliases of the `architeuthis.dux` modules that warn. Remove them and `test_the_former_wrappers_warn_and_give_the_dux_modules`.

- `RoutingAnalysis(options={"include_gusts": ...})`, deprecated in 0.3.1 in favour of `variables=["gust"]`. Remove the `DeprecationWarning` and the `"include_gusts"` default of `options` in `RoutingAnalysis.__init__`, and the gust prefix of `_variables`, so that the gusts are computed only when `"gust"` is listed. Then update the tests that rely on default gusts (`test_routing.py`, `test_plots.py`, the `routing` fixture reports) and the docstrings and `docs/user_guide.md` passages that mention the option.
- `Vessel(sfc=...)` and the `Vessel.sfc` property, deprecated in favour of `sfoc` (`_warn_sfc`). Remove them and `test_sfc_is_the_deprecated_name_of_sfoc`.
- The implicit `max_bhp` and `sails_contribution`: remove `IMPLICIT_VESSEL_VARIABLES` and its part of `_variables` in `core.py`, and `test_unlisted_max_bhp_and_sails_are_still_computed_until_0_4`. Tests using the `vessel` fixture through `analyse` then lose `max_bhp` unless they list it.
- The `max_power` default of 1e12 kW: replace `_UNSET` by None in `Vessel.__init__` and drop its warning; update `test_max_power_defaults_to_1e12_until_0_4` and the `unset` case of `test_the_power_limit_is_optional`.
- The former name `avg_bhp`: remove `RENAMED_ENTRIES`, `_renamed` and `_RenamedEntries` in `report.py` (`RoutingReport` and the `ctx` of `core.py` then become plain dicts again), and `test_avg_bhp_is_the_deprecated_name_of_bhp`.
- The zero `sfoc`: in `Vessel._load`, raise `ValueError` for a missing `sfoc` as for `hotel_load`; update the two `test_a_missing_sfoc_is_zero_until_0_4`.

## Known inconsistencies

- `tall` and `wide` are duplicated in `common.py` and `core.py`, and `core.py` defines an unused `sigmoid`, `transform` and `added_wave_load`. `ROADMAP.md` plans to move these helpers into `numpy`.
- `raise(ValueError, "...")` appears in `forecast.py`. In Python 3 this raises `TypeError` rather than the intended error.

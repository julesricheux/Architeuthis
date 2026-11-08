# Architeuthis

Open-source marine weather and decision-making framework for hybrid sailing ships. It couples mesh-free, fully differentiable methods in a unified optimization environment to compute optimal routes under real-world constraints.

"Mesh-free" means routes are not searched on a graph: waypoints are continuous decision variables in a single nonlinear program (NLP). Weather, bathymetry and vessel polars are differentiable lookup tables queried at those waypoints. CasADi differentiates through everything and IPOPT solves it.

## Conventions

- **Unified math:** use `import architeuthis.numpy as np` in anything that may run symbolically.
- **Differentiable first:** no branching on values that may be symbolic, and prefer smooth formulations. Use `np.where`, `np.softmax`, `np.softmin`, `np.blend` and `np.sigmoid` rather than `if`, boolean masks or in-place assignment.
- **Object model:** domain objects inherit from `ArchiteuthisObject` (`common.py`), which takes `name` and `verbose`. Data-backed objects inherit from `ArchiteuthisData` or `ArchiteuthisSpatialData`. Analyses inherit from `ArchiteuthisAnalysis` (`core.py`).
- **Naming:** PEP8 with descriptive names. Use keyword arguments unless self-explanatory, and one parameter per line in long signatures and calls.
- **Maritime abbreviations** are the accepted exception to descriptive names; see the glossary below.
- **Console output:** user-facing status goes through `common.status` with the existing emoji vocabulary (📦 ✅ ⬇️ ➕ ➖ 🟦 💔 ⚠️). It prints by default, and `set_status_sink` sends it elsewhere, to a GUI for example.
- **No side effect at import:** no network access, logging setup or file writing when a module is imported. Fetch on first use, as `icebergs` does.
- **Project docs:** record notable changes in `CHANGELOG.md` (Keep a Changelog, SemVer) and planned work in `ROADMAP.md`.
- **Vendored code:** `numpy/`, `optimization/` and `modeling/` are adapted from [AeroSandbox](https://github.com/peterdsharpe/AeroSandbox) 4.2.9 (MIT). Keep the attribution headers and make domain changes outside these packages where possible. Docstrings there still say `asb.`.

## Environment and commands

Python >= 3.11, developed on 3.13 with conda (`environment.yaml` creates `py313-architeuthis`). Line endings are LF for `.py`, `.md` and `.txt`.

The package does not need installing for development: **run everything from the repository root** using `python -m ...`. `pip install -e ".[test]"` is the alternative, and it is what CI does.

```bash
conda env create -f environment.yaml
```

```bash
python -m pytest
```

A single test: `python -m pytest tests/optimization/test_opti_rosenbrock.py::test_2D_rosenbrock`. Only the end-to-end routing tests: `python -m pytest -m integration`. The suite takes under a minute and needs no network or credentials. There is no linter or formatter configuration.

Credentials come from environment variables, and each is only needed for its provider: `CDS_API_KEY`, `CMEMS_USER`, `CMEMS_PWD`, `EUMDAC_USER`, `EUMDAC_PWD`. Herbie sources (IFS, GFS, HRDPS) need none.

Downloads are cached under `~/data/` (`common._HOME`) in `topo/`, `cmems/`, `cds/`, `eumetsat/` and `iip/`. `RouteLibrary`, `RouteSetLibrary`, `PassagePlanLibrary` and `ExclusionZoneLibrary` store JSON in `route_library/`, `route_sets/`, `passage_plans/` and `exclusion_zones/`. The UI reads route reports from `routes/`, a different format, written by `ReportCollection.save`. Vessel polars are NetCDF files that are not in the repository.

Development is Spyder-based: scripts use `#%%` cells and many modules have a `__main__` block used as a manual check.

Branches: work on `develop`, PRs target `main`.

## Architecture

```text
architeuthis.numpy         NumPy/CasADi unified math (AeroSandbox)
architeuthis.optimization  Opti (cas.Opti subclass), OptiSol (AeroSandbox)
architeuthis.modeling      Fitted/interpolated models, black_box (AeroSandbox)
        |
common.py      ArchiteuthisObject > ArchiteuthisData > ArchiteuthisSpatialData
        |       load_data() pipeline, add_interpolator(), __call__(), credentials
        +-- vessel.py     Vessel: polars NetCDF + hotel_load, sfc, max_power
        +-- forecast.py   Topography; Forecast > Herbie (deterministic, ensemble),
        |                 Copernicus (CMEMS), CDS (ERA5)
        +-- satellite.py  EUMETSATData > ASCATData, PoseidonData (validation)
        |
icebergs.py    IIP iceberg limit, fetched on first use: berg_zone polygon, berg_geojson
        |
route.py       Waypoint, Leg, Route (waypoints + divergences + spread), RouteSet, RouteLibrary
voyage.py      Schedule, Voyage (Route + Schedule), PassagePlan, PassagePlanLibrary
exclusion.py   ExclusionZone, ExclusionZoneLibrary, default_exclusion_zones
report.py      RoutingReport (dict), ReportCollection (list): tables, GPX, JSON storage
        |       all offline: they do not import core
core.py        RoutingAnalysis (run, evaluate), exclusion_zones; re-exports the above
presets.py     Ready-made forecasts and topography. Import the module: `from architeuthis import presets`
        |
ui.py          Dash/Leaflet viewer of forecast fields and saved route reports

toolbox/       geo_utils (route geometry), plot_utils (figures, documented in the README),
               json_utils (report JSON codec), inspect_tools, string_formatting...
wrappers/      json_wrapper (GeoJSON), leaflet_wrapper (zone layers), legacy provider wrappers
examples/      simple_routing, long_term_routing, ensemble_routing, post_leg_rewind,
               passage_planning, ifs_route_tested_with_gfs, short_term_routing, comparison_ascat_models
tests/         numpy, optimization, modeling (AeroSandbox), domain (Architeuthis)
```

Stubs that are not functional yet: `environment.Environment` (also has a broken bare import), `ECMWFForecast`, `AtmosphericForecast`, `OceanographicForecast`. `architeuthis/__init__.py` exports only `Opti` and `OptiSol`, so import everything else from submodules.

### Data pipeline

`ArchiteuthisData.load_data()` is a template method: `_locate_data` > `_download_data` > `_read_data` > `_convert_data` > `_extend_data`. A new data source overrides these hooks and must normalize to:

- **Longitude** in [-180, 180) and sorted coordinates.
- **Time** as a float epoch-seconds coordinate named `valid_time`.
- **Dimension order** matching the `coord_dims` passed to `add_interpolator`.

`add_interpolator` builds a CasADi `interpolant` from the array. Know these behaviours:

- Dimensions are **positional**: the array is squeezed, sliced and raveled in Fortran order, so array dimension order must equal `coord_dims` order. The names only select coordinates.
- **NaN becomes 0**, so land currents and missing values read as calm conditions.
- Herbie and Copernicus forecasts append two fake time steps (+1e6 s, +1e7 s) filled with 0, so fields fade to zero past the horizon rather than failing. `RoutingAnalysis.check_valid_time` assumes this by treating `valid_time[-3]` as the last real step; `CDSForecast` does not pad, so the check is off by two steps there.
- Calling `obj(var_key, X)` takes `X` with shape `(n_queries, n_dims)` and returns a column vector.

`Topography` computes `distance_to_iso0`, normally registered with `var_key="z"`: a signed distance to the navigable boundary in **nautical miles**, positive on land or inside exclusion zones and negative at sea. `depth_offset` treats shallow water as land and `z_margin` adds clearance. Its coordinates are `lat` and `lon` (ETOPO 2022), unlike the `latitude` and `longitude` of forecasts. Exclusion zones are `ExclusionZone` objects or plain `[lat, lon]` lists, rasterized into this field; the caller must pass them to `Topography`, typically `default_exclusion_zones()`.

### Routing problem (`RoutingAnalysis.run`)

- **Objective:** minimize total fuel, `sum((bhp + hotel_load) * dt * sfc) / 1e6` in tonnes.
- **Fixed:** ETD, ETA, departure and arrival, so the schedule is a hard requirement and speed is an outcome (`sog = distance / dt`).
- **Time grid:** comes from the atmospheric forecast. Segment centers (`ctim`) are the `valid_time` values strictly between ETD and ETA, and nodes (`tim`) are ETD, their midpoints and ETA. `skip_tim` thins them.
- **Decision variables:** `vlat` and `vlon`, offsets of interior nodes from a reference route. With `vary_fac=True`, also `deviation_fac`, which blends `Voyage.route_minus`, `route_ortho` and `route_plus` (-1, 0, +1).
- **Evaluation:** weather is sampled at segment midpoints, topography at nodes resampled with `n=3`, and the vessel with `[stw, tws, |twa|, swh, |mwa|]`.
- **Constraints:** a callable `ctx -> list` or a plain list, given to the constructor or to `run`. `ctx` exposes the symbolic quantities plus `vessel` and `opti`. The default is `max_bhp < vessel.max_power` and `z < 0`.
- **`solve=False`:** evaluates the reference route without optimizing it, giving a baseline for comparison.
- **Shared model:** `_passage(tim, ctim, lat, lon, ...)` builds every symbolic quantity; `run` feeds it Opti variables and `evaluate` plain MX symbols. Change the physics there only.
- **Results:** `run` also sets `analysis.report` and `analysis.passage_plan` (a `PassagePlan` named `<route>_<etd>Z`, with `describe()` metadata).
- **Tags:** `run(tags=...)` and `evaluate(tags=...)` add entries to the report. By default it has `solve` (int), `model`, `vessel` (`Vessel.label`) and `member`.
- **Callback:** `run(callback=...)` is called at each IPOPT iteration, with the iteration number.
- **Open loop:** `evaluate(plan)` computes the same report for fixed positions with another vessel, forecast or member, through a `ca.Function` and without IPOPT. Constraints are only measured: `max_constraint_violation` and `constraint_violations`, with `ctx["opti"] = None`. `status` is 0.
- **Output:** `run` returns a `RoutingReport`, a dict of numeric arrays and scalars, with the tags above.

Required interpolator keys:

| Object | Keys | Units |
| --- | --- | --- |
| `atmosphere` | `u10`, `v10`, optional `gust` (otherwise `tws * GUST_DEFAULT_RATIO`) | m/s, converted to kt |
| `wave` | `swh`, `mwd` | m, deg |
| `current` | `uo`, `vo` | m/s, converted to kt |
| `topography` | `z` | nm |
| `vessel` | `bhp`, `max_bhp`, `sails_contribution`; axes `stw, tws, twa, hs, wa` | kW; kt, kt, deg, m, deg |

Modelling choices to preserve or change deliberately: wind and wave angles are relative to COG, apparent wind uses SOG rather than STW, and leeway is not modelled.

### Glossary and units

Speeds in knots, distances in nautical miles, angles in degrees, time in float epoch seconds, power in kW. Positions are always `[lat, lon]`, latitude first. A `c` prefix (`clat`, `ctim`) marks a segment center.

| Term | Meaning | Term | Meaning |
| --- | --- | --- | --- |
| `stw`, `sog` | speed through water, over ground | `swh`, `hs` | significant wave height |
| `cog`, `ctw` | course over ground, through water | `mwd`, `mwa` | mean wave direction, angle |
| `tws`, `twd`, `twa` | true wind speed, direction, angle | `cs`, `cd` | current speed, direction (going to) |
| `aws`, `awa` | apparent wind speed, angle | `bhp`, `sfc` | brake power, specific fuel consumption (g/kWh) |
| `etd`, `eta` | departure, arrival time | `f00`, `fxx` | forecast base time, lead times |

## Pitfalls

**Import side effects**

- Importing the package has none, and `tests/domain/test_import_side_effects.py` checks it. `load_data` calls `common.setup_logging`, which leaves logging alone if the application has configured it, and `ensure_cdsapirc` runs before a CDS download and never writes `key: None`.
- `architeuthis.icebergs` fetches the IIP bulletin and shapefiles on first use of `berg_zone`, `polygon` or `berg_geojson` (module `__getattr__`, connect timeout 10 s), once per session unless `refresh()` is called. Reading `core.exclusion_zones` or calling `default_exclusion_zones()` counts as a use, so these can take time. Offline, it falls back to the last downloads in `~/data/iip/` (`IcebergBulletin.txt`, shapefiles), else to an empty `berg_zone` and GeoJSON, with a warning. `Topography` skips exclusion zones with fewer than 3 points, so routing then runs **without the iceberg limit**.
- `architeuthis/ui.py` is a script, not a library: importing it downloads forecasts and needs a report JSON in `~/data/routes/`. Run it from inside `architeuthis/` because of `./assets/` relative paths; it serves on port 8052. Its first lines remove `architeuthis/` from `sys.path`, where `architeuthis/numpy` would hide numpy, and it selects the Agg backend, because a GUI backend kills the process at the first raster or contour. So when checking the UI, do not set `MPLBACKEND`, which is not what a user has. In debug mode its reloader runs the script twice, and any restart downloads the forecasts again. Layers that do not depend on its data belong in `wrappers/leaflet_wrapper.py`, where they can be tested.
- `ui.py` overwrites the tracked `assets/noaa_overlay.png` at every start, so that file often shows as modified. Do not include it in unrelated commits.

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
- `Vessel.hotel_load` and `Vessel.sfc` are wrapped into callables, while `Vessel.max_power` stays a raw value. `sfc` defaults to 0, which makes the objective zero.
- `EnsembleHerbieForecast.add_interpolator` takes `var_dim, time_dim, member_dim, latitude_dim, longitude_dim`, the order in which `RoutingAnalysis` queries it.
- Report consumers (`json_wrapper.route_to_geojson`, `ui.py`) also need `init_fac`, which `run` does not produce: callers give it in `tags`. `ReportCollection.save` writes to `~/data/routes/` by default.
- `core.exclusion_zones` and `core.berg_zone` are computed each time they are read (module `__getattr__`), so `from architeuthis.core import exclusion_zones` fetches the iceberg limit at that line.

## Testing

Tests live in `tests/`, configured in `pyproject.toml`. `.github/workflows/tests.yml` runs them with coverage on every push, on Ubuntu (Python 3.11 to 3.13) and Windows (3.13). `publish.yml` releases to PyPI from `v*` tags and does not depend on the tests.

CI installs the latest dependencies, so it can differ from a local environment. In particular, casadi 3.7 and 3.8 do not always converge the same way, so keep test objectives reasonably well conditioned.

- **`tests/numpy`, `tests/optimization`, `tests/modeling`:** vendored from AeroSandbox, including the `import architeuthis as asb` style.
- **`tests/domain`:** Architeuthis code. `test_route.py` covers routes, voyages and passage plans offline. `test_routing.py` runs `RoutingAnalysis.run` and `evaluate` end to end, marked `integration`. `test_plots.py` draws every figure from real reports with Agg. `test_ui.py` runs the real `ui.py` without its server, with forecasts and downloads replaced. `test_import_side_effects.py` checks imports in a new interpreter with the network cut off.
- **Expected failure:** `test_black_box_nonsmooth_function` is `xfail` because IPOPT can fail on the kink of `abs()`.

Rules for new tests:

- **Stay offline.** `tests/conftest.py` points `HOME` at a temporary folder, removes credentials and replaces `architeuthis.icebergs` with a stub. Mock providers with `patch("architeuthis.forecast.<name>")`, or `load_data` as `test_presets.py` does.
- **Use synthetic data.** The fixtures in `tests/domain/conftest.py` provide forecasts, topographies, a vessel and real reports (`baseline_report`, `optimized_report`, `routing`): assign a dataset to `.data`, skip `load_data()`, then call `add_interpolator`. The reports are shared, so copy them to change them.
- **Pass `linear_solver: mumps`** in routing tests, because of the `spral` crash described under Pitfalls.
- **Keep the checkout clean.** Importing `wrappers/json_wrapper.py` or `ui.py` writes `assets/dashExtensions_default.js` to the working directory, so import them from a temporary folder, as `tests/domain/test_toolbox.py` does.
- **Do not change `--tb=native`.** Other traceback styles parse `casadi.py`, which raises `MemoryError` and aborts the session.

Not covered: the real IIP server (`test_icebergs.py` replaces `requests.get`), `ui.py` with real forecasts and in a browser, the rendering of cartopy maps, `satellite.py`, and the default `spral` solver options.

## Known inconsistencies

- `examples/short_term_routing.py` is an operational script rather than a clean example: hard-coded local polar paths, bare `from geo_utils import` and `from plot_utils import` that need `toolbox/` on the path, and legacy Earth2014 dimension names for `Topography`, which now needs `"lat"` and `"lon"`.
- Versions disagree: `pyproject.toml` 0.1.4, `__init__.py` 0.1.3.
- `tall` and `wide` are duplicated in `common.py` and `core.py`, and `core.py` defines an unused `sigmoid`, `transform` and `added_wave_load`. `ROADMAP.md` plans to move these helpers into `numpy`.
- `raise(ValueError, "...")` appears in `forecast.py` and `ui.py`. In Python 3 this raises `TypeError` rather than the intended error.

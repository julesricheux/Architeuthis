<!-- Logo placeholder: add the file at media/logo-architeuthis-color.png -->
<img alt="Architeuthis logo" src="media/logo-architeuthis-color.png" width="100%">

<div align="center">

# Architeuthis: Weather Routing for Wind-powered Hybrid Vessels 🦑

**Minimize fuel on a fixed schedule, with real forecasts, real constraints and your own vessel model.**

<!-- Badges -->

[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/architeuthis)](https://pypi.org/project/architeuthis/)
[![PyPI](https://img.shields.io/pypi/v/architeuthis.svg)](https://pypi.org/project/architeuthis/)
[![Tests](https://github.com/julesricheux/Architeuthis/actions/workflows/tests.yml/badge.svg?branch=develop)](https://github.com/julesricheux/Architeuthis/actions/workflows/tests.yml)
[![Downloads](https://static.pepy.tech/badge/architeuthis)](https://pepy.tech/projects/architeuthis)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

## 📚 [User Guide](docs/user_guide.md) | 🧪 [Examples](examples/README.md) | ❔ [Issues](https://github.com/julesricheux/Architeuthis/issues)

<!-- (Badges) -->

</div>

---

## What is Architeuthis?

An open-source marine weather and decision-making framework for hybrid sailing ships. It couples mesh-free, fully differentiable methods in a unified optimization environment to compute optimal routes under real-world constraints.

No graph, no grid search: the waypoints are continuous variables of a single nonlinear program. Weather, bathymetry and your vessel are differentiable models queried at those waypoints, [CasADi](https://github.com/casadi/casadi) differentiates through all of it and [IPOPT](https://github.com/coin-or/Ipopt) finds the route.

- ⛽ **Fuel-optimal routes** on a fixed departure and arrival time
- 🧩 **Any vessel model**: a polar table, or your own semi-empirical functions with their fitted parameters
- 🌊 **Wind, waves, currents and more**: IFS, GFS, ensembles, Mercator, ERA5, and any other field your model needs
- 🧊 **Real-world constraints**: land, shallow water, exclusion zones, the iceberg limit, maximum power, your own rules
- 🎲 **Forecast uncertainty**: optimize each ensemble member, test a plan against other models, members or vessels
- 🛰️ **Satellite observations**: ASCAT winds to check the forecasts, and one seamless cloud layer from Meteosat and GOES-East
- 📊 **Ready-to-use outputs**: A4 reports, maps, tables, GPX tracks, and a 3D globe of routes and forecasts to send aboard as one file

**Architeuthis** provides the **onshore weather routing support** of [Neoliner Origin](https://www.neoline.eu/) 🌬️⛵⚓

**Keywords:** weather routing, voyage optimization, fuel saving, wind-assisted ship propulsion, hybrid vessel, passage planning, nonlinear optimization, CasADi, IPOPT, GRIB2, xarray, python

---

## 🚀 Quick Start

```bash
pip install architeuthis            # add [app] for the analyst's page, ui.py
```

Or from source: `git clone https://github.com/julesricheux/Architeuthis.git`, then `conda env create -f environment.yaml` and run everything from the repository root (Python 3.11 or later).

A North Atlantic crossing on yesterday's ECMWF forecast, with no account and no credentials:

```python
import pandas as pd
import xarray as xr

from architeuthis.core import RoutingAnalysis
from architeuthis.forecast import DeterministicHerbieForecast, Forecast, Topography
from architeuthis.report import ReportCollection
from architeuthis.route import Route, Waypoint
from architeuthis.toolbox.plot_utils import plot_report
from architeuthis.vessel import Vessel
from architeuthis.voyage import Voyage

domain = dict(min_lon=-60., max_lon=0., min_lat=38., max_lat=56.)
today = pd.Timestamp("now").floor("1d")
date = today - pd.Timedelta(days=1)                               # yesterday's 00 UTC run
steps = list(range(0, 145, 3)) + list(range(150, 241, 6))         # lead times, in hours

atmosphere = DeterministicHerbieForecast("wind", model="ifs", product="oper", regex=r":10[u|v]:", fxx=steps, date=date, **domain)
atmosphere.load_data()
for key in ("u10", "v10"):
    atmosphere.add_interpolator(key, "valid_time", "latitude", "longitude")

wave = DeterministicHerbieForecast("wave", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=steps, date=date, **domain)
wave.load_data()
wave.add_wave_components()                                        # direction through its components
for key in ("swh", "uw", "vw"):
    wave.add_interpolator(key, "valid_time", "latitude", "longitude")

calm = xr.zeros_like(atmosphere.data["u10"])                      # calm water; see CopernicusForecast for currents
current = Forecast("calm_current", date=None, fxx=None, **domain)
current.data = xr.Dataset({"uo": calm, "vo": calm})
for key in ("uo", "vo"):
    current.add_interpolator(key, "valid_time", "latitude", "longitude")

topography = Topography("topography", **domain)
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

vessel = Vessel("vessel", filepath="my_vessel_polar.nc", sfoc=220., hotel_load=194., max_power=4100.)  # g/kWh, kW, kW
vessel.load_data()
for key in ("bhp", "max_bhp", "sails_contribution"):
    vessel.add_interpolator(key, "stw", "tws", "twa", "hs", "wa", method="linear")

route = Route("crossing", [Waypoint(47.725, -4.380, "Penmarch"), Waypoint(46.551, -53.321, "Cape Race")])
voyage = Voyage("crossing", etd=today, eta=today + pd.Timedelta(days=8), route=route)

analysis = RoutingAnalysis(
    "crossing", vessel, voyage, atmosphere, wave, current, topography,
    variables=["max_bhp", "sails_contribution"],  # the fuel only needs bhp: ask for the rest
)
report = analysis.run()

reports = ReportCollection([report])
print(reports.summary())
reports.to_gpx()     # a track for your navigation system
reports.save()       # for ui.py
plot_report(report)  # one A4 page: speed, sails, power, waves and wind
```

---

## 🚢 Your Vessel

Architeuthis ships no vessel model: bring yours, **as a table or as functions**. Both are models of the same object, queried the same way, and the routing does not care which one it gets.

**📋 A polar table**, from a VPP, sea trials or anything else: a NetCDF file with, for example, `bhp`, `max_bhp` and `sails_contribution` (kW, kW, %) on the axes `stw, tws, twa, hs, wa` (kt, kt, deg, m, deg). That is the [Quick Start](#-quick-start).

**🧮 Or your own functions**, with their fitted parameters, and no file at all:

```python
import architeuthis.numpy as np

def my_polar(x, p):
    tws = (x["tws"] + x["tws100"]) / 2.                           # wind between 10 m and 100 m
    sails = p["c_sail"] * tws**2 * x["stw"] * np.sind(x["twa100"])**2
    calm = p["c_calm"] * x["stw"]**3 * (1. + p["k_t"] * (x["water_temperature"] - 15.))
    return calm - sails, {"calm": calm, "sails": sails}

inputs = ["stw", "tws", "tws100", "twa100", "water_temperature"]
vessel = Vessel("my_ship", sfoc=220., max_power=4100.)
vessel.add_function("bhp", my_polar, inputs, args={"p": fitted})
vessel.add_function("sails_contribution", my_polar, inputs, args={"p": fitted}, output="sails")
```

### ⛽ The routing only needs the consumption

The objective is the fuel, so the vessel needs one model of its consumption, the first of:

| Model | Unit | Burnt at |
| --- | --- | --- |
| `hourly_consumption` | kg/h | (it is the consumption) |
| `total_power`, propulsion and hotel | kW | `sfoc`, g/kWh |
| `bhp`, propulsion | kW | `sfoc`, after adding `hotel_load`, kW |

Each can be a table, a function or a constant (`vessel.add_constant("bhp", 1500.)`). `hotel_load` and `sfoc` are numbers or functions of the power given to `Vessel(...)`, or models of their own, which can take `bhp` or `total_power` as an input: an sfoc curve of the engine load, for example. Any other model of the vessel, such as `max_bhp` or `sails_contribution`, is computed only when you list it: `RoutingAnalysis(..., variables=["max_bhp"])`. Until 0.4.0, `max_bhp` and `sails_contribution` are still computed when the vessel has them, with a deprecation warning that asks to list them.

### ✨ The routing finds what your model needs

Name an input, and the routing provides it. No wiring, no plumbing:

| Your model asks for | The routing |
| --- | --- |
| `stw`, `sog`, `tws`, `twd`, `twa`, `aws`, `awa`, `hs`/`swh`, `wa`/`mwa` | computes them along the route, relative to the vessel |
| `tws100`, `twa100`, `aws100`, `awa100`... at **any height** | computes them the same way from the forecast's `u100` and `v100` |
| **anything else**: `water_temperature`, `mwp`, `air_temperature`... | samples the forecast that has a model of that name |

So the forecasts above only need a few more lines, and the routing is unchanged:

```python
atmosphere = DeterministicHerbieForecast("wind", model="ifs", product="oper", regex=r":(?:10[uv]|100[uv]):", ...)  # one download, several levels
atmosphere.add_interpolator("u100", "valid_time", "latitude", "longitude")
atmosphere.add_interpolator("v100", "valid_time", "latitude", "longitude")
current.add_interpolator("thetao", "valid_time", "latitude", "longitude", var_key="water_temperature")
```

A forecast can hold functions too, to convert a unit or combine fields: `atmosphere.add_function("air_temperature", lambda x: atmosphere("t2m", x) - 273.15, inputs=["valid_time", "latitude", "longitude"])`.

Quantities your model does not use can be computed all the same, to constrain them or see them in the reports: `RoutingAnalysis(..., variables=["tws_gust", "wave.slope"])` puts the gusts and a wave slope in `ctx` and in every report.

**💡 Good practice**

- **Stay differentiable:** write with `architeuthis.numpy`, and use `np.where`, `np.softmax` or `np.sigmoid` rather than `if` on values.
- **Mind the units:** routing quantities are in kt and degrees, angles in absolute value. Forecast fields arrive as stored (m/s, K): convert them with `fac=` or a function.
- **Return components:** `(value, {"sails": ...})`, then pick one with `output=`.
- **Set a realistic `max_power`, or `None`:** a huge power limit unsettles the solver. `max_power=None` leaves the power free; until 0.4.0, leaving it out still gives 1e12 kW, with a warning.

The complete script is [`examples/function_polar_routing.py`](examples/function_polar_routing.py), and the [User Guide](docs/user_guide.md) has the details.

---

## 📤 Sharing with the Crew

The routes, the forecasts of the voyage and the exclusion zones fit in one HTML file of a few MB. It opens in any browser, offline, on a 3D globe, dark or light: boats moving along their routes, a timeline of the forecasts, wind barbs, wave glyphs that tell the height, isobars, a weather picker to drag anywhere, the values the analyst chose on each route, and their comments on the strategy.

```python
reports.share(
    forecasts={"IFS": [atmosphere, wave]},
    routes=[0, 2],                          # leave out the routes the crew does not need
    variables=["sog", "tws", "twa", "swh"],   # shown when hovering a route
    note="Expect the low to cross the route on Saturday: keep north.",
)                                           # ~/data/shared/<title>_<time>.html
```

Or run `python -m architeuthis.ui`: the page shows the file as the crew will see it, beside checkboxes for the routes, the tooltips and the models, a description of each route, and comments placed by clicking the routes, and downloads it. See the [User Guide](docs/user_guide.md#sharing-routes).

---

## 🛰️ Satellite Observations

See what the sea and the sky actually did, to judge a forecast or brief a crew.

**☁️ Cloud images, no account.** Meteosat and GOES-East joined into one seamless layer over the North Atlantic, every 10 minutes, in the infrared (day and night) and the visible (by day). Each pixel comes from the satellite that sees it most directly, and both are put back on one physical scale, so they meet without a seam:

```python
import matplotlib.pyplot as plt
from architeuthis.satellite import GeostationaryImagery

clouds = GeostationaryImagery("clouds", start="2026-11-19 12:00Z", end="2026-11-19 15:00Z",
                              min_lon=-75., max_lon=5., min_lat=35., max_lat=60.,
                              channels=["ir", "visible"], resolution=0.05)
clouds.load_data()                                   # brightness temperature (K) and brightness (0-1)
plt.imshow(clouds.image(-1, "ir", colormap="blue"), extent=clouds.extent())  # Windy-style colours
```

**🌬️ ASCAT winds**, the scatterometer of the Metop satellites, from EUMETSAT a couple of hours after the pass, or from Copernicus Marine a day later when EUMETSAT is not available:

```python
from architeuthis.satellite import ASCATData

ascat = ASCATData("ascat", start="2026-11-18", end="2026-11-19", min_lon=-20., max_lon=0., min_lat=40., max_lat=52.)
ascat.load_data()                                    # wind_speed (m/s), wind_dir (where it goes)
print(ascat.source)                                  # "eumetsat" or "cmems"
```

Images and swaths are cached in `~/data/`, so a second run downloads nothing. See [`examples/cloud_imagery.py`](examples/cloud_imagery.py), [`examples/ascat_sources.py`](examples/ascat_sources.py) and the [User Guide](docs/user_guide.md#satellite-observations).

---

## 🔑 Credentials and Settings

### > What You Need to Set

Mostly nothing: forecasts, relief, the iceberg limit and cloud images need no account. A credential is only asked for by the provider that needs it, so create the accounts of the data you want, and nothing else.

| Provider | Gives | Credentials |
| --- | --- | --- |
| ECMWF, NOAA, MSC, through [Herbie](https://github.com/blaylockbk/Herbie) | IFS, GFS, their ensembles and wave models, HRDPS: `DeterministicHerbieForecast`, `EnsembleHerbieForecast`, `HRDPSForecast` | None |
| NOAA ETOPO, International Ice Patrol | Relief (`Topography`), iceberg limit (`iceberg_zone`) | None |
| EUMETView, NASA GIBS | Cloud images: `GeostationaryImagery`, `EUMETViewData`, `GIBSData` | None |
| [Copernicus Marine](#copernicus-marine-currents-and-ascat) | Currents and ocean fields, `CopernicusForecast`; ASCAT winds, `CopernicusASCATData` and the fallback of `ASCATData` | `CMEMS_USER`, `CMEMS_PWD` |
| [Climate Data Store](#climate-data-store-era5) | ERA5 reanalysis, `CDSForecast` | `CDS_API_KEY` |
| [EUMETSAT Data Store](#eumetsat-satellite-observations) | ASCAT winds, `EUMETSATASCATData` and the first choice of `ASCATData`; Sentinel-6 altimeter winds and waves, `PoseidonData` | `EUMDAC_KEY`, `EUMDAC_SECRET` |

For ASCAT winds, either EUMETSAT or Copernicus Marine is enough. Get a credential with the tutorial of its provider below, then [save it once](#-saving-your-credentials-once). `ARCHITEUTHIS_HOME`, optional, [moves the data folder](#-the-data-folder).

### > Saving Your Credentials Once

In the environment where Architeuthis lives, run `set` with the names you need. It asks for each value, hidden:

```bash
python -m architeuthis.credentials set CMEMS_USER CMEMS_PWD
```

Then check what Architeuthis finds, without showing any value:

```bash
python -m architeuthis.credentials status
```
```text
CDS_API_KEY    missing
CMEMS_USER     credential store
CMEMS_PWD      credential store
EUMDAC_KEY     missing
EUMDAC_SECRET  missing
```

Done: every session finds them, in Spyder, a notebook or a script. They stay encrypted by your operating system (Windows Credential Manager, macOS Keychain, Secret Service), through [keyring](https://pypi.org/project/keyring/). Run `set` again to change one, and remove one with:

```bash
python -m architeuthis.credentials delete CMEMS_PWD
```

From Python: `save_credential("CMEMS_PWD")` and `credential_sources()`, in `architeuthis.credentials`. A missing credential stops the download before it starts, with a ⚠️ message and the command that fixes it.

### > Where Architeuthis Looks

Only when a download needs them, never at import, taking the first value found:

1. **An environment variable** of the same name, or one of the providers' own: `CDSAPI_KEY`, `COPERNICUSMARINE_SERVICE_USERNAME`, `COPERNICUSMARINE_SERVICE_PASSWORD`, and `EUMDAC_USER` and `EUMDAC_PWD`, the former names of `EUMDAC_KEY` and `EUMDAC_SECRET`.
2. **The credential store**, where `set` saves them.
3. **The provider's own file**: `copernicusmarine login`, or `~/.cdsapirc`.

Environment variables suit servers, CI jobs and containers, where there is no credential store, and override the store for a while. Saving a credential removes its variables from the current session, with a ⚠️ message naming them: delete them where they are defined too, or new sessions keep reading the old value. Give them as secrets of the platform; saved in a profile (`setx`, `~/.bashrc`, `conda env config vars`) they sit in plain text.

### > The Data Folder

Everything goes to `~/data/`:

| Folder | Holds |
| --- | --- |
| `topo/`, `cmems/`, `cds/`, `eumetsat/`, `wms/`, `iip/` | Downloads: relief, currents, reanalysis, satellite data, satellite images (by server, layer and box), iceberg limit |
| `route_library/`, `route_sets/`, `passage_plans/`, `exclusion_zones/` | Your saved routes, plans and zones |
| `routes/` | Reports saved by `ReportCollection.save`, read by `ui.py` |
| `shared/`, `viewer/` | Files written by `ReportCollection.share`, and the MapLibre library they hold |

Set `ARCHITEUTHIS_HOME` to move it, then open a new terminal: `setx ARCHITEUTHIS_HOME "D:\architeuthis-data"` on Windows, `export ARCHITEUTHIS_HOME="$HOME/architeuthis-data"` in `~/.bashrc` elsewhere. Herbie keeps the GRIB files in its own `save_dir` (`~/.config/herbie/config.toml`).

### > Keeping Credentials Safe

- 🔒 **Never write a credential in code**, a notebook or a comment: a repository's history keeps it forever.
- **If one leaks,** change it at the provider, then `set` it again.
- **Coming from 0.2.0 or earlier?** Your environment variables still work. Move them to the store with `set`, check with `status`, then delete them and the `~/.cdsapirc` Architeuthis wrote.

### Copernicus Marine (currents and ASCAT)

1. Create a free account at [data.marine.copernicus.eu/register](https://data.marine.copernicus.eu/register).
2. Save your username and password:

   ```bash
   python -m architeuthis.credentials set CMEMS_USER CMEMS_PWD
   ```

3. Check them (prints `True`):

   ```python
   import copernicusmarine
   from architeuthis.credentials import get_credential

   print(copernicusmarine.login(get_credential("CMEMS_USER"), get_credential("CMEMS_PWD"), check_credentials_valid=True))
   ```

The same account gives the currents of `CopernicusForecast` and the ASCAT winds of `CopernicusASCATData`. Already logged in with `copernicusmarine login`? Architeuthis uses that file when it finds no credential of its own.

### Climate Data Store (ERA5)

1. Create a free account at the [Climate Data Store](https://cds.climate.copernicus.eu/how-to-api).
2. Accept the Terms of Use of each dataset you need, at the bottom of its download tab: [ERA5 single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download), for example. Without it, requests fail with a licence error.
3. Copy the *Personal Access Token* of your profile, and save it:

   ```bash
   python -m architeuthis.credentials set CDS_API_KEY
   ```

Architeuthis hands the token to the client and writes no file. Without one, the client falls back to your own `~/.cdsapirc`:

```text
url: https://cds.climate.copernicus.eu/api
key: your-personal-access-token
```

### EUMETSAT (satellite observations)

1. Create a free account on the [EUMETSAT User Portal](https://eoportal.eumetsat.int/).
2. Open the [API key page](https://api.eumetsat.int/api-key/), signed in. Not your login: save your **Consumer Key** as `EUMDAC_KEY` and your **Consumer Secret** as `EUMDAC_SECRET`:

   ```bash
   python -m architeuthis.credentials set EUMDAC_KEY EUMDAC_SECRET
   ```

3. Check them (prints an expiry date):

   ```python
   import eumdac
   from architeuthis.credentials import get_credential

   print(eumdac.AccessToken((get_credential("EUMDAC_KEY"), get_credential("EUMDAC_SECRET"))).expiration)
   ```

Architeuthis downloads with it the ASCAT winds of the OSI SAF (`EO:EUM:DAT:METOP:OSI-104`) for `EUMETSATASCATData`, and the Sentinel-6 Poseidon-4 products (`EO:EUM:DAT:0142`) for `PoseidonData`.

---

## 🗺️ The Routing Problem

- **Objective:** total fuel, `sum(hourly_consumption * dt) / 1e3`, in tonnes, where the consumption is `(bhp + hotel_load) * sfoc / 1e3` kg/h, `total_power * sfoc / 1e3` or your own `hourly_consumption`.
- **Fixed:** departure, arrival, ETD and ETA. The schedule is a requirement, the speed an outcome.
- **Environment:** the wind, waves and current you give; any of them left out is zero, so `RoutingAnalysis("analysis", vessel, voyage, atmosphere, topography=topography)` routes in the wind alone.
- **Variables:** the positions along the route, and optionally a factor blending the reference route towards two alternatives.
- **Constraints:** every position at sea and, if the vessel has a `max_power`, `max_bhp` (when listed), else `bhp` or `total_power`, below it. Or your own, on any quantity of the route or any additional variable (`variables=`).

---

## 🙏 Credits

Architeuthis stands on the work of others, with our thanks:

- **[AeroSandbox](https://github.com/peterdsharpe/AeroSandbox)** by Peter D. Sharpe (MIT). The `numpy`, `optimization` and `modeling` packages are adapted from version 4.2.9 ([license](https://github.com/peterdsharpe/AeroSandbox/blob/master/LICENSE.txt)).
- **[Herbie](https://github.com/blaylockbk/Herbie)** by Brian K. Blaylock (MIT) downloads the forecasts, and its README inspired this one.
- **[CasADi](https://github.com/casadi/casadi)** (LGPL) and **[IPOPT](https://github.com/coin-or/Ipopt)** (EPL) differentiate and solve the routing problem.
- **[Copernicus Marine Toolbox](https://github.com/mercator-ocean/copernicus-marine-toolbox)**, **[xarray](https://github.com/pydata/xarray)**, **[Cartopy](https://github.com/SciTools/cartopy)**, **[Dash](https://github.com/plotly/dash)** and the other dependencies of [`pyproject.toml`](pyproject.toml).
- The forecast, ocean, relief and ice data of their providers.

## Contributing

Report bugs or suggest features in the [issues](https://github.com/julesricheux/Architeuthis/issues), and **star this repository!** ⭐

## ⚖️ License

[GNU General Public License v3.0](LICENSE).

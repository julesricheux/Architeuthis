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
- 📊 **Ready-to-use outputs**: A4 reports, maps, tables, GPX tracks and an interactive viewer

**Architeuthis** provides the **onshore weather routing support** of [Neoliner Origin](https://www.neoline.eu/) 🌬️⛵⚓

**Keywords:** weather routing, voyage optimization, fuel saving, wind-assisted ship propulsion, hybrid vessel, passage planning, nonlinear optimization, CasADi, IPOPT, GRIB2, xarray, python

---

## 🚀 Quick Start

```bash
pip install architeuthis            # add [app] for the interactive viewer
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

vessel = Vessel("vessel", filepath="my_vessel_polar.nc", sfc=220., hotel_load=194., max_power=4100.)  # g/kWh, kW, kW
vessel.load_data()
for key in ("bhp", "max_bhp", "sails_contribution"):
    vessel.add_interpolator(key, "stw", "tws", "twa", "hs", "wa", method="linear")

route = Route("crossing", [Waypoint(47.725, -4.380, "Penmarch"), Waypoint(46.551, -53.321, "Cape Race")])
voyage = Voyage("crossing", etd=today, eta=today + pd.Timedelta(days=8), route=route)

report = RoutingAnalysis("crossing", vessel, voyage, atmosphere, wave, current, topography).run()

reports = ReportCollection([report])
print(reports.summary())
reports.to_gpx()     # a track for your navigation system
reports.save()       # for the viewer
plot_report(report)  # one A4 page: speed, sails, power, waves and wind
```

---

## 🚢 Your Vessel

Architeuthis ships no vessel model: bring yours, **as a table or as functions**. Both are models of the same object, queried the same way, and the routing does not care which one it gets.

**📋 A polar table**, from a VPP, sea trials or anything else: a NetCDF file with `bhp`, `max_bhp` and `sails_contribution` (kW, kW, %) on the axes `stw, tws, twa, hs, wa` (kt, kt, deg, m, deg). That is the [Quick Start](#-quick-start).

**🧮 Or your own functions**, with their fitted parameters, and no file at all:

```python
import architeuthis.numpy as np

def my_polar(x, p):
    tws = (x["tws"] + x["tws100"]) / 2.                           # wind between 10 m and 100 m
    sails = p["c_sail"] * tws**2 * x["stw"] * np.sind(x["twa100"])**2
    calm = p["c_calm"] * x["stw"]**3 * (1. + p["k_t"] * (x["water_temperature"] - 15.))
    return calm - sails, {"calm": calm, "sails": sails}

inputs = ["stw", "tws", "tws100", "twa100", "water_temperature"]
vessel = Vessel("my_ship", sfc=220., max_power=4100.)
vessel.add_function("bhp", my_polar, inputs, args={"p": fitted})
vessel.add_function("max_bhp", my_polar, inputs, args={"p": fitted})
vessel.add_function("sails_contribution", my_polar, inputs, args={"p": fitted}, output="sails")
```

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

**💡 Good practice**

- **Stay differentiable:** write with `architeuthis.numpy`, and use `np.where`, `np.softmax` or `np.sigmoid` rather than `if` on values.
- **Mind the units:** routing quantities are in kt and degrees, angles in absolute value. Forecast fields arrive as stored (m/s, K): convert them with `fac=` or a function.
- **Return components:** `(value, {"sails": ...})`, then pick one with `output=`.
- **Set a realistic `max_power` and `sfc`:** a huge power limit unsettles the solver, and the objective is zero without `sfc`.

The complete script is [`examples/function_polar_routing.py`](examples/function_polar_routing.py), and the [User Guide](docs/user_guide.md) has the details.

---

## 🔑 Credentials and Settings

### > What You Need to Set

Mostly nothing: IFS, GFS, HRDPS, ETOPO and the iceberg limit need no account. Each credential is needed only by its provider.

| What | For | How |
| --- | --- | --- |
| `CMEMS_USER`, `CMEMS_PWD` | Currents, `forecast.CopernicusForecast` | [Save them once](#-saving-your-credentials-once), [get them](#copernicus-marine-currents) |
| `CDS_API_KEY` | Reanalysis, `forecast.CDSForecast` | [Save it once](#-saving-your-credentials-once), [get it](#climate-data-store-era5) |
| `EUMDAC_KEY`, `EUMDAC_SECRET` | Satellite data, `satellite.ASCATData`, `satellite.PoseidonData` | [Save them once](#-saving-your-credentials-once), [get them](#eumetsat-satellite-observations) |
| `ARCHITEUTHIS_HOME` | Optional: keep downloads elsewhere than `~/data/` | [An environment variable](#-the-data-folder) |

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

Environment variables suit servers, CI jobs and containers, where there is no credential store, and override the store for a while. Give them as secrets of the platform; saved in a profile (`setx`, `~/.bashrc`, `conda env config vars`) they sit in plain text.

### > The Data Folder

Everything goes to `~/data/`:

| Folder | Holds |
| --- | --- |
| `topo/`, `cmems/`, `cds/`, `eumetsat/`, `iip/` | Downloads: relief, currents, reanalysis, satellite data, iceberg limit |
| `route_library/`, `route_sets/`, `passage_plans/`, `exclusion_zones/` | Your saved routes, plans and zones |
| `routes/` | Reports saved by `ReportCollection.save`, read by the viewer |

Set `ARCHITEUTHIS_HOME` to move it, then open a new terminal: `setx ARCHITEUTHIS_HOME "D:\architeuthis-data"` on Windows, `export ARCHITEUTHIS_HOME="$HOME/architeuthis-data"` in `~/.bashrc` elsewhere. Herbie keeps the GRIB files in its own `save_dir` (`~/.config/herbie/config.toml`).

### > Keeping Credentials Safe

- 🔒 **Never write a credential in code**, a notebook or a comment: a repository's history keeps it forever.
- **If one leaks,** change it at the provider, then `set` it again.
- **Coming from 0.2.0 or earlier?** Your environment variables still work. Move them to the store with `set`, check with `status`, then delete them and the `~/.cdsapirc` Architeuthis wrote.

### Copernicus Marine (currents)

Create a free account at [data.marine.copernicus.eu/register](https://data.marine.copernicus.eu/register), then save your username as `CMEMS_USER` and your password as `CMEMS_PWD`. To check them (prints `True`):

```python
import copernicusmarine
from architeuthis.credentials import get_credential

print(copernicusmarine.login(get_credential("CMEMS_USER"), get_credential("CMEMS_PWD"), check_credentials_valid=True))
```

### Climate Data Store (ERA5)

Create a free account at the [Climate Data Store](https://cds.climate.copernicus.eu/how-to-api), save the *Personal Access Token* of your profile as `CDS_API_KEY`, and accept the Terms of Use of each dataset you need, such as [ERA5 single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download). Architeuthis hands the token to the client and writes no file; without one, the client falls back to your own `~/.cdsapirc`:

```text
url: https://cds.climate.copernicus.eu/api
key: your-personal-access-token
```

### EUMETSAT (satellite observations)

Not your login: on the [API key page](https://api.eumetsat.int/api-key/) of a free EUMETSAT account, save your **Consumer Key** as `EUMDAC_KEY` and your **Consumer Secret** as `EUMDAC_SECRET`. To check them (prints an expiry date):

```python
import eumdac
from architeuthis.credentials import get_credential

print(eumdac.AccessToken((get_credential("EUMDAC_KEY"), get_credential("EUMDAC_SECRET"))).expiration)
```

---

### 🗺️ The Routing Problem

- **Objective:** total fuel, `sum((bhp + hotel_load) * dt * sfc) / 1e6`, in tonnes.
- **Fixed:** departure, arrival, ETD and ETA. The schedule is a requirement, the speed an outcome.
- **Variables:** the positions along the route, and optionally a factor blending the reference route towards two alternatives.
- **Constraints:** brake power below `max_power` and every position at sea, or your own.

---

### 🙏 Credits

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

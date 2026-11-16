<!-- Logo placeholder: add the file at media/logo-architeuthis-color.png -->
<img alt="Architeuthis logo" src="media/logo-architeuthis-color.png" width="100%">

<div align="center">

# Architeuthis: Weather Routing for Wind-powered Hybrid Vessels 🦑

**Minimize fuel on a fixed schedule, with real forecasts, constraints and custom vessel model.**

<!-- Badges -->

[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/architeuthis)](https://pypi.org/project/architeuthis/)
[![PyPI](https://img.shields.io/pypi/v/architeuthis.svg)](https://pypi.org/project/architeuthis/)
[![Tests](https://github.com/julesricheux/Architeuthis/actions/workflows/tests.yml/badge.svg?branch=develop)](https://github.com/julesricheux/Architeuthis/actions/workflows/tests.yml)
[![Downloads](https://static.pepy.tech/badge/architeuthis)](https://pepy.tech/projects/architeuthis)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

## 📚 [User Guide](docs/user_guide.md) | ❔ [Issues](https://github.com/julesricheux/Architeuthis/issues)

<!-- (Badges) -->

</div>

---

## What is Architeuthis?

An open-source marine weather and decision-making framework for hybrid sailing ships. It couples mesh-free, fully differentiable methods in a unified optimization environment to compute optimal routes under real-world constraints.

"Mesh-free" means that routes are not searched on a graph. The waypoints are continuous variables of a single nonlinear program, and weather, bathymetry and vessel performance are differentiable tables queried at those waypoints. [CasADi](https://github.com/casadi/casadi) differentiates through everything and [IPOPT](https://github.com/coin-or/Ipopt) solves the problem.

**Key Features:**
- ⛽ **Fuel-optimal routes** - Minimize the fuel of a voyage with a fixed departure and arrival time
- 🚢 **Motor and hybrid vessels** - Bring your vessel as a performance table, with or without sails
- 🌊 **Wind, waves and currents** - Ready-made IFS, GFS, ensemble and Mercator sources
- 🧊 **Real-world constraints** - Land, shallow water, exclusion zones, the iceberg limit, maximum power and your own constraints
- 🎲 **Forecast uncertainty** - Optimize each ensemble member, and test a plan against other models, members or vessels
- 📊 **Ready-to-use outputs** - A4 reports, maps, tables, GPX tracks and an interactive viewer

**Keywords:** weather routing, voyage optimization, fuel saving, wind-assisted ship propulsion, hybrid vessel, passage planning, nonlinear optimization, CasADi, IPOPT, GRIB2, xarray, python

**Architeuthis** is the tool used for the **onshore weather routing support** for [Neoliner Origin](https://www.neoline.eu/) 🌬️⛵⚓

---

## 🚀 Quick Start

### ⚙️ Installation

Architeuthis needs Python 3.11 or later.

**With pip:**
```bash
pip install architeuthis
```

Add the interactive viewer with:
```bash
pip install "architeuthis[app]"
```

**From source, with conda:**
```bash
git clone https://github.com/julesricheux/Architeuthis.git
```
```bash
cd Architeuthis
```
```bash
conda env create -f environment.yaml
```

The environment is named `py313-architeuthis`. The package then needs no installation: run everything from the repository root.

### 💡 Simple Example

This example routes a vessel across the North Atlantic with recent ECMWF forecasts. It needs no credentials, only a polar file for your vessel (see [Your Vessel](#-your-vessel)).

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

# Yesterday's 00 UTC forecast, with its lead times in hours
today = pd.Timestamp("now").floor("1d")
date = today - pd.Timedelta(days=1)
steps = list(range(0, 145, 3)) + list(range(150, 241, 6))

atmosphere = DeterministicHerbieForecast("wind", model="ifs", product="oper", regex=r":10[u|v]:", fxx=steps, date=date, **domain)
atmosphere.load_data()
atmosphere.add_interpolator("u10", "valid_time", "latitude", "longitude")
atmosphere.add_interpolator("v10", "valid_time", "latitude", "longitude")

wave = DeterministicHerbieForecast("wave", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=steps, date=date, **domain)
wave.load_data()
wave.add_wave_components()  # the direction is interpolated through its components
wave.add_interpolator("swh", "valid_time", "latitude", "longitude")
wave.add_interpolator("uw", "valid_time", "latitude", "longitude")
wave.add_interpolator("vw", "valid_time", "latitude", "longitude")

# Calm water on the grid of the wind. For real currents, see CopernicusForecast in examples/post_leg_rewind.py
calm = xr.zeros_like(atmosphere.data["u10"])
current = Forecast("calm_current", date=None, fxx=None, **domain)
current.data = xr.Dataset({"uo": calm, "vo": calm})
current.add_interpolator("uo", "valid_time", "latitude", "longitude")
current.add_interpolator("vo", "valid_time", "latitude", "longitude")

topography = Topography("topography", **domain)
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

# Specific fuel consumption in g/kWh, loads and power in kW
vessel = Vessel("vessel", filepath="my_vessel_polar.nc", sfc=220., hotel_load=194., max_power=4100.)
vessel.load_data()
for key in ("bhp", "max_bhp", "sails_contribution"):
    vessel.add_interpolator(key, "stw", "tws", "twa", "hs", "wa", method="linear")

# The reference route and the schedule, in UTC
route = Route("crossing", [Waypoint(47.725, -4.380, "Penmarch"), Waypoint(46.551, -53.321, "Cape Race")])
voyage = Voyage("crossing", etd=today, eta=today + pd.Timedelta(days=8), route=route)

# Optimize
analysis = RoutingAnalysis("crossing", vessel, voyage, atmosphere, wave, current, topography)
report = analysis.run()

# Results
reports = ReportCollection([report])
print(reports.summary())
reports.to_gpx()     # a track for your navigation system
reports.save()       # for the viewer
plot_report(report)  # one A4 page: speed, sails, power, waves and wind against time
```

---

## 🚢 Your Vessel

Architeuthis does not include a vessel model. You provide a NetCDF performance table, which can come from a velocity prediction program, sea trials or a simpler model. A motor vessel and a hybrid vessel only differ by the content of this table: for a motor vessel, `sails_contribution` is zero.

| Variable | Meaning | Unit |
| --- | --- | --- |
| `bhp` | Average brake power | kW |
| `max_bhp` | Brake power with load fluctuations, checked against `max_power` | kW |
| `sails_contribution` | Share of the propulsion from sails, for the reports | % |

Each variable has the five dimensions below, in this order:

| Dimension | Meaning | Unit |
| --- | --- | --- |
| `stw` | Speed through water | kt |
| `tws` | True wind speed | kt |
| `twa` | True wind angle, 0 to 180 | deg |
| `hs` | Significant wave height | m |
| `wa` | Wave angle, 0 to 180 | deg |

`sfc` and `hotel_load` are given to `Vessel` as constants or as functions of the power, and `sfc` must be set because the objective is zero without it. A polar named `..._eff45.nc` gets the label `eff45` in reports, or you can give any `label`.

---

## 🔑 Credentials and Settings

### > What You Need to Set

Most of Architeuthis needs no setting at all. The table lists everything you may have to set yourself, and when:

| What | When you need it | How |
| --- | --- | --- |
| `CMEMS_USER`, `CMEMS_PWD` | Currents, with `forecast.CopernicusForecast` | [Save them once](#-saving-your-credentials-once), see [Copernicus Marine](#copernicus-marine-currents) |
| `CDS_API_KEY` | Reanalysis, with `forecast.CDSForecast` | [Save it once](#-saving-your-credentials-once), see [Climate Data Store](#climate-data-store-era5) |
| `EUMDAC_KEY`, `EUMDAC_SECRET` | Satellite observations, with `satellite.ASCATData` or `satellite.PoseidonData` | [Save them once](#-saving-your-credentials-once), see [EUMETSAT](#eumetsat-satellite-observations) |
| `ARCHITEUTHIS_HOME` | Optional: to keep downloads and results somewhere else than `~/data/` | [An environment variable](#-the-data-folder) |

IFS, GFS, HRDPS, ETOPO and the iceberg limit need no account. Each credential is needed only by its provider, so you can start without any.

Everything else is fixed by the package and is not meant to be changed: the version, the provider addresses, and the folders inside the data folder.

### > Saving Your Credentials Once

1. Create your account with each provider you need, as explained [below](#copernicus-marine-currents).
2. Open a terminal where Architeuthis is installed: activate its environment (`conda activate py313-architeuthis`). If you work from the source without installing it, go to the root of the repository.
3. Run this command with the names you need. It asks for each value, hidden when it is secret, so the value never appears on the screen or in the history of the terminal:
```bash
python -m architeuthis.credentials set CMEMS_USER CMEMS_PWD
```
4. Check what Architeuthis finds, without showing any value:
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

That is all. Architeuthis now finds them in every session, in Spyder, a notebook or a script, with nothing to set in your code and nothing to restart. They stay on your computer, encrypted by your operating system, under the name `architeuthis`: in the *Windows Credential Manager*, the *macOS Keychain*, or the *Secret Service* of your Linux desktop (GNOME Keyring, KWallet). This goes through the [keyring](https://pypi.org/project/keyring/) package, installed with Architeuthis.

**To change a credential,** for a new password for example, run `set` again with its name. **To remove one:**
```bash
python -m architeuthis.credentials delete CMEMS_PWD
```

The same is possible from Python, in Spyder for example:
```python
from architeuthis.credentials import credential_sources, save_credential

save_credential("CMEMS_PWD")  # asks for it, hidden
print(credential_sources())   # where each one is found, without its value
```

**If a credential is missing,** the download stops before it starts, with a ⚠️ message and a `MissingCredentialError` that names it and gives the command that saves it.

### > Where Architeuthis Looks

Credentials are read when a download needs them, never when Architeuthis is imported. For each one, Architeuthis takes the first value found:

1. **An environment variable** of the same name, such as `CMEMS_PWD`. The variables of the providers' own clients are read too: `CDSAPI_KEY`, `COPERNICUSMARINE_SERVICE_USERNAME` and `COPERNICUSMARINE_SERVICE_PASSWORD`, and `EUMDAC_USER` and `EUMDAC_PWD`, the former names of `EUMDAC_KEY` and `EUMDAC_SECRET`.
2. **The credential store**, where `set` saves them.
3. **The provider's own file**, for Copernicus Marine and the Climate Data Store only, if neither of the above has the credentials: the file of `copernicusmarine login`, or `~/.cdsapirc`.

### > Environment Variables

Saving credentials once is the recommended way. Use environment variables where there is no credential store, on a CI job, a container or a Linux server, or to use another account for a while: a variable takes precedence over the saved credential.

For the current Python session only, which works even after Architeuthis is imported:
```python
import os
from getpass import getpass

os.environ["CMEMS_PWD"] = getpass("Copernicus Marine password: ")
```

On a server or a CI job, give them as secrets of the platform, such as GitHub Actions secrets or Docker secrets. Saved in your user profile, with `setx` on Windows, `export` in `~/.bashrc` or `conda env config vars set`, they work too, but they are stored there in plain text.

### > The Data Folder

Downloads, libraries and reports are kept in `~/data/`, the `data` folder of your home directory:

| Folder | Holds |
| --- | --- |
| `topo/`, `cmems/`, `cds/`, `eumetsat/`, `iip/` | Downloads: relief, currents, reanalysis, satellite data and the iceberg limit |
| `route_library/`, `route_sets/`, `passage_plans/`, `exclusion_zones/` | Your saved routes, passage plans and zones |
| `routes/` | Reports saved by `ReportCollection.save`, read by the viewer |

To keep them elsewhere, on a larger disk for example, set `ARCHITEUTHIS_HOME` to that folder. It is read when Architeuthis is imported, so set it for good, then open a new terminal or restart Spyder.

**Windows,** in PowerShell:
```powershell
setx ARCHITEUTHIS_HOME "D:\architeuthis-data"
```

**Linux and macOS,** in `~/.bashrc` or `~/.zshrc`:
```bash
export ARCHITEUTHIS_HOME="$HOME/architeuthis-data"
```

The GRIB files of IFS, GFS and HRDPS are kept by Herbie in its own folder, set by `save_dir` in `~/.config/herbie/config.toml` and also `~/data/` by default. `ARCHITEUTHIS_HOME` does not move them.

### > Keeping Credentials Safe

- 🔒 **Never write a credential in your code**, a notebook or a comment. Anything committed to a repository stays in its history, even after it is removed from the files, and a public repository exposes it to everyone.
- **Prefer `set` to `setx`, `~/.bashrc` or `conda env config vars`,** which store values in plain text.
- **If a credential leaks,** change it at the provider right away, then run `set` again.
- **Coming from version 0.2.0 or earlier,** which read environment variables only: they still work. To secure them, run `set` for each one, check with `status`, then delete the variables and the `~/.cdsapirc` that Architeuthis wrote.

### Copernicus Marine (currents)

1. Create a free account at [data.marine.copernicus.eu/register](https://data.marine.copernicus.eu/register).
2. Save your username as `CMEMS_USER` and your password as `CMEMS_PWD`.
3. Check them, which prints `True` if they are valid:
```python
import copernicusmarine

from architeuthis.credentials import get_credential

print(copernicusmarine.login(get_credential("CMEMS_USER"), get_credential("CMEMS_PWD"), check_credentials_valid=True))
```

If you already stored your credentials with `copernicusmarine login`, Architeuthis lets the toolbox use them when it finds none of its own. That file is in plain text, in `~/.copernicusmarine/`, so prefer `set`.

### Climate Data Store (ERA5)

1. Create a free account at the [Climate Data Store](https://cds.climate.copernicus.eu/how-to-api).
2. Copy your *Personal Access Token* from your profile page, and save it as `CDS_API_KEY`.
3. Open the page of each dataset you need, such as [ERA5 single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download), and accept its Terms of Use. Downloads are refused until you do.

Architeuthis gives the token to the CDS client directly and writes no file. If it finds none, the client reads its own `~/.cdsapirc` if you have one, a plain text file like this one:
```text
url: https://cds.climate.copernicus.eu/api
key: your-personal-access-token
```

### EUMETSAT (satellite observations)

These two credentials are **not** your login and password:

1. Create a free EUMETSAT account and open the [API key page](https://api.eumetsat.int/api-key/).
2. Save your **Consumer Key** as `EUMDAC_KEY` and your **Consumer Secret** as `EUMDAC_SECRET`.
3. Check them, which prints an expiry date, or `401 Unauthorized` if they are wrong:
```python
import eumdac

from architeuthis.credentials import get_credential

print(eumdac.AccessToken((get_credential("EUMDAC_KEY"), get_credential("EUMDAC_SECRET"))).expiration)
```

`eumdac set-credentials` configures the `eumdac` command only, so Architeuthis still needs its own.

---

### 🗺️ The Routing Problem

- **Objective:** total fuel, `sum((bhp + hotel_load) * dt * sfc) / 1e6`, in tonnes.
- **Fixed:** departure and arrival, ETD and ETA. The schedule is a requirement and the speed is an outcome.
- **Variables:** the positions along the route, and optionally a factor that blends the reference route towards two alternatives.
- **Constraints:** by default, brake power below `max_power` and every position in navigable water. Your own constraints can replace them.

---

### 🙏 Credits

Architeuthis stands on the work of others, with our thanks:

- **[AeroSandbox](https://github.com/peterdsharpe/AeroSandbox)** by Peter D. Sharpe (MIT). The `numpy`, `optimization` and `modeling` packages are adapted from version 4.2.9 ([license](https://github.com/peterdsharpe/AeroSandbox/blob/master/LICENSE.txt)).
- **[Herbie](https://github.com/blaylockbk/Herbie)** by Brian K. Blaylock (MIT) downloads the forecasts, and its README inspired the structure of this one.
- **[CasADi](https://github.com/casadi/casadi)** (LGPL) and **[IPOPT](https://github.com/coin-or/Ipopt)** (EPL) differentiate and solve the routing problem.
- **[Copernicus Marine Toolbox](https://github.com/mercator-ocean/copernicus-marine-toolbox)**, **[xarray](https://github.com/pydata/xarray)**, **[Cartopy](https://github.com/SciTools/cartopy)**, **[Dash](https://github.com/plotly/dash)** and the other dependencies listed in [`pyproject.toml`](pyproject.toml).
- The forecast, ocean, relief and ice data of their providers.

## Contributing

Please report bugs or suggest features via [issues](https://github.com/julesricheux/Architeuthis/issues) and **star this repository!** ⭐

## ⚖️ License

[GNU General Public License v3.0](LICENSE).

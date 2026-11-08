<!-- Logo placeholder: add the file at media/logo-architeuthis-color.png -->
<img alt="Architeuthis logo" src="media/logo-architeuthis-color.png" width="100%">

<div align="center">

# Architeuthis: Weather Routing for Wind-powered Hybrid Vessels 🦑

**Minimize fuel on a fixed schedule, with real forecasts and your own vessel model.**

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

**Keywords:** weather routing, voyage optimization, fuel saving, wind-assisted ship propulsion, hybrid vessel, passage planning, nonlinear programming, CasADi, IPOPT, GRIB2, xarray, python

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

This example routes a vessel across the North Atlantic with recent ECMWF forecasts. It needs no credentials, only a polar file for your vessel (see [Your Vessel](#your-vessel)).

```python
import pandas as pd

from architeuthis import presets
from architeuthis.common import Domain
from architeuthis.core import RoutingAnalysis
from architeuthis.report import ReportCollection
from architeuthis.route import Route, Waypoint
from architeuthis.toolbox.plot_utils import plot_report
from architeuthis.voyage import Voyage

domain = Domain(min_lon=-60., max_lon=0., min_lat=38., max_lat=56.)

# Yesterday's 00 UTC forecast, with its lead times in hours
today = pd.Timestamp("now").floor("1d")
date = today - pd.Timedelta(days=1)
steps = list(range(0, 145, 3)) + list(range(150, 241, 6))

atmosphere = presets.atmosphere("ifs", domain, date=date, fxx=steps)
wave = presets.wave("ifs", domain, date=date, fxx=steps)
current = presets.calm_current(atmosphere)  # presets.current_mercator needs a Copernicus Marine account
topography = presets.topography(domain)

# Specific fuel consumption in g/kWh, loads and power in kW
vessel = presets.vessel("my_vessel_polar.nc", sfc=220., hotel_load=194., max_power=4100.)

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

Architeuthis is the tool used for the onshore weather routing support for [Neoliner Origin](https://www.neoline.eu/)

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

`sfc` and `hotel_load` are given to `presets.vessel` as constants or as functions of the power, and `sfc` must be set because the objective is zero without it. A polar named `..._eff45.nc` gets the label `eff45` in reports, or you can give any `label`.

---

## 🔑 Credentials

IFS, GFS, HRDPS, ETOPO and the iceberg limit need no account. The other providers are free but need one, and only when you use them:

| You want | Provider | Environment variables |
| --- | --- | --- |
| Currents, `presets.current_mercator()` | [Copernicus Marine](#copernicus-marine-currents) | `CMEMS_USER`, `CMEMS_PWD` |
| Reanalysis, `forecast.CDSForecast` | [Climate Data Store](#climate-data-store-era5) | `CDS_API_KEY` |
| Satellite observations, `satellite.ASCATData`, `satellite.PoseidonData` | [EUMETSAT](#eumetsat-satellite-observations) | `EUMDAC_USER`, `EUMDAC_PWD` |

### > Setting an Environment Variable

Architeuthis reads these variables **when it is imported**, so set them first, then open a new terminal or restart Spyder. The examples below use `CMEMS_USER`: do the same for each variable.

**Windows:** search for *Edit environment variables for your account* in the Start menu, then choose *New*. Or, in PowerShell:
```powershell
setx CMEMS_USER "your-username"
```

**Linux and macOS:** add this line to `~/.bashrc` or `~/.zshrc`:
```bash
export CMEMS_USER="your-username"
```

**In a conda environment,** so that the values only apply there, then activate the environment again:
```bash
conda env config vars set CMEMS_USER="your-username" -n py313-architeuthis
```

**For one session only,** before any Architeuthis import:
```python
import os
from getpass import getpass

os.environ["CMEMS_USER"] = "your-username"
os.environ["CMEMS_PWD"] = getpass("Copernicus Marine password: ")

from architeuthis import presets
```

To check which variables Python can see, without showing their values:
```python
import os

for name in ("CMEMS_USER", "CMEMS_PWD", "CDS_API_KEY", "EUMDAC_USER", "EUMDAC_PWD"):
    print(name, "is set" if os.environ.get(name) else "is missing")
```

> 🔒 **Keep credentials out of your code.** Anything committed to a repository stays in its history, even after it is removed from the files, and a public repository exposes it to everyone. These methods store values in plain text in your user profile, so keep them out of shared machines and shared folders. If a credential leaks, change it at the provider right away. A value typed in a command also stays in the shell history.

### Copernicus Marine (currents)

1. Create a free account at [data.marine.copernicus.eu/register](https://data.marine.copernicus.eu/register).
2. Set `CMEMS_USER` to your username and `CMEMS_PWD` to your password.
3. Check them, which prints `True` if they are valid:
```python
import os

import copernicusmarine

print(copernicusmarine.login(os.environ["CMEMS_USER"], os.environ["CMEMS_PWD"], check_credentials_valid=True))
```

If you prefer, leave the variables unset and store your credentials once with `copernicusmarine login`. The toolbox then finds them in `~/.copernicusmarine/`. The startup log still says that they are incomplete, which you can ignore.

### Climate Data Store (ERA5)

1. Create a free account at the [Climate Data Store](https://cds.climate.copernicus.eu/how-to-api).
2. Copy your *Personal Access Token* from your profile page, and set `CDS_API_KEY` to it.
3. Open the page of each dataset you need, such as [ERA5 single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download), and accept its Terms of Use. Downloads are refused until you do.

At its first download, Architeuthis writes the token to `~/.cdsapirc` and uses this file from then on. **If you change your token, update or delete this file**, because a new `CDS_API_KEY` does not replace it. You can also write the file yourself and leave the variable unset:
```text
url: https://cds.climate.copernicus.eu/api
key: your-personal-access-token
```

### EUMETSAT (satellite observations)

Despite their names, these two variables do **not** take your login and password:

1. Create a free EUMETSAT account and open the [API key page](https://api.eumetsat.int/api-key/).
2. Set `EUMDAC_USER` to your **Consumer Key** and `EUMDAC_PWD` to your **Consumer Secret**.
3. Check them, which prints an expiry date, or `401 Unauthorized` if they are wrong:
```python
import os

import eumdac

print(eumdac.AccessToken((os.environ["EUMDAC_USER"], os.environ["EUMDAC_PWD"])).expiration)
```

`eumdac set-credentials` configures the `eumdac` command only, so Architeuthis still needs the variables.

---

### 🗺️ The Routing Problem

- **Objective:** total fuel, `sum((bhp + hotel_load) * dt * sfc) / 1e6`, in tonnes.
- **Fixed:** departure and arrival, ETD and ETA. The schedule is a requirement and the speed is an outcome.
- **Variables:** the positions along the route, and optionally a factor that blends the reference route towards two alternatives.
- **Constraints:** by default, brake power below `max_power` and every position in navigable water. Your own constraints can replace them.

---

### 🙏 Credits

Architeuthis stands on the work of others, with our thanks:

- **[AeroSandbox](https://github.com/peterdsharpe/AeroSandbox)** by Peter D. Sharpe (MIT). The `numpy`, `optimization` and `modeling` packages are adapted from version 4.2.9.
- **[Herbie](https://github.com/blaylockbk/Herbie)** by Brian K. Blaylock (MIT) downloads the forecasts, and its README inspired the structure of this one.
- **[CasADi](https://github.com/casadi/casadi)** (LGPL) and **[IPOPT](https://github.com/coin-or/Ipopt)** (EPL) differentiate and solve the routing problem.
- **[Copernicus Marine Toolbox](https://github.com/mercator-ocean/copernicus-marine-toolbox)**, **[xarray](https://github.com/pydata/xarray)**, **[Cartopy](https://github.com/SciTools/cartopy)**, **[Dash](https://github.com/plotly/dash)** and the other dependencies listed in [`pyproject.toml`](pyproject.toml).
- The forecast, ocean, relief and ice data of the providers listed under [Supported Data Sources](#supported-data-sources).

## Contributing

Please report bugs or suggest features via [issues](https://github.com/julesricheux/Architeuthis/issues) and **star this repository!** ⭐

## ⚖️ License

[MIT](LICENSE).

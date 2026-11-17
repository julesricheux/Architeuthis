# -*- coding: utf-8 -*-
"""
Sky along a route: the cloud genera diagnosed from forecast fields.

Nine fields of a weather model describe the sky well enough to tell
apart the ten genera of the WMO International Cloud Atlas, stored in
`architeuthis/data/cloud_genera.json`: the total, low, middle and high
cloud covers, the CAPE, the precipitation rate, the 2 m temperature
and dewpoint, and the temperature at 700 hPa. `SKY_FIELDS` gives their
names in IFS and GFS, `IFS_SKY_REGEX` and `GFS_SKY_REGEX` select them
with Herbie.

`diagnose` gives, for each point, the cover in oktas, the cloud base,
and one genus per étage as an observer on deck would code it, hidden
when the clouds below cover the sky. `describe` writes one line per
point for the crew. Both work on plain NumPy values, after a routing
or without one, and never run symbolically.

The rules are simple thresholds, to be calibrated against observations
(`THRESHOLDS`). Cirrocumulus is never diagnosed, since it would need
fields of the upper air: it is reported as Cirrus.

Created on Tue Nov 17 2026

@author: jrich
"""

import copy
import json
from functools import lru_cache
from importlib import resources
from typing import Mapping, Optional

import numpy as onp

# Keys of the fields, as the forecasts register them and `diagnose` reads them.
SKY_VARIABLES = ("tcc", "lcc", "mcc", "hcc", "cape", "prate", "t2m", "d2m", "t700")

# Per model: key > (name of the variable read by cfgrib, factor to the
# units of `diagnose`: covers in 0-1, CAPE in J/kg, rate in mm/h, K).
SKY_FIELDS = {
    "ifs": {
        "tcc": ("tcc", 1.0),
        "lcc": ("lcc", 1.0),
        "mcc": ("mcc", 1.0),
        "hcc": ("hcc", 1.0),
        "cape": ("mucape", 1.0),
        "prate": ("tprate", 3600.0),  # kg m-2 s-1 > mm/h
        "t2m": ("t2m", 1.0),
        "d2m": ("d2m", 1.0),
        "t700": ("t", 1.0),
    },
    "gfs": {
        "tcc": ("tcc", 0.01),  # % > fraction
        "lcc": ("lcc", 0.01),
        "mcc": ("mcc", 0.01),
        "hcc": ("hcc", 0.01),
        "cape": ("cape", 1.0),
        "prate": ("prate", 3600.0),
        "t2m": ("t2m", 1.0),
        "d2m": ("d2m", 1.0),
        "t700": ("t", 1.0),
    },
}

# Herbie searches of the nine fields. IFS open data: surface fields and
# t at 700 hPa. GFS: instantaneous covers and rate only (`hour fcst` at
# the end, not the `hour ave fcst` averages that cfgrib would give the
# same names), CAPE of the lowest 255 hPa, the closest to the IFS
# most-unstable CAPE. GFS has no middle and high covers at step 0: start
# its steps at 3 h.
IFS_SKY_REGEX = r":(?:tcc|lcc|mcc|hcc|mucape|tprate|2t|2d):sfc:|:t:700:pl:"
GFS_SKY_REGEX = (
    r":(?:TCDC:entire atmosphere|LCDC:low cloud layer|MCDC:middle cloud layer"
    r"|HCDC:high cloud layer|PRATE:surface):\d+ hour fcst$"
    r"|:CAPE:255-0 mb above ground:|:(?:TMP|DPT):2 m above ground:|:TMP:700 mb:"
)

# Thresholds of the rules: covers in 0-1, CAPE in J/kg, rates in mm/h,
# temperatures in K. Starting values, to calibrate.
THRESHOLDS = {
    "low_cover": 0.1,  # least low cover for a low genus
    "middle_cover": 0.1,
    "high_cover": 0.05,
    "cb_cape": 1000.0,  # Cb: CAPE and rate...
    "cb_rate": 2.0,
    "cb_strong_cape": 2000.0,  # ...or a stronger CAPE and a lighter rate
    "cb_strong_rate": 0.5,
    "cu_max_cover": 0.7,  # Cu: broken low cover and unstable air
    "cu_cape": 100.0,
    "cu_stability": 14.0,  # lower-tropospheric stability below this
    "st_cover": 0.6,  # St: near-saturated air under a low layer
    "st_spread": 1.5,
    "fog_cover": 0.9,
    "fog_spread": 0.5,
    "thick_middle_cover": 0.8,  # As or Ns rather than Ac
    "ns_low_cover": 0.5,
    "ns_rate": 1.0,
    "cs_cover": 0.7,  # Cs rather than Ci
    "ci_max_cover": 0.9,  # Ci still seen beside Cs below this cover
    "visible_cover": 0.1,  # least open sky below an étage, else hidden
    "rain_rate": 0.1,  # least rate worth reporting
    "moderate_rate": 2.5,
    "heavy_rate": 7.6,
    "snow_temperature": 274.15,  # 2 m temperature below which it snows
}

NONE = -1  # no cloud of this étage
HIDDEN = -2  # clouds hidden by those below

ETAGES = ("low", "middle", "high")

# Height of the cloud base per kelvin of 2 m dewpoint spread (m/K).
LCL_METERS_PER_KELVIN = 125.0
# R/cp of dry air, for the potential temperature.
KAPPA = 0.2857


@lru_cache(maxsize=1)
def _genera_table() -> dict:
    with (resources.files("architeuthis") / "data" / "cloud_genera.json").open(encoding="utf-8") as stream:
        return json.load(stream)


def load_genera() -> dict:
    """
    Read the table of the ten WMO cloud genera.

    Returns:
        A copy of `architeuthis/data/cloud_genera.json`: its `etages`,
        heights of the three étages, and its `genera`, in the order of
        the Atlas, whose position is the index used by `diagnose`.

    Example:
        >>> load_genera()["genera"][6]["abbreviation"]
        'Sc'
    """
    return copy.deepcopy(_genera_table())


def genus_index(abbreviation: str) -> int:
    """
    Position of a genus in the table, as `diagnose` codes it.

    Args:
        abbreviation: Abbreviation of the genus, such as "Sc".

    Returns:
        Its index in `load_genera()["genera"]`.

    Example:
        >>> genus_index("Cb")
        9
    """
    for index, genus in enumerate(_genera_table()["genera"]):
        if genus["abbreviation"] == abbreviation:
            return index
    raise KeyError(f"No cloud genus abbreviated {abbreviation!r}.")


def genus_abbreviation(index: int) -> str:
    """
    Abbreviation of a genus coded by `diagnose`.

    Args:
        index: Index in the table, or `NONE` or `HIDDEN`.

    Returns:
        The abbreviation, "" for `NONE` and "/" for `HIDDEN`, as in the
        WMO codes.
    """
    if index == NONE:
        return ""
    if index == HIDDEN:
        return "/"
    return _genera_table()["genera"][int(index)]["abbreviation"]


def genera_present(mask: int, main: Optional[int] = None) -> list:
    """
    Genera of a bit mask of `diagnose`, the main one first.

    Args:
        mask: Value of `cloud_low_genera`, `cloud_middle_genera` or
            `cloud_high_genera` at one point.
        main: Main genus of the étage at that point, put first when it
            is present.

    Returns:
        The indices of the genera, in the order of the table after the
        main one.

    Example:
        >>> mask = 1 << genus_index("Cu") | 1 << genus_index("Cb")
        >>> genera_present(mask, main=genus_index("Cb"))
        [9, 8]
    """
    mask = int(mask)
    indices = [index for index in range(len(_genera_table()["genera"])) if mask >> index & 1]
    if main is not None and int(main) in indices:
        indices.remove(int(main))
        indices.insert(0, int(main))
    return indices


def add_sky_models(forecast, model: Optional[str] = None) -> None:
    """
    Register the nine fields of `diagnose` on a loaded forecast.

    Each field gets its key of `SKY_VARIABLES` and the units of
    `diagnose`, whatever its name and units in the model. Linear
    interpolation keeps the covers within 0 and 1.

    Args:
        forecast: Loaded deterministic forecast, downloaded with
            `IFS_SKY_REGEX` or `GFS_SKY_REGEX`.
        model: "ifs" or "gfs", by default the model of the forecast.

    Example:
        >>> add_sky_models(forecast)  # doctest: +SKIP
        >>> forecast("lcc", {"valid_time": t, "latitude": 47.0,
        ...                  "longitude": -10.0})  # doctest: +SKIP
    """
    model = (model or forecast.model).lower()
    if model not in SKY_FIELDS:
        raise ValueError(f"No sky fields known for the model {model!r}: give one of {sorted(SKY_FIELDS)}.")
    for key, (var_dim, fac) in SKY_FIELDS[model].items():
        forecast.add_interpolator(
            var_dim,
            "valid_time",
            "latitude",
            "longitude",
            var_key=key,
            method="linear",
            fac=fac,
        )


def sample(forecast, valid_time, latitude, longitude) -> dict:
    """
    Read the nine fields of `diagnose` at given times and positions.

    Args:
        forecast: Forecast holding the models of `add_sky_models`.
        valid_time: Times in epoch seconds.
        latitude: Latitudes in degrees.
        longitude: Longitudes in degrees.

    Returns:
        A dict of NumPy arrays keyed by `SKY_VARIABLES`.
    """
    query = {"valid_time": valid_time, "latitude": latitude, "longitude": longitude}
    return {key: onp.asarray(forecast(key, query), dtype=float).ravel() for key in SKY_VARIABLES}


def lower_tropospheric_stability(t2m, t700):
    """
    Potential temperature at 700 hPa minus that of the surface air.

    The 2 m temperature stands in for the potential temperature of the
    surface, at about 1000 hPa over the sea. Above some 16 K, a marine
    layer of Sc or St caps the air; below some 14 K, Cu develop.

    Args:
        t2m: 2 m temperature (K).
        t700: Temperature at 700 hPa (K).

    Returns:
        The stability (K).
    """
    return onp.asarray(t700, dtype=float) * (1000.0 / 700.0) ** KAPPA - onp.asarray(t2m, dtype=float)


def condensation_height(t2m, d2m):
    """
    Height of the base of clouds formed by rising surface air.

    Uses the usual 125 m per kelvin of dewpoint spread, an estimate of
    the lifting condensation level.

    Args:
        t2m: 2 m temperature (K).
        d2m: 2 m dewpoint (K).

    Returns:
        The height (m), never below 0.
    """
    spread = onp.asarray(t2m, dtype=float) - onp.asarray(d2m, dtype=float)
    return LCL_METERS_PER_KELVIN * onp.maximum(spread, 0.0)


def diagnose(
    fields: Mapping,
    thresholds: Optional[Mapping] = None,
) -> dict:
    """
    Diagnose the sky from the nine fields of `SKY_VARIABLES`.

    One genus per étage, the first that applies in the priority order
    below; an étage is `HIDDEN` where the étages below leave at most
    `visible_cover` of the sky open:

    - Low: Cb (strong CAPE and rate), St (low cover over air near its
      dewpoint), Cu (broken cover in unstable air), else Sc.
    - Middle: Ns (thick middle and low covers, steady rain and weak
      CAPE), As (thick middle cover), else Ac.
    - High: Cs (wide cover), else Ci.

    Every genus present in the column is also given per étage, as a
    bit mask over the table, whether hidden from deck or not: Cu around
    a Cb or beside Sc, Sc beside St, Ac beside As, Ci beside Cs or from
    the anvil of a Cb. `genera_present` reads it.

    Args:
        fields: Mapping of scalars or arrays keyed by `SKY_VARIABLES`,
            in the units of `add_sky_models`: a routing report with
            these variables, or the result of `sample`.
        thresholds: Values replacing some of `THRESHOLDS`.

    Returns:
        A dict of arrays of the shape of the fields:
        `cloud_oktas` (0 to 8, 9 for a sky hidden by fog),
        `cloud_base` (m, NaN without clouds), `cloud_low`,
        `cloud_middle` and `cloud_high` (index of `load_genera()`,
        `NONE` or `HIDDEN`), `cloud_low_genera`,
        `cloud_middle_genera` and `cloud_high_genera` (bit masks of
        every genus present), `fog` (bool) and `stability` (K).

    Example:
        >>> sky = diagnose(report)  # doctest: +SKIP
        >>> report.update(sky)  # doctest: +SKIP
    """
    missing = [key for key in SKY_VARIABLES if key not in fields]
    if missing:
        raise KeyError(f"The sky needs the fields {missing}: register them with add_sky_models.")
    limits = THRESHOLDS | dict(thresholds or {})

    values = {key: onp.asarray(fields[key], dtype=float) for key in SKY_VARIABLES}
    tcc, lcc, mcc, hcc = (onp.clip(values[key], 0.0, 1.0) for key in ("tcc", "lcc", "mcc", "hcc"))
    cape = onp.maximum(values["cape"], 0.0)
    rate = onp.maximum(values["prate"], 0.0)
    t2m, d2m = values["t2m"], values["d2m"]
    spread = t2m - d2m
    stability = lower_tropospheric_stability(t2m, values["t700"])

    cumulonimbus = (
        ((cape > limits["cb_cape"]) & (rate > limits["cb_rate"]))
        | ((cape > limits["cb_strong_cape"]) & (rate > limits["cb_strong_rate"]))
    )
    low_clouds = lcc >= limits["low_cover"]
    low = onp.select(
        [
            cumulonimbus,
            low_clouds & (lcc > limits["st_cover"]) & (spread < limits["st_spread"]),
            low_clouds
            & (lcc <= limits["cu_max_cover"])
            & ((cape > limits["cu_cape"]) | (stability < limits["cu_stability"])),
            low_clouds,
        ],
        [genus_index("Cb"), genus_index("St"), genus_index("Cu"), genus_index("Sc")],
        default=NONE,
    )

    thick_middle = mcc > limits["thick_middle_cover"]
    middle = onp.select(
        [
            thick_middle
            & (lcc > limits["ns_low_cover"])
            & (rate > limits["ns_rate"])
            & (cape <= limits["cb_cape"]),
            thick_middle,
            mcc >= limits["middle_cover"],
        ],
        [genus_index("Ns"), genus_index("As"), genus_index("Ac")],
        default=NONE,
    )

    high = onp.select(
        [hcc > limits["cs_cover"], hcc >= limits["high_cover"]],
        [genus_index("Cs"), genus_index("Ci")],
        default=NONE,
    )

    # Every genus present in the column, the main one included, as a
    # bit mask over the table: Cu around a Cb, Sc beside Cu or St, Ac
    # beside As, Ci beside Cs or from the anvil of a Cb.
    unstable = (cape > limits["cu_cape"]) | (stability < limits["cu_stability"])
    middle_clouds = mcc >= limits["middle_cover"]
    high_clouds = hcc >= limits["high_cover"]
    present = {
        "low": {
            "Cb": cumulonimbus,
            "St": low_clouds & (lcc > limits["st_cover"]) & (spread < limits["st_spread"]),
            "Cu": low_clouds & unstable,
            "Sc": low_clouds & ((lcc > limits["cu_max_cover"]) | ~unstable),
        },
        "middle": {
            "Ac": middle_clouds & ~thick_middle,
            "As": thick_middle & (middle != genus_index("Ns")),
        },
        "high": {
            "Cs": hcc > limits["cs_cover"],
            "Ci": high_clouds & ((hcc < limits["ci_max_cover"]) | cumulonimbus),
        },
    }
    masks = {}
    for etage, main in (("low", low), ("middle", middle), ("high", high)):
        mask = onp.where(main >= 0, onp.left_shift(1, onp.maximum(main, 0)), 0)
        for abbreviation, condition in present[etage].items():
            mask = mask | onp.where(condition, 1 << genus_index(abbreviation), 0)
        masks[etage] = mask.astype(int)

    # Seen from deck: hidden where the étages below leave less than
    # `visible_cover` of the sky open, as an observer codes "/".
    middle = onp.where((middle != NONE) & (1.0 - lcc <= limits["visible_cover"]), HIDDEN, middle)
    high = onp.where(
        (high != NONE) & (1.0 - onp.maximum(lcc, mcc) <= limits["visible_cover"]),
        HIDDEN,
        high,
    )

    fog = (lcc > limits["fog_cover"]) & (spread < limits["fog_spread"])

    # WMO oktas: 0 and 8 only for a sky really clear or overcast.
    oktas = onp.rint(8.0 * tcc)
    oktas = onp.where((tcc >= 0.01) & (oktas == 0), 1, oktas)
    oktas = onp.where((tcc <= 0.99) & (oktas == 8), 7, oktas)
    oktas = onp.where(fog, 9, oktas).astype(int)

    etages = _genera_table()["etages"]
    base = onp.select(
        [fog, low != NONE, middle != NONE, high != NONE],
        [
            0.0,
            condensation_height(t2m, d2m),
            1000.0 * etages["middle"]["height_km"]["temperate"][0],
            1000.0 * etages["high"]["height_km"]["temperate"][0],
        ],
        default=onp.nan,
    )

    return {
        "cloud_oktas": oktas,
        "cloud_base": base,
        "cloud_low": low.astype(int),
        "cloud_middle": middle.astype(int),
        "cloud_high": high.astype(int),
        "cloud_low_genera": masks["low"],
        "cloud_middle_genera": masks["middle"],
        "cloud_high_genera": masks["high"],
        "fog": fog,
        "stability": stability,
    }


def draw(sky: Mapping, valid_time, **kwargs):
    """
    Draw the sky along a route as a meteogram.

    Shortcut of `architeuthis.toolbox.plot_utils.plot_sky`, imported
    on call, so that this module stays light.

    Args:
        sky: The fields and their diagnosis, as
            `fields | diagnose(fields)`.
        valid_time: Time of each point, in epoch seconds.
        **kwargs: Arguments of `plot_sky`: `title`, `labels`,
            `figsize`, `dpi`, `save_as`, `show`.

    Returns:
        The figure.

    Example:
        >>> sky = fields | diagnose(fields)  # doctest: +SKIP
        >>> draw(sky, valid_time, title="GFS")  # doctest: +SKIP
    """
    from architeuthis.toolbox.plot_utils import plot_sky

    return plot_sky(sky, valid_time, **kwargs)


def _precipitation(rate, t2m, low, middle, limits) -> str:
    if not rate >= limits["rain_rate"]:
        return ""
    if rate < limits["moderate_rate"]:
        intensity = "light"
    elif rate < limits["heavy_rate"]:
        intensity = "moderate"
    else:
        intensity = "heavy"

    if t2m < limits["snow_temperature"]:
        form = "snow"
    elif low == genus_index("St") and middle == NONE:
        form = "drizzle"
    else:
        form = "rain"

    if low in (genus_index("Cu"), genus_index("Cb")):
        form += " showers"
    return f"{intensity} {form}"


def describe(
    sky: Mapping,
    thresholds: Optional[Mapping] = None,
) -> list:
    """
    One line per point describing the sky, for the crew.

    For example "6/8 · Cu+Sc 600 m · As · light rain": the cover, the
    low genera and their base, the middle and high genera seen from
    deck, and the precipitation. Several genera of an étage are joined
    by "+", the main one first. A Cb also gives the CAPE.

    Args:
        sky: Mapping holding the result of `diagnose`, and `prate`,
            `t2m` and `cape` for the precipitation: a report updated
            with `diagnose`, or the fields and the diagnosis merged.
        thresholds: Values replacing some of `THRESHOLDS`.

    Returns:
        The lines, one per point.

    Example:
        >>> fields = sample(forecast, t, lat, lon)  # doctest: +SKIP
        >>> describe(fields | diagnose(fields))  # doctest: +SKIP
    """
    limits = THRESHOLDS | dict(thresholds or {})
    columns = {
        key: onp.atleast_1d(onp.asarray(sky[key])).ravel()
        for key in ("cloud_oktas", "cloud_base", "cloud_low", "cloud_middle", "cloud_high", "fog")
    }
    count = len(columns["cloud_oktas"])
    for etage in ETAGES:
        key = f"cloud_{etage}_genera"
        if key in sky:
            columns[key] = onp.atleast_1d(onp.asarray(sky[key])).ravel()
        else:
            # A diagnosis of the main genera only.
            main = columns[f"cloud_{etage}"]
            columns[key] = onp.where(main >= 0, onp.left_shift(1, onp.maximum(main, 0)), 0)

    def names(etage, i, main):
        return "+".join(
            genus_abbreviation(genus) for genus in genera_present(columns[f"cloud_{etage}_genera"][i], main)
        )

    extra = {
        key: onp.atleast_1d(onp.asarray(sky[key], dtype=float)).ravel() if key in sky else onp.full(count, onp.nan)
        for key in ("prate", "t2m", "cape")
    }

    lines = []
    for i in range(count):
        oktas = int(columns["cloud_oktas"][i])
        low, middle, high = (int(columns[key][i]) for key in ("cloud_low", "cloud_middle", "cloud_high"))
        if columns["fog"][i]:
            parts = ["fog, sky obscured"]
        elif oktas == 0:
            parts = ["0/8 clear sky"]
        else:
            parts = [f"{oktas}/8"]
            if low != NONE:
                text = f"{names('low', i, low)} {int(round(columns['cloud_base'][i], -2))} m"
                if low == genus_index("Cb") and onp.isfinite(extra["cape"][i]):
                    text += f" (CAPE {int(round(extra['cape'][i], -2))} J/kg)"
                parts.append(text)
            parts += [
                names(etage, i, genus)
                for etage, genus in (("middle", middle), ("high", high))
                if genus not in (NONE, HIDDEN)
            ]
        precipitation = _precipitation(extra["prate"][i], extra["t2m"][i], low, middle, limits)
        if precipitation:
            parts.append(precipitation)
        lines.append(" · ".join(parts))
    return lines

"""The sky diagnosed from forecast fields, `architeuthis/sky.py`."""

import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from architeuthis import sky
from architeuthis.forecast import Forecast

# Typical fields of a few skies at sea, in the units of `diagnose`.
CALM = {"tcc": 0.0, "lcc": 0.0, "mcc": 0.0, "hcc": 0.0, "cape": 0.0, "prate": 0.0, "t2m": 290.0, "d2m": 282.0, "t700": 275.0}
SKIES = {
    # Trade winds: scattered Cu, unstable air, nothing aloft.
    "trade_cumulus": CALM | {"tcc": 0.35, "lcc": 0.35, "cape": 300.0, "t2m": 298.0, "d2m": 293.0, "t700": 282.0},
    # Marine layer under a strong inversion.
    "marine_stratocumulus": CALM | {"tcc": 0.9, "lcc": 0.9, "t2m": 288.0, "d2m": 284.0, "t700": 282.0},
    # Warm front: Ns over a low layer, steady rain, Cs above.
    "warm_front": CALM | {"tcc": 1.0, "lcc": 0.7, "mcc": 0.95, "hcc": 0.9, "prate": 3.0, "d2m": 289.0},
    # Ahead of it, only As and Cs.
    "altostratus": CALM | {"tcc": 1.0, "mcc": 0.9, "hcc": 0.8},
    # Thunderstorm.
    "cumulonimbus": CALM | {"tcc": 0.9, "lcc": 0.5, "mcc": 0.3, "hcc": 0.6, "cape": 1800.0, "prate": 6.0, "t2m": 300.0, "d2m": 295.0},
    # Winter showers: polar air over a warmer sea, a few hundred J/kg.
    "winter_shower": CALM | {"tcc": 0.8, "lcc": 0.6, "mcc": 0.4, "hcc": 0.3, "cape": 250.0, "prate": 1.5, "t2m": 281.0, "d2m": 277.0, "t700": 258.0},
    # Warm air over cold water.
    "fog": CALM | {"tcc": 1.0, "lcc": 1.0, "t2m": 284.0, "d2m": 283.8, "t700": 280.0},
    "clear": CALM,
    "cirrus": CALM | {"tcc": 0.3, "hcc": 0.3},
}


def genera(diagnosis):
    return tuple(sky.genus_abbreviation(int(diagnosis[key])) for key in ("cloud_low", "cloud_middle", "cloud_high"))


@pytest.mark.parametrize(
    "name, expected",
    [
        ("trade_cumulus", ("Cu", "", "")),
        ("marine_stratocumulus", ("Sc", "", "")),
        # Air near its dewpoint under the rain: ragged St.
        ("warm_front", ("St", "Ns", "/")),
        ("altostratus", ("", "As", "/")),
        ("cumulonimbus", ("Cb", "Ac", "Ci")),
        ("winter_shower", ("Cb", "Ac", "Ci")),
        ("clear", ("", "", "")),
        ("cirrus", ("", "", "Ci")),
    ],
)
def test_each_sky_gets_its_genera(name, expected):
    assert genera(sky.diagnose(SKIES[name])) == expected


def test_showers_need_unstable_air_to_be_cumulonimbus():
    """
    Rain with some CAPE in stable air, as at a front, stays Ns.
    """
    front = SKIES["warm_front"] | {"cape": 300.0}
    assert sky.lower_tropospheric_stability(front["t2m"], front["t700"]) > sky.THRESHOLDS["cb_stability"]
    assert genera(sky.diagnose(front))[:2] == ("St", "Ns")
    # The same shower without rain is Cu, and a strong CAPE is a Cb in any air.
    assert genera(sky.diagnose(SKIES["winter_shower"] | {"prate": 0.0}))[0] == "Cu"
    assert genera(sky.diagnose(front | {"cape": 1500.0}))[0] == "Cb"


def test_low_layer_near_its_dewpoint_is_stratus_or_fog():
    stratus = sky.diagnose(SKIES["fog"] | {"lcc": 0.8, "tcc": 0.8, "d2m": 283.0})
    fog = sky.diagnose(SKIES["fog"])

    assert genera(stratus)[0] == "St"
    assert not stratus["fog"] and fog["fog"]
    assert fog["cloud_oktas"] == 9
    assert fog["cloud_base"] == 0.0


def test_cloud_base_follows_the_dewpoint_spread():
    diagnosis = sky.diagnose(SKIES["trade_cumulus"])

    assert diagnosis["cloud_base"] == pytest.approx(125.0 * 5.0)
    assert np.isnan(sky.diagnose(SKIES["clear"])["cloud_base"])
    # Without low clouds, the base of the lowest étage present.
    assert sky.diagnose(SKIES["cirrus"])["cloud_base"] == 5000.0


def test_oktas_keep_zero_and_eight_for_clear_and_overcast_skies():
    covers = np.array([0.0, 0.02, 0.5, 0.97, 1.0])
    fields = {key: np.full(covers.shape, value) for key, value in CALM.items()} | {"tcc": covers}

    assert list(sky.diagnose(fields)["cloud_oktas"]) == [0, 1, 4, 7, 8]


def test_works_on_arrays_and_keeps_their_shape():
    names = list(SKIES)
    fields = {key: np.array([SKIES[name][key] for name in names]) for key in sky.SKY_VARIABLES}

    diagnosis = sky.diagnose(fields)

    assert all(np.shape(value) == (len(names),) for value in diagnosis.values())
    for i, name in enumerate(names):
        single = sky.diagnose(SKIES[name])
        assert all(diagnosis[key][i] == single[key] or np.isnan(single[key]) for key in ("cloud_low", "cloud_middle", "cloud_high", "cloud_oktas", "cloud_base"))


def test_thresholds_can_be_replaced():
    sky_fields = SKIES["trade_cumulus"]

    assert genera(sky.diagnose(sky_fields, thresholds={"cu_cape": 500.0, "cu_stability": 5.0}))[0] == "Sc"
    assert sky.THRESHOLDS["cu_cape"] == 100.0


def test_out_of_range_covers_from_interpolation_are_clipped():
    diagnosis = sky.diagnose(CALM | {"tcc": 1.03, "lcc": -0.02, "hcc": 1.1})

    assert diagnosis["cloud_oktas"] == 8
    assert genera(diagnosis) == ("", "", "Cs")


def test_missing_fields_are_named():
    with pytest.raises(KeyError, match="prate"):
        sky.diagnose({key: value for key, value in CALM.items() if key != "prate"})


def test_describe_writes_one_line_per_point_for_the_crew():
    names = ["trade_cumulus", "warm_front", "cumulonimbus", "fog", "clear"]
    fields = {key: np.array([SKIES[name][key] for name in names]) for key in sky.SKY_VARIABLES}

    lines = sky.describe(fields | sky.diagnose(fields))

    assert lines == [
        "3/8 · Cu 600 m",
        "8/8 · St+Sc 100 m · Ns · moderate rain",
        "7/8 · Cb+Cu 600 m (CAPE 1800 J/kg) · Ac · Ci · moderate rain showers",
        "fog, sky obscured",
        "0/8 clear sky",
    ]


def test_describe_tells_snow_and_drizzle():
    snow = SKIES["warm_front"] | {"t2m": 272.0, "d2m": 271.0, "prate": 0.5}
    drizzle = SKIES["fog"] | {"lcc": 0.8, "tcc": 0.8, "d2m": 283.0, "prate": 0.2}

    assert sky.describe(snow | sky.diagnose(snow))[0].endswith("light snow")
    assert sky.describe(drizzle | sky.diagnose(drizzle))[0].endswith("light drizzle")


def test_genera_follow_the_table():
    table = sky.load_genera()

    assert [sky.genus_index(genus["abbreviation"]) for genus in table["genera"]] == list(range(10))
    assert sky.genus_abbreviation(sky.NONE) == "" and sky.genus_abbreviation(sky.HIDDEN) == "/"
    # The table is a copy: changing it changes nothing for the next reader.
    table["genera"].clear()
    assert len(sky.load_genera()["genera"]) == 10
    with pytest.raises(KeyError):
        sky.genus_index("Xx")


def test_lower_tropospheric_stability():
    # Potential temperature at 700 hPa of 275 K is about 304.5 K.
    assert sky.lower_tropospheric_stability(290.0, 275.0) == pytest.approx(14.5, abs=0.1)


# Lines of the real index files of the 00 UTC runs of 2026-11-17, step 6 h, as Herbie searches them.
GFS_INVENTORY = [
    ":TMP:2 mb:6 hour fcst",
    ":TMP:700 mb:6 hour fcst",
    ":TMP:2 m above ground:6 hour fcst",
    ":DPT:2 m above ground:6 hour fcst",
    ":CPRAT:surface:6 hour fcst",
    ":PRATE:surface:6 hour fcst",
    ":PRATE:surface:0-6 hour ave fcst",
    ":CAPE:surface:6 hour fcst",
    ":CAPE:255-0 mb above ground:6 hour fcst",
    ":LCDC:low cloud layer:6 hour fcst",
    ":LCDC:low cloud layer:0-6 hour ave fcst",
    ":MCDC:middle cloud layer:6 hour fcst",
    ":MCDC:middle cloud layer:0-6 hour ave fcst",
    ":HCDC:high cloud layer:6 hour fcst",
    ":HCDC:high cloud layer:0-6 hour ave fcst",
    ":TCDC:entire atmosphere:6 hour fcst",
    ":TCDC:entire atmosphere:0-6 hour ave fcst",
    ":TCDC:convective cloud layer:6 hour fcst",
]
IFS_INVENTORY = [
    ":tcc:sfc:g:0001:od:fc:oper", ":lcc:sfc:g:0001:od:fc:oper", ":mcc:sfc:g:0001:od:fc:oper",
    ":hcc:sfc:g:0001:od:fc:oper", ":mucape:sfc:g:0001:od:fc:oper", ":tprate:sfc:g:0001:od:fc:oper",
    ":tp:sfc:g:0001:od:fc:oper", ":cp:sfc:g:0001:od:fc:oper", ":2t:sfc:g:0001:od:fc:oper",
    ":2d:sfc:g:0001:od:fc:oper", ":t:700:pl:g:0001:od:fc:oper", ":t:850:pl:g:0001:od:fc:oper",
    ":r:700:pl:g:0001:od:fc:oper", ":10u:sfc:g:0001:od:fc:oper",
]


def test_gfs_search_keeps_the_nine_instantaneous_fields():
    found = [line for line in GFS_INVENTORY if re.search(sky.GFS_SKY_REGEX, line)]

    assert found == [
        ":TMP:700 mb:6 hour fcst",
        ":TMP:2 m above ground:6 hour fcst",
        ":DPT:2 m above ground:6 hour fcst",
        ":PRATE:surface:6 hour fcst",
        ":CAPE:255-0 mb above ground:6 hour fcst",
        ":LCDC:low cloud layer:6 hour fcst",
        ":MCDC:middle cloud layer:6 hour fcst",
        ":HCDC:high cloud layer:6 hour fcst",
        ":TCDC:entire atmosphere:6 hour fcst",
    ]


def test_ifs_search_keeps_the_nine_fields():
    found = {line.split(":")[1] + (":700" if ":700:" in line else "") for line in IFS_INVENTORY if re.search(sky.IFS_SKY_REGEX, line)}

    assert found == {"tcc", "lcc", "mcc", "hcc", "mucape", "tprate", "2t", "2d", "t:700"}


def test_gfs_search_reads_the_lines_ending_with_a_colon():
    # Herbie 2025 ends each line of the GFS inventory with a colon.
    found = [line for line in GFS_INVENTORY if re.search(sky.GFS_SKY_REGEX, line + ":")]

    assert len(found) == 9
    assert ":TCDC:entire atmosphere:6 hour fcst" in found
    assert ":TCDC:entire atmosphere:0-6 hour ave fcst" not in found


def test_ifs_search_reads_the_empty_level_written_nan():
    # Herbie 2025 writes the missing level of the surface fields "nan".
    inventory = [line.replace(":sfc:", ":nan:sfc:").replace(":pl:", ":pl:nan:") for line in IFS_INVENTORY]

    found = {line.split(":")[1] + (":700" if ":700:" in line else "") for line in inventory if re.search(sky.IFS_SKY_REGEX, line)}

    assert found == {"tcc", "lcc", "mcc", "hcc", "mucape", "tprate", "2t", "2d", "t:700"}


@pytest.mark.parametrize("model", ["ifs", "gfs"])
def test_forecast_fields_are_registered_in_the_units_of_the_diagnosis(model):
    time = (pd.date_range("2026-11-17", periods=3, freq="6h") - pd.Timestamp("1970-01-01")).total_seconds().to_numpy()
    latitude = np.arange(40.0, 50.1, 2.0)
    longitude = np.arange(-20.0, -9.9, 2.0)
    shape = (len(time), len(latitude), len(longitude))
    # The raw values of the model, as cfgrib names them.
    cover = 50.0 if model == "gfs" else 0.5
    raw = {"tcc": cover, "lcc": cover, "mcc": cover, "hcc": cover, "t2m": 290.0, "d2m": 286.0, "t": 276.0}
    raw |= {"mucape": 400.0, "tprate": 1e-3} if model == "ifs" else {"cape": 400.0, "prate": 1e-3}
    forecast = Forecast("sky_test", date=0.0, fxx=None, verbose=False)
    forecast.data = xr.Dataset(
        {name: (("valid_time", "latitude", "longitude"), np.full(shape, value)) for name, value in raw.items()},
        coords={"valid_time": time, "latitude": latitude, "longitude": longitude},
    )

    sky.add_sky_models(forecast, model=model)
    fields = sky.sample(forecast, time[[0, 1]] + 600.0, np.array([42.1, 45.3]), np.array([-15.2, -12.7]))

    assert set(fields) == set(sky.SKY_VARIABLES)
    assert fields["lcc"] == pytest.approx([0.5, 0.5])
    assert fields["prate"] == pytest.approx([3.6, 3.6])
    assert fields["cape"] == pytest.approx([400.0, 400.0])
    assert fields["t700"] == pytest.approx([276.0, 276.0])
    assert len(sky.describe(fields | sky.diagnose(fields))) == 2


def test_unknown_model_is_refused():
    forecast = Forecast("sky_test", date=0.0, fxx=None, verbose=False)

    with pytest.raises(ValueError, match="hrrr"):
        sky.add_sky_models(forecast, model="hrrr")


def test_an_etage_is_hidden_only_when_the_sky_below_is_covered():
    # A thin high cloud above a half-covered sky is still seen.
    seen = sky.diagnose(CALM | {"tcc": 0.55, "lcc": 0.5, "hcc": 0.06, "cape": 300.0})
    hidden = sky.diagnose(CALM | {"tcc": 0.95, "lcc": 0.95, "hcc": 0.06})

    assert genera(seen)[2] == "Ci"
    assert genera(hidden)[2] == "/"


def test_draw_is_the_meteogram_of_plot_utils():
    fields = {key: np.array([SKIES[name][key] for name in ("clear", "cumulonimbus")]) for key in sky.SKY_VARIABLES}

    fig = sky.draw(fields | sky.diagnose(fields), [0.0, 10800.0], show=False)

    assert "Cb" in {text.get_text() for text in fig.axes[0].texts}
    plt.close(fig)


def present(diagnosis, etage):
    main = int(diagnosis[f"cloud_{etage}"])
    return [sky.genus_abbreviation(genus) for genus in sky.genera_present(int(diagnosis[f"cloud_{etage}_genera"]), main)]


@pytest.mark.parametrize(
    "name, etage, expected",
    [
        ("cumulonimbus", "low", ["Cb", "Cu"]),
        ("warm_front", "low", ["St", "Sc"]),
        ("trade_cumulus", "low", ["Cu"]),
        ("marine_stratocumulus", "low", ["Sc"]),
        ("cumulonimbus", "high", ["Ci"]),
        ("clear", "low", []),
    ],
)
def test_every_genus_present_is_given_main_first(name, etage, expected):
    assert present(sky.diagnose(SKIES[name]), etage) == expected


def test_hidden_etages_keep_their_genera_in_the_column():
    # As hides from deck the Cs above it, still present in the column.
    diagnosis = sky.diagnose(SKIES["altostratus"])

    assert int(diagnosis["cloud_high"]) == sky.HIDDEN
    # Without a main genus, in the order of the table.
    assert present(diagnosis, "high") == ["Ci", "Cs"]


def test_broken_cumulus_under_a_wide_layer_gives_both():
    diagnosis = sky.diagnose(CALM | {"tcc": 0.8, "lcc": 0.8, "cape": 400.0, "hcc": 0.8})

    assert present(diagnosis, "low") == ["Sc", "Cu"]
    assert present(diagnosis, "high") == ["Cs", "Ci"]


def test_main_genus_is_always_among_those_present():
    names = list(SKIES)
    fields = {key: np.array([SKIES[name][key] for name in names]) for key in sky.SKY_VARIABLES}
    diagnosis = sky.diagnose(fields)

    for etage in sky.ETAGES:
        for main, mask in zip(diagnosis[f"cloud_{etage}"], diagnosis[f"cloud_{etage}_genera"]):
            if main >= 0:
                assert mask >> main & 1
            else:
                assert main == sky.HIDDEN or mask == 0

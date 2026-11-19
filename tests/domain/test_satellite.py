"""
Satellite observations: ASCAT from EUMETSAT or Copernicus Marine, offline.
"""
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from architeuthis.credentials import MissingCredentialError
from architeuthis.satellite import (
    ASCAT_SOURCES,
    ASCATData,
    CopernicusASCATData,
    CopernicusSatelliteData,
    EUMETSATASCATData,
)

DOMAIN = dict(min_lon=-20.0, max_lon=0.0, min_lat=40.0, max_lat=52.0)
START, END = "2026-11-17 06:00", "2026-11-18 12:00"
ASCAT_VARIABLES = {"lat", "lon", "time", "valid_time", "wind_speed", "wind_dir"}


@pytest.fixture
def cmems_credentials(monkeypatch):
    monkeypatch.setenv("CMEMS_USER", "my-user")
    monkeypatch.setenv("CMEMS_PWD", "my-password")


# ------------------------------------------------------------------------------
# Copernicus Marine
# ------------------------------------------------------------------------------


def cmems_grid(times):
    """One CMEMS L3 dataset: two days on a 2 x 3 grid, as the server sends it."""
    latitude = np.array([41.0, 45.0])
    longitude = np.array([-15.0, -10.0, -5.0])
    days = pd.to_datetime(["2026-11-17", "2026-11-18"])
    measurement = np.full((2, 2, 3), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    for day, time in enumerate(times):
        measurement[day, :, :2] = np.datetime64(time)  # the swath misses the last column
    speed = np.where(np.isnat(measurement), np.nan, 10.0)
    dims = ("time", "latitude", "longitude")
    return xr.Dataset(
        {
            "wind_speed": (dims, speed),
            "wind_to_dir": (dims, np.where(np.isnat(measurement), np.nan, 90.0)),
            "measurement_time": (dims, measurement),
        },
        coords={"time": days, "latitude": latitude, "longitude": longitude},
    )


@patch("architeuthis.copernicus.copernicusmarine.subset")
def test_copernicus_ascat_downloads_each_metop_and_orbit_from_the_first_day(subset, cmems_credentials):
    subset.return_value.file_path = "dummy.nc"
    ascat = CopernicusASCATData("ascat", start=START, end=END, **DOMAIN)

    ascat._download_data()

    datasets = [call.kwargs["dataset_id"] for call in subset.call_args_list]
    assert datasets == [
        "cmems_obs-wind_glo_phy_nrt_l3-metopb-ascat-asc-0.125deg_P1D-i",
        "cmems_obs-wind_glo_phy_nrt_l3-metopb-ascat-des-0.125deg_P1D-i",
        "cmems_obs-wind_glo_phy_nrt_l3-metopc-ascat-asc-0.125deg_P1D-i",
        "cmems_obs-wind_glo_phy_nrt_l3-metopc-ascat-des-0.125deg_P1D-i",
    ]
    kwargs = subset.call_args.kwargs
    assert kwargs["username"] == "my-user"
    assert kwargs["password"] == "my-password"
    # Daily steps are stamped at midnight, in UTC: naive dates are local to the toolbox
    assert kwargs["start_datetime"] == pd.Timestamp("2026-11-17", tz="UTC")
    assert kwargs["end_datetime"] == pd.Timestamp(END, tz="UTC")
    assert kwargs["coordinates_selection_method"] == "inside"
    assert "minimum_depth" not in kwargs
    assert kwargs["minimum_longitude"] == DOMAIN["min_lon"]
    assert ascat.path == ["dummy.nc"] * 4
    assert "my-password" not in repr(vars(ascat))


@patch("architeuthis.copernicus.copernicusmarine.subset")
def test_copernicus_satellite_without_credentials_stops_before_downloading(subset):
    data = CopernicusSatelliteData("cmems", "dummy-dataset", ["wind_speed"], start=START, end=END)

    with pytest.raises(MissingCredentialError, match="CMEMS_USER, CMEMS_PWD"):
        data._download_data()

    subset.assert_not_called()


def test_copernicus_ascat_keeps_the_measurements_of_the_period():
    ascat = CopernicusASCATData("ascat", start=START, end=END, satellites=["metopb"], orbits=["asc", "des"])
    ascat.data = [
        cmems_grid(["2026-11-17 05:00", "2026-11-18 10:00"]),  # first one before the start
        cmems_grid(["2026-11-17 20:00", "2026-11-18 21:00"]),  # last one after the end
    ]

    ascat._convert_data()

    data = ascat.data
    assert ASCAT_VARIABLES <= set(data.data_vars)
    assert {data[name].dims for name in ASCAT_VARIABLES} == {("swath", "day", "latitude", "longitude")}
    kept = np.isfinite(data["wind_speed"].values)
    assert kept.sum() == 2 * 4  # two swaths of four cells
    assert np.all(np.isfinite(data["valid_time"].values) == kept)
    assert set(data["time"].values[kept].astype("datetime64[h]").astype(str)) == {"2026-11-18T10", "2026-11-17T20"}
    assert data["valid_time"].values[kept].min() == pd.Timestamp("2026-11-17 20:00", tz="UTC").timestamp()
    assert np.all(data["wind_dir"].values[kept] == 90.0)  # wind_to_dir, where the wind goes
    # Positions match the winds cell by cell once flattened
    assert np.all(data["lon"].values.ravel()[kept.ravel()] <= -10.0)


def test_copernicus_ascat_masks_the_cells_outside_the_domain():
    ascat = CopernicusASCATData("ascat", start=START, end=END, satellites=["metopb"], orbits=["asc"], min_lat=43.0)
    ascat.data = [cmems_grid(["2026-11-17 20:00", "2026-11-18 10:00"])]

    ascat._convert_data()

    kept = np.isfinite(ascat.data["wind_speed"].values)
    assert kept.sum() == 2 * 2
    assert np.all(ascat.data["lat"].values[kept] == 45.0)


# ------------------------------------------------------------------------------
# EUMETSAT
# ------------------------------------------------------------------------------


def eumetsat_product(name, content=b"swath"):
    """A Data Store product whose download is a zip holding one NetCDF file."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(f"folder/{name}.nc", content)
    product = MagicMock()
    stream = io.BytesIO(archive.getvalue())
    stream.name = f"{name}.zip"
    product.open.return_value.__enter__.return_value = stream
    return product


def eumetsat_ascat(tmp_path, products):
    ascat = EUMETSATASCATData("ascat", start=START, end=END, verbose=False, **DOMAIN)
    ascat.output_path = str(tmp_path)
    ascat.collection = MagicMock()
    ascat.collection.search.return_value = products
    return ascat


def test_eumetsat_searches_the_domain_and_unzips_the_products(tmp_path):
    ascat = eumetsat_ascat(tmp_path, [eumetsat_product("a"), eumetsat_product("b")])

    ascat._download_data()

    kwargs = ascat.collection.search.call_args.kwargs
    assert kwargs["bbox"] == "-20.0, 40.0, 0.0, 52.0"
    assert kwargs["dtstart"] == START
    assert sorted(ascat.path) == [str(tmp_path / "a.nc"), str(tmp_path / "b.nc")]
    assert (tmp_path / "a.nc").read_bytes() == b"swath"


def test_eumetsat_does_not_download_a_product_again(tmp_path):
    eumetsat_ascat(tmp_path, [eumetsat_product("a", b"first")])._download_data()
    ascat = eumetsat_ascat(tmp_path, [eumetsat_product("a", b"second")])

    ascat._download_data()

    assert ascat.path == [str(tmp_path / "a.nc")]
    assert (tmp_path / "a.nc").read_bytes() == b"first"
    assert not list(tmp_path.glob("*.part"))


def test_eumetsat_without_product_raises(tmp_path):
    ascat = eumetsat_ascat(tmp_path, [])

    with pytest.raises(FileNotFoundError, match="No product"):
        ascat._download_data()


def test_eumetsat_ascat_gives_the_same_variables_as_copernicus():
    ascat = EUMETSATASCATData("ascat", start=START, end=END, **DOMAIN)
    dims = ("NUMROWS", "NUMCELLS")
    ascat.data = xr.Dataset({
        "lat": (dims, [[45.0, 45.0], [60.0, 45.0]]),
        "lon": (dims, [[350.0, 345.0], [350.0, 100.0]]),
        "time": (dims, np.full((2, 2), np.datetime64("2026-11-18T10:00", "ns"))),
        "wind_speed": (dims, np.full((2, 2), 8.0)),
        "wind_dir": (dims, np.full((2, 2), 45.0)),
    })

    ascat._convert_data()

    assert ASCAT_VARIABLES <= set(ascat.data.data_vars)
    assert np.isfinite(ascat.data["wind_speed"].values).tolist() == [[True, True], [False, False]]
    assert ascat.data["lon"].values[0].tolist() == [-10.0, -15.0]
    assert ascat.data["valid_time"].values[0, 0] == pd.Timestamp("2026-11-18 10:00", tz="UTC").timestamp()


# ------------------------------------------------------------------------------
# Source selection
# ------------------------------------------------------------------------------


def loads(data):
    """A `load_data` replacement that fills an object with `data`."""

    def load_data(self):
        self.data = data
        self.path = [self.name]

    return load_data


def fails(error):
    def load_data(self):
        raise error

    return load_data


def test_ascat_comes_from_eumetsat_first():
    with (
        patch.object(EUMETSATASCATData, "load_data", loads("eumetsat data")),
        patch.object(CopernicusASCATData, "load_data", fails(AssertionError("not needed"))),
    ):
        ascat = ASCATData("ascat", start=START, end=END, **DOMAIN)
        ascat.load_data()

    assert ascat.source == "eumetsat"
    assert ascat.data == "eumetsat data"


def test_ascat_falls_back_on_copernicus_when_eumetsat_fails(capsys):
    with (
        patch.object(EUMETSATASCATData, "load_data", fails(ConnectionError("504 Gateway Timeout"))),
        patch.object(CopernicusASCATData, "load_data", loads("cmems data")),
    ):
        ascat = ASCATData("ascat", start=START, end=END, verbose=False, **DOMAIN)
        ascat.load_data()

    assert ascat.source == "cmems"
    assert ascat.data == "cmems data"
    output = capsys.readouterr().out
    assert "⚠️ ASCAT from eumetsat failed (ConnectionError: 504 Gateway Timeout), trying cmems." in output


def test_ascat_from_copernicus_only_never_asks_eumetsat():
    with (
        patch.object(EUMETSATASCATData, "load_data", fails(AssertionError("not asked"))),
        patch.object(CopernicusASCATData, "load_data", loads("cmems data")),
    ):
        ascat = ASCATData("ascat", start=START, end=END, sources="cmems")
        ascat.load_data()

    assert ascat.source == "cmems"


def test_ascat_raises_the_last_error_when_every_source_fails(capsys):
    with (
        patch.object(EUMETSATASCATData, "load_data", fails(ConnectionError("down"))),
        patch.object(CopernicusASCATData, "load_data", fails(MissingCredentialError("CMEMS_USER"))),
        pytest.raises(MissingCredentialError),
    ):
        ASCATData("ascat", start=START, end=END).load_data()

    assert capsys.readouterr().out.count("⚠️ ASCAT from") == 2


def test_ascat_passes_its_period_and_domain_to_the_source():
    seen = {}

    def load_data(self):
        seen.update(vars(self))
        self.data = None

    with patch.object(CopernicusASCATData, "load_data", load_data):
        ASCATData("ascat", start=START, end=END, verbose=False, sources=["cmems"], **DOMAIN).load_data()

    assert {key: seen[key] for key in ("start", "end", "verbose", *DOMAIN)} == {
        "start": START, "end": END, "verbose": False, **DOMAIN,
    }


def test_ascat_refuses_an_unknown_source():
    with pytest.raises(ValueError, match="Unknown ASCAT source"):
        ASCATData("ascat", sources=["eumetsat", "noaa"])
    assert set(ASCAT_SOURCES) == {"eumetsat", "cmems"}

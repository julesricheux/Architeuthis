# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 18:25:18 2026

@author: jrich
"""

import pytest
from unittest.mock import MagicMock, patch
import xarray as xr
import numpy as np
import datetime as dt

from architeuthis.forecast import (
    Forecast,
    HerbieForecast,
    DeterministicHerbieForecast,
    EnsembleHerbieForecast,
    CopernicusForecast,
)


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------

@pytest.fixture
def dummy_date():
    return dt.datetime(2025, 1, 15, 0)


@pytest.fixture
def dummy_dataset():
    data = xr.Dataset(
        {
            "u10": (("valid_time", "latitude", "longitude"), np.zeros((1, 2, 2)))
        },
        coords={
            "valid_time": [0],
            "latitude": [0.0, 1.0],
            "longitude": [0.0, 1.0],
        },
    )
    return data


# ------------------------------------------------------------------------------
# Base Forecast
# ------------------------------------------------------------------------------

def test_forecast_base_properties(dummy_date):
    f = Forecast(
        name="test",
        date=dummy_date,
        fxx=[0, 6],
        min_lon=-10,
        max_lon=10,
        min_lat=-5,
        max_lat=5,
    )

    assert f.forecast_time == dummy_date
    assert f.valid_time == [0, 6]
    assert f.data is None
    assert f.path is None


def test_forecast_load_data_calls_all_steps(dummy_date):
    f = Forecast(
        name="test",
        date=dummy_date,
        fxx=[0],
        min_lon=-10,
        max_lon=10,
        min_lat=-5,
        max_lat=5,
    )

    f._locate_data = MagicMock()
    f._download_data = MagicMock()
    f._read_data = MagicMock()
    f._convert_data = MagicMock()

    f.load_data()

    f._locate_data.assert_called_once()
    f._download_data.assert_called_once()
    f._read_data.assert_called_once()
    f._convert_data.assert_called_once()


# ------------------------------------------------------------------------------
# Herbie Forecasts
# ------------------------------------------------------------------------------

@patch("forecast.FastHerbie")
def test_herbie_locate_data(mock_fh, dummy_date):
    hf = HerbieForecast(
        name="herbie",
        model="gfs",
        product="pgrb2",
        date=dummy_date,
        fxx=[0, 6],
    )

    hf._locate_data()
    assert hf._HerbieForecast__FH is not None
    mock_fh.assert_called_once()


@patch("forecast.FastHerbie")
def test_herbie_download_data(mock_fh, dummy_date):
    instance = mock_fh.return_value
    instance.download.return_value = ["file1.grib", "file2.grib"]

    hf = HerbieForecast(
        name="herbie",
        model="gfs",
        product="pgrb2",
        date=dummy_date,
        fxx=[0],
    )

    hf._locate_data()
    hf._download_data()

    assert hf.path == ["file1.grib", "file2.grib"]


@patch("forecast.xr.open_mfdataset")
def test_deterministic_herbie_read(mock_open, dummy_dataset, dummy_date):
    mock_open.return_value = dummy_dataset

    hf = DeterministicHerbieForecast(
        name="det",
        model="gfs",
        product="pgrb2",
        date=dummy_date,
        fxx=[0],
    )
    hf.path = ["dummy.grib"]

    hf._read_data()

    assert isinstance(hf.data, xr.Dataset)
    mock_open.assert_called_once()


@patch("forecast.xr.open_mfdataset")
def test_ensemble_herbie_read(mock_open, dummy_dataset, dummy_date):
    mock_open.return_value = dummy_dataset

    hf = EnsembleHerbieForecast(
        name="ens",
        model="gefs",
        product="pgrb2",
        date=dummy_date,
        fxx=[0],
    )
    hf.path = ["dummy_pf.grib"]

    hf._read_data()

    assert isinstance(hf.data, xr.Dataset)
    mock_open.assert_called_once()


# ------------------------------------------------------------------------------
# Copernicus Forecast
# ------------------------------------------------------------------------------

@patch("forecast.copernicusmarine.subset")
def test_copernicus_download(mock_subset, dummy_date):
    mock_subset.return_value.file_path = "dummy.nc"

    cf = CopernicusForecast(
        name="cmems",
        dataset="dummy-dataset",
        variables=["uo", "vo"],
        date=dummy_date,
        end=dummy_date + dt.timedelta(days=1),
    )

    cf._download_data()

    assert cf.path == "dummy.nc"
    mock_subset.assert_called_once()


@patch("forecast.xr.open_dataset")
def test_copernicus_read_and_convert(mock_open, dummy_date):
    ds = xr.Dataset(
        {"temp": ("time", [1.0, 2.0])},
        coords={"time": np.array(["2025-01-01", "2025-01-02"], dtype="datetime64[ns]")},
    )
    mock_open.return_value = ds

    cf = CopernicusForecast(
        name="cmems",
        dataset="dummy",
        variables=["temp"],
        date=dummy_date,
        end=dummy_date + dt.timedelta(days=1),
        time_unit="s",
    )

    cf.path = "dummy.nc"
    cf._read_data()
    cf._convert_data()

    assert cf.data["time"].dtype == float

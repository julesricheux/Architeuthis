import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pyproj
import pytest
import xarray as xr

import architeuthis.forecast as forecast_module
from architeuthis.credentials import MissingCredentialError
from architeuthis.forecast import (
    HRDPSForecast,
    _regrid_to_lat_lon,
    CDSForecast,
    CopernicusForecast,
    DeterministicHerbieForecast,
    EnsembleHerbieForecast,
    Forecast,
    HerbieForecast,
    open_grib,
)

BASE_DATE = dt.datetime(2025, 1, 15)
PADDING_SECONDS = [1e6, 1e7]


def raw_grid(time_name="valid_time", longitude=(0.0, 90.0, 270.0)):
    """Build a 2-step grid with unsorted, descending latitudes and 0-360 longitudes."""
    longitude = np.asarray(longitude)
    latitude = np.array([10.0, 0.0])
    time = pd.to_datetime(["2025-01-15T00:00", "2025-01-15T03:00"]).to_numpy()
    values = np.arange(2 * latitude.size * longitude.size, dtype=float).reshape(2, 2, longitude.size)
    return xr.Dataset(
        {"u10": ((time_name, "latitude", "longitude"), values + 1.0)},
        coords={time_name: time, "latitude": latitude, "longitude": longitude},
    )


def herbie_forecast(**kwargs):
    return HerbieForecast("herbie", model="gfs", product="pgrb2", date=BASE_DATE, fxx=[0, 3], **kwargs)


# ------------------------------------------------------------------------------
# Base forecast
# ------------------------------------------------------------------------------


def test_forecast_exposes_its_times():
    forecast = Forecast("test", date=BASE_DATE, fxx=[0, 6])

    assert forecast.forecast_time == BASE_DATE
    assert forecast.valid_time == [0, 6]
    assert forecast.data is None
    assert forecast.path is None


def test_forecast_finds_latest_run_when_date_is_missing():
    with patch.object(Forecast, "_find_latest", return_value=BASE_DATE) as find_latest:
        forecast = Forecast("test", date=None, fxx=[0])

    find_latest.assert_called_once()
    assert forecast.f00 == BASE_DATE


def test_add_interpolator_defaults_key_to_variable_name():
    forecast = Forecast("test", date=BASE_DATE, fxx=[0])
    forecast.data = xr.Dataset(
        {"u10": (("valid_time", "latitude", "longitude"), np.ones((2, 2, 2)))},
        coords={"valid_time": [0.0, 1.0], "latitude": [0.0, 1.0], "longitude": [0.0, 1.0]},
    )

    forecast.add_interpolator("u10", "valid_time", "latitude", "longitude")
    forecast.add_interpolator("u10", "valid_time", "latitude", "longitude", var_key="wind", fac=3.0)

    assert forecast.var_keys == {"u10", "wind"}
    assert float(forecast("wind", np.array([[0.5, 0.5, 0.5]]))) == pytest.approx(3.0)


def test_forecast_is_queried_by_standard_names():
    forecast = Forecast("test", date=BASE_DATE, fxx=[0])
    forecast.data = xr.Dataset(
        {"u10": (("time", "lat", "lon"), np.arange(8.0).reshape(2, 2, 2))},
        coords={"time": [0.0, 1.0], "lat": [0.0, 1.0], "lon": [0.0, 1.0]},
    )

    forecast.add_interpolator("u10", "time", "lat", "lon")
    query = {"valid_time": 1.0, "latitude": np.array([0.0, 1.0]), "longitude": 1.0}

    assert forecast.input_names("u10") == ["valid_time", "latitude", "longitude"]
    assert np.asarray(forecast("u10", query)).ravel() == pytest.approx([5.0, 7.0])


def wave_forecast(direction_name="mwd", swh=None, direction=None):
    axis = [0.0, 1.0]
    swh = np.full((2, 2, 2), 2.0) if swh is None else swh
    direction = np.full((2, 2, 2), 270.0) if direction is None else direction
    forecast = Forecast("wave", date=BASE_DATE, fxx=[0], verbose=False)
    forecast.data = xr.Dataset(
        {
            "swh": (("valid_time", "latitude", "longitude"), swh),
            direction_name: (("valid_time", "latitude", "longitude"), direction),
        },
        coords={"valid_time": axis, "latitude": axis, "longitude": axis},
    )
    return forecast


@pytest.mark.parametrize(
    "direction, expected",
    [(270.0, (4.0, 0.0)), (0.0, (0.0, -4.0)), (90.0, (-4.0, 0.0)), (180.0, (0.0, 4.0))],
)
def test_wave_components_go_where_the_waves_go_weighted_by_energy(direction, expected):
    forecast = wave_forecast(direction=np.full((2, 2, 2), direction))

    forecast.add_wave_components()

    # swh = 2 m: the components are swh**2 = 4 m² along the direction the waves go to.
    assert float(forecast.data["uw"][0, 0, 0]) == pytest.approx(expected[0], abs=1e-12)
    assert float(forecast.data["vw"][0, 0, 0]) == pytest.approx(expected[1], abs=1e-12)
    assert forecast.data["uw"].attrs["units"] == "m**2"


def test_wave_components_take_other_names():
    forecast = wave_forecast(direction_name="dirpw")

    forecast.add_wave_components(mwd_dim="dirpw", u_dim="east", v_dim="north")

    assert {"east", "north"} <= set(forecast.data.data_vars)
    assert "uw" not in forecast.data


def test_missing_waves_add_no_component():
    swh = np.full((2, 2, 2), 2.0)
    swh[:, 0, 0] = np.nan  # land
    forecast = wave_forecast(swh=swh)
    forecast.add_wave_components()
    forecast.add_interpolator("uw", "valid_time", "latitude", "longitude")

    # NaN becomes 0, so the land corner pulls the magnitude but not the direction.
    assert float(forecast("uw", {"valid_time": 0.0, "latitude": 0.0, "longitude": 0.0})) == 0.0


def test_wave_components_interpolate_across_north():
    direction = np.zeros((2, 2, 2))
    direction[:, :, 0], direction[:, :, 1] = 350.0, 10.0
    forecast = wave_forecast(direction=direction)
    forecast.add_wave_components()
    for key in ("uw", "vw"):
        forecast.add_interpolator(key, "valid_time", "latitude", "longitude")
    query = {"valid_time": 0.5, "latitude": 0.5, "longitude": 0.5}

    uw, vw = float(forecast("uw", query)), float(forecast("vw", query))

    # Halfway between 350 and 10 deg, the waves come from the north, not from 180 deg.
    assert np.mod(np.degrees(np.arctan2(uw, vw)) + 180.0, 360.0) == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------------------------------
# Herbie
# ------------------------------------------------------------------------------


@patch("architeuthis.forecast.HerbieLatest")
def test_herbie_finds_latest_run(herbie_latest):
    herbie_latest.return_value.valid_date = BASE_DATE

    forecast = HerbieForecast("herbie", model="gfs", product="pgrb2", date=None)

    herbie_latest.assert_called_once_with(model="gfs", product="pgrb2")
    assert forecast.f00 == BASE_DATE


@patch("architeuthis.forecast.FastHerbie")
def test_herbie_locates_and_downloads(fast_herbie):
    fast_herbie.return_value.download.return_value = ["file1.grib", "file2.grib"]
    forecast = herbie_forecast(regex=":10[u|v]:")

    forecast._locate_data()
    forecast._download_data()

    fast_herbie.assert_called_once_with([BASE_DATE], model="gfs", product="pgrb2", fxx=[0, 3])
    fast_herbie.return_value.download.assert_called_once_with(":10[u|v]:")
    assert forecast.path == ["file1.grib", "file2.grib"]


def test_herbie_conversion_normalizes_coordinates():
    forecast = herbie_forecast()
    forecast.data = raw_grid()

    forecast._convert_data()

    assert forecast.data["longitude"].values.tolist() == [-90.0, 0.0, 90.0]
    assert forecast.data["latitude"].values.tolist() == [0.0, 10.0]
    assert forecast.data["valid_time"].dtype == float


def test_herbie_conversion_crops_to_the_domain():
    forecast = herbie_forecast(min_lon=-10.0, max_lon=100.0, min_lat=5.0, max_lat=15.0)
    forecast.data = raw_grid()

    forecast._convert_data()

    assert forecast.data["longitude"].values.tolist() == [0.0, 90.0]
    # A single remaining latitude row is squeezed down to a scalar coordinate.
    assert forecast.data["latitude"].item() == 10.0


def test_herbie_conversion_pads_two_zero_filled_time_steps():
    forecast = herbie_forecast()
    forecast.data = raw_grid()
    last_real_time = pd.Timestamp("2025-01-15T03:00").timestamp()

    forecast._convert_data()

    valid_time = forecast.data["valid_time"].values
    assert valid_time.size == 4
    assert valid_time[1] == last_real_time
    assert valid_time[-2:] - last_real_time == pytest.approx(PADDING_SECONDS)
    assert np.all(forecast.data["u10"].values[-2:] == 0.0)
    assert np.all(forecast.data["u10"].values[:2] > 0.0)


def test_ensemble_read_uses_cfgrib_with_the_perturbed_members():
    forecast = EnsembleHerbieForecast("read", model="ifs", product="enfo", date=BASE_DATE)
    forecast.path = ["dummy.grib"]

    with patch("architeuthis.forecast.xr.open_mfdataset") as open_mfdataset:
        forecast._read_data()

    args, kwargs = open_mfdataset.call_args
    assert args == (["dummy.grib"],)
    assert kwargs["engine"] == "cfgrib"
    assert kwargs.get("filter_by_keys") == {"dataType": "pf"}
    assert forecast.data is open_mfdataset.return_value


def write_grib(path, fields, step):
    """
    Write GRIB2 fields at heights above ground, as one file of a Herbie download.

    Written with ecCodes directly: the writer of cfgrib relies on a private
    function that recent xarray versions removed.
    """
    import eccodes

    with open(path, "wb") as stream:
        for param_id, height, value in fields:
            message = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
            keys = {
                "Ni": 4,
                "Nj": 3,
                "latitudeOfFirstGridPointInDegrees": 50.0,
                "longitudeOfFirstGridPointInDegrees": -20.0,
                "latitudeOfLastGridPointInDegrees": 48.0,
                "longitudeOfLastGridPointInDegrees": -17.0,
                "iDirectionIncrementInDegrees": 1.0,
                "jDirectionIncrementInDegrees": 1.0,
                "dataDate": int(BASE_DATE.strftime("%Y%m%d")),
                "dataTime": 0,
                "step": step,
                "typeOfLevel": "heightAboveGround",
                "level": height,
                "paramId": param_id,
            }
            for key, key_value in keys.items():
                eccodes.codes_set(message, key, key_value)
            eccodes.codes_set_values(message, np.full(12, value))
            eccodes.codes_write(message, stream)
            eccodes.codes_release(message)
    return str(path)


def test_deterministic_read_merges_fields_at_different_heights(tmp_path):
    # As the IFS 10 m wind with the 2 m temperature, which cfgrib alone cannot merge.
    forecast = DeterministicHerbieForecast("read", model="ifs", product="oper", date=BASE_DATE)
    forecast.path = [
        write_grib(tmp_path / f"step_{step}.grib2", [(165, 10, 4.0 + step), (167, 2, 285.0 + step)], step)  # 10u, 2t
        for step in (0, 3)
    ]

    forecast._read_data()

    assert set(forecast.data.data_vars) == {"u10", "t2m"}
    assert "heightAboveGround" not in forecast.data.coords
    assert forecast.data.sizes["valid_time"] == 2
    assert forecast.data["u10"].mean(["latitude", "longitude"]).values == pytest.approx([4.0, 7.0])
    assert forecast.data["t2m"].mean(["latitude", "longitude"]).values == pytest.approx([285.0, 288.0])


def test_reading_the_gust_with_the_wind_gives_no_xarray_warning(tmp_path):
    # The IFS 10 m wind and gust: cfgrib merges them with a default of xarray that
    # is about to change, which warned once per field and file.
    import warnings

    path = write_grib(tmp_path / "step_3.grib2", [(165, 10, 4.0), (166, 10, 1.0), (49, 10, 11.0), (167, 2, 285.0)], 3)

    # Recorded, not raised: cfgrib catches any error of its merges.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = open_grib(path, backend_kwargs={"indexpath": ""}, decode_timedelta=False)

    assert not [warning for warning in caught if "future version of xarray" in str(warning.message)]
    assert set(data.data_vars) == {"u10", "v10", "fg10", "t2m"}
    assert float(data["fg10"].mean()) == pytest.approx(11.0)
    assert float(data["u10"].mean()) == pytest.approx(4.0)


def test_ensemble_interpolator_has_four_dimensions():
    forecast = EnsembleHerbieForecast("ensemble", model="ifs", product="enfo", date=BASE_DATE)
    member = [1.0, 2.0]
    axis = [0.0, 1.0]
    values = np.broadcast_to(np.array(member)[:, None, None, None], (2, 2, 2, 2))
    forecast.data = xr.Dataset(
        {"u10": (("number", "valid_time", "latitude", "longitude"), values)},
        coords={"number": member, "valid_time": axis, "latitude": axis, "longitude": axis},
    )

    forecast.add_interpolator("u10", "number", "valid_time", "latitude", "longitude")

    assert float(forecast("u10", np.array([[2.0, 0.5, 0.5, 0.5]]))) == pytest.approx(2.0)


def test_ensemble_is_queried_with_a_member():
    forecast = EnsembleHerbieForecast("ensemble", model="ifs", product="enfo", date=BASE_DATE)
    member = [1.0, 2.0]
    axis = [0.0, 1.0]
    values = np.broadcast_to(np.array(member)[None, :, None, None], (2, 2, 2, 2))
    forecast.data = xr.Dataset(
        {"u10": (("valid_time", "number", "latitude", "longitude"), values)},
        coords={"valid_time": axis, "number": member, "latitude": axis, "longitude": axis},
    )

    forecast.add_interpolator("u10", "valid_time", "number", "latitude", "longitude")
    query = {"valid_time": np.array([0.2, 0.8]), "member": 2.0, "latitude": 0.5, "longitude": 0.5}

    assert forecast.input_names("u10") == ["valid_time", "member", "latitude", "longitude"]
    assert np.asarray(forecast("u10", query)).ravel() == pytest.approx([2.0, 2.0])


# ------------------------------------------------------------------------------
# Copernicus Marine
# ------------------------------------------------------------------------------


def copernicus_forecast():
    return CopernicusForecast(
        "cmems",
        dataset="dummy-dataset",
        variables=["uo", "vo"],
        date=BASE_DATE,
        end=BASE_DATE + dt.timedelta(days=1),
    )


@pytest.fixture
def cmems_credentials(monkeypatch):
    monkeypatch.setenv("CMEMS_USER", "my-user")
    monkeypatch.setenv("CMEMS_PWD", "my-password")


@patch("architeuthis.forecast.copernicusmarine.subset")
def test_copernicus_downloads_the_requested_subset(subset, cmems_credentials):
    subset.return_value.file_path = "dummy.nc"
    forecast = copernicus_forecast()

    forecast._download_data()

    assert forecast.path == "dummy.nc"
    kwargs = subset.call_args.kwargs
    assert kwargs["username"] == "my-user"
    assert kwargs["password"] == "my-password"
    assert kwargs["dataset_id"] == "dummy-dataset"
    assert kwargs["variables"] == ["uo", "vo"]
    assert kwargs["start_datetime"] == BASE_DATE
    assert kwargs["skip_existing"] is True


@patch("architeuthis.forecast.copernicusmarine.subset")
def test_copernicus_credentials_are_read_when_downloading(subset, monkeypatch):
    forecast = copernicus_forecast()
    monkeypatch.setenv("COPERNICUSMARINE_SERVICE_USERNAME", "late-user")
    monkeypatch.setenv("COPERNICUSMARINE_SERVICE_PASSWORD", "late-password")

    forecast._download_data()

    assert subset.call_args.kwargs["password"] == "late-password"


def test_copernicus_object_holds_no_credential(cmems_credentials):
    forecast = copernicus_forecast()

    assert "my-password" not in repr(vars(forecast))


@patch("architeuthis.forecast.copernicusmarine.subset")
def test_copernicus_without_credentials_stops_before_downloading(subset, capsys):
    with pytest.raises(MissingCredentialError, match="CMEMS_USER, CMEMS_PWD"):
        copernicus_forecast()._download_data()

    subset.assert_not_called()
    assert "⚠️" in capsys.readouterr().out


@patch("architeuthis.forecast.copernicusmarine.subset")
def test_copernicus_login_file_is_left_to_the_toolbox(subset, monkeypatch, tmp_path):
    monkeypatch.setenv("COPERNICUSMARINE_CREDENTIALS_DIRECTORY", str(tmp_path))
    (tmp_path / ".copernicusmarine-credentials").write_text("")

    copernicus_forecast()._download_data()

    assert subset.call_args.kwargs["username"] is None
    assert subset.call_args.kwargs["password"] is None


def test_copernicus_conversion_renames_time_and_pads_it():
    forecast = copernicus_forecast()
    forecast.data = raw_grid(time_name="time")

    forecast._convert_data()

    assert "time" not in forecast.data.coords
    assert forecast.data["valid_time"].dtype == float
    assert forecast.data["valid_time"].size == 4
    assert np.all(forecast.data["u10"].values[-2:] == 0.0)


# ------------------------------------------------------------------------------
# Climate Data Store
# ------------------------------------------------------------------------------


def cds_forecast(**kwargs):
    arguments = {
        "products": "reanalysis",
        "variables": ["10m_u_component_of_wind"],
        "start": pd.Timestamp("2025-01-31T23:00"),
        "end": pd.Timestamp("2025-02-01T01:00"),
    }
    return CDSForecast("cds", "reanalysis-era5-single-levels", **{**arguments, **kwargs})


def test_cds_defaults_to_a_one_hour_window():
    forecast = cds_forecast(end=None)

    assert forecast.f99 == forecast.f00 + pd.Timedelta(1, unit="h")


def test_cds_request_covers_the_period_and_domain():
    forecast = cds_forecast(min_lon=-80.0, max_lon=0.0, min_lat=30.0, max_lat=60.0)

    forecast._generate_request()

    assert forecast.request["product_type"] == ["reanalysis"]
    assert forecast.request["month"] == ["01", "02"]
    assert forecast.request["day"] == ["01", "31"]
    assert forecast.request["time"] == ["00:00", "01:00", "23:00"]
    assert forecast.request["area"] == [60.0, -80.0, 30.0, 0.0]


def test_cds_reuses_a_cached_file(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_module, "_HOME", str(tmp_path))
    monkeypatch.setenv("CDS_API_KEY", "my-key")
    forecast = cds_forecast()

    with patch("architeuthis.forecast.cdsapi.Client") as client:
        client.return_value.retrieve.return_value = MagicMock()
        forecast._download_data()
        first_path = forecast.path
        client.return_value.retrieve.return_value.download.assert_called_once_with(target=first_path)

        open(first_path, "w").close()
        forecast._download_data()

    assert forecast.path == first_path
    assert first_path.endswith(".grib")
    client.return_value.retrieve.assert_called_once()


def test_cds_cache_key_depends_on_the_request(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_module, "_HOME", str(tmp_path))
    monkeypatch.setenv("CDS_API_KEY", "my-key")
    first, second = cds_forecast(), cds_forecast(max_lat=10.0)

    with patch("architeuthis.forecast.cdsapi.Client"):
        first._download_data()
        second._download_data()

    assert first.path != second.path


def test_cds_key_goes_to_the_client_and_never_to_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_module, "_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(forecast_module, "_USER_HOME", str(tmp_path))
    monkeypatch.setenv("CDS_API_KEY", "my-key")

    with patch("architeuthis.forecast.cdsapi.Client") as client:
        cds_forecast()._download_data()

    client.assert_called_once_with(url=forecast_module._CDS_URL, key="my-key")
    assert not (tmp_path / ".cdsapirc").exists()


def test_cds_without_key_uses_the_cdsapirc_of_the_user(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_module, "_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(forecast_module, "_USER_HOME", str(tmp_path))
    (tmp_path / ".cdsapirc").write_text("url: x\nkey: y\n")

    with patch("architeuthis.forecast.cdsapi.Client") as client:
        cds_forecast()._download_data()

    client.assert_called_once_with()


def test_cds_without_any_key_stops_before_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast_module, "_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(forecast_module, "_USER_HOME", str(tmp_path))

    with patch("architeuthis.forecast.cdsapi.Client") as client, pytest.raises(MissingCredentialError, match="CDS_API_KEY"):
        cds_forecast()._download_data()

    client.assert_not_called()


def test_cds_conversion_renames_time_without_padding():
    forecast = cds_forecast()
    forecast.data = raw_grid(time_name="time")

    forecast._convert_data()

    assert forecast.data["longitude"].values.tolist() == [-90.0, 0.0, 90.0]
    assert forecast.data["latitude"].values.tolist() == [0.0, 10.0]
    assert forecast.data["valid_time"].size == 2
    assert forecast.data["valid_time"].dtype == float


def projected_wind():
    """A wind on a Mercator grid without coordinates, as HRDPS is on its rotated grid."""
    longitude = np.linspace(-70.0, -45.0, 60)
    latitude = np.linspace(40.0, 52.0, 50)
    grid_longitude, grid_latitude = np.meshgrid(longitude, latitude)
    time = pd.date_range("2026-02-24", periods=3, freq="1h")
    return xr.Dataset(
        {"u10": (("valid_time", "y", "x"), np.stack([grid_longitude + 100.0 * hour for hour in range(3)]))},
        coords={
            "valid_time": time,
            "latitude": (("y", "x"), grid_latitude),
            "longitude": (("y", "x"), grid_longitude),
        },
    )


def test_regridding_gives_a_regular_grid_in_the_order_of_forecasts():
    latitude, longitude = np.arange(44.0, 48.0, 0.5), np.arange(-61.0, -53.0, 0.5)

    regridded = _regrid_to_lat_lon(projected_wind(), pyproj.CRS("EPSG:3857"), latitude, longitude, skip=1)

    assert regridded["u10"].dims == ("valid_time", "latitude", "longitude")
    assert regridded["latitude"].values.tolist() == latitude.tolist()
    assert regridded["longitude"].ndim == 1
    # The field is the longitude: it comes back within a grid step, 25 deg / 60 points.
    assert regridded["u10"].isel(valid_time=0).values == pytest.approx(
        np.broadcast_to(longitude, (latitude.size, longitude.size)), abs=1.0
    )
    assert regridded["u10"].isel(valid_time=2).mean().item() == pytest.approx(regridded["u10"].isel(valid_time=0).mean().item() + 200.0)


def test_hrdps_looks_for_its_latest_run_on_the_source_that_has_it():
    # The default of HerbieLatest is AWS and NOMADS, where HRDPS never is.
    herbie_latest = MagicMock(return_value=MagicMock(valid_date=pd.Timestamp("2026-02-24")))

    with patch("architeuthis.forecast.HerbieLatest", herbie_latest):
        forecast = HRDPSForecast("wind", fxx=[0], verbose=False)

    assert forecast.f00 == pd.Timestamp("2026-02-24")
    assert herbie_latest.call_args.kwargs["priority"] == ["msc"]


def test_hrdps_downloads_both_wind_components_of_its_run():
    calls = []

    class FakeFastHerbie:
        def __init__(self, dates, **kwargs):
            calls.append((dates, kwargs))

        def download(self):
            return [f"file_{calls[-1][1]['variable']}"]

    forecast = HRDPSForecast("wind", date="2026-02-24", fxx=[0, 1], verbose=False)

    with patch("architeuthis.forecast.FastHerbie", FakeFastHerbie):
        forecast._download_data()

    assert [kwargs["variable"] for _, kwargs in calls] == ["UGRD", "VGRD"]
    assert all(kwargs["level"] == "AGL-10m" and kwargs["model"] == "hrdps" and kwargs["fxx"] == [0, 1] for _, kwargs in calls)
    assert forecast.path == [["file_UGRD"], ["file_VGRD"]]


def test_hrdps_reads_and_regrids_with_the_projection_of_its_run():
    wind = projected_wind()

    class FakeHerbie:
        def __init__(self, *args, **kwargs):
            pass

        def xarray(self):
            return SimpleNamespace(herbie=SimpleNamespace(crs=pyproj.CRS("EPSG:3857")))

    forecast = HRDPSForecast(
        "wind",
        date="2026-02-24",
        fxx=[0],
        min_lon=-61.0,
        max_lon=-53.0,
        min_lat=44.0,
        max_lat=48.0,
        resolution=0.5,
        verbose=False,
    )
    forecast.path = [["u"], ["v"]]

    with (
        patch("architeuthis.forecast.Herbie", FakeHerbie),
        patch("architeuthis.forecast.xr.open_mfdataset", lambda paths, **kwargs: wind if paths == ["u"] else wind.rename(u10="v10")),
    ):
        forecast._read_data()

    forecast._convert_data()
    forecast._extend_data()

    assert {"u10", "v10"} <= set(forecast.data)
    assert forecast.data["latitude"].values[0] == 44.0
    assert forecast.data["longitude"].values[0] == -61.0
    # Epoch seconds, and two steps past the horizon where the field fades to zero.
    assert forecast.data["valid_time"].values[0] == pd.Timestamp("2026-02-24").timestamp()
    assert forecast.data["valid_time"].size == 3 + 2


class TestCalmForecast:
    @pytest.mark.parametrize("source", ["atmosphere", "wave", "current"])
    def test_its_fields_are_zero_at_each_point(self, source):
        calm = forecast_module.calm_forecast(source)
        query = {"valid_time": np.array([0.0, 3600.0, 7200.0]), "latitude": np.array([45.0, 46.0, 47.0]), "longitude": -5.0}

        assert calm.data is None
        assert calm.name == f"calm_{source}"
        assert set(calm.models) == set(forecast_module.ENVIRONMENT_FIELDS[source])
        for key in forecast_module.ENVIRONMENT_FIELDS[source]:
            assert calm.input_names(key) == ["valid_time", "latitude", "longitude"]
            assert np.array(calm(key, query)).ravel().tolist() == [0.0, 0.0, 0.0]

    def test_its_fields_are_symbolic_constants_of_a_symbolic_query(self):
        import casadi as ca

        calm = forecast_module.calm_forecast("atmosphere")
        latitude = ca.MX.sym("latitude", 4, 1)
        u10 = calm("u10", {"valid_time": ca.DM.zeros(4, 1), "latitude": latitude, "longitude": latitude})
        # No derivative, even of the direction of this zero wind
        direction = ca.atan2(u10, calm("v10", {"valid_time": 0.0, "latitude": latitude, "longitude": latitude}))

        assert u10.shape == (4, 1)
        # Symbolic, so that the routing does not hand DM to NumPy functions
        assert isinstance(u10, ca.MX)
        assert float(ca.evalf(u10[0])) == 0.0
        assert ca.jacobian(direction, latitude).nnz() == 0

    def test_other_models_can_be_added(self):
        calm = forecast_module.calm_forecast("atmosphere", name="still_air")
        calm.add_constant("t2m", 288.0)

        assert calm.name == "still_air"
        assert float(calm("t2m", {"valid_time": 0.0, "latitude": 45.0, "longitude": -5.0})) == 288.0

    def test_an_unknown_source_is_refused(self):
        with pytest.raises(ValueError, match="atmosphere"):
            forecast_module.calm_forecast("topography")

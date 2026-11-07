import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import xarray as xr

import architeuthis.forecast as forecast_module
from architeuthis.forecast import Topography

SEA_DEPTH = -100.0
LAND_HEIGHT = 50.0


def elevation_grid(elevation):
    """Wrap a (lat, lon) elevation array on a 1-degree grid, as read from ETOPO."""
    elevation = np.asarray(elevation, dtype=float)
    latitude = np.arange(elevation.shape[0], dtype=float)
    longitude = np.arange(elevation.shape[1], dtype=float)
    return xr.Dataset(
        {"z": (("lat", "lon"), elevation)},
        coords={"lat": latitude, "lon": longitude},
    )


def half_land_grid():
    """Sea on the five western columns, land on the five eastern ones."""
    elevation = np.full((5, 10), SEA_DEPTH)
    elevation[:, 5:] = LAND_HEIGHT
    return elevation_grid(elevation)


def converted(data, **kwargs):
    topography = Topography("topography", verbose=False, **kwargs)
    topography.data = data
    topography._convert_data()
    return topography


def test_distance_is_positive_on_land_and_negative_at_sea():
    distance = converted(half_land_grid()).data["distance_to_iso0"].values

    assert np.all(distance[:, :5] < 0.0)
    assert np.all(distance[:, 5:] > 0.0)


def test_distance_is_in_nautical_miles_and_grows_away_from_the_coast():
    distance = converted(half_land_grid()).data["distance_to_iso0"].values
    nautical_miles_per_longitude_degree = 60.0 * np.cos(np.radians(2.0))

    assert distance[2, 4] == pytest.approx(-nautical_miles_per_longitude_degree)
    assert distance[2, 0] == pytest.approx(-5.0 * nautical_miles_per_longitude_degree)


def test_depth_offset_treats_shallow_water_as_land():
    elevation = np.full((5, 10), SEA_DEPTH)
    elevation[:, 5:] = -5.0
    grid = elevation_grid(elevation)

    assert np.all(converted(grid.copy(deep=True)).data["distance_to_iso0"].values < 0.0)
    distance = converted(grid.copy(deep=True), depth_offset=10.0).data["distance_to_iso0"].values
    assert np.all(distance[:, 5:] > 0.0)


def test_z_margin_shifts_the_whole_field():
    reference = converted(half_land_grid()).data["distance_to_iso0"].values
    shifted = converted(half_land_grid(), z_margin=7.0).data["distance_to_iso0"].values

    assert shifted == pytest.approx(reference + 7.0)


def test_exclusion_zone_is_treated_as_land():
    zone = [[0.5, 0.5], [0.5, 2.5], [3.5, 2.5], [3.5, 0.5], [0.5, 0.5]]  # [lat, lon]

    distance = converted(half_land_grid(), exclusion_zones=[zone]).data["distance_to_iso0"].values

    assert distance[2, 1] > 0.0
    assert distance[2, 3] < 0.0


def test_conversion_wraps_longitudes_and_crops_the_domain():
    elevation = np.full((3, 4), SEA_DEPTH)
    data = xr.Dataset(
        {"z": (("lat", "lon"), elevation)},
        coords={"lat": [20.0, 10.0, 0.0], "lon": [0.0, 90.0, 180.0, 270.0]},
    )

    result = converted(data, min_lon=-100.0, max_lon=100.0, min_lat=5.0).data

    assert result["lon"].values.tolist() == [-90.0, 0.0, 90.0]
    assert result["lat"].values.tolist() == [10.0, 20.0]


def test_interpolator_exposes_the_distance_as_z():
    topography = converted(half_land_grid())

    topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

    assert float(topography("z", np.array([[2.0, 0.0]]))) < 0.0
    assert float(topography("z", np.array([[2.0, 9.0]]))) > 0.0


def test_located_path_is_under_the_data_directory(monkeypatch):
    monkeypatch.setattr(forecast_module, "_HOME", "home")
    topography = Topography("topography")

    topography._locate_data()

    assert topography.path == os.path.join("home", "topo", "ETOPO_2022_v1_60s_N90W180_surface.nc")


def test_existing_file_is_not_downloaded_again(tmp_path):
    topography = Topography("topography")
    topography.path = tmp_path / "topography.nc"
    topography.path.touch()

    with patch("architeuthis.forecast.requests.get") as get:
        topography._download_data()

    get.assert_not_called()


def test_missing_file_is_downloaded(tmp_path):
    topography = Topography("topography")
    topography.path = tmp_path / "topography.nc"
    response = MagicMock()
    response.iter_content.return_value = [b"abc", b"", b"def"]

    with patch("architeuthis.forecast.requests.get") as get:
        get.return_value.__enter__.return_value = response
        topography._download_data()

    response.raise_for_status.assert_called_once()
    assert topography.path.read_bytes() == b"abcdef"


def test_empty_exclusion_zone_is_ignored():
    # The iceberg zone is empty when no IIP bulletin could be fetched.
    distance = converted(half_land_grid(), exclusion_zones=[[]]).data["distance_to_iso0"].values

    assert np.array_equal(distance, converted(half_land_grid()).data["distance_to_iso0"].values)

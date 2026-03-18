# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 10:52:01 2026

@author: jrich
"""

import pytest
from unittest.mock import patch, MagicMock

import architeuthis.numpy as np

# Adjust import to match your module name
from architeuthis.vessel import Vessel


@pytest.fixture
def dummy_columns():
    return ["bhp", "max_bhp", "leeway"]


@pytest.fixture
def dummy_points():
    return np.array([
        [6., 15., 60., 4.1, 60.],
        [8., 15., 60., 1.0, 60.],
    ])


def test_vessel_raises_if_no_filepath():
    with pytest.raises(ValueError):
        Vessel(filepath=None)


@patch("vessel.build_interpolators_dict_from_path")
def test_interpolator_is_built(mock_builder, dummy_columns):
    mock_interp = {
        "bhp": MagicMock(),
        "max_bhp": MagicMock(),
        "leeway": MagicMock(),
    }
    mock_builder.return_value = mock_interp

    vessel = Vessel(
        filepath="dummy.nc",
        columns=dummy_columns,
        method="bspline",
    )

    mock_builder.assert_called_once_with(
        "dummy.nc",
        columns=dummy_columns,
        method="bspline",
    )

    assert vessel.interpolator is mock_interp


@patch("vessel.build_interpolators_dict_from_path")
def test_call_with_explicit_column(
    mock_builder,
    dummy_columns,
    dummy_points,
):
    mock_func = MagicMock(return_value=42.0)

    mock_builder.return_value = {
        "bhp": mock_func,
    }

    vessel = Vessel(
        filepath="dummy.nc",
        columns=dummy_columns,
    )

    result = vessel(dummy_points, col="bhp")

    mock_func.assert_called_once()
    np.testing.assert_array_equal(
        mock_func.call_args.args[0],
        np.transpose(dummy_points),
    )

    assert result == 42.0


@patch("vessel.build_interpolators_dict_from_path")
def test_call_uses_first_column_by_default(
    mock_builder,
    dummy_columns,
    dummy_points,
):
    mock_func = MagicMock(return_value=3.14)

    mock_builder.return_value = {
        "bhp": mock_func,
        "max_bhp": MagicMock(),
        "leeway": MagicMock(),
    }

    vessel = Vessel(
        filepath="dummy.nc",
        columns=dummy_columns,
    )

    result = vessel(dummy_points)

    mock_func.assert_called_once()
    assert result == 3.14

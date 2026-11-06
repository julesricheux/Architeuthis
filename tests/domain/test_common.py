import casadi as ca
import numpy as np
import pytest
import xarray as xr

from architeuthis.common import ArchiteuthisData, ArchiteuthisObject


class Table(ArchiteuthisData):
    """Minimal concrete data object holding `value = x + 10 * y`."""

    def __init__(self, values=None):
        super().__init__("table", verbose=False)
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([0.0, 1.0])
        if values is None:
            values = x[:, None] + 10.0 * y[None, :]
        self.data = xr.Dataset(
            {"value": (("x", "y"), values)},
            coords={"x": x, "y": y},
        )

    def add(self, var_key="value", x_slice=slice(None), y_slice=slice(None), **kwargs):
        self.add_interpolator("value", ["x", "y"], [x_slice, y_slice], var_key, **kwargs)


def evaluate(table, *queries, var_key="value"):
    return np.asarray(table(var_key, np.array(queries))).ravel()


def test_abstract_classes_cannot_be_instantiated():
    with pytest.raises(TypeError):
        ArchiteuthisObject("object", verbose=False)
    with pytest.raises(TypeError):
        ArchiteuthisData("data", verbose=False)


def test_load_data_runs_the_pipeline_in_order():
    calls = []

    class Recorder(ArchiteuthisData):
        def __init__(self):
            super().__init__("recorder", verbose=False)

        def _locate_data(self):
            calls.append("locate")

        def _download_data(self):
            calls.append("download")

        def _read_data(self):
            calls.append("read")

        def _convert_data(self):
            calls.append("convert")

        def _extend_data(self):
            calls.append("extend")

    Recorder().load_data()

    assert calls == ["locate", "download", "read", "convert", "extend"]


def test_interpolator_respects_dimension_order_on_non_square_data():
    table = Table()
    table.add()

    # Values differ for every (x, y), so a wrong raveling order cannot pass.
    assert evaluate(table, [2.0, 1.0], [1.0, 0.0]) == pytest.approx([12.0, 1.0])


def test_interpolator_is_linear_between_grid_points():
    table = Table()
    table.add()

    assert evaluate(table, [0.5, 0.5]) == pytest.approx([5.5])


def test_call_returns_one_row_per_query():
    table = Table()
    table.add()

    result = table("value", np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]]))

    assert result.shape == (3, 1)


def test_nan_is_replaced_by_zero():
    values = np.full((3, 2), np.nan)
    values[0, 0] = 1.0
    table = Table(values)
    table.add()

    assert evaluate(table, [0.0, 0.0], [2.0, 1.0]) == pytest.approx([1.0, 0.0])


def test_correction_factor_scales_the_values():
    table = Table()
    table.add(fac=2.0)

    assert evaluate(table, [2.0, 1.0]) == pytest.approx([24.0])


def test_coordinate_slices_subsample_the_grid():
    table = Table()
    table.add(x_slice=slice(None, None, 2))

    # Only x = 0 and x = 2 remain, and the field is linear in x.
    assert evaluate(table, [1.0, 1.0]) == pytest.approx([11.0])


def test_adding_an_existing_key_keeps_the_first_interpolator():
    table = Table()
    table.add(fac=1.0)
    table.add(fac=100.0)

    assert evaluate(table, [1.0, 0.0]) == pytest.approx([1.0])


def test_remove_interpolator():
    table = Table()
    table.add()

    table.remove_interpolator("value")

    assert table.interpolators == {}
    assert table.var_keys == set()


def test_call_without_interpolators_returns_none():
    assert Table()("value", np.array([[0.0, 0.0]])) is None


def test_interpolator_is_differentiable():
    table = Table()
    table.add()
    query = ca.MX.sym("query", 1, 2)

    gradient = ca.Function("gradient", [query], [ca.jacobian(table("value", query), query)])

    assert np.asarray(gradient([0.5, 0.5])).ravel() == pytest.approx([1.0, 10.0])

import logging

import casadi as ca
import numpy as np
import pytest
import xarray as xr

from architeuthis import common
from architeuthis.common import (
    ArchiteuthisData,
    ArchiteuthisObject,
    ensure_cdsapirc,
    set_status_sink,
    setup_logging,
    status,
)


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


# ------------------------------------------------------------------------------
# Status messages
# ------------------------------------------------------------------------------


@pytest.fixture
def default_sink():
    yield
    set_status_sink(None)


def test_status_is_printed_by_default(capsys, default_sink):
    status("done")

    assert capsys.readouterr().out == "done\n"


def test_status_can_go_elsewhere(capsys, default_sink):
    messages = []
    set_status_sink(messages.append)

    status("done")

    assert messages == ["done"]
    assert capsys.readouterr().out == ""


def test_status_can_be_restored(capsys, default_sink):
    set_status_sink(lambda message: None)
    set_status_sink(None)

    status("back")

    assert capsys.readouterr().out == "back\n"


def test_objects_report_through_status(default_sink):
    messages = []
    set_status_sink(messages.append)
    table = Table()
    table.add_interpolator("value", ["x", "y"], [slice(None), slice(None)], "value", "linear")

    table.remove_interpolator("value")

    assert any("value" in message for message in messages)


# ------------------------------------------------------------------------------
# Setup on first use
# ------------------------------------------------------------------------------


@pytest.fixture
def clean_logging(monkeypatch):
    # The logging plugin of pytest adds its handlers around each phase of a test, so the tests
    # empty the list themselves, through this function.
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    monkeypatch.setattr(common, "_credentials_reported", False)

    def clean(*new_handlers):
        root.handlers[:] = new_handlers
        return root

    yield clean
    root.handlers[:] = handlers
    root.setLevel(level)


def test_setup_logging_configures_the_console(clean_logging):
    root = clean_logging()

    setup_logging()

    assert len(root.handlers) == 1
    assert root.level == logging.INFO


def test_setup_logging_keeps_the_logging_of_the_application(clean_logging):
    handler = logging.NullHandler()
    root = clean_logging(handler)

    setup_logging()

    assert root.handlers == [handler]


def test_setup_logging_can_force_its_configuration(clean_logging):
    handler = logging.NullHandler()
    root = clean_logging(handler)

    setup_logging(level=logging.WARNING, force=True)

    assert handler not in root.handlers
    assert root.level == logging.WARNING


def test_missing_credentials_are_reported_once(clean_logging, monkeypatch):
    messages = []
    monkeypatch.setattr(common.log, "info", messages.append)
    clean_logging()

    setup_logging()
    setup_logging()

    assert sum("CDS API key" in message for message in messages) == 1


def test_load_data_sets_logging_up(clean_logging):
    root = clean_logging()

    Table().load_data()

    assert len(root.handlers) == 1


class TestCdsapirc:
    @pytest.fixture
    def path(self, monkeypatch, tmp_path):
        path = tmp_path / ".cdsapirc"
        monkeypatch.setattr(common, "file_path", str(path))
        return path

    def test_written_from_the_key(self, path, monkeypatch):
        monkeypatch.setattr(common, "_CDS_API_KEY", "my-key")

        ensure_cdsapirc()

        assert "key: my-key" in path.read_text()

    def test_existing_file_is_kept(self, path, monkeypatch):
        monkeypatch.setattr(common, "_CDS_API_KEY", "my-key")
        path.write_text("mine")

        ensure_cdsapirc()

        assert path.read_text() == "mine"

    def test_never_written_without_a_key(self, path, monkeypatch, capsys):
        # It used to be written at import with `key: None`, which then hid the real problem.
        monkeypatch.setattr(common, "_CDS_API_KEY", None)

        ensure_cdsapirc()

        assert not path.exists()
        assert "CDS_API_KEY is not set" in capsys.readouterr().out

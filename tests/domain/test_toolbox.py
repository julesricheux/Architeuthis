import importlib
import json

import numpy as np
import pytest

from architeuthis.toolbox.chart_utils import density_from_zoom
from architeuthis.toolbox.inspect_tools import ensure_callable
from architeuthis.toolbox.string_formatting import get_request_id


@pytest.fixture
def json_wrapper(tmp_path, monkeypatch):
    # Importing this module makes dash_extensions write assets/dashExtensions_default.js
    # in the working directory, which must not be the repository.
    monkeypatch.chdir(tmp_path)
    return importlib.import_module("architeuthis.wrappers.json_wrapper")


def test_package_exposes_the_optimizer():
    import architeuthis
    from architeuthis.optimization import Opti, OptiSol

    assert architeuthis.Opti is Opti
    assert architeuthis.OptiSol is OptiSol


@pytest.mark.parametrize("value", [3, 3.5])
def test_ensure_callable_wraps_numbers(value):
    assert ensure_callable(value)("any", keyword="argument") == value


def test_ensure_callable_keeps_callables():
    assert ensure_callable(abs) is abs


def test_request_id_ignores_dict_and_set_ordering():
    first = {"variable": {"u10", "v10"}, "area": [60, -80]}
    second = {"area": [60, -80], "variable": {"v10", "u10"}}

    assert get_request_id(first) == get_request_id(second)


def test_request_id_keeps_list_ordering_meaningful():
    assert get_request_id({"area": [60, -80]}) != get_request_id({"area": [-80, 60]})


def test_request_id_refuses_unstable_objects():
    with pytest.raises(TypeError):
        get_request_id({"unsupported": object()})


def test_report_arrays_survive_a_json_round_trip(json_wrapper):
    report = {
        "lat": np.array([46.5, 47.0]),
        "nodes": np.int64(20),
        "fuel": 38.5,
    }

    encoded = json.dumps(report, cls=json_wrapper.CustomEncoder)
    decoded = json.loads(encoded, object_hook=json_wrapper.custom_decoder)

    assert isinstance(decoded["lat"], np.ndarray)
    assert decoded["lat"].tolist() == [46.5, 47.0]
    assert isinstance(decoded["nodes"], np.int64)
    assert decoded["nodes"] == 20
    assert decoded["fuel"] == 38.5


def test_density_decreases_when_zooming_in():
    assert density_from_zoom(1) > density_from_zoom(10) >= 1

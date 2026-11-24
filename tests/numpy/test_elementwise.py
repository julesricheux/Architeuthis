"""
The element-wise functions of architeuthis.numpy on CasADi values.

Created on Tue Nov 24 2026
"""

import warnings

import casadi as cas
import numpy as onp
import pytest

import architeuthis.numpy as np
from architeuthis.numpy import elementwise

UNARY = [name for name in elementwise.__all__ if name not in ("arctan2", "fmax", "fmin", "hypot")]
BINARY = ["arctan2", "fmax", "fmin", "hypot"]
DOMAIN = {"arccosh": (1.5, 3.0), "arcsin": (-0.5, 0.5), "arccos": (-0.5, 0.5), "arctanh": (-0.5, 0.5)}


def values(name):
    low, high = DOMAIN.get(name, (0.2, 0.9))
    return onp.linspace(low, high, 4)


@pytest.mark.parametrize("name", elementwise.__all__)
def test_the_package_gives_the_wrapped_function(name):
    """
    `np.<name>` is the wrapper, not NumPy's.
    """
    assert getattr(np, name) is getattr(elementwise, name)


@pytest.mark.parametrize("name", UNARY + BINARY)
def test_casadi_values_give_no_warning_and_the_numpy_result(name):
    """
    MX and DM give NumPy's values, without casadi's FutureWarning.
    """
    function = getattr(np, name)
    reference = getattr(onp, name)
    count = 2 if name in BINARY else 1
    numbers = [values(name)[::-1] if k else values(name) for k in range(count)]
    symbols = [cas.MX.sym(f"x{k}", 4) for k in range(count)]
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        expression = function(*symbols)
        numeric = function(*(cas.DM(number) for number in numbers))
    assert isinstance(expression, cas.MX)
    evaluated = cas.Function("f", symbols, [expression])(*numbers)
    expected = reference(*numbers)
    assert onp.allclose(onp.ravel(evaluated.full()), expected)
    assert isinstance(numeric, onp.ndarray)
    assert onp.allclose(numeric.ravel(), expected)


def test_numbers_and_arrays_stay_numpy():
    """
    Plain numbers and arrays go to NumPy unchanged.
    """
    assert np.sqrt(4.0) == 2.0
    assert onp.array_equal(np.fmax(onp.array([1.0, -1.0]), 0.0), [1.0, 0.0])


def test_degree_functions_take_symbols_without_warning():
    """
    sind, cosd and arctan2d of the package give no warning on MX.
    """
    x = cas.MX.sym("x")
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        expression = np.arctan2d(np.sind(x), np.cosd(x))
    assert float(cas.Function("f", [x], [expression])(30.0)) == pytest.approx(30.0)

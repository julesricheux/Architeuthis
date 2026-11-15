"""
Tests of HybridInterpolator, checked against InterpolatedModel.

Created on 2026-11-15
"""
import pickle

import casadi as ca
import numpy as onp
import pytest

import architeuthis as asb
import architeuthis.numpy as np
from architeuthis.modeling import HybridInterpolator, InterpolatedModel
from architeuthis.modeling.surrogate_model import SurrogateModel


def f2(x1, x2):
    """
    Smooth function sampled on the 2D grid.
    """
    return x1**2 + (x2 + 1) ** 2


X1 = np.linspace(0, 10, 11)
X2 = np.linspace(0, 10, 21)
XX1, XX2 = np.meshgrid(X1, X2, indexing="ij")
COORDS = {"x1": X1, "x2": X2}
VALUES = f2(XX1, XX2)


def models(method, fill_value=np.nan):
    """
    The hybrid and reference models built from the same data.
    """
    kwargs = dict(
        x_data_coordinates=COORDS,
        y_data_structured=VALUES,
        method=method,
        fill_value=fill_value,
    )
    return HybridInterpolator(**kwargs), InterpolatedModel(**kwargs)


def test_is_a_surrogate_model():
    hybrid, reference = models("bspline")
    assert isinstance(hybrid, SurrogateModel)
    assert hybrid.input_names() == reference.input_names() == ["x1", "x2"]
    assert hybrid.input_dimensionality() == 2
    assert onp.array_equal(hybrid.y_data, reference.y_data)
    for k in COORDS:
        assert onp.array_equal(hybrid.x_data[k], reference.x_data[k])


def test_default_arguments_match():
    hybrid = HybridInterpolator(COORDS, VALUES)
    reference = InterpolatedModel(COORDS, VALUES)
    assert hybrid.method == reference.method == "bspline"
    assert onp.isnan(hybrid.fill_value) and onp.isnan(reference.fill_value)


@pytest.mark.parametrize("method", ["linear", "nearest"])
def test_same_values_as_interpolated_model(method):
    hybrid, reference = models(method)
    x = {"x1": onp.array([1.5, 2.25, 9.9]), "x2": onp.array([2.5, 3.7, 0.1])}
    assert hybrid(x) == pytest.approx(reference(x))


def test_bspline_is_close_to_function():
    hybrid, _ = models("bspline")
    x = {"x1": onp.array([1.5, 2.25, 9.9]), "x2": onp.array([2.5, 3.7, 0.1])}
    # Quadratic data: a cubic spline reproduces it
    assert hybrid(x) == pytest.approx(f2(*x.values()))


@pytest.mark.parametrize(
    "x",
    [
        {"x1": 5.5, "x2": 5.5},
        {"x1": onp.array([1.5, 2.5]), "x2": onp.array([2.5, 3.5])},
        {"x1": 2.0, "x2": onp.array([2.5, 3.5, 4.5])},
        {"x1": onp.full((3, 4), 2.0), "x2": onp.full((3, 4), 3.0)},
    ],
)
def test_same_output_types_as_interpolated_model(x):
    hybrid, reference = models("linear")
    out, ref = hybrid(x), reference(x)
    assert type(out) is type(ref)
    assert onp.shape(out) == onp.shape(ref)
    assert out == pytest.approx(ref)


@pytest.mark.parametrize("method", ["linear", "bspline"])
def test_numpy_and_casadi_agree(method):
    hybrid, _ = models(method, fill_value=None)
    rng = onp.random.default_rng(0)
    x1, x2 = rng.uniform(-2, 12, (2, 50))  # Inside and outside the grid
    numeric = hybrid({"x1": x1, "x2": x2})
    dm = hybrid({"x1": ca.DM(x1), "x2": ca.DM(x2)})

    s = ca.MX.sym("s", 2)
    symbolic = ca.Function("f", [s], [hybrid({"x1": s[0], "x2": s[1]})])
    pointwise = [float(symbolic([a, b])) for a, b in zip(x1, x2)]

    assert dm == pytest.approx(numeric, rel=1e-10)
    assert pointwise == pytest.approx(numeric, rel=1e-10)


def test_fill_value_on_both_sides():
    hybrid, reference = models("linear", fill_value=-1.0)
    x = {"x1": onp.array([-1.0, 5.0, 11.0]), "x2": onp.array([5.0, 5.0, 5.0])}
    expected = [-1.0, f2(5.0, 5.0), -1.0]
    assert hybrid(x) == pytest.approx(expected)
    assert reference(x) == pytest.approx(expected)
    dm = hybrid({k: ca.DM(v) for k, v in x.items()})
    assert dm == pytest.approx(expected)


def test_extrapolation_with_fill_value_none():
    linear, _ = models("linear", fill_value=None)
    bspline, _ = models("bspline", fill_value=None)
    nearest, _ = models("nearest", fill_value=None)
    x = {"x1": 12.0, "x2": 5.0}
    assert linear(x) == pytest.approx(f2(10.0, 5.0) + 2 * (100 - 81))
    assert bspline(x) == pytest.approx(f2(10.0, 5.0))
    assert nearest(x) == pytest.approx(f2(10.0, 5.0))


def test_one_dimensional_input():
    x = np.linspace(0, 1, 11)
    hybrid = HybridInterpolator(x, x**2, method="linear")
    reference = InterpolatedModel(x, x**2, method="linear")
    for query in (0.25, onp.array([0.25, 0.5]), ca.DM([0.25, 0.5])):
        out, ref = hybrid(query), reference(query)
        assert type(out) is type(ref)
        assert out == pytest.approx(ref)
    s = ca.MX.sym("s", 3)
    assert hybrid(s).shape == reference(s).shape


def test_nearest_rejects_symbolic_inputs():
    hybrid, _ = models("nearest")
    with pytest.raises(TypeError):
        hybrid({"x1": ca.MX.sym("a"), "x2": 1.0})


def test_invalid_inputs():
    with pytest.raises(ValueError):
        HybridInterpolator(COORDS, VALUES.T)
    with pytest.raises(ValueError):
        HybridInterpolator(COORDS, VALUES, method="cubic")
    hybrid, _ = models("linear")
    with pytest.raises(TypeError):
        hybrid(onp.array([1.0, 2.0]))  # A dict is expected


def test_pickle():
    hybrid, _ = models("bspline")
    x = {"x1": 3.3, "x2": 4.4}
    clone = pickle.loads(pickle.dumps(hybrid))
    assert clone(x) == pytest.approx(hybrid(x))
    s = ca.MX.sym("s")
    assert float(ca.Function("f", [s], [clone({"x1": s, "x2": 4.4})])(3.3)) == (
        pytest.approx(hybrid(x))
    )


def test_optimize_through_hybrid_interpolator():
    hybrid, _ = models("bspline", fill_value=None)
    opti = asb.Opti()
    x1 = opti.variable(init_guess=5.0, lower_bound=0, upper_bound=10)
    x2 = opti.variable(init_guess=5.0, lower_bound=0, upper_bound=10)
    opti.minimize(hybrid({"x1": x1, "x2": x2}) + (x1 - 3) ** 2)
    sol = opti.solve(verbose=False, options={"ipopt.linear_solver": "mumps"})
    # x1 ** 2 + (x1 - 3) ** 2 is minimal at 1.5; x2 runs to its lower bound
    assert sol(x1) == pytest.approx(1.5, abs=1e-4)
    assert sol(x2) == pytest.approx(0.0, abs=1e-4)


if __name__ == "__main__":
    pytest.main([__file__])

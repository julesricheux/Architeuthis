"""
Gridded interpolation built once, consistent on NumPy and CasADi inputs.

HybridInterpolator has the interface of InterpolatedModel, but builds its
NumPy and CasADi interpolators once, from the same data, instead of at
every call, so that both sides give the same values.
"""
from typing import Literal

import casadi as ca
import numpy as _onp
from scipy.interpolate import NdBSpline, RegularGridInterpolator, make_interp_spline

import architeuthis.numpy as np
from architeuthis.modeling.surrogate_model import SurrogateModel


class HybridInterpolator(SurrogateModel):
    """
    Model interpolated on gridded N-dimensional data, R^N -> R^1.

    It is called like InterpolatedModel, with the same inputs and the
    same output types and shapes:

    >>> y = my_hybrid_interpolator(x)

    where `x` is a dict of floats or arrays keyed by axis name, or, for
    a 1D model built from a single array, a float or an array. Values
    of a dict are broadcast against each other. CasADi inputs (DM, SX,
    MX) are allowed, and a symbolic input gives a symbolic output.

    Unlike InterpolatedModel, which builds a new CasADi interpolant at
    each call and evaluates NumPy inputs with SciPy, it builds both
    evaluators once, from the same data. They give the same values: for
    "bspline", both use the same tensor-product B-spline coefficients,
    fitted with SciPy.

    Example:
        >>> x1 = np.linspace(0, 5, 11)
        >>> x2 = np.linspace(0, 10, 21)
        >>> X1, X2 = np.meshgrid(x1, x2, indexing="ij")
        >>> model = HybridInterpolator(
        ...     x_data_coordinates={"x1": x1, "x2": x2},
        ...     y_data_structured=X1**2 + X2,
        ... )
        >>> model({"x1": 2.5, "x2": np.array([1.0, 2.0])})
    """

    def __init__(
        self,
        x_data_coordinates: np.ndarray | dict[str, np.ndarray],
        y_data_structured: np.ndarray,
        method: Literal["bspline", "linear", "nearest"] = "bspline",
        fill_value=np.nan,
        degree: int = 3,
        name: str = "hybrid_interpolator",
    ):
        """
        Args:
            x_data_coordinates: Coordinates of each axis of the grid: a
                dict of 1D arrays keyed by axis name or, in 1D, a single
                1D array. Each axis is strictly ascending.
            y_data_structured: Gridded values, of shape
                `tuple(len(c) for c in x_data_coordinates.values())`.
            method: "bspline" (C2 for degree 3, suitable for
                optimization), "linear" (C0) or "nearest" (NumPy and DM
                inputs only: no CasADi plugin and no useful gradient).
            fill_value: Value returned outside the grid. If None,
                "linear" extrapolates, "bspline" keeps the value at the
                boundary and "nearest" takes the nearest grid point.
            degree: B-spline degree, reduced along any axis that has
                too few points.
            name: Name of the CasADi function.
        """
        try:
            x_data_coordinates_values = tuple(x_data_coordinates.values())
        except AttributeError:  # If x_data_coordinates is not a dict
            x_data_coordinates_values = (x_data_coordinates,)
        x_data_coordinates_values = tuple(
            _onp.asarray(coordinates, dtype=float)
            for coordinates in x_data_coordinates_values
        )
        y_data_structured = _onp.asarray(y_data_structured, dtype=float)

        ### Validate inputs
        for coordinates in x_data_coordinates_values:
            if coordinates.ndim != 1:
                raise ValueError(
                    "`x_data_coordinates` must be a dict of 1D arrays "
                    "or, in the 1D case, a single 1D array."
                )
        implied_y_data_shape = tuple(
            len(coordinates) for coordinates in x_data_coordinates_values
        )
        if y_data_structured.shape != implied_y_data_shape:
            raise ValueError(
                f"The shape of `y_data_structured` should be "
                f"{implied_y_data_shape}, not {y_data_structured.shape}."
            )
        if method not in ("bspline", "linear", "nearest"):
            raise ValueError(
                f"{method=!r} is not a valid option. "
                f"Valid options are: 'linear', 'bspline', 'nearest'."
            )

        ### Store data, as InterpolatedModel does
        self.x_data_coordinates = x_data_coordinates
        self.x_data_coordinates_values = x_data_coordinates_values
        self.y_data_structured = y_data_structured
        self.method = method
        self.fill_value = fill_value
        self.degree = degree
        self.name = name

        ### Unstructured versions of the data, for plotting, etc.
        x_data = x_data_coordinates
        if isinstance(x_data, dict):
            x_data_values = _onp.meshgrid(*x_data_coordinates_values, indexing="ij")
            x_data = {
                k: v.reshape(-1)
                for k, v in zip(x_data_coordinates.keys(), x_data_values)
            }
        self.x_data = x_data
        self.y_data = _onp.ravel(y_data_structured, order="F")

        ### Build both evaluators once
        self._lower = _onp.array([c[0] for c in x_data_coordinates_values])
        self._upper = _onp.array([c[-1] for c in x_data_coordinates_values])
        grids = list(x_data_coordinates_values)

        if method == "bspline":
            degrees = [min(degree, len(g) - 1) for g in grids]
            coefficients, knots = y_data_structured, []
            for axis, (grid, k) in enumerate(zip(grids, degrees)):
                spline = make_interp_spline(grid, coefficients, k=k, axis=axis)
                # SciPy moves the fitted axis to the front: put it back
                coefficients = _onp.moveaxis(spline.c, 0, axis)
                knots.append(spline.t)
            self._numpy_function = NdBSpline(
                tuple(knots), coefficients, tuple(degrees)
            )
            self._casadi_function = ca.Function.bspline(
                name,
                [list(t) for t in knots],
                coefficients.ravel(order="F").tolist(),  # CasADi uses Fortran order
                degrees,
                1,
            )
        else:
            # fill_value=None: extrapolate, as the CasADi linear interpolant
            # does; the fill value itself is applied in _interpolate_*.
            self._numpy_function = RegularGridInterpolator(
                grids,
                y_data_structured,
                method=method,
                bounds_error=False,
                fill_value=None,
            )
            self._casadi_function = (
                ca.interpolant(
                    name,
                    "linear",
                    grids,
                    self.y_data,
                )
                if method == "linear"
                else None
            )

    @property
    def ndim(self) -> int:
        """
        Number of input dimensions of the model.

        Returns:
            The number of axes of the grid.
        """
        return len(self.x_data_coordinates_values)

    def __call__(self, x):
        """
        Evaluate the model.

        Args:
            x: A dict of floats or arrays keyed by axis name, broadcast
                against each other or, for a 1D model built from a
                single array, a float or an array. NumPy or CasADi.

        Returns:
            The interpolated values, as InterpolatedModel returns them:
            with a dict input, a NumPy array of the broadcast shape of
            the values, or a CasADi column for a symbolic input. With a
            non-dict input, a 1D NumPy array, a float for a scalar DM,
            or a CasADi column for a symbolic input.
        """
        super().__call__(x)  # Type checking against x_data

        ### Same input handling as InterpolatedModel
        if isinstance(self.x_data_coordinates, dict):

            def get_shape(value):
                if np.is_casadi_type(value, recursive=False):
                    if value.shape[1] == 1:
                        return (np.length(value),)

                try:
                    return value.shape
                except AttributeError:
                    return tuple()

            shape = np.broadcast_shapes(*[get_shape(v) for v in x.values()])
            shape_for_reshaping = (int(np.prod(shape)),)

            def reshape(value):
                try:
                    return np.reshape(value, shape_for_reshaping)
                except ValueError:
                    if (
                        isinstance(value, int)
                        or isinstance(value, float)
                        or value.shape == tuple()
                        or np.prod(value.shape) == 1
                    ):
                        return value * np.ones(shape_for_reshaping)
                raise ValueError("Could not reshape value of one of the inputs!")

            x = np.stack(
                tuple(reshape(x[k]) for k in self.x_data_coordinates.keys()),
                axis=1,
            )
            return np.reshape(self._interpolate(x), shape)

        return self._interpolate(x)

    def _interpolate(self, xi):
        """
        Interpolate at points, like `np.interpn` does.

        Args:
            xi: Points of shape (n_points, ndim), NumPy or CasADi. In
                1D, a float or a 1D array is also accepted.

        Returns:
            A 1D NumPy array for NumPy inputs, a float or a 1D NumPy
            array for DM inputs, a CasADi column otherwise.
        """
        if not np.is_casadi_type(xi, recursive=True):
            xi = _onp.reshape(_onp.asarray(xi, dtype=float), (-1, self.ndim))
            return self._interpolate_numpy(xi)

        if xi.shape[1] != self.ndim:
            if xi.shape[0] != self.ndim:
                raise ValueError("`xi` must have the shape (n_points, n_dimensions)!")
            xi = xi.T

        if self._casadi_function is None:  # "nearest"
            if not isinstance(xi, ca.DM):
                raise TypeError(
                    f"{self.method=!r} cannot take symbolic inputs; "
                    "use 'linear' or 'bspline'."
                )
            fi = ca.DM(self._interpolate_numpy(_onp.array(xi, dtype=float)))
        else:
            fi = self._interpolate_casadi(xi)

        ### If DM output (i.e. a numeric value), convert it back to an array
        if isinstance(fi, ca.DM):
            if fi.shape == (1, 1):
                return float(fi)
            return _onp.array(fi, dtype=float).reshape(-1)
        return fi

    def _interpolate_numpy(self, xi):
        """
        Evaluate the NumPy interpolator.

        Args:
            xi: NumPy array of shape (n_points, ndim).

        Returns:
            A 1D NumPy array of length n_points.
        """
        xi_eval = xi
        if self.method == "bspline":
            xi_eval = _onp.clip(xi, self._lower, self._upper)
        fi = _onp.asarray(self._numpy_function(xi_eval), dtype=float).reshape(-1)

        if self.fill_value is not None:
            outside = _onp.any((xi < self._lower) | (xi > self._upper), axis=1)
            fi = _onp.where(outside, self.fill_value, fi)
        return fi

    def _interpolate_casadi(self, xi):
        """
        Evaluate the CasADi interpolator.

        Args:
            xi: CasADi matrix of shape (n_points, ndim).

        Returns:
            A CasADi column of length n_points.
        """
        columns = [xi[:, axis] for axis in range(self.ndim)]
        columns_eval = columns
        if self.method == "bspline":
            columns_eval = [
                ca.fmin(ca.fmax(column, lower), upper)
                for column, lower, upper in zip(columns, self._lower, self._upper)
            ]
        # An (ndim, n_points) input makes CasADi map over the columns
        fi = self._casadi_function(ca.horzcat(*columns_eval).T).T

        if self.fill_value is not None:
            for column, lower, upper in zip(columns, self._lower, self._upper):
                fi = np.where(column > upper, self.fill_value, fi)
                fi = np.where(column < lower, self.fill_value, fi)
        return fi


if __name__ == "__main__":
    import time

    import matplotlib.pyplot as plt

    from architeuthis.modeling.interpolation import InterpolatedModel
    from architeuthis.optimization import Opti

    def best_of(fn, repeat=5):
        """
        Best wall time of `repeat` runs, in seconds.
        """
        times = []
        for _ in range(repeat):
            t0 = time.perf_counter()
            fn()
            times.append(time.perf_counter() - t0)
        return min(times)

    def fmt(t):
        """
        Format a duration in seconds.
        """
        return f"{t * 1e3:9.2f} ms" if t >= 1e-3 else f"{t * 1e6:9.1f} µs"

    def solve(model, y, obj):
        """
        Solve f(x, y) = obj for x with IPOPT.
        """
        opti = Opti()
        x = opti.variable(init_guess=0.0, lower_bound=-9, upper_bound=9)
        opti.minimize((model({"x": x, "y": y}) - obj) ** 2)
        sol = opti.solve(
            verbose=False,
            options={"ipopt": {"hessian_approximation": "limited-memory"}},
        )
        return float(sol(x)), sol.stats()["iter_count"]

    # --- Data: f(x, y) = (-x - 2)^3 + y^3 on a fine grid. InterpolatedModel
    # rebuilds its interpolant at every call, so a finer grid is very slow.
    n = 200
    X = np.linspace(-10, 10, n)
    Y = np.linspace(-10, 10, n)
    XX, YY = np.meshgrid(X, Y, indexing="ij")
    f = (-XX - 2.0) ** 3 + YY**3
    print(f"grid {n} x {n} = {f.size:,} points\n")

    builders = {
        "Interpolated bspline": lambda: InterpolatedModel(
            {"x": X, "y": Y}, f, method="bspline", fill_value=None
        ),
        "Hybrid linear": lambda: HybridInterpolator(
            {"x": X, "y": Y}, f, method="linear", fill_value=None
        ),
        "Hybrid bspline": lambda: HybridInterpolator(
            {"x": X, "y": Y}, f, method="bspline", fill_value=None
        ),
    }
    models, timings, solutions = {}, {}, {}
    rng = np.random.default_rng(0)
    pts_1k = rng.uniform(-10, 10, (2, 1_000))
    y, obj = 1.5, 10.0

    for label, build in builders.items():
        t = timings[label] = {}
        t0 = time.perf_counter()
        models[label] = model = build()
        t["build"] = time.perf_counter() - t0
        t["numpy 1 pt"] = best_of(lambda: model({"x": 0.3, "y": y}))
        t["numpy 1k pts"] = best_of(lambda: model({"x": pts_1k[0], "y": pts_1k[1]}))
        t0 = time.perf_counter()
        solutions[label] = solve(model, y, obj)
        t["IPOPT solve"] = time.perf_counter() - t0

    # --- Report
    labels = list(models)
    print(f"{'':14s}" + "".join(f"{m:>22s}" for m in labels))
    for k in timings[labels[0]]:
        print(f"{k:14s}" + "".join(f"{fmt(timings[m][k]):>22s}" for m in labels))

    x_exact = -2.0 - np.cbrt(obj - y**3)
    print(f"\nexact                x = {x_exact:.6f}")
    for label, (x_opt, n_iter) in solutions.items():
        print(f"{label:20s} x = {x_opt:.6f}  ({n_iter} iterations)")

    # --- Plot (data points subsampled: 1e6 scatter points is very slow)
    X_plot, Y_plot = np.meshgrid(
        np.linspace(-10, 10, 100),
        np.linspace(-10, 10, 100),
        indexing="ij",
    )
    step = n // 20
    hybrids = {k: v for k, v in models.items() if k.startswith("Hybrid")}
    fig = plt.figure(figsize=(11, 5))
    for i, (label, model) in enumerate(hybrids.items()):
        F_plot = model({"x": X_plot, "y": Y_plot})  # arrays in -> array out
        ax = fig.add_subplot(1, len(hybrids), i + 1, projection="3d")
        ax.scatter(
            XX[::step, ::step].ravel(),
            YY[::step, ::step].ravel(),
            f[::step, ::step].ravel(),
            color="k",
            s=5,
        )
        ax.plot_surface(
            X_plot,
            Y_plot,
            F_plot,
            color="red",
            alpha=0.25,
            edgecolors=(1, 1, 1, 0.5),
            linewidth=0.5,
            rcount=40,
            ccount=40,
        )
        ax.set(title=label, xlabel="x", ylabel="y")
    plt.tight_layout()
    plt.show()

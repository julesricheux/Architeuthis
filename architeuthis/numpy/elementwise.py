"""
Element-wise functions of NumPy that also take CasADi values.

An Architeuthis addition to the AeroSandbox package: from casadi 3.8,
a NumPy function called on a casadi value raises a FutureWarning (casadi
issue #2959). These functions give the result of casadi 3.7.2 without
it: a casadi expression for symbolic values (SX, MX), and the NumPy
result for numbers, including numeric casadi matrices (DM), turned into
NumPy arrays first.

Created on Tue Nov 24 2026
"""

import casadi as _cas
import numpy as _onp

__all__ = [
    "sin",
    "cos",
    "tan",
    "arcsin",
    "arccos",
    "arctan",
    "arctan2",
    "sinh",
    "cosh",
    "tanh",
    "arcsinh",
    "arccosh",
    "arctanh",
    "sqrt",
    "exp",
    "log",
    "log10",
    "floor",
    "ceil",
    "sign",
    "fmax",
    "fmin",
    "hypot",
]

_SYMBOLIC = (_cas.SX, _cas.MX)


def _numeric(value):
    """
    A numeric casadi matrix as a NumPy array, any other value as it is.
    """
    return value.full() if isinstance(value, _cas.DM) else value


def _wrap(numpy_function, casadi_function):
    """
    One function of both: casadi's for symbolic values, else NumPy's.
    """

    def function(*args):
        if any(isinstance(arg, _SYMBOLIC) for arg in args):
            return casadi_function(*args)
        return numpy_function(*(_numeric(arg) for arg in args))

    function.__name__ = numpy_function.__name__
    function.__qualname__ = numpy_function.__name__
    function.__doc__ = (
        f"\n    numpy.{numpy_function.__name__}, also on CasADi values.\n\n"
        f"    Symbolic values (SX, MX) go to casadi.{casadi_function.__name__},\n"
        "    numbers and DM to NumPy, as with casadi 3.7.2.\n    "
    )
    return function


sin = _wrap(_onp.sin, _cas.sin)
cos = _wrap(_onp.cos, _cas.cos)
tan = _wrap(_onp.tan, _cas.tan)
arcsin = _wrap(_onp.arcsin, _cas.asin)
arccos = _wrap(_onp.arccos, _cas.acos)
arctan = _wrap(_onp.arctan, _cas.atan)
arctan2 = _wrap(_onp.arctan2, _cas.atan2)
sinh = _wrap(_onp.sinh, _cas.sinh)
cosh = _wrap(_onp.cosh, _cas.cosh)
tanh = _wrap(_onp.tanh, _cas.tanh)
arcsinh = _wrap(_onp.arcsinh, _cas.asinh)
arccosh = _wrap(_onp.arccosh, _cas.acosh)
arctanh = _wrap(_onp.arctanh, _cas.atanh)
sqrt = _wrap(_onp.sqrt, _cas.sqrt)
exp = _wrap(_onp.exp, _cas.exp)
log = _wrap(_onp.log, _cas.log)
log10 = _wrap(_onp.log10, _cas.log10)
floor = _wrap(_onp.floor, _cas.floor)
ceil = _wrap(_onp.ceil, _cas.ceil)
sign = _wrap(_onp.sign, _cas.sign)
fmax = _wrap(_onp.fmax, _cas.fmax)
fmin = _wrap(_onp.fmin, _cas.fmin)
hypot = _wrap(_onp.hypot, lambda x, y: _cas.sqrt(x**2 + y**2))

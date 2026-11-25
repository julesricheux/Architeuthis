import numpy as _onp
from architeuthis.numpy import elementwise as _elementwise
from numpy import pi as _pi

_deg2rad = 180.0 / _pi
_rad2deg = _pi / 180.0


def degrees(x):
    """Converts an input x from radians to degrees"""
    return x * _deg2rad


def radians(x):
    """Converts an input x from degrees to radians"""
    return x * _rad2deg


def sind(x):
    """Returns the sin of an angle x, given in degrees"""
    return _elementwise.sin(radians(x))


def cosd(x):
    """Returns the cos of an angle x, given in degrees"""
    return _elementwise.cos(radians(x))


def tand(x):
    """Returns the tangent of an angle x, given in degrees"""
    return _elementwise.tan(radians(x))


def arcsind(x):
    """Returns the arcsin of an x, in degrees"""
    return degrees(_elementwise.arcsin(x))


def arccosd(x):
    """Returns the arccos of an x, in degrees"""
    return degrees(_elementwise.arccos(x))


def arctand(x):
    """Returns the arctan of an x, in degrees"""
    return degrees(_elementwise.arctan(x))


def arctan2d(y, x):
    """Returns the angle associated with arctan(y, x), in degrees"""
    return degrees(_elementwise.arctan2(y, x))

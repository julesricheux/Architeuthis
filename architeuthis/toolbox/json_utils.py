# -*- coding: utf-8 -*-
"""
JSON encoding of routing reports, which hold numpy arrays and scalars.

This module only needs numpy, so reports can be written and read without
the Dash stack. `CustomEncoder` and `custom_decoder` also remain
importable from `wrappers.json_wrapper`.
"""

import json

import numpy as np


class CustomEncoder(json.JSONEncoder):
    """
    JSON encoder of tuples, NumPy arrays and NumPy scalars.

    They are written as dicts tagged by `__type__`, which
    `custom_decoder` reads back.
    """

    def default(self, obj):
        """
        Encode a tuple, a NumPy array or a NumPy scalar.

        Args:
            obj: The value that JSON cannot encode by itself.
        """

        if isinstance(obj, tuple):
            return {
                "__type__": "tuple",
                "value": list(obj)
            }

        if isinstance(obj, np.ndarray):
            return {
                "__type__": "ndarray",
                "dtype": str(obj.dtype),
                "value": obj.tolist()
            }

        if isinstance(obj, np.generic):
            return {
                "__type__": "np_scalar",
                "dtype": str(obj.dtype),
                "value": obj.item()
            }

        return super().default(obj)


def custom_decoder(obj):
    """
    Rebuild the values written by `CustomEncoder`.

    Use it as `object_hook` of `json.load`.

    Args:
        obj: A decoded dict, returned as it is without `__type__`.

    Raises:
        TypeError: If `__type__` is unknown.
    """

    if "__type__" not in obj:
        return obj

    t = obj["__type__"]

    if t == "tuple":
        return tuple(obj["value"])

    if t == "ndarray":
        return np.array(obj["value"], dtype=obj["dtype"])

    if t == "np_scalar":
        return np.dtype(obj["dtype"]).type(obj["value"])

    raise TypeError(f"Unknown serialized type: {t}")

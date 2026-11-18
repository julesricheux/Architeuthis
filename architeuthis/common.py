# -*- coding: utf-8 -*-
"""
Base classes of the domain and data objects, and shared helpers.

It defines `ArchiteuthisObject`, `ArchiteuthisData` with its `load_data`
pipeline and its models (lookup tables or functions), `FunctionModel`
and `ArchiteuthisSpatialData`.
It holds the paths of the package and the `status` output. The
credentials are in `credentials`.

Created on Thu Jan 15 12:44:25 2026

@author: jrich
"""

import os
import logging
from abc import ABC, abstractmethod

import architeuthis.numpy as np
from architeuthis.modeling import HybridInterpolatedModel

from casadi import DM

from typing import Any, Callable, Literal, Optional, Sequence, Union
from pandas import Timestamp
from datetime import datetime

log = logging.getLogger(__name__)

Datetime = Union[datetime, Timestamp, str]

_USER_HOME = os.path.expanduser("~")

# Where downloads, libraries and reports are kept. ARCHITEUTHIS_HOME moves it,
# read once at import like the other constants.
_HOME = os.path.expanduser(os.environ.get("ARCHITEUTHIS_HOME") or os.path.join(_USER_HOME, "data"))

_CDS_URL = "https://cds.climate.copernicus.eu/api"


# ------------------------------------------------------------------------------
# Status messages
# ------------------------------------------------------------------------------

_status_sink = None


def status(message: str = "") -> None:
    """
    Report progress to the user.

    It is printed by default, or sent to the function given to
    `set_status_sink`, for example to display it in a GUI.
    """
    if _status_sink is None:
        print(message)
    else:
        _status_sink(message)


def set_status_sink(sink: Optional[Callable[[str], Any]]) -> None:
    """
    Send `status` messages to `sink(message)`. `None` restores printing.
    """
    global _status_sink
    _status_sink = sink


# ------------------------------------------------------------------------------
# Setup done on first use, not at import: a GUI or a library importing Architeuthis
# keeps its own logging and files.
# ------------------------------------------------------------------------------

def setup_logging(level: int = logging.INFO, force: bool = False) -> None:
    """
    Log to the console.

    `load_data` calls this. It leaves logging alone if the application
    has already configured it, unless `force` is True.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=force,
    )


_TOPOGRAPHY_URL = "https://www.ngdc.noaa.gov/thredds/fileServer/global/ETOPO2022/60s/60s_surface_elev_netcdf/ETOPO_2022_v1_60s_N90W180_surface.nc"

_banner = """
===================================================================
                  ▄▄                               ▄▄              
                  ██    ▀▀  ██                ██   ██    ▀▀        
 ▀▀█▄ ████▄ ▄████ ████▄ ██ ▀██▀▀ ▄█▀█▄ ██ ██ ▀██▀▀ ████▄ ██  ▄█▀▀▀ 
▄█▀██ ██ ▀▀ ██    ██ ██ ██  ██   ██▄█▀ ██ ██  ██   ██ ██ ██  ▀███▄ 
▀█▄██ ██    ▀████ ██ ██ ██▄ ██   ▀█▄▄▄ ▀██▀█  ██   ██ ██ ██▄ ▄▄▄█▀

                      I  S    A  L  I  V  E                        
===================================================================
"""

# North-going offset added to the wave components before arctan2, in m²
# (swh**2): it biases the direction by less than 0.6 deg from swh = 1 m.
WAVE_COMPONENTS_OFFSET = 0.

GUST_DEFAULT_RATIO = 1.23 # (https://cimmse.wordpress.com/2013/09/20/a-wind-gust-factor-database-of-marine-observations-from-10-tropical-cyclones-2/)

# Input names of the lookup tables, the keys of the queries
TOPOGRAPHY_KEYS = ("latitude", "longitude")
FORECAST_KEYS = ("valid_time", "latitude", "longitude")
ENSEMBLE_KEYS = ("valid_time", "member", "latitude", "longitude")
VESSEL_KEYS = ("stw", "tws", "twa", "hs", "wa")


def tall(array):
    """
    Reshape an array to a column vector.
    """
    return np.reshape(array, (-1, 1))

def wide(array):
    """
    Reshape an array to a row vector.
    """
    return np.reshape(array, (1, -1))


def to_timestamp(value: Union[Datetime, float, int]) -> float:
    """
    Convert a date to float epoch seconds.

    This is the time unit used throughout Architeuthis.

    Numbers are returned unchanged (as float). Datetimes, pandas
    Timestamps, numpy datetime64 values and ISO strings are converted;
    naive values are UTC.
    """
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return float(value)

    timestamp = Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return float(timestamp.timestamp())


def _constant(x: dict, value: float) -> float:
    """
    The function of a constant model: `value`, whatever `x`.
    """
    return value


class FunctionModel:
    """
    A model computed by a function, R^N -> R^1.

    It is called like a HybridInterpolatedModel, with a dict of inputs,
    and calls `function(x, **args)`, where `x` holds the inputs named
    in `inputs`. `args` are fixed arguments, such as fitted parameters.
    Written with `architeuthis.numpy`, the function takes CasADi inputs
    and the routing differentiates through it.

    Args:
        function: Function of a dict of inputs, and of `args`.
        inputs: Names of the inputs, the keys of the queries.
        args: Fixed keyword arguments of `function`.
        output: Which part of the result is the value: None for the
            result itself, or the first item of a tuple result; a key,
            looked up in a dict result, else in the dicts of a tuple
            result such as `(value, components)`; an index of a tuple
            result; or a function of the result.
        name: Name of this model.

    Example:
        >>> def power(x, p):
        ...     return p["k"] * x["stw"]**3
        >>> model = FunctionModel(power, ["stw"], {"p": {"k": 1.2}})
        >>> model({"stw": 10.})
    """

    def __init__(
        self,
        function: Callable,
        inputs: Sequence[str],
        args: Optional[dict] = None,
        output: Union[None, str, int, Callable] = None,
        name: Optional[str] = None,
    ):
        self.function = function
        self.inputs = list(inputs)
        self.args = dict(args) if args is not None else {}
        self.output = output
        self.name = name if name is not None else getattr(function, "__name__", "function")

    def input_names(self) -> list[str]:
        """
        Names of the inputs of this model.

        Returns:
            The keys that a query of this model takes.
        """
        return list(self.inputs)

    def __call__(self, x: dict):
        """
        Evaluate the function and select its output.

        Args:
            x: Inputs keyed by name. Keys that are not inputs of this
                model are not passed to the function.

        Returns:
            The selected output of the function.
        """
        missing = [key for key in self.inputs if key not in x]
        if missing:
            raise KeyError(f"{self.name} needs the inputs {missing}.")

        result = self.function({key: x[key] for key in self.inputs}, **self.args)
        return self._select(result)

    def _select(self, result):
        output = self.output
        if output is None:
            return result[0] if isinstance(result, tuple) else result
        if callable(output):
            return output(result)
        if isinstance(output, int):
            return result[output]
        if isinstance(result, dict):
            return result[output]
        if isinstance(result, tuple):
            for item in result:
                if isinstance(item, dict) and output in item:
                    return item[output]
        raise KeyError(f"{self.name} has no output {output!r}.")


class ArchiteuthisObject(ABC):
    """
    Base class of the domain objects.

    Args:
        name: Name of this object, used in status messages.
        verbose: Whether to report progress.
    """
    
    @abstractmethod
    def __init__(
        self,
        name: str,
        verbose: bool,
    ):
        self.name = name
        self.verbose = verbose
    
    
class ArchiteuthisData(ArchiteuthisObject):
    """
    Base class of the objects backed by data or by models.

    Calling this object queries one of its `models`, by key. A model is
    any callable taking a dict of inputs, with an `input_names()`
    method: `add_interpolator` builds a lookup table from `data`, which
    `load_data` fills, `add_function` wraps a function and its fixed
    arguments, and `add_model` registers any other.

    Args:
        name: Name of this object, used in status messages.
        verbose: Whether to report progress.
    """
    
    @abstractmethod
    def __init__(
        self,
        name: str,
        verbose: bool,
    ):
        super().__init__(name, verbose)
        
        self.path = None
        self.data = None
        self.var_keys = set()
        self.models = {}

    @property
    def interpolators(self) -> dict:
        """
        The models of this object, interpolated or not.

        This is the former name of `models`, kept for compatibility.
        """
        return self.models

    def load_data(self):
        """
        Locate, download, read, convert and extend the data.

        This template method calls `_locate_data`, `_download_data`,
        `_read_data`, `_convert_data` and `_extend_data`, the hooks that
        a data source overrides.
        """
        setup_logging()

        self._locate_data()
        self._download_data()
        
        status(f"📦 Reading {self.name} data ...")
        self._read_data()
        status("✅ Reading completed.")
        
        self._convert_data()
        self._extend_data()

    def _locate_data(self):
        pass
    
    def _download_data(self):
        pass
    
    def _read_data(self):
        pass
    
    def _convert_data(self):
        pass
    
    def _extend_data(self):
        pass
        
    def add_interpolator(
        self,
        var_dim: str,
        coord_dims: Sequence[str],
        coord_slices: Sequence[slice],
        var_key: str,
        method: Literal["bspline", "linear", "nearest"] = "bspline",
        fac: float = 1.0,
        coord_keys: Optional[Sequence[str]] = None,
    ):
        """
        Build the lookup table of a variable of `data`.

        The table is a HybridInterpolatedModel, which takes NumPy and
        CasADi queries alike. Dimensions are positional: the array is
        squeezed and sliced, so its dimension order must be the one of
        `coord_dims`. NaN values become 0. Outside the grid, "linear"
        extrapolates and "bspline" keeps the value at the boundary. A
        `var_key` that already exists is left as it is.

        Args:
            var_dim: Name of the variable in `data`.
            coord_dims: Names of the coordinates, in the order of the
                array.
            coord_slices: One slice per coordinate, applied to the
                coordinates and the data.
            var_key: Key of the lookup table when calling this object.
            method: Interpolation method, "linear", "bspline" or
                "nearest" ("nearest" takes numeric queries only).
            fac: Factor applied to the values, to correct or convert
                them.
            coord_keys: Names of the inputs of the lookup table, one per
                coordinate, by default `coord_dims`. Queries are dicts
                with these keys.
        """
        if var_key in self.var_keys:
            status(f"🟦 {var_key} already in {self.name} models.")
            return

        if coord_keys is None:
            coord_keys = coord_dims
        if len(coord_keys) != len(coord_dims):
            raise ValueError(
                f"{self.name}: {len(coord_keys)} coord_keys "
                f"for {len(coord_dims)} coord_dims."
            )

        x = {
            key: np.asarray(self.data.coords[dim].values[sel], dtype=float)
            for key, dim, sel in zip(coord_keys, coord_dims, coord_slices)
        }

        f = np.nan_to_num(
            self.data[var_dim].to_numpy().squeeze()[*coord_slices],
            nan=0.,
        ) * fac  # apply correction factor if specified

        model = HybridInterpolatedModel(
            x_data_coordinates=x,
            y_data_structured=f,
            method=method,
            fill_value=None,  # extrapolate, as the former CasADi interpolant
            name=f"LUT_{var_dim}",
        )
        self.add_model(var_key, model, description=var_dim)

    def add_function(
        self,
        var_key: str,
        function: Callable,
        inputs: Sequence[str],
        args: Optional[dict] = None,
        output: Union[None, str, int, Callable] = None,
    ):
        """
        Register a function as the model of a variable.

        It is called as `function(x, **args)`, where `x` is a dict of
        the `inputs` of the query. Written with `architeuthis.numpy`, it
        takes CasADi inputs and the routing differentiates through it.
        A `var_key` that already exists is left as it is.

        Args:
            var_key: Key of the model when calling this object.
            function: Function of a dict of inputs, and of `args`.
            inputs: Names of the inputs, the keys of the queries.
            args: Fixed keyword arguments, such as fitted parameters.
            output: Which part of the result is the value, see
                `FunctionModel`: for example a key of the components
                of a `(value, components)` result.

        Example:
            >>> vessel.add_function(
            ...     "bhp",
            ...     propulsion_power,
            ...     inputs=["stw", "tws", "twa", "swh", "mwa"],
            ...     args={"p": parameters},
            ... )
        """
        model = FunctionModel(
            function=function,
            inputs=inputs,
            args=args,
            output=output,
            name=f"{self.name}_{var_key}",
        )
        self.add_model(var_key, model, description=getattr(function, "__name__", None))

    def add_constant(
        self,
        var_key: str,
        value: float,
    ):
        """
        Register a constant as the model of a variable.

        The model takes no input and returns `value` for any query, a
        brake power or a hotel load for example. A `var_key` that
        already exists is left as it is.

        Args:
            var_key: Key of the model when calling this object.
            value: The value of the variable.

        Example:
            >>> vessel.add_constant("hotel_load", 180.)
        """
        model = FunctionModel(
            function=_constant,
            inputs=(),
            args={"value": float(value)},
            name=f"{self.name}_{var_key}",
        )
        self.add_model(var_key, model, description=f"constant {float(value):g}")

    def add_model(
        self,
        var_key: str,
        model: Callable,
        description: Optional[str] = None,
    ):
        """
        Register a model, queried by calling this object.

        A model is called with a dict of inputs, NumPy or CasADi, and
        its `input_names()` method gives their keys. A `var_key` that
        already exists is left as it is.

        Args:
            var_key: Key of the model when calling this object.
            model: A HybridInterpolatedModel, a FunctionModel or any
                object with the same interface.
            description: What the model is, for the status message.
        """
        if var_key in self.var_keys:
            status(f"🟦 {var_key} already in {self.name} models.")
            return

        self.models[var_key] = model
        self.var_keys.add(var_key)

        what = f": {description}" if description else ""
        status(f"➕ Added {var_key}{what} to {self.name} models.")

    def remove_model(
        self,
        var_key: str,
    ):
        """
        Remove a model, if it exists.

        Args:
            var_key: Key of the model.
        """
        if var_key in self.var_keys:
            del self.models[var_key]
            self.var_keys.remove(var_key)
            status(f"➖ Removed {var_key} from {self.name} models.")
        else:
            status(f"💔 {var_key} not found in {self.name} models.")

    def remove_interpolator(
        self,
        var_key: str,
    ):
        """
        Remove a model, if it exists, as `remove_model` does.

        Args:
            var_key: Key given to `add_interpolator`.
        """
        self.remove_model(var_key)

    def __call__(
        self,
        var_key,
        X,
    ):
        """
        Query a model: a lookup table, a function or another.

        Args:
            var_key: Key given to `add_interpolator`, `add_function`
                or `add_model`.
            X: Query points, as a dict of floats or arrays keyed by the
                input names of the model (see `input_names`), broadcast
                against each other. NumPy or CasADi. Other keys are
                ignored, so one query can serve several models. An
                array of shape (n_queries, n_dims), with columns in the
                order of the inputs, is also accepted.

        Returns:
            A CasADi column vector, DM for numeric queries, or None if
            this object has no model.

        Example:
            >>> forecast("u10", {
            ...     "valid_time": t,
            ...     "latitude": lat,
            ...     "longitude": lon,
            ... })
        """
        if not self.models:
            status(f"💔 {self.name} has no models and thus cannot be called.")
            return None

        model = self.models[var_key]
        names = model.input_names()

        if not isinstance(X, dict):
            if np.is_casadi_type(X, recursive=False):
                if X.shape[1] != len(names):
                    raise ValueError(
                        f"{self.name}: queries of {var_key} have "
                        f"{len(names)} columns {names}, not {X.shape[1]}."
                    )
            else:
                X = np.reshape(np.asarray(X, dtype=float), (-1, len(names)))
            X = {name: X[:, i] for i, name in enumerate(names)}
        else:
            missing = [name for name in names if name not in X]
            if missing:
                raise KeyError(f"{self.name}: queries of {var_key} need {missing}.")
            X = {name: X[name] for name in names}

        result = tall(model(X))
        # Numeric queries are evaluated with NumPy, but return a DM column
        # as the former CasADi interpolant did, so float() and casadi
        # operations keep working on them.
        if not np.is_casadi_type(result, recursive=False):
            result = DM(result)
        return result

    def input_names(
        self,
        var_key: str,
    ) -> list[str]:
        """
        Names of the inputs of a model.

        Args:
            var_key: Key of the model.

        Returns:
            The keys that a query of this model takes.
        """
        return self.models[var_key].input_names()

    
class ArchiteuthisSpatialData(ArchiteuthisData):
    """
    Base class of the datasets limited to a domain.

    Args:
        name: Name of this object, used in status messages.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        verbose: Whether to report progress.
    """
    
    @abstractmethod
    def __init__(
        self,
        name: str,
        min_lon: float,
        max_lon: float,
        min_lat: float,
        max_lat: float,
        verbose: bool,
    ):
        super().__init__(name, verbose)
        
        self.min_lon = min_lon
        self.max_lon = max_lon
        self.min_lat = min_lat
        self.max_lat = max_lat

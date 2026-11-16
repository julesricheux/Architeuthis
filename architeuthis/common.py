# -*- coding: utf-8 -*-
"""
Base classes of the domain and data objects, and shared helpers.

It defines `ArchiteuthisObject`, `ArchiteuthisData` with its `load_data`
pipeline and its lookup tables, and `ArchiteuthisSpatialData`.
It reads the credentials from the environment and holds the `status`
output.

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

def _get_env_var(key):
    if key in os.environ:
        return os.environ[key]
    else:
        return None

log = logging.getLogger(__name__)

Datetime = Union[datetime, Timestamp, str]

_USER = os.path.expanduser("~")

#TODO should probably be in __init__
_HOME = os.path.join(
    _USER,
    "data",
)

_CDS_URL = "https://cds.climate.copernicus.eu/api"
_CDS_API_KEY = _get_env_var("CDS_API_KEY")

_CMEMS_USER = _get_env_var("CMEMS_USER")
_CMEMS_PWD = _get_env_var("CMEMS_PWD")

_EUMDAC_USER = _get_env_var("EUMDAC_USER")
_EUMDAC_PWD = _get_env_var("EUMDAC_PWD")

_EUMDAC_CREDENTIALS = (_EUMDAC_USER, _EUMDAC_PWD)

file_path = os.path.join(
    _USER,
    ".cdsapirc",
)


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

_credentials_reported = False


def setup_logging(level: int = logging.INFO, force: bool = False) -> None:
    """
    Log to the console and report data providers without credentials.

    `load_data` calls this. It leaves logging alone if the application
    has already configured it, unless `force` is True.
    """
    global _credentials_reported

    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=force,
    )

    if _credentials_reported:
        return
    _credentials_reported = True

    if _CDS_API_KEY is None:
        log.info("CDS API key was not specified. Copernicus atmosphere data will be unavailable.")
    if (_CMEMS_USER is None) or (_CMEMS_PWD is None):
        log.info("CMEMS credentials are incomplete. Copernicus marine service data will be unavailable.")
    if (_EUMDAC_USER is None) or (_EUMDAC_PWD is None):
        log.info("EUMDAC credentials are incomplete. Corresponding satellite data will be unavailable.")


def ensure_cdsapirc() -> None:
    """
    Write `~/.cdsapirc` if it is missing, from `CDS_API_KEY`.

    Called before a CDS download.
    """
    if os.path.exists(file_path):
        return

    if _CDS_API_KEY is None:
        status(f"⚠️ Warning: {file_path} is missing and CDS_API_KEY is not set. The CDS download may fail.")
        return

    content = f"""url: {_CDS_URL}
    key: {_CDS_API_KEY}
    """
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        status(f"Successfully created {file_path}")
    except OSError as e:
        status(f"Error: Could not write to {file_path}. {e}")


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
    Base class of the objects backed by a dataset.

    `load_data` fills `data`, and `add_interpolator` builds the lookup
    tables that calling this object queries.

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
        self.interpolators = {}
        
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
            status(f"🟦 {var_key} already in {self.name} interpolators.")
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

        self.interpolators[var_key] = HybridInterpolatedModel(
            x_data_coordinates=x,
            y_data_structured=f,
            method=method,
            fill_value=None,  # extrapolate, as the former CasADi interpolant
            name=f"LUT_{var_dim}",
        )
        self.var_keys.add(var_key)

        status(f"➕ Added {var_key}: {var_dim} to {self.name} interpolators.")

    def remove_interpolator(
        self,
        var_key: str,
    ):
        """
        Remove a lookup table, if it exists.

        Args:
            var_key: Key given to `add_interpolator`.
        """
        if var_key in self.var_keys:
            del self.interpolators[var_key]
            self.var_keys.remove(var_key)
            status(f"➖ Removed {var_key} from {self.name} interpolators.")
        else:
            status(f"💔 {var_key} not found in {self.name} interpolators.")

    def __call__(
        self,
        var_key,
        X,
    ):
        """
        Query a lookup table.

        Args:
            var_key: Key given to `add_interpolator`.
            X: Query points, as a dict of floats or arrays keyed by the
                input names of the table (see `input_names`), broadcast
                against each other. NumPy or CasADi. An array of shape
                (n_queries, n_dims), with columns in the order of the
                inputs, is also accepted.

        Returns:
            A CasADi column vector, DM for numeric queries, or None if
            this object has no lookup table.

        Example:
            >>> forecast("u10", {
            ...     "valid_time": t,
            ...     "latitude": lat,
            ...     "longitude": lon,
            ... })
        """
        if not self.interpolators:
            status(f"💔 {self.name} has no interpolators and thus cannot be called.")
            return None

        interpolator = self.interpolators[var_key]

        if not isinstance(X, dict):
            names = interpolator.input_names()
            if np.is_casadi_type(X, recursive=False):
                if X.shape[1] != len(names):
                    raise ValueError(
                        f"{self.name}: queries of {var_key} have "
                        f"{len(names)} columns {names}, not {X.shape[1]}."
                    )
            else:
                X = np.reshape(np.asarray(X, dtype=float), (-1, len(names)))
            X = {name: X[:, i] for i, name in enumerate(names)}

        result = tall(interpolator(X))
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
        Names of the inputs of a lookup table.

        Args:
            var_key: Key given to `add_interpolator`.

        Returns:
            The keys that a query of this table takes.
        """
        return self.interpolators[var_key].input_names()

    
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

# -*- coding: utf-8 -*-
"""
The vessel: its consumption, polars and power limit.

Created on Thu Jan 15 10:16:15 2026

@author: jrich
"""

from __future__ import annotations

import os
import re
import warnings

import xarray as xr
import architeuthis.numpy as np

from typing import Optional, Sequence, Union
from collections.abc import Callable
from architeuthis.toolbox.inspect_tools import ensure_callable

from architeuthis.common import ArchiteuthisData, VESSEL_KEYS, status
from architeuthis.fuels import Fuel, fuel_key, get_fuel

# Models that give the fuel consumption, by order of precedence. Routing
# needs one of them: it is the objective.
CONSUMPTION_KEYS = ("hourly_consumption", "total_power", "bhp")
# Quantities of the consumption, in the order they are computed: each can be
# an input of the models after it, as the total power of an sfoc table.
CONSUMPTION_QUANTITIES = ("bhp", "hotel_load", "total_power", "sfoc", "hourly_consumption")
# Variables of a usual polar table, and its axes, in its order.
POLAR_KEYS = ("bhp", "max_bhp", "sails_contribution")
POLAR_DIMS = ("stw", "tws", "twa", "hs", "wa")

# Fuel type of a vessel by default, a key of `fuels.FUELS`, whose density
# (0.85 kg/L) turns consumptions, volumes in L/h, into the fuel of a voyage,
# a mass in tonnes.
DEFAULT_FUEL = "mdo"

# Power limit when `max_power` is not given, until 0.4.0, where it becomes None.
_DEFAULT_MAX_POWER = 1e12 # kW
_UNSET = object()


def _label_from_path(filepath: str) -> str:
    """
    Short label of a polar file.

    This is the `eff45` of `..._eff45.nc`, otherwise the file name.
    """
    stem = os.path.splitext(os.path.basename(str(filepath)))[0]
    match = re.search(r"eff\d+$", stem)
    return match.group(0) if match else stem


def _warn_sfc():
    """
    Deprecation warning of the former name of `sfoc`.
    """
    warnings.warn(
        "Vessel 'sfc' is deprecated and will be removed in 0.4.0: use 'sfoc', "
        "the specific fuel oil consumption in g/kWh.",
        DeprecationWarning,
        stacklevel=3,
    )


class Vessel(ArchiteuthisData):
    """
    Represents the vessel and its performance characteristics.

    Its performance is given by models queried by key, as for any data
    object: tables interpolated from a polar file (`load_data`, then
    `add_interpolator`), functions such as semi-empirical models with
    fitted parameters (`add_function`), or constants
    (`add_constant`).

    Routing only needs the fuel consumption, its objective, given by
    the first of these models that the vessel has:

    - `hourly_consumption`: the fuel consumption itself, in L/h.
    - `total_power`: the power of all consumers, propulsion and
      hotel, in kW, burnt at `sfoc`.
    - `bhp`: the brake power of the propulsion, in kW, plus
      `hotel_load`, burnt at `sfoc`.

    Consumptions are volumes, in L/h: the mass burnt at `sfoc` is
    divided by `fuel_density`, and the fuel of a voyage is the volume
    times `fuel_density`, in tonnes. The density is that of
    `fuel_type` in `fuels.FUELS` unless given.

    `hotel_load` and `sfoc` are numbers, functions of the power (the
    brake power for `hotel_load`, the total power for `sfoc`), or
    models of this key, which take precedence and may name `bhp` or
    `total_power` among their inputs. Any other model, such as
    `max_bhp` or `sails_contribution`, is computed only when the
    routing lists it in its `variables` (until 0.4.0, these two are
    still computed by default, with a `DeprecationWarning`). Each
    model is given the inputs it names: see `RoutingAnalysis`.

    `label` is a short identifier that tags the reports of this vessel
    and appears in the UI, `eff45` for example. By default it is taken
    from the polar file name, or is the name without a file.

    Args:
        name: Name of this object, used in status messages.
        filepath: Polar file, NetCDF. None for a vessel whose models
            are functions or constants.
        hotel_load: Hotel load in kW, added to `bhp`: a number or a
            function of the brake power.
        max_power: Power limit in kW of the default constraints, or
            None for no limit. Not given, it is 1e12 kW with a
            `DeprecationWarning`: None from 0.4.0.
        sfoc: Specific fuel oil consumption in g/kWh, for `bhp` and
            `total_power`: a number or a function of the total power.
            Missing when needed, it is 0 with a `DeprecationWarning`,
            which makes the fuel zero: an error from 0.4.0.
        verbose: Whether to report progress.
        label: Short identifier of the vessel in reports.
        fuel_type: Fuel burnt, a key of `fuels.FUELS` ("mdo",
            "hfo", "lng", "methanol", "unleaded"...) or of
            `fuels.FUEL_ALIASES`, or a `fuels.Fuel`: marine diesel oil
            by default. It gives `fuel_density` when that is not
            given, and its emission factors (`fuel`).
        fuel_density: Density of the fuel in kg/L, from the bunker
            delivery note for example; None for that of `fuel_type`
            (0.85 for "mdo").
        sfc: Former name of `sfoc`, deprecated: removed in 0.4.0.

    Example:
        >>> vessel = Vessel("ship", sfoc=190., max_power=4000.)
        >>> vessel.add_function("total_power", power, ["stw", "tws"])
    """

    def __init__(
        self,
        name: str,
        filepath: Optional[str] = None,
        hotel_load: Union[Callable, float, int] = 0., # kW
        max_power: Optional[float] = _UNSET, # kW
        sfoc: Union[Callable, float, int, None] = None, # g/kWh
        verbose: bool = True,
        label: Optional[str] = None,
        fuel_type: Union[str, Fuel] = DEFAULT_FUEL,
        fuel_density: Optional[float] = None, # kg/L
        sfc: Union[Callable, float, int, None] = None,
    ):
        super().__init__(name, verbose)

        self.path = filepath
        if label is None:
            label = _label_from_path(filepath) if filepath is not None else name
        self.label = label

        if sfc is not None:
            _warn_sfc()
            if sfoc is not None:
                raise TypeError("Give sfoc only: sfc is its former name.")
            sfoc = sfc

        self.fuel = get_fuel(fuel_type)
        self.fuel_type = fuel_key(self.fuel) or self.fuel.label
        self.fuel_density = self.fuel.density if fuel_density is None else float(fuel_density)
        if not self.fuel_density > 0.:
            raise ValueError(f"The fuel density of {name} should be positive, in kg/L: {fuel_density}.")
        self.hotel_load = ensure_callable(hotel_load)
        self.sfoc = ensure_callable(sfoc)
        if max_power is _UNSET:
            warnings.warn(
                "Vessel max_power not given: it is 1e12 kW, a slack that can unsettle "
                "IPOPT. From 0.4.0, its default is None, no power limit. Give "
                "max_power=... or max_power=None.",
                DeprecationWarning,
                stacklevel=2,
            )
            max_power = _DEFAULT_MAX_POWER
        self.max_power = max_power

    @property
    def sfc(self):
        """
        Former name of `sfoc`, deprecated: removed in 0.4.0.
        """
        _warn_sfc()
        return self.sfoc

    @sfc.setter
    def sfc(self, value):
        """
        Set `sfoc` through its former name, deprecated.
        """
        _warn_sfc()
        self.sfoc = ensure_callable(value)

    @property
    def consumption_model(self) -> Optional[str]:
        """
        The model that gives the consumption, or None.

        This is the first of `CONSUMPTION_KEYS` that the vessel has.
        """
        return next((key for key in CONSUMPTION_KEYS if key in self.models), None)

    def _formulation(self) -> str:
        formulation = self.consumption_model
        if formulation is None:
            raise KeyError(
                f"{self.name} has no consumption model. Add one of 'bhp' (with "
                "hotel_load and sfoc), 'total_power' (with sfoc) or "
                "'hourly_consumption' (L/h), with add_interpolator, "
                "add_function or add_constant."
            )
        return formulation

    def consumption_keys(self) -> list[str]:
        """
        Keys of the models that `consumption` queries.

        Returns:
            The consumption model, then the `hotel_load` and `sfoc`
            models it uses, if the vessel has them.
        """
        formulation = self._formulation()
        keys = [formulation]
        if formulation == "bhp" and "hotel_load" in self.models:
            keys.append("hotel_load")
        if formulation != "hourly_consumption" and "sfoc" in self.models:
            keys.append("sfoc")
        return keys

    def consumption_quantities(self) -> list[str]:
        """
        Quantities that `consumption` gives, by formulation.

        Returns:
            Names among `CONSUMPTION_QUANTITIES`.
        """
        start = {"bhp": 0, "total_power": 2, "hourly_consumption": 4}[self._formulation()]
        return list(CONSUMPTION_QUANTITIES[start:])

    def _load(self, key, query, power):
        """
        `hotel_load` or `sfoc`: their model, else their attribute.
        """
        if key in self.models:
            return self(key, query)
        function = getattr(self, key)
        if function is None and key == "sfoc":
            warnings.warn(
                f"{self.name} has no sfoc for its {self.consumption_model} model: it "
                "is 0 g/kWh, which makes the fuel zero. From 0.4.0, this raises "
                "an error. Give Vessel(sfoc=...) or a model 'sfoc'.",
                DeprecationWarning,
                stacklevel=4,
            )
            return 0.
        if function is None:
            raise ValueError(
                f"{self.name} needs {key} for its {self.consumption_model} model: "
                f"give Vessel({key}=...), a number or a function of the power, or "
                f"add a model {key!r}."
            )
        return function(power)

    def consumption(self, query: dict) -> dict:
        """
        Fuel consumption and the quantities that give it.

        With a `bhp` model, the total power is `bhp + hotel_load`. The
        total power, from it or from a `total_power` model, is burnt
        at `sfoc`, and the mass divided by `fuel_density`. An
        `hourly_consumption` model gives the consumption directly, in
        L/h. Each model takes the inputs it names in `query`, and
        those computed before it: `bhp`, `hotel_load`, `total_power`.

        Args:
            query: Inputs of the models, keyed by name, NumPy or
                CasADi.

        Returns:
            A dict of the quantities of `consumption_quantities`, in
            order: `bhp` and `hotel_load` (kW), `total_power` (kW),
            `sfoc` (g/kWh) and `hourly_consumption` (L/h). A constant
            may stay a scalar.

        Example:
            >>> vessel.consumption({"stw": 12., "tws": 20., ...})
        """
        formulation = self._formulation()
        query = dict(query)

        if formulation == "hourly_consumption":
            return {"hourly_consumption": self("hourly_consumption", query)}

        quantities = {}
        if formulation == "bhp":
            bhp = self("bhp", query)
            query["bhp"] = bhp
            hotel_load = self._load("hotel_load", query, bhp)
            query["hotel_load"] = hotel_load
            total_power = bhp + hotel_load
            quantities |= {"bhp": bhp, "hotel_load": hotel_load}
        else:
            total_power = self("total_power", query)
        query["total_power"] = total_power

        sfoc = self._load("sfoc", query, total_power)
        # kW * g/kWh = g/h, in kg/h, then in L/h
        hourly_consumption = np.abs(total_power) * sfoc / 1e3 / self.fuel_density

        return quantities | {
            "total_power": total_power,
            "sfoc": sfoc,
            "hourly_consumption": hourly_consumption,
        }

    def _locate_data(self):
        assert self.path is not None, f"💔 {self.name} has no polar file: use add_function."
        assert os.path.exists(self.path), f"💔 '{self.path}' does not exist."
        self.info(f"✅ {self.name} data found.")

    def _read_data(self):
        self.data = xr.open_dataset(self.path) # TODO add columns selection to save memory

    def _convert_data(self):
        # TODO complete missing points
        pass

    def add_interpolator(
        self,
        var_dim: str,
        stw_dim: str,
        tws_dim: str,
        twa_dim: str,
        hs_dim: str,
        wa_dim: str,
        var_key: str = None,
        stw_slice: slice = slice(None, None, None),
        tws_slice: slice = slice(None, None, None),
        twa_slice: slice = slice(None, None, None),
        hs_slice: slice = slice(None, None, None),
        wa_slice: slice = slice(None, None, None),
        method: str = "linear",
    ):
        """
        Build the lookup table of a variable of the polars.

        It is queried with a dict keyed by `stw`, `tws`, `twa`, `hs` and
        `wa`, whatever the names of the coordinates.

        Args:
            var_dim: Name of the variable in the data.
            stw_dim: Name of the speed through water coordinate.
            tws_dim: Name of the true wind speed coordinate.
            twa_dim: Name of the true wind angle coordinate.
            hs_dim: Name of the significant wave height coordinate.
            wa_dim: Name of the wave angle coordinate.
            var_key: Key of the lookup table, by default `var_dim`.
            stw_slice: Slice of the speeds through water.
            tws_slice: Slice of the true wind speeds.
            twa_slice: Slice of the true wind angles.
            hs_slice: Slice of the wave heights.
            wa_slice: Slice of the wave angles.
            method: Interpolation method, "linear", "bspline" or
                "nearest".
        """
        if var_key is None:
            var_key = var_dim

        coord_dims = [stw_dim, tws_dim, twa_dim, hs_dim, wa_dim]
        coord_slices = [stw_slice, tws_slice, twa_slice, hs_slice, wa_slice]

        super().add_interpolator(
            var_dim,
            coord_dims,
            coord_slices,
            var_key,
            method,
            coord_keys=VESSEL_KEYS,
        )

    def add_interpolators(
        self,
        keys: Sequence[str] = POLAR_KEYS,
        dims: Sequence[str] = POLAR_DIMS,
        method: str = "linear",
    ):
        """
        Add an interpolator for each variable of `keys`.

        By default `keys` holds the variables of a usual polar table:
        `bhp`, `max_bhp` and `sails_contribution`.
        """
        for key in keys:
            self.add_interpolator(key, *dims, method=method)


if __name__=="__main__":

    # vessel_data = "C:\\Users\\jules\\output_sails.nc"
    vessel_data = r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff100.nc"
    # vessel_data = "C:\\Users\\jrich\\output_sails.nc"

    columns = ["bhp", "max_bhp", "leeway"]

    vessel = Vessel("base_vessel", vessel_data, max_power=1000., hotel_load=100., sfoc=190.)
    vessel.load_data()

    vessel.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("max_bhp", "stw", "tws", "twa", "hs", "wa", method="linear")

    vessel_query = {
        "stw": np.array([6., 8.]),
        "tws": 15.,
        "twa": 60.,
        "hs": np.array([4.1, 1.]),
        "wa": 60.,
    }

    bhp = vessel("bhp", vessel_query)
    print(bhp)
    print(vessel.consumption(vessel_query))

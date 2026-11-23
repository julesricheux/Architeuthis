# -*- coding: utf-8 -*-
"""
The routing problem: `RoutingAnalysis` and its evaluation.

It also re-exports the offline classes of routes, voyages and reports.

Created on Mon Jan 19 15:54:06 2026

@author: jrich
"""


import json
import re
import warnings

import casadi as ca
import numpy as onp
import pandas as pd

import architeuthis.numpy as np

from abc import abstractmethod
from typing import Callable, Mapping, Optional, Sequence, Union
from architeuthis.vessel import CONSUMPTION_QUANTITIES, Vessel
from architeuthis.common import _banner, status
from architeuthis.optimization import Opti
from architeuthis.forecast import ENVIRONMENT_FIELDS, Forecast, Topography, calm_forecast
from architeuthis.report import RoutingReport, _RenamedEntries
from architeuthis.common import ArchiteuthisObject, GUST_DEFAULT_RATIO, WAVE_COMPONENTS_OFFSET
# Route and voyage classes live in their own modules, which work without network
# access; they are re-exported here for compatibility.
from architeuthis.route import Leg, Route, RouteLibrary, RouteSet, RouteSetLibrary, Waypoint  # noqa: F401
from architeuthis.voyage import PassagePlan, PassagePlanLibrary, Schedule, Voyage  # noqa: F401
from architeuthis.exclusion import (  # noqa: F401
    ExclusionZone,
    ExclusionZoneLibrary,
)
from architeuthis.toolbox.geo_utils import (
    great_circle_route,
    distances,
    midpoints,
    headings,
    poly_deviated_route,
    resample_coordinates,
)

# Useful for broadcasting with matrices later.
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


def added_wave_load(hs):
    """
    Added wave load for a wave height `hs`, from a linear regression.
    """
    a = 3.951610803604126 / 100. # regression 11/12/2025
    
    return a*hs

def sigmoid(x):
    """
    Smooth step from -1 to 1, `2 * arctan(x) / pi`.
    """
    return 2*np.arctan(x)/np.pi


def transform(x, delta):
    """
    `sigmoid(x)`, scaled by `delta` as a column vector.
    """
    # return x
    # return 2 * (np.sigmoid(x) - 0.5) * delta
    return (sigmoid(x)) * tall(delta)

# Vessel models still computed when the vessel has them and they are not listed
# in the variables, with a DeprecationWarning: only when listed from 0.4.0.
IMPLICIT_VESSEL_VARIABLES = ("max_bhp", "sails_contribution")

# Powers that the default constraints keep below `Vessel.max_power`: the first
# of them in the context.
POWER_LIMITED_QUANTITIES = ("max_bhp", "bhp", "total_power")


def default_routing_constraints(ctx: dict) -> list:
    """
    Default constraints function for RoutingAnalysis.

    Every position is at sea, `z < 0`. If the vessel has a
    `max_power`, the first of `max_bhp` (when listed in the
    variables), `bhp` and `total_power` that the passage has stays
    below it.

    Args:
        ctx: The quantities of the passage, with `vessel`.

    Returns:
        The list of constraints.
    """
    constraints = []
    max_power = ctx["vessel"].max_power
    power = next((key for key in POWER_LIMITED_QUANTITIES if key in ctx), None)
    if max_power is not None and power is not None:
        constraints.append(ctx[power] < max_power)
    constraints.append(ctx["z"] < 0.)
    return constraints


def _column(value, like):
    """
    A CasADi column as long as `like`: a scalar is repeated.
    """
    if not isinstance(value, (ca.MX, ca.SX, ca.DM)):
        value = ca.DM(onp.asarray(value, dtype=float))
    if value.shape == (1, 1) and like.shape[0] != 1:
        value = ca.repmat(value, like.shape[0], 1)
    return value

DEFAULT_SOLVER_OPTIONS = {
    "ipopt":{
        # "tol": 1e-3,
        "acceptable_tol": 1e9,

        # 'linear_solver': 'mumps',
        'linear_solver': 'spral',
        
        "hessian_approximation": "limited-memory",
    },
}

SOLVED = {
    "Solve_Succeeded",
    "Solved_To_Acceptable_Level",
}


def __getattr__(name: str):
    """
    Compute `berg_zone` when it is read.

    The iceberg limit is thus fetched when it is used, not when this
    module is imported.
    """
    if name == "berg_zone":
        from architeuthis.icebergs import berg_zone
        return berg_zone
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


#%%

class ArchiteuthisAnalysis(ArchiteuthisObject):
    """
    Base class of the analyses.

    `status` is 0 when not solved, 1 when solved and 2 when not
    converged.

    Args:
        name: Name of this object, used in status messages.
        verbose: Whether to report progress.
    """

    @abstractmethod
    def __init__(
        self,
        name: str,
        verbose: bool = True,
    ):
        self.status = 0 # 0: not solved, 1: solved, 2: not converged

        super().__init__(name, verbose)


# The consumption quantities of the vessel in passages and reports, under the
# keys of its models. Which of them a passage has depends on the vessel.
_CONSUMPTION_QUANTITIES = CONSUMPTION_QUANTITIES

# Quantities computed on a passage and returned in reports, in addition to positions and times.
_REPORT_QUANTITIES = (
    "fuel", *_CONSUMPTION_QUANTITIES, "stw", "sog", "cog", "ctw", "tws", "twd", "twa",
    "aws", "awa", "swh", "mwd", "mwa", "z", "cs", "cd",
    "tim", "lat", "lon", "ctim", "clat", "clon", "d",
)
_GUST_QUANTITIES = ("tws_gust", "aws_gust")
# The quantities of every passage, which a variable may only name as itself, as
# the consumption quantities that the vessel gives.
_PASSAGE_QUANTITIES = frozenset(_REPORT_QUANTITIES) - frozenset(_CONSUMPTION_QUANTITIES)

# Vessel inputs of the wind at a height, `twa100` for example: computed from the
# forecast variables `u100` and `v100`, as the 10 m wind is from `u10` and `v10`.
_WIND_AT_HEIGHT = re.compile(r"^(tws|twd|twa|aws|awa)(\d+)$")

# The variable that asks for the gusts, in kt: the true and apparent wind gusts.
GUST_VARIABLE = "gust"

# Step of the time grid when no forecast has data, in seconds.
DEFAULT_TIME_STEP = 3. * 3600.

# Where a variable named by a model key is looked for, in this order, unless
# its specification names the source: "wave.slope".
VARIABLE_SOURCES = ("atmosphere", "wave", "current", "vessel")

# Report entries and context keys that are not passage quantities, which an
# additional variable cannot be named.
_RESERVED_NAMES = frozenset((
    "etd", "eta", "transit_sog", "transit_time", "init_fac", "pos", "cpos",
    "dist", "dist_rel", "status", "constraint_violations",
    "max_constraint_violation", "plan", "vessel", "opti",
    # default tags, which would replace them in the report
    "solve", "model", "member",
))

KNOTS_PER_METER_PER_SECOND = 3600. / 1852.

# A variable: a name, a model key or callable, or a list or dict of them.
VariableSpecification = Union[str, Callable[[dict], object]]
Variables = Union[
    None,
    str,
    Mapping[str, Optional[VariableSpecification]],
    Sequence[Union[str, Mapping[str, Optional[VariableSpecification]]]],
]


def normalize_variables(variables: Variables) -> dict:
    """
    Additional variables as a dict of names and specifications.

    A name alone is its own specification: `"slope"` is
    `{"slope": "slope"}`, and so is `{"slope": None}`. Its source
    prefix is not part of the name: `"wave.slope"` is
    `{"slope": "wave.slope"}`. `"gust"` alone asks for the gusts, and
    becomes `tws_gust` and `aws_gust`; the gust model itself, in m/s,
    is named otherwise, as in `{"gust_ms": "atmosphere.gust"}`.

    Args:
        variables: None, a name, a dict of names and specifications,
            or a list of names and of such dicts. A specification is a
            model key, optionally prefixed by its source as in
            `"wave.slope"`, or a callable of the context.

    Returns:
        A new dict of names and specifications, in the given order.

    Example:
        >>> list(normalize_variables(["gust", "wave.slope"]).items())
        [('tws_gust', 'tws_gust'), ('aws_gust', 'aws_gust'),
         ('slope', 'wave.slope')]
    """
    if variables is None:
        return {}
    if isinstance(variables, str):
        entries = [(variables, None)]
    elif isinstance(variables, Mapping):
        entries = list(variables.items())
    else:
        entries = []
        for entry in variables:
            if isinstance(entry, str):
                entries.append((entry, None))
            elif isinstance(entry, Mapping):
                entries.extend(entry.items())
            else:
                raise TypeError(
                    "variables are names, or dicts of names and specifications, "
                    f"not {entry!r}."
                )

    normalized = {}
    for name, specification in entries:
        if not isinstance(name, str) or not name:
            raise TypeError(f"A variable name must be a non-empty string, not {name!r}.")
        if specification is None:
            specification = name
            prefix, dot, key = name.partition(".")
            if dot and prefix in VARIABLE_SOURCES and key:
                name = key
        if name == GUST_VARIABLE and specification == GUST_VARIABLE:
            normalized |= {key: key for key in _GUST_QUANTITIES}
            continue
        if not (isinstance(specification, str) or callable(specification)):
            raise TypeError(
                f"Variable {name!r}: a specification is a model key, such as "
                f"'wave.slope', or a callable of the context, not {specification!r}."
            )
        normalized[name] = specification
    return normalized


def _describe_variables(variables: dict) -> dict:
    """
    JSON-friendly copy of normalized variables.

    Callables are given by their name.
    """
    return {
        name: specification if isinstance(specification, str) else getattr(specification, "__name__", "function")
        for name, specification in variables.items()
    }


def _evaluate_at(opti, expression, parameter_values):
    """
    Numeric value of an expression of parameters only, without solving.

    Args:
        opti: The Opti instance that holds the parameters.
        expression: A CasADi expression, or a plain number.
        parameter_values: `opti.value_parameters()`.

    Returns:
        A float for a scalar, otherwise a NumPy array, as `OptiSol`
        returns them.
    """
    if not isinstance(expression, (ca.MX, ca.SX, ca.DM)):
        return expression
    value = onp.asarray(opti.value(expression, parameter_values), dtype=float)
    return float(value) if value.size == 1 else value


def _constraint_violation(constraint):
    """
    Symbolic violation of `a < b`, `a <= b` or `a == b`, or None.

    It is positive when the constraint is violated.
    """
    if not isinstance(constraint, (ca.MX, ca.SX)):
        return None
    if constraint.is_op(ca.OP_LT) or constraint.is_op(ca.OP_LE):
        return constraint.dep(0) - constraint.dep(1)
    if constraint.is_op(ca.OP_EQ):
        return ca.fabs(constraint.dep(0) - constraint.dep(1))
    return None


def _numeric(value):
    """
    Convert a casadi result like `OptiSol` does.

    This gives a float for one value, else a 1D array.
    """
    array = onp.asarray(ca.DM(value).full() if isinstance(value, (ca.DM, ca.MX, ca.SX)) else value, dtype=float)
    if array.size == 1:
        return float(array.item())
    return array.ravel()


def _describe(
    obj,
    attributes=(
        "model", "product", "dataset", "f00", "path", "label", "consumption_model", "max_power",
        "fuel_type", "fuel_density", "members",
    ),
):
    """
    A JSON-friendly description of a data object.

    It goes into the passage plan metadata.
    """
    if obj is None:
        return None
    description = {"class": type(obj).__name__, "name": getattr(obj, "name", None)}
    for attribute in attributes:
        value = getattr(obj, attribute, None)
        if value is None or callable(value):
            continue
        try:
            json.dumps(value)
        except TypeError:
            value = str(value)
        description[attribute] = value
    return description


# TODO find a name for the method?
class RoutingAnalysis(ArchiteuthisAnalysis):
    """
    Minimum-fuel routing of a voyage through forecast fields.

    `run` optimizes the positions on a schedule fixed by the voyage, and
    stores the result as `self.report` (a dict of arrays) and
    `self.passage_plan` (a `PassagePlan`). `evaluate(plan)` computes the
    same report for given positions, without optimizing, with this
    analysis' vessel and forecasts: an open-loop check of a passage
    plan.

    `wave` must have the interpolators `swh`, `uw` and `vw`, the last
    two added by `Forecast.add_wave_components`: the wave direction is
    interpolated through its components, as the wind is.

    The environment may be incomplete: `atmosphere`, `wave` and
    `current` are None by default, and each one left to None is a
    `calm_forecast` of that source, whose fields are zero: a calm
    wind (`u10`, `v10`), a flat sea (`swh`, `uw`, `vw`) or no current
    (`uo`, `vo`). The time grid comes from the first of them with
    data, the atmosphere normally, or is every `DEFAULT_TIME_STEP`
    without any. The topography is required.

    The objective is the fuel, in tonnes, from the consumption of the
    vessel in L/h times its `fuel_density`: its `hourly_consumption`
    model, or its `total_power` or its `bhp` plus hotel load, burnt at
    its `sfoc` (see `Vessel`). These quantities are in the report,
    under the keys of the vessel models (`bhp` for the brake power,
    `hourly_consumption` in L/h). Other
    vessel models, such as `max_bhp` or `sails_contribution`, are
    computed only when listed in `variables`. Until 0.4.0, `max_bhp`
    and `sails_contribution` are still computed when the vessel has
    them, with a `DeprecationWarning`: list them.

    Each vessel model is queried with the inputs it names among
    `stw`, `sog`, `tws`, `twa`, `hs` or `swh`, `wa` or `mwa`, `aws` and
    `awa` (angles in absolute value), and the consumption quantities
    computed before it, such as `bhp` or `total_power` for an `sfoc`
    model. Any other input, a water
    temperature or a wave period for example, is a forecast variable:
    it is read from the first of `atmosphere`, `wave` and `current`
    that has a model with that key. The wind at another height,
    `tws100`, `twd100`, `twa100`, `aws100` or `awa100` for example, is
    computed from the forecast variables `u100` and `v100`, relative to
    the vessel as the 10 m wind is.

    `variables` asks for more quantities along the passage, which the
    vessel models need not use: they are computed at segment midpoints,
    passed to the constraints in `ctx` and stored in the report, under
    their name. It is a name, a list of names, or a dict of names and
    specifications, and `run` and `evaluate` can add more. A
    specification is:

    - `"gust"`: the gusts, `tws_gust` and `aws_gust` (kt), from the
      atmospheric model `gust` in m/s, or `tws * GUST_DEFAULT_RATIO`
      without it.
    - A model key, such as `"slope"` or `"pres"`: the first of
      `atmosphere`, `wave`, `current` and `vessel` with a model of that
      key is queried, in the units of the model. A prefix picks the
      source: `"atmosphere.gust"`, `"vessel.leeway"`. Forecasts are
      queried at the time and position of the segments, the vessel
      with the inputs its models name, as for the polars.
    - A quantity that the routing computes: `tws_gust` or `aws_gust`
      alone, the wind at another height
      (`tws100`, `twd100`, `twa100`, `aws100`, `awa100`, angles signed
      as `twa`), or any quantity of the report, such as `tws`.
    - A callable `ctx -> expression`, given the quantities of the
      passage and the variables listed before it, with `vessel`.

    `options={"include_gusts": True}` is deprecated, and will be
    removed in 0.4.0: give `variables=["gust"]`. Until then, the gusts
    are still computed by default, without `options`.

    Example:
        >>> wave.add_function(
        ...     "slope",
        ...     lambda x: wave("swh", x) / wave("mwp", x),
        ...     inputs=["valid_time", "latitude", "longitude"],
        ... )
        >>> analysis = RoutingAnalysis(
        ...     "analysis", vessel, voyage, atmosphere, wave, current,
        ...     topography,
        ...     variables=[
        ...         "max_bhp",
        ...         "gust",
        ...         "slope",
        ...         {"excess": lambda c: c["tws_gust"] - c["tws"]},
        ...     ],
        ...     constraints=lambda ctx: [
        ...         ctx["max_bhp"] < ctx["vessel"].max_power,
        ...         ctx["z"] < 0.,
        ...         ctx["excess"] < 15.,
        ...     ],
        ... )
    """

    def __init__(
        self,
        name: str,
        vessel: Vessel,
        voyage: Optional[Voyage],
        atmosphere: Optional[Forecast] = None,
        wave: Optional[Forecast] = None,
        current: Optional[Forecast] = None,
        topography: Topography = None,
        atmosphere_member: float = None,
        wave_member: float = None,
        constraints: Optional[Callable[[dict], list]] = default_routing_constraints,
        options: Optional[dict] = None,
        variables: Variables = None,
        verbose: bool = True,
    ):
        if topography is None:
            raise TypeError(f"RoutingAnalysis {name!r} needs a topography.")

        self.vessel = vessel
        self.voyage = voyage
        self.topography = topography
        # A source left to None is calm: its routing fields are zero
        self.atmosphere = self._source("atmosphere", atmosphere, verbose)
        self.wave = self._source("wave", wave, verbose)
        self.current = self._source("current", current, verbose)

        self.atmosphere_member = atmosphere_member
        self.wave_member = wave_member
        self.constraints = constraints
        if options is not None and "include_gusts" in options:
            warnings.warn(
                "RoutingAnalysis(options={'include_gusts': ...}) is deprecated and will "
                "be removed in 0.4.0. Give variables=['gust'] to compute tws_gust and "
                "aws_gust; from 0.4.0, they are computed only then.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.options = options if options is not None else {"include_gusts": True}
        self.variables = normalize_variables(variables)

        self.report = None
        self.passage_plan = None

        super().__init__(name, verbose)


    @staticmethod
    def _source(source: str, forecast: Optional[Forecast], verbose: bool) -> Forecast:
        """
        The forecast of a source, a `calm_forecast` if None.
        """
        if forecast is not None:
            return forecast
        if verbose:
            status(f"➖ No {source} given: {', '.join(ENVIRONMENT_FIELDS[source])} are zero.")
        return calm_forecast(source)

    def _forecasts(self) -> list:
        """
        The forecasts with data, among the atmosphere, wave and current.

        A `calm_forecast` has none.
        """
        return [
            forecast
            for forecast in (self.atmosphere, self.wave, self.current)
            if forecast.data is not None
        ]

    def check_valid_time(self, etd: float = None, eta: float = None):
        """
        Warn if the schedule is outside a forecast.

        The last real step is taken as `valid_time[-3]`, because
        forecasts end with two fake time steps.

        Args:
            etd: Departure time, by default the one of the voyage.
            eta: Arrival time, by default the one of the voyage.
        """
        etd = self.voyage.etd if etd is None else etd
        eta = self.voyage.eta if eta is None else eta

        for forecast in self._forecasts():
            f00 = forecast.data["valid_time"].values[0]
            f99 = forecast.data["valid_time"].values[-3]

            if etd < f00:
                status(f"⚠️ Warning: ETD sooner than earliest {forecast.name.upper()} forecast valid time.")
            if eta > f99:
                status(f"⚠️ Warning: ETA later than furthest {forecast.name.upper()} forecast valid time.")

    def _variables(self, variables: Variables = None) -> dict:
        """
        Additional variables of a run or an evaluation.

        These are the gusts of `options["include_gusts"]` (deprecated),
        the vessel models of `IMPLICIT_VESSEL_VARIABLES` that are not
        listed (deprecated), then the variables of this analysis, then
        `variables`.
        """
        gusts = {key: key for key in _GUST_QUANTITIES} if self.options.get("include_gusts", False) else {}
        listed = normalize_variables(self.variables) | normalize_variables(variables)
        implicit = {
            key: key for key in IMPLICIT_VESSEL_VARIABLES
            if key in self.vessel.models and key not in listed
        }
        if implicit:
            names = ", ".join(implicit)
            warnings.warn(
                f"RoutingAnalysis computes {names} because the vessel has these "
                "models. This is deprecated: from 0.4.0, vessel models other than "
                f"the consumption are computed only when listed, as in "
                f"variables={list(implicit)}.",
                DeprecationWarning,
                stacklevel=3,
            )
        return gusts | implicit | listed

    def _resolve_variable(self, name: str, specification, quantities=_PASSAGE_QUANTITIES) -> tuple:
        """
        How a variable is computed: `(kind, source, key)`.

        `kind` is "function", "quantity" (of the passage, among
        `quantities`), "derived" (gusts, wind at a height) or "model"
        (of `source`).
        """
        if name in _RESERVED_NAMES:
            raise ValueError(f"{name!r} is a reserved report entry: give this variable another name.")

        if callable(specification):
            resolved = ("function", None, specification)
        else:
            prefix, dot, rest = specification.partition(".")
            source, key = (prefix, rest) if dot and prefix in VARIABLE_SOURCES else (None, specification)
            if source is not None:
                if key not in getattr(self, source).models:
                    raise KeyError(
                        f"Variable {name!r}: {getattr(self, source).name} ({source}) has no "
                        f"model {key!r}. Add it with add_interpolator or add_function."
                    )
                resolved = ("model", source, key)
            elif key in quantities:
                resolved = ("quantity", None, key)
            elif key in _GUST_QUANTITIES or _WIND_AT_HEIGHT.match(key):
                resolved = ("derived", None, key)
            else:
                source = next((source for source in VARIABLE_SOURCES if key in getattr(self, source).models), None)
                if source is None:
                    names = ", ".join(f"{getattr(self, source).name} ({source})" for source in VARIABLE_SOURCES)
                    raise KeyError(
                        f"Variable {name!r}: {key!r} is not a routing quantity, and no "
                        f"model of {names} has this key. Add it with add_interpolator "
                        "or add_function."
                    )
                resolved = ("model", source, key)

        if name in quantities and resolved != ("quantity", None, name):
            raise ValueError(
                f"{name!r} is already computed by the routing: give the variable "
                f"{specification!r} another name."
            )
        return resolved

    def _passage(self, tim, ctim, lat, lon, variables: Optional[dict] = None) -> dict:
        """
        Symbolic model of a passage through nodes `tim`, `lat`, `lon`.

        The weather is sampled at segment midpoints at times `ctim`. All
        inputs are column vectors. `variables`, normalized, are added
        to the quantities, in their order.
        """
        variables = {} if variables is None else variables

        # The consumption quantities depend on the models of the vessel
        quantities = _PASSAGE_QUANTITIES | frozenset(self.vessel.consumption_quantities())
        plan = [
            (name, *self._resolve_variable(name, specification, quantities))
            for name, specification in variables.items()
        ]

        clon = midpoints(lon)
        clat = midpoints(lat)

        environment_query = {
            "valid_time": ctim,
            "latitude": clat,
            "longitude": clon,
        }

        # Ensemble forecasts also take the member, broadcast to all segments
        if self.atmosphere_member is not None:
            atmosphere_query = {**environment_query, "member": self.atmosphere_member}
        else:
            atmosphere_query = environment_query

        if self.wave_member is not None:
            wave_query = {**environment_query, "member": self.wave_member}
        else:
            wave_query = environment_query

        u10 = self.atmosphere("u10", atmosphere_query)
        v10 = self.atmosphere("v10", atmosphere_query)

        missing = {"swh", "uw", "vw"} - set(self.wave.interpolators)
        if missing:
            raise KeyError(
                f"{self.wave.name} has no interpolator for {sorted(missing)}. The wave "
                "direction is interpolated through its components: call "
                "add_wave_components, then add_interpolator for swh, uw and vw."
            )

        swh = self.wave("swh", wave_query)
        uw = self.wave("uw", wave_query)
        vw = self.wave("vw", wave_query)

        uc = self.current("uo", environment_query) * 3600./1852.
        vc = self.current("vo", environment_query) * 3600./1852.

        tlat, tlon = resample_coordinates(
            lat[1:-1],
            lon[1:-1],
            n=3,
        )

        topography_query = {
            "latitude": tlat,
            "longitude": tlon,
        }

        z = self.topography("z", topography_query)

        tws = np.sqrt(u10**2. + v10**2.) * 3600./1852.
        twd = np.mod(np.arctan2d(u10, v10)+180., 360.)

        # Direction the waves come from, as twd. The components weigh swh**2, and
        # the small offset keeps arctan2 differentiable where they vanish: land,
        # missing values and the fake steps past the forecast horizon.
        mwd = np.mod(np.arctan2d(uw, vw + WAVE_COMPONENTS_OFFSET) + 180., 360.)

        cog = headings(lat, lon)

        twa = np.mod(twd-cog + 180., 360.) - 180
        mwa = np.mod(mwd-cog + 180., 360.) - 180

        d = distances(lat, lon)
        dt = np.diff(tim) / 3600.
        sog = d/dt

        duog = sog * np.sind(cog)
        dvog = sog * np.cosd(cog)

        dutw = duog - uc
        dvtw = dvog - vc

        stw = np.sqrt(dutw**2. + dvtw**2.)
        ctw = np.mod(np.arctan2d(dutw, dvtw), 360.)

        # Apparent wind components relative to vessel heading
        u_aw = tws * np.sind(twa)
        v_aw = tws * np.cosd(twa) + sog

        # Apparent Wind Speed (AWS) and Apparent Wind Angle (AWA)
        aws = np.sqrt(u_aw**2. + v_aw**2.)
        awa = np.arctan2d(u_aw, v_aw)

        # Current Speed (CS) and Current direction (CD)
        cs = np.sqrt(uc**2. + vc**2.) # current speed in kts
        cd = np.mod(np.arctan2d(uc, vc), 360.) # current going to from 0 to 360 deg

        # Every vessel model takes the inputs it names: polar tables the first
        # five, semi-empirical functions possibly others, and the consumption
        # quantities computed before it. Angles are absolute.
        vessel_query = {
            "stw": stw,
            "tws": tws,
            "twa": np.abs(twa),
            "hs": swh,
            "wa": np.abs(mwa),
            "sog": sog,
            "swh": swh,
            "mwa": np.abs(mwa),
            "aws": aws,
            "awa": np.abs(awa),
            "twd": twd,
        }

        # Other inputs are forecast variables, read from the first forecast that
        # has a model of them: a water temperature, a wave period... The wind at
        # another height (tws100, twa100, awa100...) is computed from u100 and
        # v100, relative to the vessel as the 10 m wind is.
        forecast_queries = (
            (self.atmosphere, atmosphere_query),
            (self.wave, wave_query),
            (self.current, environment_query),
        )
        consumption_keys = self.vessel.consumption_keys()
        vessel_keys = consumption_keys + [
            key for _, kind, source, key in plan
            if kind == "model" and source == "vessel" and key not in consumption_keys
        ]
        for key in self._vessel_inputs(vessel_keys):
            if key in vessel_query or key in CONSUMPTION_QUANTITIES:
                continue
            wind = _WIND_AT_HEIGHT.match(key)
            if wind is not None:
                vessel_query |= self._wind_at_height(wind.group(2), cog, sog, forecast_queries)
            else:
                vessel_query[key] = self._forecast_variable(key, forecast_queries)

        # The objective: L/h over each segment, times kg/L, in tonnes
        consumption = {
            key: _column(value, dt)
            for key, value in self.vessel.consumption(vessel_query).items()
        }
        vessel_query |= consumption
        fuel = np.sum(consumption["hourly_consumption"] * dt) * self.vessel.fuel_density / 1e3

        passage = {
            "fuel": fuel,
            **consumption,
            "z": z,
            "sog": sog,
            "stw": stw,
            "ctw": ctw,
            "tws": tws,
            "twd": twd,
            "twa": twa,
            "aws": aws,
            "awa": awa,
            "swh": swh,
            "mwd": mwd,
            "mwa": mwa,
            "cog": cog,
            "cs": cs,
            "cd": cd,
            "d": d,
            "tim": tim,
            "lat": lat,
            "lon": lon,
            "ctim": ctim,
            "clat": clat,
            "clon": clon,
        }

        # Additional variables, in their order: a callable sees those before it
        model_queries = {
            "atmosphere": atmosphere_query,
            "wave": wave_query,
            "current": environment_query,
            "vessel": vessel_query,
        }
        derived = {}
        for name, kind, source, key in plan:
            if kind == "model":
                passage[name] = getattr(self, source)(key, model_queries[source])
            elif kind == "quantity":
                passage[name] = passage[key]
            elif kind == "derived":
                passage[name] = self._derived_variable(key, passage, derived, atmosphere_query, forecast_queries)
            else:
                passage[name] = key({"vessel": self.vessel} | passage)

        return passage

    def _derived_variable(self, key, passage, derived, atmosphere_query, forecast_queries):
        """
        A quantity that the routing computes on request.

        `derived` caches them for one passage, so that `aws_gust` and
        `tws_gust` read the gust once and in kt, whatever the names of
        the variables.
        """
        if key in derived:
            return derived[key]

        if key == "tws_gust":
            if "gust" in self.atmosphere.models:
                value = self.atmosphere("gust", atmosphere_query) * KNOTS_PER_METER_PER_SECOND
            else:
                self.info("🌪️ Info: gust not found in interpolators. Defaulting to the standard ratio.")
                value = passage["tws"] * GUST_DEFAULT_RATIO
        elif key == "aws_gust":
            tws_gust = self._derived_variable("tws_gust", passage, derived, atmosphere_query, forecast_queries)
            u_aw_gust = tws_gust * np.sind(passage["twa"])
            v_aw_gust = tws_gust * np.cosd(passage["twa"]) + passage["sog"]
            value = np.sqrt(u_aw_gust**2. + v_aw_gust**2.)
        else:
            height = _WIND_AT_HEIGHT.match(key).group(2)
            wind = self._wind_at_height(
                height, passage["cog"], passage["sog"], forecast_queries, absolute=False,
            )
            derived |= wind
            value = wind[key]

        derived[key] = value
        return value

    def _vessel_inputs(self, var_keys: Sequence[str]) -> list:
        """
        Inputs of the vessel models that routing queries, in order.
        """
        inputs = []
        for var_key in var_keys:
            for name in self.vessel.input_names(var_key):
                if name not in inputs:
                    inputs.append(name)
        return inputs

    def _forecast_variable(self, key, forecast_queries):
        """
        A vessel input read from the forecasts, at segment midpoints.

        The atmosphere is looked at first, then the wave, the current.
        """
        for forecast, query in forecast_queries:
            if key in forecast.models:
                return forecast(key, query)
        names = ", ".join(forecast.name for forecast, _ in forecast_queries)
        raise KeyError(
            f"{self.vessel.name} needs {key!r}, which no forecast ({names}) "
            "has. Add a model of it, with add_interpolator or add_function."
        )

    def _wind_at_height(self, height, cog, sog, forecast_queries, absolute: bool = True) -> dict:
        """
        The wind at a height, relative to the vessel, as vessel inputs.

        `u{height}` and `v{height}` (m/s) are read from the forecasts
        and give the same quantities as `u10` and `v10`: `tws`, `twd`,
        `twa`, `aws` and `awa` suffixed with the height, in kt and
        degrees, angles relative to the COG in absolute value, or
        signed as in reports if `absolute` is False.
        """
        u = self._forecast_variable(f"u{height}", forecast_queries) * 3600./1852.
        v = self._forecast_variable(f"v{height}", forecast_queries) * 3600./1852.

        tws = np.sqrt(u**2. + v**2.)
        twd = np.mod(np.arctan2d(u, v) + 180., 360.)
        twa = np.mod(twd - cog + 180., 360.) - 180

        u_aw = tws * np.sind(twa)
        v_aw = tws * np.cosd(twa) + sog
        aws = np.sqrt(u_aw**2. + v_aw**2.)
        awa = np.arctan2d(u_aw, v_aw)

        return {
            f"tws{height}": tws,
            f"twd{height}": twd,
            f"twa{height}": np.abs(twa) if absolute else twa,
            f"aws{height}": aws,
            f"awa{height}": np.abs(awa) if absolute else awa,
        }

    def _resolve_constraints(self, constraints, ctx) -> list:
        active_constraints = constraints if constraints is not None else self.constraints

        if callable(active_constraints):
            return active_constraints(ctx)
        if isinstance(active_constraints, list):
            return active_constraints
        return []

    @staticmethod
    def _report(values: dict, etd, eta, init_fac, reference_distance, status, variables=()) -> RoutingReport:
        transit_time = (eta - etd) / 3600.
        dist = float(onp.sum(values["d"]))

        report = RoutingReport({
            "etd": etd,
            "eta": eta,
            "transit_sog": reference_distance / transit_time,
            "transit_time": transit_time,
            "init_fac": init_fac,
        })
        report |= {
            key: values[key]
            for key in _REPORT_QUANTITIES
            if key in values and key not in ("tim", "lat", "lon", "ctim", "clat", "clon", "d")
        }
        report |= {
            "pos": [[la, lo] for la, lo in zip(onp.ravel(values["lat"]), onp.ravel(values["lon"]))],
            "tim": values["tim"],
            "lat": values["lat"],
            "lon": values["lon"],
            "cpos": [[cla, clo] for cla, clo in zip(onp.ravel(values["clat"]), onp.ravel(values["clon"]))],
            "ctim": values["ctim"],
            "clat": values["clat"],
            "clon": values["clon"],
            "dist": dist,
            "dist_rel": dist / reference_distance,
            "status": status,
        }

        report |= {name: values[name] for name in variables}

        return report

    def _default_tags(self, solve) -> dict:
        """
        What identifies a report in tables, plots and the UI.

        `tags` can replace any of it.
        """
        return {
            "solve": int(bool(solve)),
            "model": getattr(self.atmosphere, "model", self.atmosphere.name),
            "vessel": getattr(self.vessel, "label", self.vessel.name),
            "member": self.atmosphere_member,
        }

    def describe(self) -> dict:
        """
        JSON-friendly description of this analysis.

        It covers the vessel, forecasts and options of the analysis.
        """
        return {
            "analysis": self.name,
            "vessel": _describe(self.vessel),
            "atmosphere": _describe(self.atmosphere),
            "wave": _describe(self.wave),
            "current": _describe(self.current),
            "topography": _describe(self.topography, attributes=("path", "depth_offset", "z_margin")),
            "atmosphere_member": self.atmosphere_member,
            "wave_member": self.wave_member,
            "exclusion_zones": [
                getattr(zone, "name", "unnamed")
                for zone in getattr(self.topography, "exclusion_zones", [])
            ],
            "options": dict(self.options),
            "variables": _describe_variables(self.variables),
        }

    def _time_grid(self, skip_tim: int):
        """
        Segment centers `ctim` and nodes `tim` of the passage.

        They come from the first forecast with data, the atmospheric
        one normally, or are every `DEFAULT_TIME_STEP` without any.
        """
        etd = self.voyage.etd
        eta = self.voyage.eta

        forecasts = self._forecasts()
        if forecasts:
            fxx = forecasts[0].data.valid_time.values
        else:
            fxx = onp.arange(
                onp.floor(etd / DEFAULT_TIME_STEP),
                onp.ceil(eta / DEFAULT_TIME_STEP) + 1,
            ) * DEFAULT_TIME_STEP
        ctim0 = fxx[(fxx > etd) * (fxx < eta)][skip_tim::1+skip_tim]

        tim0 = np.concatenate((
            [etd],
            midpoints(ctim0),
            [eta],
        ))

        return tim0, ctim0

    def _reference_path(self, curv_abc, deviation_fac):
        """
        Reference positions at curvilinear abscissae `curv_abc`.

        They are blended by `deviation_fac`.
        """
        lat0minus, lon0minus = self.voyage.route_minus(curv_abc)
        lat0ortho, lon0ortho = self.voyage.route_ortho(curv_abc)
        lat0plus, lon0plus = self.voyage.route_plus(curv_abc)

        lat0 = np.fmax(deviation_fac, 0) * lat0plus + (1-np.abs(deviation_fac)) * lat0ortho - np.fmin(deviation_fac, 0.) * lat0minus
        lon0 = np.fmax(deviation_fac, 0) * lon0plus + (1-np.abs(deviation_fac)) * lon0ortho - np.fmin(deviation_fac, 0.) * lon0minus

        return lat0, lon0

    def _store_results(self, report: RoutingReport, tags: dict, run_options: dict):
        """
        Keep the last report and passage plan on this analysis.
        """
        self.report = report
        self.passage_plan = PassagePlan.from_report(
            report,
            route=self.voyage.route,
            name=f"{self.voyage.route.name}_{pd.Timestamp(self.voyage.etd, unit='s'):%Y%m%dT%H%M}Z",
            metadata=self.describe() | {"run": run_options, "tags": tags},
            verbose=self.verbose,
        )

    def run(
        self,
        init_fac: float = 0.,
        vary_fac: bool = False,
        skip_tim: int = 0,
        max_iter: int = 1000,
        solver_options: dict = DEFAULT_SOLVER_OPTIONS,
        solve: bool = True,
        constraints: Optional[Union[Callable[[dict], list], list]] = None,
        tags: Optional[dict] = None,
        callback: Optional[Callable[[int], object]] = None,
        variables: Variables = None,
    ) -> RoutingReport:
        """
        Optimize the positions of the voyage.

        If `solve` is False, evaluate its reference route instead.

        Args:
            init_fac: Deviation factor of the reference route, between
                the minus (-1), ortho (0) and plus (+1) routes of the
                voyage.
            vary_fac: Whether the deviation factor is also optimized.
            skip_tim: Thins the time grid by keeping one forecast step
                out of `1 + skip_tim`.
            max_iter: Maximum number of IPOPT iterations.
            solver_options: Options of the solver, as in `Opti.solve`.
            solve: False evaluates the reference route without
                optimizing it.
            constraints: Constraints of this run, replacing those of the
                analysis: a callable `ctx -> list` or a list.
            tags: Entries added to the report, identifying it in tables,
                plots and the UI. `solve`, `model` (of the atmospheric
                forecast), `vessel` (its label) and `member` are set by
                default and can be replaced here.
            callback: Called at each IPOPT iteration with the iteration
                number, for example to report progress in a GUI. See
                `Opti.solve`.
            variables: Additional variables of this run, added to those
                of the analysis (see the class): computed along the
                passage, in `ctx` and in the report.

        Returns:
            A `RoutingReport`, a dict of numeric arrays and scalars,
            also stored in `self.report`. The timed positions are stored
            in `self.passage_plan`.
        """
        if self.voyage is None:
            raise ValueError("RoutingAnalysis.run needs a voyage. To evaluate a passage plan without one, use evaluate.")

        run_variables = self._variables(variables)

        etd = self.voyage.etd
        eta = self.voyage.eta

        self.check_valid_time()

        tim0, ctim0 = self._time_grid(skip_tim)

        npts = len(tim0)
        curv_abc = (tim0 - etd) / (eta - etd)

        # Initializing opti
        opti = Opti()

        if vary_fac and solve:
            deviation_fac = opti.variable(init_guess=init_fac)
        else:
            deviation_fac = opti.parameter(init_fac)

        lat0, lon0 = self._reference_path(curv_abc, deviation_fac)

        # TODO no constraints so add an inside-bounds check at the end of the computation
        if solve:
            vlon = opti.variable(n_vars=npts-2, init_guess=0.,)
            vlat = opti.variable(n_vars=npts-2, init_guess=0.,)
        else:
            vlon = 0.
            vlat = 0.

        tim = opti.parameter(n_params=npts)
        opti.set_value(tim, tim0)

        ctim = opti.parameter(n_params=npts-1)
        opti.set_value(ctim, ctim0)

        lon = np.concatenate((lon0[:1], lon0[1:-1] + vlon, lon0[-1:]))
        lat = np.concatenate((lat0[:1], lat0[1:-1] + vlat, lat0[-1:]))

        passage = self._passage(tim, ctim, lat, lon, run_variables)

        # --- Dynamic Constraints Context ---
        ctx = _RenamedEntries({"vessel": self.vessel, "opti": opti} | passage)
        cons = self._resolve_constraints(constraints, ctx)

        if solve:
            opti.subject_to(cons)
            opti.minimize(passage["fuel"])

        self.info(_banner)

        if solve:
            sol = opti.solve(
                max_iter=max_iter,
                callback=callback,
                behavior_on_failure="return_last",
                options=solver_options,
                verbose=self.verbose,
            )
            solve_status = 1 if opti.return_status() in SOLVED else 2
            values = {key: sol(expression) for key, expression in passage.items()}
        else:
            # The reference route has no variable: evaluate it at the parameter
            # values rather than give IPOPT an empty problem, which spral crashes
            # on with casadi 3.7.2 on Windows and MUMPS rejects.
            sol = None
            solve_status = 1
            parameter_values = opti.value_parameters()
            values = {
                key: _evaluate_at(opti, expression, parameter_values)
                for key, expression in passage.items()
            }

        self.opti = opti
        self.sol = sol
        self.status = solve_status

        output = self._report(
            values,
            etd=etd,
            eta=eta,
            init_fac=init_fac,
            reference_distance=self.voyage.distance,
            status=solve_status,
            variables=run_variables,
        )

        run_tags = self._default_tags(solve) | (tags or {})
        output |= run_tags

        self._store_results(
            output,
            tags=run_tags,
            run_options={
                "init_fac": init_fac,
                "vary_fac": vary_fac,
                "skip_tim": skip_tim,
                "max_iter": max_iter,
                "solve": solve,
                "variables": _describe_variables(normalize_variables(variables)),
            },
        )

        return output

    def evaluate(
        self,
        plan: Union[PassagePlan, dict],
        constraints: Optional[Union[Callable[[dict], list], list]] = None,
        tags: Optional[dict] = None,
        variables: Variables = None,
    ) -> RoutingReport:
        """
        Open-loop evaluation of a passage plan.

        It uses the vessel and forecasts of this analysis.

        The positions and times of the plan are kept exactly: nothing is
        optimized and IPOPT is not called. This measures how the
        consumption of a plan, optimized under some conditions, changes
        under other ones (vessel, weather model, ensemble member,
        options). The analysis needs no voyage for this: it can be built
        with `voyage=None`, as the plan gives the positions and times.

        Args:
            plan: A `PassagePlan`, or a report returned by `run`.
            constraints: Constraints to check, as in `run`. They are not
                enforced: their largest violation is reported in
                `max_constraint_violation` (positive when violated) and
                per constraint in `constraint_violations`. `ctx["opti"]`
                is None.
            tags: Entries added to the report, as in `run`. `plan`, the
                name of the plan, is also set by default when `plan` is
                a `PassagePlan`.
            variables: Additional variables of this evaluation, added
                to those of the analysis, as in `run`.

        Returns:
            A report with the keys of `run`, `status` 0 (not solved) and
            `init_fac` None.
        """
        if isinstance(plan, dict):
            plan_tim, plan_ctim, plan_lat, plan_lon = (onp.ravel(plan[key]) for key in ("tim", "ctim", "lat", "lon"))
            etd, eta = float(plan["etd"]), float(plan["eta"])
            reference_distance = plan["dist"] / plan["dist_rel"]
        else:
            plan_tim, plan_ctim, plan_lat, plan_lon = plan.tim, plan.ctim, plan.lat, plan.lon
            etd, eta = plan.etd, plan.eta
            reference_distance = plan.route.distance

        evaluation_variables = self._variables(variables)
        self.check_valid_time(etd, eta)

        npts = len(plan_tim)
        tim = ca.MX.sym("tim", npts, 1)
        ctim = ca.MX.sym("ctim", npts - 1, 1)
        lat = ca.MX.sym("lat", npts, 1)
        lon = ca.MX.sym("lon", npts, 1)

        passage = self._passage(tim, ctim, lat, lon, evaluation_variables)

        ctx = _RenamedEntries({"vessel": self.vessel, "opti": None} | passage)
        violations = [
            violation
            for violation in map(_constraint_violation, self._resolve_constraints(constraints, ctx))
            if violation is not None
        ]

        keys = list(passage.keys())
        function = ca.Function(
            "passage",
            [tim, ctim, lat, lon],
            [ca.MX(passage[key]) for key in keys] + [ca.mmax(violation) for violation in violations],
        )
        results = function(plan_tim, plan_ctim, plan_lat, plan_lon)
        if not isinstance(results, (list, tuple)):
            results = [results]

        values = {key: _numeric(result) for key, result in zip(keys, results)}
        constraint_violations = [float(_numeric(result)) for result in results[len(keys):]]

        report = self._report(
            values,
            etd=etd,
            eta=eta,
            init_fac=None,
            reference_distance=reference_distance,
            status=0,
            variables=evaluation_variables,
        )
        report["constraint_violations"] = constraint_violations
        report["max_constraint_violation"] = max(constraint_violations, default=0.)

        report |= self._default_tags(solve=False)
        if isinstance(plan, PassagePlan):
            report["plan"] = plan.name
        report |= tags or {}

        return report

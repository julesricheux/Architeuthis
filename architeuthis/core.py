# -*- coding: utf-8 -*-
"""
Created on Mon Jan 19 15:54:06 2026

@author: jrich
"""


import json

import casadi as ca
import numpy as onp
import pandas as pd

import architeuthis.numpy as np

from abc import abstractmethod
from typing import Callable, Optional, Union
from architeuthis.vessel import Vessel
from architeuthis.common import _banner, status
from architeuthis.optimization import Opti
from architeuthis.forecast import Forecast, Topography
from architeuthis.report import RoutingReport
from architeuthis.common import ArchiteuthisObject, GUST_DEFAULT_RATIO
# Route and voyage classes live in their own modules, which work without network
# access; they are re-exported here for compatibility.
from architeuthis.route import Leg, Route, RouteLibrary, RouteSet, RouteSetLibrary, Waypoint  # noqa: F401
from architeuthis.voyage import PassagePlan, PassagePlanLibrary, Schedule, Voyage  # noqa: F401
from architeuthis.exclusion import (  # noqa: F401
    ExclusionZone,
    ExclusionZoneLibrary,
    default_exclusion_zones,
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
    return np.reshape(array, (-1, 1))


def wide(array):
    return np.reshape(array, (1, -1))


def added_wave_load(hs):
    a = 3.951610803604126 / 100. # regression 11/12/2025
    
    return a*hs

def sigmoid(x):
    return 2*np.arctan(x)/np.pi


def transform(x, delta):
    # return x
    # return 2 * (np.sigmoid(x) - 0.5) * delta
    return (sigmoid(x)) * tall(delta)

def default_routing_constraints(ctx: dict) -> list:
    """Default constraints function for RoutingAnalysis."""
    return [
        ctx["max_bhp"] < ctx["vessel"].max_power,
        # (wide(ctx["z"]) @ tall(ctx["z"])) == 0.,
        ctx["z"] < 0.,
    ]

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
    # `exclusion_zones` remains a list of zones, in the same order, but the iceberg limit it
    # holds is only fetched when it is used, not when this module is imported.
    if name == "exclusion_zones":
        return default_exclusion_zones()
    if name == "berg_zone":
        from architeuthis.icebergs import berg_zone
        return berg_zone
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


#%%

class ArchiteuthisAnalysis(ArchiteuthisObject):

    @abstractmethod
    def __init__(
        self,
        name: str,
        verbose: bool = True,
    ):
        self.status = 0 # 0: not solved, 1: solved, 2: not converged

        super().__init__(name, verbose)


# Quantities computed on a passage and returned in reports, in addition to positions and times.
_REPORT_QUANTITIES = (
    "fuel", "stw", "sog", "cog", "ctw", "tws", "twd", "twa", "aws", "awa",
    "swh", "mwd", "mwa", "z", "cs", "cd", "avg_bhp", "max_bhp", "sails_contribution",
    "tim", "lat", "lon", "ctim", "clat", "clon", "d",
)
_GUST_QUANTITIES = ("tws_gust", "aws_gust")


def _constraint_violation(constraint):
    """Symbolic violation of `a < b`, `a <= b` or `a == b` (positive when violated), or None."""
    if not isinstance(constraint, (ca.MX, ca.SX)):
        return None
    if constraint.is_op(ca.OP_LT) or constraint.is_op(ca.OP_LE):
        return constraint.dep(0) - constraint.dep(1)
    if constraint.is_op(ca.OP_EQ):
        return ca.fabs(constraint.dep(0) - constraint.dep(1))
    return None


def _numeric(value):
    """Convert a casadi result like `OptiSol` does: a float for one value, else a 1D array."""
    array = onp.asarray(ca.DM(value).full() if isinstance(value, (ca.DM, ca.MX, ca.SX)) else value, dtype=float)
    if array.size == 1:
        return float(array.item())
    return array.ravel()


def _describe(obj, attributes=("model", "product", "dataset", "f00", "path", "label", "max_power", "members")):
    """A JSON-friendly description of a data object, for passage plan metadata."""
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

    `run` optimizes the positions on a schedule fixed by the voyage, and stores the result
    as `self.report` (a dict of arrays) and `self.passage_plan` (a `PassagePlan`).
    `evaluate(plan)` computes the same report for given positions, without optimizing,
    with this analysis' vessel and forecasts: an open-loop check of a passage plan.
    """

    def __init__(
        self,
        name: str,
        vessel: Vessel,
        voyage: Optional[Voyage],
        atmosphere: Forecast,
        wave: Forecast,
        current: Forecast,
        topography: Topography,
        atmosphere_member: float = None,
        wave_member: float = None,
        constraints: Optional[Callable[[dict], list]] = default_routing_constraints,
        options: Optional[dict] = None,
        verbose: bool = True,
    ):
        self.vessel = vessel
        self.voyage = voyage
        self.atmosphere = atmosphere
        self.wave = wave
        self.current = current
        self.topography = topography

        self.atmosphere_member = atmosphere_member
        self.wave_member = wave_member
        self.constraints = constraints
        self.options = options if options is not None else {"include_gusts": True}

        self.report = None
        self.passage_plan = None

        super().__init__(name, verbose)


    def check_valid_time(self, etd: float = None, eta: float = None):
        etd = self.voyage.etd if etd is None else etd
        eta = self.voyage.eta if eta is None else eta

        for forecast in [self.atmosphere, self.wave, self.current]:
            f00 = forecast.data["valid_time"].values[0]
            f99 = forecast.data["valid_time"].values[-3]

            if etd < f00:
                status(f"⚠️ Warning: ETD sooner than earliest {forecast.name.upper()} forecast valid time.")
            if eta > f99:
                status(f"⚠️ Warning: ETA later than furthest {forecast.name.upper()} forecast valid time.")

    def _gust_options(self):
        include_gusts = ("include_gusts" in self.options.keys() and self.options["include_gusts"])
        interpolate_gust = include_gusts and "gust" in self.atmosphere.interpolators.keys()

        if include_gusts and not interpolate_gust:
            status("🌪️ Info: gust not found in interpolators. Defaulting to the standard ratio.")

        return include_gusts, interpolate_gust

    def _passage(self, tim, ctim, lat, lon, include_gusts, interpolate_gust) -> dict:
        """
        Symbolic model of a passage through nodes (`tim`, `lat`, `lon`), with the weather
        sampled at segment midpoints at times `ctim`. All inputs are column vectors.
        """
        clon = midpoints(lon)
        clat = midpoints(lat)

        environment_query = np.concatenate([
            ctim, clat, clon,
        ], axis=1)

        if self.atmosphere_member is not None:
            atmosphere_query = np.concatenate([
                ctim, ctim * 0. + self.atmosphere_member, clat, clon,
            ], axis=1)
        else:
            atmosphere_query = environment_query

        if self.wave_member is not None:
            wave_query = np.concatenate([
                ctim, ctim * 0. + self.wave_member, clat, clon,
            ], axis=1)
        else:
            wave_query = environment_query

        u10 = self.atmosphere("u10", atmosphere_query)
        v10 = self.atmosphere("v10", atmosphere_query)

        swh = self.wave("swh", wave_query)
        mwd = self.wave("mwd", wave_query)

        uc = self.current("uo", environment_query) * 3600./1852.
        vc = self.current("vo", environment_query) * 3600./1852.

        tlat, tlon = resample_coordinates(
            lat[1:-1],
            lon[1:-1],
            n=3,
        )

        topography_query = np.concatenate([
            tlat,
            tlon,
        ], axis=1)

        z = self.topography("z", topography_query)

        tws = np.sqrt(u10**2. + v10**2.) * 3600./1852.
        twd = np.mod(np.arctan2d(u10, v10)+180., 360.)

        if include_gusts and interpolate_gust:
            tws_gust = self.atmosphere("gust", atmosphere_query) * 3600./1852.
        else:
            tws_gust = tws * GUST_DEFAULT_RATIO

        # TODO find why east/north wave generates unstability
        # swh = np.sqrt(uw**2. + vw**2.)
        # mwd = np.mod(np.arctan2d(uw, vw)+180, 360.)

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

        vessel_query = np.concatenate([
            stw, tws, np.abs(twa), swh, np.abs(mwa),
        ], axis=1)

        avg_bhp = self.vessel("bhp", vessel_query)
        max_bhp = self.vessel("max_bhp", vessel_query)
        sc = self.vessel("sails_contribution", vessel_query)

        hotel_load = self.vessel.hotel_load(avg_bhp) # kW

        sfc = self.vessel.sfc(avg_bhp+hotel_load) # g/kWh

        consumption = np.abs(avg_bhp + hotel_load) * dt # kWh

        fuel = np.sum(consumption * sfc) / 1e6 # tons # TODO get rid of sfc to rather have f(power) = cons

        passage = {
            "fuel": fuel,
            "max_bhp": max_bhp,
            "avg_bhp": avg_bhp,
            "sails_contribution": sc,
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

        if include_gusts:
            u_aw_gust = tws_gust * np.sind(twa)
            v_aw_gust = tws_gust * np.cosd(twa) + sog
            passage |= {
                "tws_gust": tws_gust,
                "aws_gust": np.sqrt(u_aw_gust**2. + v_aw_gust**2.),
            }

        return passage

    def _resolve_constraints(self, constraints, ctx) -> list:
        active_constraints = constraints if constraints is not None else self.constraints

        if callable(active_constraints):
            return active_constraints(ctx)
        if isinstance(active_constraints, list):
            return active_constraints
        return []

    @staticmethod
    def _report(values: dict, etd, eta, init_fac, reference_distance, status, include_gusts) -> RoutingReport:
        transit_time = (eta - etd) / 3600.
        dist = float(onp.sum(values["d"]))

        report = RoutingReport({
            "etd": etd,
            "eta": eta,
            "transit_sog": reference_distance / transit_time,
            "transit_time": transit_time,
            "init_fac": init_fac,
        })
        report |= {key: values[key] for key in _REPORT_QUANTITIES if key not in ("tim", "lat", "lon", "ctim", "clat", "clon", "d")}
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

        if include_gusts:
            report |= {key: values[key] for key in _GUST_QUANTITIES}

        return report

    def _default_tags(self, solve) -> dict:
        """What identifies a report in tables, plots and the UI. `tags` can replace any of it."""
        return {
            "solve": int(bool(solve)),
            "model": getattr(self.atmosphere, "model", self.atmosphere.name),
            "vessel": getattr(self.vessel, "label", self.vessel.name),
            "member": self.atmosphere_member,
        }

    def describe(self) -> dict:
        """JSON-friendly description of the vessel, forecasts and options of this analysis."""
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
        }

    def _time_grid(self, skip_tim: int):
        """Segment centers (`ctim`) and nodes (`tim`) of the passage, from the atmospheric forecast."""
        etd = self.voyage.etd
        eta = self.voyage.eta

        fxx = self.atmosphere.data.valid_time.values
        ctim0 = fxx[(fxx > etd) * (fxx < eta)][skip_tim::1+skip_tim]

        tim0 = np.concatenate((
            [etd],
            midpoints(ctim0),
            [eta],
        ))

        return tim0, ctim0

    def _reference_path(self, curv_abc, deviation_fac):
        """Reference positions at curvilinear abscissae `curv_abc`, blended by `deviation_fac`."""
        lat0minus, lon0minus = self.voyage.route_minus(curv_abc)
        lat0ortho, lon0ortho = self.voyage.route_ortho(curv_abc)
        lat0plus, lon0plus = self.voyage.route_plus(curv_abc)

        lat0 = np.fmax(deviation_fac, 0) * lat0plus + (1-np.abs(deviation_fac)) * lat0ortho - np.fmin(deviation_fac, 0.) * lat0minus
        lon0 = np.fmax(deviation_fac, 0) * lon0plus + (1-np.abs(deviation_fac)) * lon0ortho - np.fmin(deviation_fac, 0.) * lon0minus

        return lat0, lon0

    def _store_results(self, report: RoutingReport, tags: dict, run_options: dict):
        """Keep the report and the passage plan of the last run on this analysis."""
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
    ) -> RoutingReport:
        """
        Optimize the positions of the voyage, or evaluate its reference route if `solve` is False.

        Args:
            init_fac: Deviation factor of the reference route, between the minus (-1), ortho
                (0) and plus (+1) routes of the voyage.
            vary_fac: Whether the deviation factor is also optimized.
            skip_tim: Thins the time grid by keeping one forecast step out of `1 + skip_tim`.
            max_iter: Maximum number of IPOPT iterations.
            solver_options: Options of the solver, as in `Opti.solve`.
            solve: False evaluates the reference route without optimizing it.
            constraints: Constraints of this run, replacing those of the analysis: a callable
                `ctx -> list` or a list.
            tags: Entries added to the report, identifying it in tables, plots and the UI.
                `solve`, `model` (of the atmospheric forecast), `vessel` (its label) and
                `member` are set by default and can be replaced here.
            callback: Called at each IPOPT iteration with the iteration number, for example to
                report progress in a GUI. See `Opti.solve`.

        Returns:
            A `RoutingReport`, a dict of numeric arrays and scalars, also stored in
            `self.report`. The timed positions are stored in `self.passage_plan`.
        """
        if self.voyage is None:
            raise ValueError("RoutingAnalysis.run needs a voyage. To evaluate a passage plan without one, use evaluate.")

        include_gusts, interpolate_gust = self._gust_options()

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

        passage = self._passage(tim, ctim, lat, lon, include_gusts, interpolate_gust)

        # --- Dynamic Constraints Context ---
        ctx = {"vessel": self.vessel, "opti": opti} | passage
        cons = self._resolve_constraints(constraints, ctx)

        if solve:
            opti.subject_to(cons)
            opti.minimize(passage["fuel"])

        # if self.verbose:
        status(_banner)

        sol = opti.solve(
            max_iter=max_iter,
            callback=callback,
            behavior_on_failure="return_last",
            options=solver_options,
            verbose=self.verbose,
        )

        solve_status = 1 if opti.return_status() in SOLVED else 2

        self.opti = opti
        self.sol = sol
        self.status = solve_status

        values = {key: sol(expression) for key, expression in passage.items()}

        output = self._report(
            values,
            etd=etd,
            eta=eta,
            init_fac=init_fac,
            reference_distance=self.voyage.distance,
            status=solve_status,
            include_gusts=include_gusts,
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
            },
        )

        return output

    def evaluate(
        self,
        plan: Union[PassagePlan, dict],
        constraints: Optional[Union[Callable[[dict], list], list]] = None,
        tags: Optional[dict] = None,
    ) -> RoutingReport:
        """
        Open-loop evaluation of a passage plan with this analysis' vessel and forecasts.

        The positions and times of the plan are kept exactly: nothing is optimized and
        IPOPT is not called. This measures how the consumption of a plan, optimized
        under some conditions, changes under other ones (vessel, weather model, ensemble
        member, options). The analysis needs no voyage for this: it can be built with
        `voyage=None`, as the plan gives the positions and times.

        Args:
            plan: A `PassagePlan`, or a report returned by `run`.
            constraints: Constraints to check, as in `run`. They are not enforced: their
                largest violation is reported in `max_constraint_violation` (positive when
                violated) and per constraint in `constraint_violations`. `ctx["opti"]` is None.
            tags: Entries added to the report, as in `run`. `plan`, the name of the plan, is
                also set by default when `plan` is a `PassagePlan`.

        Returns:
            A report with the keys of `run`, `status` 0 (not solved) and `init_fac` None.
        """
        if isinstance(plan, dict):
            plan_tim, plan_ctim, plan_lat, plan_lon = (onp.ravel(plan[key]) for key in ("tim", "ctim", "lat", "lon"))
            etd, eta = float(plan["etd"]), float(plan["eta"])
            reference_distance = plan["dist"] / plan["dist_rel"]
        else:
            plan_tim, plan_ctim, plan_lat, plan_lon = plan.tim, plan.ctim, plan.lat, plan.lon
            etd, eta = plan.etd, plan.eta
            reference_distance = plan.route.distance

        include_gusts, interpolate_gust = self._gust_options()
        self.check_valid_time(etd, eta)

        npts = len(plan_tim)
        tim = ca.MX.sym("tim", npts, 1)
        ctim = ca.MX.sym("ctim", npts - 1, 1)
        lat = ca.MX.sym("lat", npts, 1)
        lon = ca.MX.sym("lon", npts, 1)

        passage = self._passage(tim, ctim, lat, lon, include_gusts, interpolate_gust)

        ctx = {"vessel": self.vessel, "opti": None} | passage
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
            include_gusts=include_gusts,
        )
        report["constraint_violations"] = constraint_violations
        report["max_constraint_violation"] = max(constraint_violations, default=0.)

        report |= self._default_tags(solve=False)
        if isinstance(plan, PassagePlan):
            report["plan"] = plan.name
        report |= tags or {}

        return report

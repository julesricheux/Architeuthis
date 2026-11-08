# -*- coding: utf-8 -*-
"""
Time on top of geometry: `Schedule`, `Voyage` (a route plus a schedule) and
`PassagePlan` (the timed positions that a routing produced, which can be stored,
reloaded and evaluated again under other conditions).

This module does not import `architeuthis.core`, so it works offline.
"""

from __future__ import annotations

import os

from typing import Any, Callable, Optional, Sequence, Union

import numpy as onp

from architeuthis.common import ArchiteuthisObject, Datetime, _HOME, status, to_timestamp
from architeuthis.toolbox.geo_utils import distances
from architeuthis.route import (
    JsonLibrary,
    Leg,
    Route,
    RouteSet,
    Waypoint,
    _read_json,
    _write_json,
)


PASSAGE_PLAN_DIRECTORY = os.path.join(_HOME, "passage_plans")


class Schedule(ArchiteuthisObject):
    """
    Departure and arrival times. Dates of any common type (datetime, pandas Timestamp,
    ISO string, numpy datetime64) are converted to float epoch seconds, naive ones as UTC.
    """

    def __init__(
        self,
        name: str,
        etd: Union[Datetime, float],
        eta: Union[Datetime, float],
        verbose: bool = True,
    ):
        self.etd = to_timestamp(etd)
        self.eta = to_timestamp(eta)

        if self.eta <= self.etd:
            raise ValueError(f"Schedule {name}: ETA must be later than ETD.")

        self.transit_time = self.eta - self.etd # s

        super().__init__(name, verbose)

    def to_dict(self) -> dict:
        return {"name": self.name, "etd": self.etd, "eta": self.eta}

    @classmethod
    def from_dict(cls, data: dict, verbose: bool = True) -> "Schedule":
        return cls(data["name"], data["etd"], data["eta"], verbose=verbose)


RouteLike = Union[Route, Callable, None]


class Voyage(ArchiteuthisObject):
    """
    A route sailed on a schedule: the input of `RoutingAnalysis`.

    Either give a `route`, or `departure` and `arrival` for a direct great-circle route.
    `route_minus`, `route_ortho` and `route_plus` are the reference routes blended by the
    deviation factor; each may be a Route or a function `s -> (lat, lon)`, and they
    default to the paths derived from `route` and its spread.

    Example:
        >>> Voyage("crossing", etd="2026-02-05T12:00", eta="2026-02-17T06:00",
        ...        route=RouteLibrary().load("FRMTX-PMFSP"))
    """

    def __init__(
        self,
        name: str,
        etd: Union[Datetime, float],
        eta: Union[Datetime, float],
        departure: Optional[Sequence[float]] = None,
        arrival: Optional[Sequence[float]] = None,
        verbose: bool = True,

        route_minus: RouteLike = None,
        route_ortho: RouteLike = None,
        route_plus: RouteLike = None,

        route: Optional[Route] = None,
    ):
        if route is None:
            if departure is None or arrival is None:
                raise ValueError("Voyage needs either a route, or a departure and an arrival.")
            route = Route(f"{name}_route", [departure, arrival], verbose=verbose)
        else:
            for label, position, expected in (
                ("departure", departure, route.departure),
                ("arrival", arrival, route.arrival),
            ):
                if position is not None and not onp.allclose(Waypoint.coerce(position).position, expected):
                    raise ValueError(f"Voyage {name}: {label} {list(position)} differs from the route {label}.")

        self.route = route
        self.leg = Leg(f"{name}_leg", route.departure, route.arrival, verbose)
        self.schedule = Schedule(f"{name}_schedule", etd, eta, verbose)

        # Keep the given references so that from_position can restart them.
        self._references = {"minus": route_minus, "ortho": route_ortho, "plus": route_plus}

        self.route_minus = self._as_path(route_minus, route.minus)
        self.route_ortho = self._as_path(route_ortho, route.ortho)
        self.route_plus = self._as_path(route_plus, route.plus)

        self.transit_time = self.schedule.transit_time / 3600. # h
        self.transit_sog = self.distance / self.transit_time # kt

        super().__init__(name, verbose)

    @classmethod
    def from_routes(
        cls,
        routes: RouteSet,
        etd: Union[Datetime, float],
        eta: Union[Datetime, float],
        name: Optional[str] = None,
        verbose: bool = True,
    ) -> "Voyage":
        """
        A voyage on the routes of a `RouteSet`: the ortho route is the route of the voyage,
        and the minus and plus routes are its references, restarted by `from_position`.
        """
        return cls(
            name=name if name is not None else routes.name,
            etd=etd,
            eta=eta,
            verbose=verbose,
            route=routes.ortho,
            route_minus=routes.minus,
            route_ortho=routes.ortho,
            route_plus=routes.plus,
        )

    @staticmethod
    def _as_path(reference: RouteLike, default: Callable) -> Callable:
        if reference is None:
            return default
        if isinstance(reference, Route):
            return reference.ortho
        if callable(reference):  # a Route is callable too, but is handled above to stay restartable
            return reference
        raise TypeError(f"A reference route must be a Route or a callable, not {type(reference).__name__}.")

    @property
    def departure(self):
        return self.route.departure

    @property
    def arrival(self):
        return self.route.arrival

    @property
    def distance(self):
        """Distance through the route waypoints, in nautical miles."""
        return self.route.distance

    @property
    def etd(self):
        return self.schedule.etd

    @property
    def eta(self):
        return self.schedule.eta

    def from_position(
        self,
        position: Union[Waypoint, Sequence[float]],
        time: Union[Datetime, float],
        name: Optional[str] = None,
        next_waypoint: Union[int, str, None] = None,
        tolerance: float = 5.0,
    ) -> "Voyage":
        """
        The rest of this voyage from a position reached at `time`, keeping the same ETA.

        The route is restarted with `Route.from_position`. Reference routes given as
        Route objects are restarted too; ones given as functions cannot be, and are
        replaced by the paths derived from the restarted route.
        """
        route = self.route.from_position(
            position,
            next_waypoint=next_waypoint,
            tolerance=tolerance,
        )

        references = {}
        for key, reference in self._references.items():
            if isinstance(reference, Route):
                references[f"route_{key}"] = reference.from_position(position, tolerance=tolerance)
            elif reference is not None:
                status(f"⚠️ Warning: route_{key} is a function and cannot be restarted. Using the route {key} path instead.")

        return Voyage(
            name=name if name is not None else f"{self.name}_from_{route.waypoints[0].lat:.2f}_{route.waypoints[0].lon:.2f}",
            etd=time,
            eta=self.eta,
            verbose=self.verbose,
            route=route,
            **references,
        )


class PassagePlan(ArchiteuthisObject):
    """
    The timed positions of a passage, typically the optimum of a `RoutingAnalysis`.

    Args:
        name: Plan identifier, also its file name in a `PassagePlanLibrary`.
        route: The route the plan was computed from.
        schedule: Departure and arrival times.
        tim: Node times, float epoch seconds, from ETD to ETA.
        lat: Node latitudes.
        lon: Node longitudes.
        ctim: Times at which weather is sampled on each segment; segment midpoints of
            `tim` by default.
        metadata: Free description of how the plan was obtained (vessel, forecasts,
            options, fuel...). It must be JSON serializable.

    `RoutingAnalysis.evaluate(plan)` computes the consumption of this plan, with its
    positions fixed, for any vessel and weather.
    """

    def __init__(
        self,
        name: str,
        route: Route,
        schedule: Schedule,
        tim: Sequence[float],
        lat: Sequence[float],
        lon: Sequence[float],
        ctim: Optional[Sequence[float]] = None,
        metadata: Optional[dict] = None,
        verbose: bool = True,
    ):
        super().__init__(name, verbose)

        self.route = route
        self.schedule = schedule
        self.tim = onp.asarray(tim, dtype=float).ravel()
        self.lat = onp.asarray(lat, dtype=float).ravel()
        self.lon = onp.asarray(lon, dtype=float).ravel()
        if ctim is None:
            ctim = (self.tim[:-1] + self.tim[1:]) / 2.
        self.ctim = onp.asarray(ctim, dtype=float).ravel()
        self.metadata = dict(metadata or {})

        if not (self.tim.size == self.lat.size == self.lon.size):
            raise ValueError("tim, lat and lon must have the same length.")
        if self.ctim.size != self.tim.size - 1:
            raise ValueError("ctim must have one value per segment.")
        if self.tim.size < 2 or onp.any(onp.diff(self.tim) <= 0):
            raise ValueError("tim must hold at least two increasing times.")

    def __repr__(self) -> str:
        return f"PassagePlan({self.name!r}: {self.tim.size} nodes, {self.distance:.1f} nm, route {self.route.name!r})"

    @property
    def positions(self) -> onp.ndarray:
        """Node positions, shape (n, 2), latitude first."""
        return onp.column_stack((self.lat, self.lon))

    @property
    def distance(self) -> float:
        return float(onp.sum(distances(self.lat, self.lon)))

    @property
    def etd(self) -> float:
        return self.schedule.etd

    @property
    def eta(self) -> float:
        return self.schedule.eta

    def at(self, time: Union[Datetime, float]) -> onp.ndarray:
        """Planned position at `time`, linearly interpolated between nodes."""
        time = to_timestamp(time)
        return onp.array([
            onp.interp(time, self.tim, self.lat),
            onp.interp(time, self.tim, self.lon),
        ])

    def to_route(self, name: Optional[str] = None) -> Route:
        """A route through every node, for instance to use the plan as a reference route."""
        waypoints = [Waypoint(lat, lon) for lat, lon in zip(self.lat, self.lon)]
        first, last = self.route.waypoints[0], self.route.waypoints[-1]
        waypoints[0] = Waypoint(self.lat[0], self.lon[0], first.name)
        waypoints[-1] = Waypoint(self.lat[-1], self.lon[-1], last.name)
        return Route(name or f"{self.name}_route", waypoints, verbose=self.verbose)

    def voyage(self, name: Optional[str] = None) -> Voyage:
        """The voyage the plan answers: its route and schedule."""
        return Voyage(
            name=name or f"{self.name}_voyage",
            etd=self.etd,
            eta=self.eta,
            route=self.route,
            verbose=self.verbose,
        )

    @classmethod
    def from_report(
        cls,
        report: dict,
        route: Route,
        name: str,
        metadata: Optional[dict] = None,
        verbose: bool = True,
    ) -> "PassagePlan":
        """Build a plan from a `RoutingAnalysis.run` report, including one reloaded from JSON."""
        summary = {key: _plain(report[key]) for key in ("fuel", "dist", "status") if key in report}
        return cls(
            name=name,
            route=route,
            schedule=Schedule(f"{name}_schedule", report["etd"], report["eta"], verbose=verbose),
            tim=report["tim"],
            lat=report["lat"],
            lon=report["lon"],
            ctim=report.get("ctim"),
            metadata={**summary, **(metadata or {})},
            verbose=verbose,
        )

    def to_dict(self) -> dict:
        return {
            "type": "PassagePlan",
            "name": self.name,
            "route": self.route.to_dict(),
            "schedule": self.schedule.to_dict(),
            "tim": self.tim.tolist(),
            "lat": self.lat.tolist(),
            "lon": self.lon.tolist(),
            "ctim": self.ctim.tolist(),
            "metadata": _plain(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict, verbose: bool = True) -> "PassagePlan":
        return cls(
            name=data["name"],
            route=Route.from_dict(data["route"], verbose=verbose),
            schedule=Schedule.from_dict(data["schedule"], verbose=verbose),
            tim=data["tim"],
            lat=data["lat"],
            lon=data["lon"],
            ctim=data.get("ctim"),
            metadata=data.get("metadata"),
            verbose=verbose,
        )

    def save(self, path: str) -> str:
        _write_json(path, self.to_dict())
        if self.verbose:
            status(f"✅ Passage plan {self.name} saved to {path}.")
        return path

    @classmethod
    def load(cls, path: str, verbose: bool = True) -> "PassagePlan":
        return cls.from_dict(_read_json(path), verbose=verbose)


class PassagePlanLibrary(JsonLibrary):
    """Passage plans stored as JSON files, in `~/data/passage_plans/` by default."""

    item_class = PassagePlan
    default_directory = PASSAGE_PLAN_DIRECTORY


def _plain(value: Any) -> Any:
    """Convert numpy values (recursively) to JSON-friendly Python values."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, onp.ndarray):
        return _plain(value.tolist())
    if isinstance(value, onp.generic):
        return value.item()
    return value

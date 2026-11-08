# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 11:06:09 2026

@author: jrich

Geometric definition of a passage, independent of time and weather.

A `Route` is an ordered list of waypoints joined by great-circle segments. Each
segment may bend sideways by a `divergence` (see `geo_utils.deviated_gc_segment`),
and a `spread` per segment defines the alternative routes `minus` and `plus` that
`RoutingAnalysis` blends with its deviation factor. Routes are numeric objects: they
build reference routes before optimization and are never part of the NLP.

Routes are stored as JSON, alone or in a `RouteLibrary`, so that a frequent passage
is defined once and reused, reversed, or restarted from a position at sea.
"""

from __future__ import annotations

import json
import os
import re

from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Sequence, Union

import numpy as onp

from architeuthis.common import ArchiteuthisObject, _HOME, status
from architeuthis.toolbox.geo_utils import (
    deviated_gc_segment,
    distances,
    poly_deviated_route,
)


ROUTE_LIBRARY_DIRECTORY = os.path.join(_HOME, "route_library")
ROUTE_SET_DIRECTORY = os.path.join(_HOME, "route_sets")

# Samples per segment when projecting a position onto a route.
_PROJECTION_SAMPLES = 401


@dataclass(frozen=True)
class Waypoint:
    """A named position, latitude first. It unpacks and indexes like `[lat, lon]`."""

    lat: float
    lon: float
    name: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "lat", float(self.lat))
        object.__setattr__(self, "lon", float(self.lon))
        if not -90.0 <= self.lat <= 90.0:
            raise ValueError(f"Latitude {self.lat} is outside [-90, 90].")

    def __iter__(self):
        yield self.lat
        yield self.lon

    def __getitem__(self, index):
        return (self.lat, self.lon)[index]

    def __len__(self):
        return 2

    @property
    def position(self) -> onp.ndarray:
        return onp.array([self.lat, self.lon])

    def to_dict(self) -> dict:
        return {"name": self.name, "lat": self.lat, "lon": self.lon}

    @classmethod
    def from_dict(cls, data: dict) -> "Waypoint":
        return cls(lat=data["lat"], lon=data["lon"], name=data.get("name"))

    @classmethod
    def coerce(cls, value: Union["Waypoint", Sequence[float], dict]) -> "Waypoint":
        """Accept a Waypoint, a `[lat, lon]` sequence or a `{"lat", "lon", "name"}` dict."""
        if isinstance(value, Waypoint):
            return value
        if isinstance(value, dict):
            return cls.from_dict(value)
        lat, lon = onp.asarray(value, dtype=float).ravel()
        return cls(lat=lat, lon=lon)


def _distance_nm(first: Sequence[float], second: Sequence[float]) -> float:
    return float(distances(
        onp.array([first[0], second[0]]),
        onp.array([first[1], second[1]]),
    )[0])


class Leg(ArchiteuthisObject):
    """A great-circle segment between two positions."""

    def __init__(
        self,
        name: str,
        departure: Sequence[float],
        arrival: Sequence[float],
        verbose: bool = True,
    ):
        self.departure = departure
        self.arrival = arrival

        self.distance = _distance_nm(departure, arrival)

        super().__init__(name, verbose)


class Route(ArchiteuthisObject):
    """
    An ordered list of waypoints, with one divergence and one spread per segment.

    Args:
        name: Route identifier, also its file name in a `RouteLibrary`.
        waypoints: Waypoints, `[lat, lon]` pairs or dicts, departure first and arrival last.
        divergences: Sideways bend of each segment, as a fraction of half its angular
            length (0 is the great circle). The sign follows the travel direction.
        spread: Divergence added (`plus`) and removed (`minus`) per segment to build the
            alternative routes blended by `RoutingAnalysis(..., vary_fac=True)`.
        verbose: Print status messages.

    Example:
        >>> route = Route("FRMTX-PMFSP", [montoir, penmarch, cape_race, spm])
        >>> route.reversed()                       # PMFSP-FRMTX, same path
        >>> route.from_position([45.4, -40.2])     # remaining route from a position at sea
    """

    def __init__(
        self,
        name: str,
        waypoints: Sequence[Union[Waypoint, Sequence[float], dict]],
        divergences: Optional[Sequence[float]] = None,
        spread: Union[float, Sequence[float], None] = None,
        verbose: bool = True,
    ):
        super().__init__(name, verbose)

        self.waypoints = [Waypoint.coerce(waypoint) for waypoint in waypoints]
        if len(self.waypoints) < 2:
            raise ValueError("A route needs at least a departure and an arrival.")

        n_segments = len(self.waypoints) - 1
        self.divergences = self._per_segment(divergences, n_segments, "divergences")
        self.spread = self._per_segment(spread, n_segments, "spread")

        for first, second in zip(self.waypoints[:-1], self.waypoints[1:]):
            if first.lat == second.lat and first.lon == second.lon:
                raise ValueError(f"Route {name} has two consecutive identical waypoints at {list(first)}.")

    @staticmethod
    def _per_segment(values, n_segments, label) -> onp.ndarray:
        if values is None:
            return onp.zeros(n_segments)
        values = onp.asarray(values, dtype=float)
        if values.ndim == 0:
            return onp.full(n_segments, float(values))
        values = values.ravel()
        if values.size != n_segments:
            raise ValueError(f"Expected {n_segments} {label} (one per segment), got {values.size}.")
        return values.copy()

    def __repr__(self) -> str:
        names = " > ".join(waypoint.name or f"({waypoint.lat:.3f}, {waypoint.lon:.3f})" for waypoint in self.waypoints)
        return f"Route({self.name!r}: {names}, {self.distance:.1f} nm)"

    # --------------------------------------------------------------------------
    # Geometry
    # --------------------------------------------------------------------------

    @property
    def n_segments(self) -> int:
        return len(self.waypoints) - 1

    @property
    def departure(self) -> onp.ndarray:
        return self.waypoints[0].position

    @property
    def arrival(self) -> onp.ndarray:
        return self.waypoints[-1].position

    @property
    def lats(self) -> onp.ndarray:
        return onp.array([waypoint.lat for waypoint in self.waypoints])

    @property
    def lons(self) -> onp.ndarray:
        return onp.array([waypoint.lon for waypoint in self.waypoints])

    @property
    def legs(self) -> list[Leg]:
        return [
            Leg(
                f"{first.name or i}-{second.name or i + 1}",
                first.position,
                second.position,
                verbose=False,
            )
            for i, (first, second) in enumerate(zip(self.waypoints[:-1], self.waypoints[1:]))
        ]

    @property
    def distance(self) -> float:
        """Distance through the waypoints along great circles, in nautical miles (divergences ignored)."""
        return float(onp.sum(distances(self.lats, self.lons)))

    def path(self, divergences: Optional[Sequence[float]] = None) -> Callable:
        """
        The route as a function `s -> (lat, lon)` of the normalized abscissa `s` in [0, 1],
        as `RoutingAnalysis` expects for `route_minus`, `route_ortho` and `route_plus`.
        """
        if divergences is None:
            divergences = self.divergences
        return poly_deviated_route(list(self.lats), list(self.lons), list(divergences))

    def __call__(self, s):
        """`route(s)` is `route.ortho(s)`, so a Route replaces a `poly_deviated_route` function."""
        return self.ortho(s)

    @property
    def ortho(self) -> Callable:
        return self.path(self.divergences)

    @property
    def minus(self) -> Callable:
        return self.path(self.divergences - self.spread)

    @property
    def plus(self) -> Callable:
        return self.path(self.divergences + self.spread)

    def sample(self, n: int = 100, divergences: Optional[Sequence[float]] = None) -> onp.ndarray:
        """`n` positions evenly spaced in abscissa along the route, shape (n, 2)."""
        lat, lon = self.path(divergences)(onp.linspace(0.0, 1.0, n))
        return onp.column_stack((lat, lon))

    # --------------------------------------------------------------------------
    # Derived routes
    # --------------------------------------------------------------------------

    def reversed(self, name: Optional[str] = None) -> "Route":
        """
        The same path sailed the other way.

        A segment's divergence is measured to one side of the travel direction, so it
        changes sign when the direction does. The default name swaps the end waypoint
        names ("FRMTX-PMFSP" becomes "PMFSP-FRMTX").
        """
        if name is None:
            first, last = self.waypoints[0].name, self.waypoints[-1].name
            name = f"{last}-{first}" if first and last else f"{self.name}_reversed"

        return Route(
            name=name,
            waypoints=self.waypoints[::-1],
            divergences=0.0 - self.divergences[::-1],  # 0.0 - x avoids storing -0.0
            spread=self.spread[::-1],
            verbose=self.verbose,
        )

    def project(self, position: Sequence[float]) -> tuple[int, float, float]:
        """
        Locate the point of the route nearest to `position`.

        Returns:
            The segment index, the abscissa within that segment in [0, 1], and the
            distance from the position to the route in nautical miles.
        """
        lat, lon = Waypoint.coerce(position)
        s = onp.linspace(0.0, 1.0, _PROJECTION_SAMPLES)

        best = (0, 0.0, onp.inf)
        for i, (first, second) in enumerate(zip(self.waypoints[:-1], self.waypoints[1:])):
            segment = deviated_gc_segment(first.lat, first.lon, second.lat, second.lon, self.divergences[i])
            seg_lat, seg_lon = segment(s)
            gaps = _haversine_nm(lat, lon, seg_lat, seg_lon)
            k = int(onp.argmin(gaps))
            if gaps[k] < best[2]:
                best = (i, float(s[k]), float(gaps[k]))
        return best

    def from_position(
        self,
        position: Union[Waypoint, Sequence[float]],
        name: Optional[str] = None,
        next_waypoint: Union[int, str, None] = None,
        tolerance: float = 5.0,
    ) -> "Route":
        """
        The rest of the route from a position at sea, typically for a routing started
        after the departure.

        The new route goes straight (divergence 0) from `position` to the next waypoint,
        then follows the remaining waypoints with their own divergences. Each segment
        keeps its spread, the first one inheriting the spread of the segment the position
        lies on.

        Args:
            position: Current position, `[lat, lon]` or a Waypoint.
            name: New route name, by default `<name>_from_<lat>_<lon>`.
            next_waypoint: Index or name of the waypoint to sail to first. By default, the
                end of the route segment nearest to the position.
            tolerance: A default next waypoint closer than this (nm) to the position is
                considered reached and skipped, unless it is the arrival.
        """
        start = Waypoint.coerce(position)
        if start.name is None:
            start = Waypoint(start.lat, start.lon, name="position")

        if next_waypoint is None:
            segment, _, offset = self.project(start)
            target = segment + 1
            if target < len(self.waypoints) - 1 and _distance_nm(start, self.waypoints[target]) < tolerance:
                target += 1
            if offset > 100.0:
                status(f"⚠️ Warning: position is {offset:.0f} nm away from route {self.name}.")
        else:
            target = self._waypoint_index(next_waypoint)
            if target == 0:
                raise ValueError("The next waypoint cannot be the departure.")
            segment = target - 1

        if name is None:
            name = f"{self.name}_from_{start.lat:.2f}_{start.lon:.2f}"

        return Route(
            name=name,
            waypoints=[start] + self.waypoints[target:],
            divergences=onp.concatenate(([0.0], self.divergences[target:])),
            spread=onp.concatenate(([self.spread[segment]], self.spread[target:])),
            verbose=self.verbose,
        )

    def _waypoint_index(self, key: Union[int, str]) -> int:
        if isinstance(key, str):
            names = [waypoint.name for waypoint in self.waypoints]
            if key not in names:
                raise KeyError(f"Route {self.name} has no waypoint named {key!r}.")
            return names.index(key)
        index = int(key)
        if not -len(self.waypoints) <= index < len(self.waypoints):
            raise IndexError(f"Route {self.name} has {len(self.waypoints)} waypoints.")
        return index % len(self.waypoints)

    # --------------------------------------------------------------------------
    # Storage
    # --------------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "type": "Route",
            "name": self.name,
            "waypoints": [waypoint.to_dict() for waypoint in self.waypoints],
            "divergences": self.divergences.tolist(),
            "spread": self.spread.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict, verbose: bool = True) -> "Route":
        return cls(
            name=data["name"],
            waypoints=data["waypoints"],
            divergences=data.get("divergences"),
            spread=data.get("spread"),
            verbose=verbose,
        )

    def save(self, path: str) -> str:
        _write_json(path, self.to_dict())
        if self.verbose:
            status(f"✅ Route {self.name} saved to {path}.")
        return path

    @classmethod
    def load(cls, path: str, verbose: bool = True) -> "Route":
        return cls.from_dict(_read_json(path), verbose=verbose)


def _haversine_nm(lat, lon, lats, lons) -> onp.ndarray:
    lat, lon, lats, lons = (onp.radians(onp.asarray(value, dtype=float)) for value in (lat, lon, lats, lons))
    a = onp.sin((lats - lat) / 2) ** 2 + onp.cos(lat) * onp.cos(lats) * onp.sin((lons - lon) / 2) ** 2
    return 2 * 3440.065 * onp.arcsin(onp.sqrt(onp.clip(a, 0.0, 1.0)))


# ------------------------------------------------------------------------------
# JSON storage
# ------------------------------------------------------------------------------


def _write_json(path: str, data: dict):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def safe_file_name(name: str) -> str:
    """A file name for `name`, keeping letters, digits, `-`, `_` and `.`."""
    cleaned = re.sub(r"[^\w.\-]+", "_", str(name)).strip("._")
    if not cleaned:
        raise ValueError(f"Cannot build a file name from {name!r}.")
    return cleaned


class JsonLibrary:
    """
    A folder of named JSON objects. Subclasses set `item_class`, which must provide
    `name`, `to_dict()` and `from_dict(data, verbose)`.
    """

    item_class = None
    default_directory = None

    def __init__(self, directory: Optional[str] = None, verbose: bool = True):
        self.directory = directory if directory is not None else self.default_directory
        self.verbose = verbose

    def path(self, name: str) -> str:
        return os.path.join(self.directory, f"{safe_file_name(name)}.json")

    def names(self) -> list[str]:
        if not os.path.isdir(self.directory):
            return []
        names = []
        for file_name in sorted(os.listdir(self.directory)):
            if file_name.endswith(".json"):
                try:
                    names.append(_read_json(os.path.join(self.directory, file_name))["name"])
                except (OSError, ValueError, KeyError):
                    continue
        return names

    def __contains__(self, name: str) -> bool:
        return os.path.exists(self.path(name))

    def __iter__(self) -> Iterable:
        return (self.load(name) for name in self.names())

    def __len__(self) -> int:
        return len(self.names())

    def save(self, item, overwrite: bool = False) -> str:
        path = self.path(item.name)
        if os.path.exists(path) and not overwrite:
            raise FileExistsError(f"{item.name} is already stored in {self.directory}. Pass overwrite=True to replace it.")
        _write_json(path, item.to_dict())
        if self.verbose:
            status(f"➕ {item.name} saved to {path}.")
        return path

    def load(self, name: str):
        path = self.path(name)
        if not os.path.exists(path):
            raise KeyError(f"{name} is not stored in {self.directory}. Available: {self.names()}.")
        return self.item_class.from_dict(_read_json(path), verbose=self.verbose)

    def remove(self, name: str):
        os.remove(self.path(name))
        if self.verbose:
            status(f"➖ {name} removed from {self.directory}.")


class RouteSet(ArchiteuthisObject):
    """
    The reference routes of a voyage, kept together: `ortho` and the `minus` and `plus` routes
    that a deviation factor of -1 and +1 blend towards. `minus` and `plus` default to `ortho`.

    A `RouteSet` is stored as a single entry of a `RouteSetLibrary` and gives a voyage with
    `Voyage.from_routes(route_set, etd, eta)`.

    Reversing keeps the sides. A route going to port of the outbound passage is to starboard
    of the return passage, so `minus` and `plus` are swapped and each is reversed.
    """

    def __init__(
        self,
        name: str,
        ortho: Route,
        minus: Optional[Route] = None,
        plus: Optional[Route] = None,
        verbose: bool = True,
    ):
        self.ortho = ortho
        self.minus = minus if minus is not None else ortho
        self.plus = plus if plus is not None else ortho

        super().__init__(name, verbose)

    @property
    def routes(self) -> dict:
        return {"minus": self.minus, "ortho": self.ortho, "plus": self.plus}

    def reversed(self, name: Optional[str] = None) -> "RouteSet":
        """The same routes for the return passage."""
        return RouteSet(
            name if name is not None else f"{self.name}_reversed",
            ortho=self.ortho.reversed(),
            minus=self.plus.reversed(),
            plus=self.minus.reversed(),
            verbose=self.verbose,
        )

    def from_position(
        self,
        position: Union[Waypoint, Sequence[float]],
        name: Optional[str] = None,
        next_waypoint: Union[int, str, None] = None,
        tolerance: float = 5.0,
    ) -> "RouteSet":
        """The rest of these routes from a position at sea."""
        return RouteSet(
            name if name is not None else f"{self.name}_restart",
            ortho=self.ortho.from_position(position, next_waypoint=next_waypoint, tolerance=tolerance),
            minus=self.minus.from_position(position, tolerance=tolerance),
            plus=self.plus.from_position(position, tolerance=tolerance),
            verbose=self.verbose,
        )

    def to_dict(self) -> dict:
        return {"name": self.name} | {key: route.to_dict() for key, route in self.routes.items()}

    @classmethod
    def from_dict(cls, data: dict, verbose: bool = True) -> "RouteSet":
        return cls(
            data["name"],
            **{key: Route.from_dict(data[key], verbose=verbose) for key in ("ortho", "minus", "plus")},
            verbose=verbose,
        )

    def save(self, path: str) -> str:
        _write_json(path, self.to_dict())
        return path

    @classmethod
    def load(cls, path: str, verbose: bool = True) -> "RouteSet":
        return cls.from_dict(_read_json(path), verbose=verbose)

    def __repr__(self) -> str:
        return f"RouteSet({self.name!r}, ortho={self.ortho.name!r}, minus={self.minus.name!r}, plus={self.plus.name!r})"


class RouteLibrary(JsonLibrary):
    """
    Routes stored as JSON files, one per route, in `~/data/route_library/` by default.

    Example:
        >>> library = RouteLibrary()
        >>> library.save(route)
        >>> library.save(route.reversed())
        >>> library.load("PMFSP-FRMTX")
    """

    item_class = Route
    default_directory = ROUTE_LIBRARY_DIRECTORY


class RouteSetLibrary(JsonLibrary):
    """
    Route sets stored as JSON files, one per set, in `~/data/route_sets/` by default.

    Example:
        >>> library = RouteSetLibrary()
        >>> library.save(RouteSet("crossing", ortho=ortho, minus=port, plus=starboard))
        >>> Voyage.from_routes(library.load("crossing"), etd, eta)
    """

    item_class = RouteSet
    default_directory = ROUTE_SET_DIRECTORY

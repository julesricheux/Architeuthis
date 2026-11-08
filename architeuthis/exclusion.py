# -*- coding: utf-8 -*-
"""
Areas that a route must stay out of.

An `ExclusionZone` is a named `[lat, lon]` polygon with what the UI
needs to show it: a label, a color and whether it is displayed at first.
Zones are stored as JSON in an `ExclusionZoneLibrary`, like routes in a
`RouteLibrary`, and `Topography` rasterizes them into its distance
field. An `ExclusionZone` behaves like the plain list of `[lat, lon]`
points that it holds, and plain lists are still accepted wherever a zone
is.

`default_exclusion_zones()` gives the zones used by the routing scripts.
The iceberg limit is only fetched when this function is called, never at
import.
"""

from __future__ import annotations

import os

from typing import Iterable, Optional, Sequence

import numpy as onp

from matplotlib.path import Path

from architeuthis.common import ArchiteuthisObject, _HOME
from architeuthis.route import JsonLibrary, _read_json, _write_json


EXCLUSION_ZONE_DIRECTORY = os.path.join(_HOME, "exclusion_zones")

DEFAULT_ZONE_COLOR = "#ff8c00"
ICEBERG_ZONE_COLOR = "#ff0000"

# Number of points of the iceberg polygon that only close it to the west, behind the
# limit published by the IIP, and that are not drawn on the map.
_ICEBERG_CLOSING_POINTS = 3


class ExclusionZone(ArchiteuthisObject):
    """
    A named polygon that routes must stay out of.

    Args:
        name: Identifier, also the file name in an
            `ExclusionZoneLibrary`.
        polygon: The `[lat, lon]` points of the zone. It may be empty,
            for example the iceberg limit when no bulletin is available:
            `Topography` then skips it.
        label: Text displayed in the UI. Defaults to `name`.
        color: Color of the zone in the UI.
        outline: The `[lat, lon]` points drawn in the UI, if not the
            whole polygon. The routing always uses `polygon`.
        visible: Whether the UI displays the zone at first. It can be
            hidden and shown there at any time. This has no effect on
            the routing.
        description: Free text, such as the source of the polygon.

    Example:
        >>> zone = ExclusionZone(
        ...     "safety",
        ...     [[49.2, -65.9], [49.2, -64.9], [48.0, -64.5]],
        ...     label="Safety margin",
        ... )
        >>> ExclusionZoneLibrary().save(zone)
        >>> zones = default_exclusion_zones() + [zone]
        >>> Topography("topo", exclusion_zones=zones, **domain)
    """

    def __init__(
        self,
        name: str,
        polygon: Sequence[Sequence[float]] = (),
        label: Optional[str] = None,
        color: str = DEFAULT_ZONE_COLOR,
        outline: Optional[Sequence[Sequence[float]]] = None,
        visible: bool = True,
        description: str = "",
        verbose: bool = True,
    ):
        self.polygon = self._points(name, polygon)
        self.label = label if label is not None else name
        self.color = color
        self._outline = None if outline is None else self._points(name, outline)
        self.visible = bool(visible)
        self.description = description

        super().__init__(name, verbose)

    @staticmethod
    def _points(name: str, points) -> list:
        array = onp.asarray(list(points), dtype=float)
        if array.size == 0:
            return []
        if array.ndim != 2 or array.shape[1] != 2:
            raise ValueError(f"Exclusion zone {name}: expected [lat, lon] points, got shape {array.shape}.")
        return array.tolist()

    @property
    def outline(self) -> list:
        """
        The `[lat, lon]` points drawn on a map.
        """
        return self.polygon if self._outline is None else self._outline

    @property
    def is_empty(self) -> bool:
        """
        True when the zone has too few points to enclose anything.
        """
        return len(self.polygon) < 3

    def contains(self, lat, lon):
        """
        Whether positions are inside the zone, as a boolean array.
        """
        lat, lon = onp.ravel(lat), onp.ravel(lon)
        if self.is_empty:
            return onp.zeros(lat.shape, dtype=bool)
        return Path(self.polygon).contains_points(onp.column_stack((lat, lon)))

    # The zone reads like its list of points, the former representation of exclusion zones.
    def __len__(self) -> int:
        """
        The number of points of the polygon.
        """
        return len(self.polygon)

    def __iter__(self):
        """
        Iterate over the `[lat, lon]` points of the polygon.
        """
        return iter(self.polygon)

    def __getitem__(self, index):
        """
        A point or a slice of the polygon.
        """
        return self.polygon[index]

    def __array__(self, dtype=None, copy=None):
        """
        The polygon as an array, for NumPy, of floats by default.
        """
        return onp.asarray(self.polygon, dtype=float if dtype is None else dtype)

    def __repr__(self) -> str:
        """
        The name, number of points and label of the zone.
        """
        return f"ExclusionZone({self.name!r}, {len(self)} points, label={self.label!r})"

    # --------------------------------------------------------------------------
    # Storage
    # --------------------------------------------------------------------------

    def to_dict(self) -> dict:
        """
        A JSON-friendly dict of this zone, read by `from_dict`.
        """
        return {
            "name": self.name,
            "label": self.label,
            "color": self.color,
            "visible": self.visible,
            "description": self.description,
            "polygon": self.polygon,
            "outline": self._outline,
        }

    @classmethod
    def from_dict(cls, data: dict, verbose: bool = True) -> "ExclusionZone":
        """
        Build a zone from a dict written by `to_dict`.

        Args:
            data: The dict.
            verbose: Whether the zone reports progress.
        """
        return cls(
            data["name"],
            data["polygon"],
            label=data.get("label"),
            color=data.get("color", DEFAULT_ZONE_COLOR),
            outline=data.get("outline"),
            visible=data.get("visible", True),
            description=data.get("description", ""),
            verbose=verbose,
        )

    def save(self, path: str) -> str:
        """
        Write this zone to a JSON file.

        Args:
            path: Path of the file.

        Returns:
            The path of the file.
        """
        _write_json(path, self.to_dict())
        return path

    @classmethod
    def load(cls, path: str, verbose: bool = True) -> "ExclusionZone":
        """
        Read a zone from a JSON file written by `save`.

        Args:
            path: Path of the file.
            verbose: Whether the zone reports progress.
        """
        return cls.from_dict(_read_json(path), verbose=verbose)

    @classmethod
    def from_geojson(cls, path: str, feature_id: str, name: Optional[str] = None, **kwargs) -> "ExclusionZone":
        """
        A zone from the feature `feature_id` of a GeoJSON file.
        """
        from architeuthis.toolbox.os_utils import extract_polygons_from_geojson

        polygons = extract_polygons_from_geojson(path, [feature_id])
        if not polygons:
            raise KeyError(f"Feature {feature_id} not found in {path}.")
        return cls(name if name is not None else feature_id, polygons[0], **kwargs)


class ExclusionZoneLibrary(JsonLibrary):
    """
    Exclusion zones stored as JSON files, one per zone.

    They are in `~/data/exclusion_zones/` by default.

    Example:
        >>> library = ExclusionZoneLibrary()
        >>> library.save(zone)
        >>> library.load("safety")
        >>> list(library)  # all the stored zones
    """

    item_class = ExclusionZone
    default_directory = EXCLUSION_ZONE_DIRECTORY


# ------------------------------------------------------------------------------
# Zones used by default
# ------------------------------------------------------------------------------

NORTH_AMERICA_POLYGON = [
    [46.6475507, -53.0879974],
    [47.1448975, -52.6904297],
    [47.8057761, -52.6574707],
    [48.7272088, -53.0310059],
    [52.2547088, -55.5688477],
    [57.0646303, -61.6992188],
    [59.1759282, -64.0283203],
    [60.5221575, -64.8193359],
    [62.0833149, -66.2255859],
    [63.5485522, -70.3125000],
    [64.4348920, -73.6083984],
    [64.8862654, -77.3876953],
    [66.0715465, -86.4404297],
    [64.1681069, -92.1093750],
    [59.4450751, -96.6796875],
    [56.2677611, -95.9765625],
    [46.1950421, -92.7246094],
    [41.0793511, -87.6708984],
    [35.3532161, -75.9814453],
    [37.7620299, -77.0141602],
    [38.3761154, -76.9454956],
    [38.9935721, -76.8273926],
    [39.2577782, -76.3659668],
    [38.3416562, -75.9594727],
    [37.2980904, -75.9979248],
    [37.1121458, -75.9539795],
    [37.6164071, -75.5804443],
    [38.0351124, -75.2563477],
    [38.4084061, -75.0723267],
    [38.7883454, -75.0860596],
    [39.2705372, -74.6026611],
    [39.7747695, -74.1137695],
    [40.3904888, -73.9984131],
    [41.2881262, -70.7794189],
    [41.2365112, -69.9746704],
    [41.2943173, -69.9362183],
    [41.8347815, -69.9307251],
    [42.0615286, -70.0708008],
    [42.6440611, -70.5844116],
    [43.4130287, -70.4553223],
    [43.8345268, -68.8623047],
    [44.6881828, -67.1539307],
    [44.2412638, -66.3958740],
    [43.3930737, -66.0305786],
    [43.3850899, -65.6268311],
    [43.5007524, -65.2807617],
    [44.4631908, -63.5641479],
    [45.2555553, -60.9851074],
    [46.0045933, -59.6667480],
    [47.0252060, -60.3918457],
    [47.5394554, -59.2053223],
    [47.2549999, -55.9616089],
    [46.9146271, -55.9780884],
    [46.8414071, -55.8050537],
    [46.8733358, -55.3738403],
    [46.8188578, -54.1873169],
    [46.6098279, -53.5720825],
    [46.6263348, -53.1614685],
    [46.6484934, -53.0879974],
    [46.6475507, -53.0879974]
]

BRITTANY_POLYGON = [
    [47.234906794905456, -2.298894594711654],
    [47.25856998567288, -2.4325583888579034],
    [47.29283375261824, -2.547348407391687],
    [47.472965041672204, -3.132757632163045],
    [47.643448179530274, -3.2076668170178877],
    [47.700395091200015, -3.368297468536256],
    [47.69636166917016, -3.4548323100507234],
    [47.79791598030666, -3.8522262539473218],
    [47.85365939763104, -3.980613066215874],
    [47.84328834623138, -4.041571653262067],
    [47.79730758529769, -4.187810231946969],
    [47.7951034723181, -4.380102394509618],
    [48.04251441805747, -4.732749036488459],
    [48.271675251256646, -4.616214170859991],
    [48.33235206326594, -4.766668801789211],
    [48.51970337432375, -4.781458461018697],
    [48.67589361128423, -4.353382869976883],
    [48.75347516979233, -4.009457823390732],
    [48.84141631708758, -3.5046081884123716],
    [48.89654815888168, -3.0605321526173523],
    [48.560105723588045, -2.671292321902763],
    [48.685993556279584, -2.318443857961514],
    [47.234906794905456, -2.298894594711654],
]


def north_america_zone(verbose: bool = True) -> ExclusionZone:
    """
    The zone that keeps routes away from North America.

    Args:
        verbose: Whether the zone reports progress.
    """
    return ExclusionZone("north_america", NORTH_AMERICA_POLYGON, label="North America", verbose=verbose)


def brittany_zone(verbose: bool = True) -> ExclusionZone:
    """
    The zone that keeps routes away from Brittany.

    Args:
        verbose: Whether the zone reports progress.
    """
    return ExclusionZone("brittany", BRITTANY_POLYGON, label="Brittany", verbose=verbose)


def iceberg_zone(verbose: bool = True) -> ExclusionZone:
    """
    The latest IIP iceberg limit.

    It is downloaded the first time it is needed in a session (see
    `architeuthis.icebergs`). The zone is empty when no bulletin is
    available.
    """
    from architeuthis.icebergs import berg_zone

    return ExclusionZone(
        "iceberg_limit",
        berg_zone,
        label="Iceberg limit",
        color=ICEBERG_ZONE_COLOR,
        outline=berg_zone[:-_ICEBERG_CLOSING_POINTS],
        description="International Ice Patrol bulletin",
        verbose=verbose,
    )


def default_exclusion_zones(verbose: bool = True) -> list:
    """
    The zones used by default.

    In this order: North America, Brittany, iceberg limit.
    """
    return [north_america_zone(verbose), brittany_zone(verbose), iceberg_zone(verbose)]


def merge_exclusion_zones(*groups: Iterable) -> list:
    """
    All the zones of several groups, in order.

    A zone replaces an earlier one of the same name.
    """
    zones = {}
    for group in groups:
        for zone in group:
            zones[zone.name] = zone
    return list(zones.values())

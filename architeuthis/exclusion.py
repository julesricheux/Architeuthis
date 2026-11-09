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

The zones of a routing are defined by the user. Only `iceberg_zone()`
comes with the package, from the latest IIP bulletin: it is fetched when
this function is called, never at import.
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
        >>> zones = [zone, iceberg_zone()]
        >>> Topography("topo", exclusion_zones=zones)
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
# The iceberg limit, the only zone that comes from a data source
# ------------------------------------------------------------------------------

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

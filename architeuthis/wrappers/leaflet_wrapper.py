# -*- coding: utf-8 -*-
"""
Map layers of the UI that do not depend on its forecast data, so that they can be built
and tested without launching `ui.py`.
"""

from __future__ import annotations

import dash_leaflet as dl


def exclusion_zone_overlay(zone) -> dl.Overlay:
    """
    A layer for an exclusion zone: it can be hidden in the layers control of the map, under
    the label of the zone, which is also written on the map. A zone without data, such as the
    iceberg limit when no bulletin is available, stays listed as unavailable, not to be taken
    for a zone that is simply clear of the route.
    """
    if len(zone.outline) < 2:
        return dl.Overlay(
            dl.LayerGroup([], id=f"exclusion-zone-{zone.name}"),
            name=f"{zone.label} (unavailable)",
            checked=False,
        )

    return dl.Overlay(
        dl.Polyline(
            id=f"exclusion-zone-{zone.name}",
            positions=zone.outline,
            fill=False,
            color=zone.color,
            fillOpacity=0.2,
            children=dl.Tooltip(
                zone.label,
                permanent=True,
                direction="center",
                className="exclusion-zone-label",
            ),
        ),
        name=zone.label,
        checked=zone.visible,
    )


def exclusion_zone_overlays(zones) -> list:
    """One hideable layer per exclusion zone."""
    return [exclusion_zone_overlay(zone) for zone in zones]

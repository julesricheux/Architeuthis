# -*- coding: utf-8 -*-
"""
Helpers of the map display.

Created on Tue Dec  9 11:21:16 2025

@author: jrich
"""

def density_from_zoom(zoom, base=30):
    """
    A thinning step for map arrows, inversely proportional to zoom.

    Args:
        zoom: Zoom level of the map.
        base: The step at zoom 0.

    Returns:
        An integer of at least 1.
    """
    # invertly proportional to zoom
    return max(1, int(base / (zoom + 1)))
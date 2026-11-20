# -*- coding: utf-8 -*-
"""
Colormaps of wind, waves and satellite images for the map display.

Created on Tue Dec  9 00:49:14 2025

@author: jules
"""

import architeuthis.numpy as np
import matplotlib.colors as mcolors


def get_wind_cmap():
    """
    The colormap of wind speeds, in m/s.

    Returns:
        The colormap, smooth between its anchor colors, and its norm.
    """
    # Beaufort-like bins (m/s)
    bounds = np.array([0, 2, 6, 10, 14, 17, 21, 25, 29, 33, 37, 41, 47, 52, 56, 70, 89, 99, 150, 202]) * 0.5144
    
    # Colors for each bin
    colors = [
        "#6271b7",
        "#39619f",
        "#4a94a9",
        "#4d8d7b",
        "#53a553",
        "#359f35",
        "#a79d51",
        "#9f7f3a",
        "#a16c5c",
        "#813a4e",
        "#af5088",
        "#754a93",
        "#6d61a3",
        "#44698d",
        "#5c9098",
        "#7d44a5",
        "#e7d7d7",
        "#dbd487",
        "#cdca70",
        "#808080",
    ]
    
    # cmap = mcolors.ListedColormap(colors)
    # norm = mcolors.BoundaryNorm(bounds, cmap.N)
    
    # Normalize bounds to 0–1 for colormap construction
    norm = mcolors.Normalize(vmin=bounds.min(), vmax=bounds.max())
    scaled_positions = norm(bounds)
    
    # Pair each bound with its color → interpolation will preserve the anchor points
    color_tuples = list(zip(scaled_positions, colors))
    cmap = mcolors.LinearSegmentedColormap.from_list("custom_smooth", color_tuples, N=256)
    
    return cmap, norm


def get_wave_cmap():
    """
    The colormap of wave heights, in m.

    Returns:
        The colormap, smooth between its anchor colors, and its norm.
    """
    # Beaufort-like bins (m/s)
    bounds = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10., 12.,])
    
    # Colors for each bin
    colors = [
        "#9fb9bf",
        "#309db9",
        "#30628d",
        "#3868bf",
        "#393c8e",
        "#bb5abf",
        "#9a3097",
        "#853030",
        "#bf335f",
        "#bf6757",
        "#bfbfbf",
        "#9a7f9b",
    ]
    
    # cmap = mcolors.ListedColormap(colors)
    # norm = mcolors.BoundaryNorm(bounds, cmap.N)
    
    # Normalize bounds to 0–1 for colormap construction
    norm = mcolors.Normalize(vmin=bounds.min(), vmax=bounds.max())
    scaled_positions = norm(bounds)
    
    # Pair each bound with its color → interpolation will preserve the anchor points
    color_tuples = list(zip(scaled_positions, colors))
    cmap = mcolors.LinearSegmentedColormap.from_list("custom_smooth", color_tuples, N=256)
    
    return cmap, norm


# Colour scales of satellite images: (value, colour) stops, in increasing
# values, two stops at one value making a step; a colour may have an alpha
# ("#rrggbbaa"), for the clear sky to let the map show through.
# "infra": the legend of Windy's Infra+, brightness temperature in K: grey
# from 321 K to white at 240 K, then colours for the cold cloud tops, blue
# to red to 182 K.
# "blue": Windy's Blue, brightness temperature in K, estimated by eye
# (Windy does not publish it): clear sky transparent at 290 K, translucent
# white at 270 K, opaque white at 250 K, darker greys for colder tops.
# "visible": the image as the camera sees it, brightness from 0 to 1.
SATELLITE_STOPS = {
    "infra": [
        (182.0, "#300000"),
        (200.0, "#7a0403"),
        (205.0, "#d23104"),
        (210.0, "#fb8022"),
        (215.0, "#edd03b"),
        (220.0, "#a3fd3d"),
        (225.0, "#31f199"),
        (230.0, "#29bbec"),
        (235.0, "#466ae3"),
        (240.0, "#4040a3"),
        (240.0, "#f0f0f0"),
        (321.0, "#181818"),
    ],
    "blue": [
        (190.0, "#404040ff"),
        (250.0, "#ffffffff"),
        (270.0, "#ffffff80"),
        (290.0, "#ffffff00"),
    ],
    "visible": [
        (0.0, "#000000"),
        (1.0, "#ffffff"),
    ],
}

# Quantity each colour scale draws: brightness temperature `bt` in K, or
# `brightness` from 0 to 1, as `satellite.IMAGERY_CHANNELS` names them
SATELLITE_QUANTITIES = {
    "infra": "bt",
    "blue": "bt",
    "visible": "brightness",
}


def get_satellite_cmap(name="infra", quantity=None):
    """
    The colormap of a satellite colour scale.

    Args:
        name: "infra" (brightness temperature in K, Windy's Infra+),
            "blue" (the same, Windy's Blue, clear sky transparent) or
            "visible" (brightness from 0 to 1).
        quantity: Quantity to draw, "bt" or "brightness", to check that
            the scale draws it; None not to check.

    Returns:
        The colormap, smooth between its anchor colors, with a step
        where two share a value, and its norm. Values beyond the scale
        take its end colours.

    Example:
        cmap, norm = get_satellite_cmap("blue", quantity="bt")
    """
    if name not in SATELLITE_STOPS:
        raise ValueError(f"Unknown satellite colour scale {name}: one of {list(SATELLITE_STOPS)}.")
    if quantity is not None and SATELLITE_QUANTITIES[name] != quantity:
        fitting = [key for key, value in SATELLITE_QUANTITIES.items() if value == quantity]
        raise ValueError(f"The {name} colour scale does not draw {quantity}: choose among {fitting}.")
    bounds = np.array([value for value, _ in SATELLITE_STOPS[name]])
    colors = [color for _, color in SATELLITE_STOPS[name]]

    # Normalize bounds to 0–1 for colormap construction
    norm = mcolors.Normalize(vmin=bounds.min(), vmax=bounds.max())
    scaled_positions = norm(bounds)

    # Pair each bound with its color: a repeated position is a step
    color_tuples = list(zip(scaled_positions, colors))
    cmap = mcolors.LinearSegmentedColormap.from_list(f"satellite_{name}", color_tuples, N=1024)

    return cmap, norm

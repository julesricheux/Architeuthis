# -*- coding: utf-8 -*-
"""
Created on Tue Dec  9 00:49:14 2025

@author: jules
"""

import architeuthis.numpy as np
import matplotlib.colors as mcolors


def get_wind_cmap():
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

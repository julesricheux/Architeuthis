# -*- coding: utf-8 -*-
"""
Created on Tue Dec  9 11:21:16 2025

@author: jrich
"""

def density_from_zoom(zoom, base=30):
    # invertly proportional to zoom
    return max(1, int(base / (zoom + 1)))
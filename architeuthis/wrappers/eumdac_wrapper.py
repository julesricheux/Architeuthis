# -*- coding: utf-8 -*-
"""
Created on Thu Jan 29 17:28:10 2026

@author: jrich
"""

def find_lat_lon(ds):
    """
    Find latitude and longitude variables in an xarray Dataset
    using CF conventions (standard_name / units).

    Returns
    -------
    lat_name, lon_name : str
    """

    lat_name = None
    lon_name = None

    for name, var in ds.variables.items():
        std = var.attrs.get("standard_name", "").lower()
        units = var.attrs.get("units", "").lower()

        if std == "latitude" or units == "degrees_north":
            lat_name = name

        if std == "longitude" or units == "degrees_east":
            lon_name = name

    if lat_name is None or lon_name is None:
        raise ValueError(
            "Latitude/Longitude not found using CF conventions.\n"
            "Checked standard_name and units."
        )

    return lat_name, lon_name
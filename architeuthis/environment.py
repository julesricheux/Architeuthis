# -*- coding: utf-8 -*-
"""
A set of data layers queried together. Not functional yet.

Created on Thu Jan 15 11:13:35 2026

@author: jrich
"""

# import copernicusmarine

# import xarray as xr
# import casadi as ca
# import pandas as pd

# from scipy.ndimage import distance_transform_edt

import architeuthis.numpy as np #TODO fork aerosandbox.numpy

from common import ArchiteuthisObject

# from herbie_loading import retrieve_weather_data #TODO rename herbie_wrapper

class Environment(ArchiteuthisObject):
    """
    A set of data layers queried together. Not functional yet.

    Args:
        name: Name of this object, used in status messages.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        verbose: bool = True,
    ):
        super().__init__(name, verbose)
        self.data = set()
        
    def add_data(
        self,
        layer,
    ):
        """
        Add a data layer, if it is not already there.

        Args:
            layer: The data object to add.
        """
        if layer in self.data:
            print(f"🟦 {layer.name} already in {self.name}.")
        else:
            self.data.add(layer)
            print(f"➕ {layer.name} added to {self.name}.")
        
    def remove_data(
        self,
        layer,
    ):
        """
        Remove a data layer, if it is there.

        Args:
            layer: The data object to remove.
        """
        if layer in self.data:
            self.data.remove(layer)
            print(f"➖ {layer.name} removed from {self.name}.")
        else:
            print(f"💔 {layer.name} not in {self.name}.")
        
    def __call__(
        self,
        X,
    ):
        """
        Query every variable of every data layer.

        Args:
            X: Query points, of shape (n_queries, n_dims).

        Returns:
            A dict of the values by variable key.
        """
        res = {}
        for d in self.data: # for all layers in environment
            for v in d.var_keys: # for all available keys in layer
                res[v] = d(v, X) # interpolate variable v at X
                
        return res


if __name__=="__main__":
    env = Environment("base_env")
    
    from forecast import Topography, DeterministicHerbieForecast
    
    # IFS atmospheric data
    fh = DeterministicHerbieForecast("test_herbie", model="ifs", product="oper", regex=r":10[u|v]:", fxx=[0, 3, 6])
    fh.load_data()
    
    fh.add_interpolator("u10", "valid_time", "latitude", "longitude")
    
    
    t = Topography("topo", min_lon=-80., max_lon=0., min_lat=30., max_lat=60., depth_offset=10.)
    t.load_data()
    t.add_interpolator(
        "distance_to_iso0",
        "latitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
        "longitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
        var_key="z"
    )
    
    # env.add_data(fh)
    env.add_data(t)
    env.add_data(t)
    
    # X = np.array([[55, -80], [55, -80], [55, -80]])
    X = np.array([[55, -80], [55, -80], [55, -80]])
    
    res = env(X)

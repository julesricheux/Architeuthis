# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 12:44:25 2026

@author: jrich
"""

import os

from abc import ABC, abstractmethod

import architeuthis.numpy as np
from architeuthis.modeling import InterpolatedModel

from casadi import interpolant

from typing import Union, Sequence, Literal
from pandas import Timestamp
from datetime import datetime

Datetime = Union[datetime, Timestamp, str]

#TODO should probably be in __init__
_HOME = os.path.join(
    os.path.expanduser("~"),
    "data",
)
_CMEMS_USER = "jricheux1"
_CMEMS_PWD = "..."

_EUMDAC_USER = "..."
_EUMDAC_PWD = "..."

_EUMDAC_CREDENTIALS = (_EUMDAC_USER, _EUMDAC_PWD)

_TOPOGRAPHY_URL = "https://data.mondaic.com/topography-data/topography_earth2014_egm2008_lmax_2048.nc"

_banner = """
===================================================================
                  ▄▄                               ▄▄              
                  ██    ▀▀  ██                ██   ██    ▀▀        
 ▀▀█▄ ████▄ ▄████ ████▄ ██ ▀██▀▀ ▄█▀█▄ ██ ██ ▀██▀▀ ████▄ ██  ▄█▀▀▀ 
▄█▀██ ██ ▀▀ ██    ██ ██ ██  ██   ██▄█▀ ██ ██  ██   ██ ██ ██  ▀███▄ 
▀█▄██ ██    ▀████ ██ ██ ██▄ ██   ▀█▄▄▄ ▀██▀█  ██   ██ ██ ██▄ ▄▄▄█▀

                      I  S    A  L  I  V  E                        
===================================================================
"""


def tall(array):
    return np.reshape(array, (-1, 1))

def wide(array):
    return np.reshape(array, (1, -1))

class ArchiteuthisObject(ABC):
    
    @abstractmethod
    def __init__(
        self,
        name: str,
        verbose: bool,
    ):
        self.name = name
        self.verbose = verbose
    
    
class ArchiteuthisData(ArchiteuthisObject):
    
    @abstractmethod
    def __init__(
        self,
        name: str,
        verbose: bool,
    ):
        super().__init__(name, verbose)
        
        self.path = None
        self.data = None
        self.var_keys = set()
        self.interpolators = {}
        
    def load_data(self):
        self._locate_data()
        self._download_data()
        self._read_data()
        self._convert_data()
        self._extend_data()

    def _locate_data(self):
        pass
    
    def _download_data(self):
        pass
    
    def _read_data(self):
        pass
    
    def _convert_data(self):
        pass
    
    def _extend_data(self):
        pass
        
    def add_interpolator(
        self,
        var_dim: str,
        coord_dims: Sequence[str],
        coord_slices: Sequence [str],
        var_key: str,
        method: Literal["bspline", "linear", "nearest"] = "linear",
        fac: float = 1.0,
    ):
        if var_key in self.var_keys:
            print(f"🟦 {var_key} already in {self.name} interpolators.")
        else:
            # build interpolator x
            x = [
                np.asarray(self.data.coords[dim].values[sel])
                for dim, sel in zip(coord_dims, coord_slices)
            ]
            
            # build interpolator f
            f = np.nan_to_num(
                self.data[var_dim].to_numpy().squeeze()[*coord_slices].ravel(order='F'),
                nan=0.
            ) * fac # apply correction factor if specified
            
            # build interpolator
            self.interpolators[var_key] = interpolant(
                f"LUT_{var_dim}",
                method,
                x,
                f,
                # jit=True,
            )
            
            # TODO get up and running
            # # build interpolator x
            # x = {
            #     dim: np.asarray(self.data.coords[dim].values[sel])
            #     for dim, sel in zip(coord_dims, coord_slices)
            # }
            
            # # build interpolator f
            # f = np.nan_to_num(
            #     self.data[var_dim].to_numpy().squeeze()[*coord_slices],
            #     nan=0.
            # ) * fac # apply correction factor if specified
            
            # # build interpolator
            # self.interpolators[var_key] = InterpolatedModel(
            #     x_data_coordinates=x,
            #     y_data_structured=f,
            #     method=method,
            #     fill_value=np.nan
            # )
            # self.var_keys.add(var_key)
            
            print(f"➕ Added {var_key}: {var_dim} to {self.name} interpolators.")
    
    def remove_interpolator(
        self,
        var_key: str,
    ):
        if var_key in self.var_keys:
            del self.interpolators[var_key]
            self.var_keys.remove(var_key)
            print(f"➖ Removed {var_key} from {self.name} interpolators.")
        else:
            print(f"💔 {var_key} not found in {self.name} interpolators.")
            
    def __call__(
        self,
        var_key,
        X,
    ):
        if not self.interpolators:
            print(f"💔 {self.name} has no interpolators and thus cannot be called.")
            return None
        
        # TODO test X size. Should be (q, n)
            
        return tall(self.interpolators[var_key](np.transpose(X)))

    
class ArchiteuthisSpatialData(ArchiteuthisData):
    
    @abstractmethod
    def __init__(
        self,
        name: str,
        min_lon: float,
        max_lon: float,
        min_lat: float,
        max_lat: float,
        verbose: bool,
    ):
        super().__init__(name, verbose)
        
        self.min_lon = min_lon
        self.max_lon = max_lon
        self.min_lat = min_lat
        self.max_lat = max_lat

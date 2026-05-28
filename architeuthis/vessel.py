# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 10:16:15 2026

@author: jrich
"""

from __future__ import annotations

import os

import xarray as xr
import architeuthis.numpy as np

from typing import Union
from collections.abc import Callable
from architeuthis.toolbox.inspect_tools import ensure_callable

# from typing import Sequence
from architeuthis.common import ArchiteuthisData


class Vessel(ArchiteuthisData):
    """
    Represents the vessel and its performance characteristics.
    """

    def __init__(
        self,
        name: str,
        filepath: str,
        hotel_load: Union[Callable, float, int] = 0., # kW
        max_power: Union[Callable, float, int] = 1e12, # kW
        sfc: Union[Callable, float, int] = 0., # g/kWh
        verbose: bool = True,
    ):
        super().__init__(name, verbose)
        
        self.path = filepath
        
        self.hotel_load = ensure_callable(hotel_load) # TODO to define with kwargs to be more flexible
        self.sfc = ensure_callable(sfc) # TODO to define with kwargs to be more flexible
        # self.max_power = ensure_callable(max_power)
        
        # self.sfc = sfc 
        # self.hotel_load = hotel_load   
        self.max_power = max_power
        
    def _locate_data(self):
        assert os.path.exists(self.path), f"💔 '{self.path}' does not exist."
        print(f"✅ {self.name} data found.")
        
    def _read_data(self):
        self.data = xr.open_dataset(self.path) # TODO add columns selection to save memory
        
    def _convert_data(self):
        # TODO complete missing points
        pass
    
    def add_interpolator(
        self,
        var_dim: str,
        stw_dim: str,
        tws_dim: str,
        twa_dim: str,
        hs_dim: str,
        wa_dim: str,
        var_key: str = None,
        stw_slice: slice = slice(None, None, None),
        tws_slice: slice = slice(None, None, None),
        twa_slice: slice = slice(None, None, None),
        hs_slice: slice = slice(None, None, None),
        wa_slice: slice = slice(None, None, None),
        method: str = "linear",
    ):
        if var_key is None:
            var_key = var_dim
        
        coord_dims = [stw_dim, tws_dim, twa_dim, hs_dim, wa_dim]
        coord_slices = [stw_slice, tws_slice, twa_slice, hs_slice, wa_slice]
        
        super().add_interpolator(var_dim, coord_dims, coord_slices, var_key, method)

        
if __name__=="__main__":
    
    # vessel_data = "C:\\Users\\jules\\output_sails.nc"
    vessel_data = r"C:/Users/jrich/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff100.nc"
    # vessel_data = "C:\\Users\\jrich\\output_sails.nc"
    
    columns = ["bhp", "max_bhp", "leeway"]

    vessel = Vessel("base_vessel", vessel_data, max_power=1000., hotel_load=100.)
    vessel.load_data()
    
    vessel.add_interpolator("bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    vessel.add_interpolator("max_bhp", "stw", "tws", "twa", "hs", "wa", method="linear")
    
    vessel_query = np.array([
        [6., 15., 60, 4.1, 60],
        [8., 15., 60, 1, 60],
    ])
    
    # vessel_query = {
    #     "stw": 12.5,
    #     "tws": 11,
    #     "twa": np.abs(62.3),
    #     "hs": 1.3,
    #     "wa": np.abs(78.),
    # }
    
    bhp = vessel("bhp", vessel_query)
    print(bhp)

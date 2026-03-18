# -*- coding: utf-8 -*-
"""
Created on Mon Dec  8 22:11:15 2025

@author: jules
"""

import xarray as xr
from herbie import HerbieLatest, FastHerbie

def retrieve_weather_data(
        model: str = 'ifs',
        valid_time: str = None,
        fxx: tuple = range(0,48+1,3),
        product: str = "oper",
        variables: str = ":10[u|v]:|:msl:|:cape:",
        minimum_longitude: float =-180.,
        maximum_longitude: float =180.,
        minimum_latitude: float =-90.,
        maximum_latitude: float =90.,
    ):
    
    if not valid_time:
        HL = HerbieLatest(model=model, product=product)
        
        valid_time = HL.valid_date
    
    FH = FastHerbie(
        [valid_time],
        model=model,
        product=product,
        fxx=fxx,
    )
        
    data = FH.download(variables,)
    
    if product in ["enfo", "waef"]:
        ds = (
            xr.open_mfdataset(
                list(data),
                engine="cfgrib",
                decode_timedelta=False,
                decode_times=True,
                combine="nested",
                concat_dim=["valid_time"],
                filter_by_keys={'dataType': 'pf'}
            )
            .sel(
                latitude=slice(maximum_latitude, minimum_latitude),
                longitude=slice(minimum_longitude, maximum_longitude),
            )
            .load()
            .squeeze()
            .sortby("valid_time")
        )
    else:
        ds = (
            xr.open_mfdataset(
                list(data),
                # coords='minimal', #` TODO why ???
                engine="cfgrib",
                decode_timedelta=False,
                decode_times=True,
                combine="nested",
                concat_dim=["valid_time"],
            )
            .sel(
                latitude=slice(maximum_latitude, minimum_latitude),
                longitude=slice(minimum_longitude, maximum_longitude),
            )
            .load()
            .squeeze()
            .sortby("valid_time")
        )
        
    ds = ds.sortby("latitude")  # reorder data consistently for decreasing latitudes
    
    if 'u' in variables or 'v' in variables:
        ds.herbie.with_wind()
        
    return ds


if __name__=="__main__":
    # model = "aifs"
    # fxx = range(0,360+1,6)
    
    model = "ifs"
    fxx = range(0,360+1,3)
    
    product = "oper"
    product = "enfo"
    variables = ":10[u|v]:|:msl:|:cape:"
    
    # product = "wave"
    # product = "waef"
    # variables = ":swh:|:mwp:|:mwd:"
    
    minimum_longitude=-80.
    maximum_longitude=0.
    minimum_latitude=30.
    maximum_latitude=60.
    
    ds = retrieve_weather_data(
        model=model,
        fxx=fxx,
        product=product,
        variables=variables,
        minimum_longitude=minimum_longitude,
        maximum_longitude=maximum_longitude,
        minimum_latitude=minimum_latitude,
        maximum_latitude=maximum_latitude,
    )

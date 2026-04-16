# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 14:02:43 2026

@author: jrich
"""

from __future__ import annotations

import os
import requests
import copernicusmarine

import xarray as xr
import pandas as pd
import architeuthis.numpy as np

from herbie.misc import ANSI
from matplotlib.path import Path
from typing import Sequence, Union
from herbie import HerbieLatest, FastHerbie
from scipy.ndimage import distance_transform_edt
from architeuthis.common import ArchiteuthisSpatialData, Datetime, _CMEMS_USER, _CMEMS_PWD, _HOME, _TOPOGRAPHY_URL


def preprocess(ds):
    return ds.drop_vars("step", errors="ignore")


class Topography(ArchiteuthisSpatialData):
    
    def __init__(
        self,
        name: str,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        depth_offset: float = 0.,
        z_margin: float = 0.,
        exclusion_zones: Sequence(float) = [],
        verbose: bool = True,
    ):
        super().__init__(name, min_lon, max_lon, min_lat, max_lat, verbose)
        
        self.depth_offset = depth_offset
        self.z_margin = z_margin
        
        self.exclusion_zones = exclusion_zones
    
    def _locate_data(self):
        self.path = os.path.join(
            _HOME,
            "topo",
            "topography_earth2014_egm2008_lmax_2048.nc"
        )
        
    def _download_data(self):
        url = _TOPOGRAPHY_URL
        
        if os.path.exists(self.path):
            print("🗺️ Topography already downloaded.")
        else:
            print("🗺️ Downloading topography...")
            try:
                # Send a GET request with stream=True to handle large files efficiently
                with requests.get(url, stream=True) as response:
                    # Raise an error if the download failed (e.g., 404 or 500 errors)
                    response.raise_for_status()
                    
                    # Open the local file in 'write binary' mode
                    with open(self.path, 'wb') as f:
                        # Iterate over the response data in 8KB chunks
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk: # Filter out keep-alive new chunks
                                f.write(chunk)
                
            except requests.exceptions.RequestException as e:
                print(f"💔 Topography could not be downloaded {e}")

    def _read_data(self):
        self.data = xr.open_dataset(self.path)[["topography_earth2014_egm2008_lmax_2048_lmax_2048",]]

    def _convert_data(self):
        # =====================================================================
        # INITIAL CONVERSION
        # =====================================================================
        
        suffix = "topography_earth2014_egm2008_lmax_2048_lmax_2048"
        lat = "latitude_" + suffix
        lon = "longitude_" + suffix
    
        self.data = self.data.transpose(lat, lon)
    
        self.data[lon] = ((self.data[lon] + 180.) % 360.) - 180.
        self.data = self.data.sortby(lon)
        self.data = self.data.sortby(lat)
    
        self.data = self.data.sel({
            lat: slice(self.min_lat, self.max_lat),
            lon: slice(self.min_lon, self.max_lon),
        })
        
        # Extract the topography variable
        topo = self.data[suffix].to_numpy()
        
        # =====================================================================
        # ADD EXCLUSION ZONES
        # =====================================================================
        
        # Flatten coordinate grids
        # 1D coordinates
        LATS_1D = self.data[lat].values  # shape (nlat,)
        LONS_1D = self.data[lon].values  # shape (nlon,)
        
        # Create 2D meshgrid
        LONS, LATS = np.meshgrid(LONS_1D, LATS_1D)  # shapes (nlat, nlon)
        
        # Flatten into N x 2 array of (lat, lon)
        points = np.column_stack((LATS.ravel(), LONS.ravel()))
        
        # Compute mask for all exclusion zones
        mask_total = np.zeros(LATS.shape, dtype=bool)
        for polygon_coords in self.exclusion_zones:
            poly_path = Path(polygon_coords)
            mask_total |= poly_path.contains_points(points).reshape(LATS.shape)
        
        # Apply z value inside exclusion zones
        z_exclude = 1e3
        topo[mask_total] = z_exclude
        
        if self.verbose and mask_total.sum():
            print(f"⛔ Updated {mask_total.sum()} points inside exclusion zones.")
            
        # =====================================================================
        # COMPUTE DISTANCE TO SHORE
        # =====================================================================
        
        white = (topo >= -self.depth_offset)
        black = ~white
    
        dist_to_black = np.sqrt(distance_transform_edt(white))
        dist_to_white = np.sqrt(distance_transform_edt(black))
    
        signed_dist_np = np.where(
            white,
            dist_to_black,
            -dist_to_white
        ) + self.z_margin
        
        signed_dist_np = np.fmax(signed_dist_np, 0.)
    
        signed_dist = xr.DataArray(
            signed_dist_np,
            dims=(lat, lon),
            coords={
                lat: self.data[lat],
                lon: self.data[lon],
            },
            name="distance_to_iso0",
        )
    
        self.data["distance_to_iso0"] = signed_dist
        
    def add_interpolator(
        self,
        var_dim: str,
        latitude_dim: str,
        longitude_dim: str,
        var_key: str = None,
        latitude_slice: slice = slice(None, None, None),
        longitude_slice: slice = slice(None, None, None),
        method: str = "linear",
    ):
        if var_key is None:
            var_key = var_dim
        
        coord_dims = [latitude_dim, longitude_dim]
        coord_slices = [latitude_slice, longitude_slice]
        
        super().add_interpolator(var_dim, coord_dims, coord_slices, var_key, method)


class Forecast(ArchiteuthisSpatialData):
    
    def __init__(
        self,
        name: str,
        date: Union[Datetime, list[Datetime]],
        fxx: Union[int, list[int]],
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        time_unit: str = "s",
        verbose: bool = True,
    ):
        super().__init__(name, min_lon, max_lon, min_lat, max_lat, verbose)
        
        if date is None:
            date = self._find_latest()
            
        self.f00: Sequence[float] = date
        self.fxx: Sequence[float] = fxx
        
        self.time_unit = time_unit
    
    @property
    def forecast_time(self):
        return self.f00
    
    @property
    def valid_time(self):
        return self.fxx
    
    def _find_latest(self):
        pass
    
    def add_interpolator(
        self,
        var_dim: str,
        time_dim: str,
        latitude_dim: str,
        longitude_dim: str,
        var_key: str = None,
        time_slice: slice = slice(None, None, None),
        latitude_slice: slice = slice(None, None, None),
        longitude_slice: slice = slice(None, None, None),
        method: str = "linear",
        fac: float = 1.0,
        
    ):
        if var_key is None:
            var_key = var_dim
        
        coord_dims = [time_dim, latitude_dim, longitude_dim]
        coord_slices = [time_slice, latitude_slice, longitude_slice]
        
        super().add_interpolator(var_dim, coord_dims, coord_slices, var_key, method, fac)
    
    
class HerbieForecast(Forecast):
    def __init__(
        self,
        name: str,
        model: str,
        product: str,
        regex: str = None,
        date: Union[Datetime, list[Datetime]] = None,
        fxx: Union[int, list[int]] = [0],
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        time_unit: str = "s",
        verbose: bool = True,
    ):
        self.model = model
        self.product = product
        self.regex = regex
        
        # TODO use the regex parser to separate variables and levels, provisioning the implementation of HRDPS
        
        self.__FH = None
        
        super().__init__(name, date, fxx, min_lon, max_lon, min_lat, max_lat, time_unit, verbose)
        
    def _find_latest(self):
        print(f"📅 Date is not specified. Retrieving latest {self.model.upper()} {ANSI.orange}GRIB2 files.{ANSI.reset}")
        # print(f"📅 Date is not specified. Retrieving latest {self.model.upper()} {self.product.upper()} {ANSI.orange}GRIB2 files.{ANSI.reset}")
        return HerbieLatest(model=self.model, product=self.product).valid_date
        
    def _locate_data(self):
        self.__FH = FastHerbie(
            [self.f00],
            model=self.model,
            product=self.product,
            fxx=self.fxx,
        )
        
    def _download_data(self):
        if self.__FH is None:
            self.locate_data()
        print(f"⬇️ Downloading {self.name} data ...")
        self.path = self.__FH.download(self.regex,)
        print("✅ Download completed.")
        
    def _convert_data(self):
        self.data["longitude"] = ((self.data["longitude"] + 180.) % 360.) - 180.
        self.data = self.data.sortby("valid_time")
        self.data = self.data.sortby("latitude")
        self.data = self.data.sortby("longitude")
        
        self.data = (
            self.data
            .sel(
                latitude=slice(self.min_lat, self.max_lat),
                longitude=slice(self.min_lon, self.max_lon),
            )
            .load()
            .squeeze()
        )
        
        self.data["valid_time"] = self.data["valid_time"].astype(f"datetime64[{self.time_unit}]").astype(float)
        
        time = self.data["valid_time"].to_numpy()
        # expanded_time = np.append(time, [time.max()+pd.Timedelta(1, unit="h").total_seconds(), 1e10])
        expanded_time = np.append(time, [time.max()+1e6, time.max()+1e7])

        self.data = self.data.reindex(
            {"valid_time": expanded_time},
            fill_value=0.
        )
        

class DeterministicHerbieForecast(HerbieForecast):
    def __init__(
        self,
        name: str,
        model: str,
        product: str = None,
        regex: str = None,
        date: Union[Datetime, list[Datetime]] = None,
        fxx: Union[int, list[int]] = [0],
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        time_unit: str = "s",
        verbose: bool = True,
    ):
        super().__init__(name, model, product, regex, date, fxx, min_lon, max_lon, min_lat, max_lat, time_unit, verbose)
        
    def _read_data(self):
        self.data = xr.open_mfdataset(
            list(self.path),
            engine="cfgrib",
            decode_timedelta=False,
            decode_times=True,
            combine="nested",
            concat_dim=["valid_time"],
            # coords="different",
            coords="minimal", # for concatenation compatibility
            compat="no_conflicts",
            preprocess=preprocess, # for concatenation compatibility
        )
        
        
class EnsembleHerbieForecast(HerbieForecast):
    def __init__(
        self,
        name: str,
        model: str,
        product: str,
        regex: str = None,
        date: Union[Datetime, list[Datetime]] = None,
        fxx: Union[int, list[int]] = [0],
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        time_unit: str = "s",
        verbose: bool = True,
    ):
        super().__init__(name, model, product, regex, date, fxx, min_lon, max_lon, min_lat, max_lat, time_unit, verbose)
        self.members = []
        self.m = self.members
    
    def _read_data(self):
        self.data = xr.open_mfdataset(
            list(self.path),
            engine="cfgrib",
            decode_timedelta=False,
            decode_times=True,
            combine="nested",
            concat_dim=["valid_time"],
            # coords="different",
            coords="minimal", # for concatenation compatibility
            compat="no_conflicts",
            preprocess=preprocess, # for concatenation compatibility
            filter_by_keys={"dataType": "pf"},
        )
    
    # TODO rewrite to inherit this method correctly
    def add_interpolator(
        self,
        var_dim: str,
        member_dim: str,
        time_dim: str,
        latitude_dim: str,
        longitude_dim: str,
        var_key: str = None,
        member_slice: slice = slice(None, None, None),
        time_slice: slice = slice(None, None, None),
        latitude_slice: slice = slice(None, None, None),
        longitude_slice: slice = slice(None, None, None),
        method: str = "linear",
        fac: float = 1.0,
    ):
        from casadi import interpolant
        
        if var_key is None:
            var_key = var_dim
        
        coord_dims = [member_dim, time_dim, latitude_dim, longitude_dim]
        coord_slices = [member_slice, time_slice, latitude_slice, longitude_slice]
        
        if var_key in self.var_keys:
            print(f"🟦 {var_key} already in {self.name} interpolators.")
        else:
            x = [self.data.coords[dim].values[sel] for dim, sel in zip(coord_dims, coord_slices)]
    
            # build interpolator f
            f = np.nan_to_num(
                self.data[var_dim].to_numpy().squeeze()[*coord_slices].ravel(order='F'),
                nan=0.
            ) * fac
            
            # build interpolator
            self.interpolators[var_key] = interpolant(
                f"LUT_{var_dim}",
                method,
                x,
                f,
                # jit=True,
            )
            self.var_keys.add(var_key)
            
            print(f"➕ Added {var_key}: {var_dim} to {self.name} interpolators.")

          
class CopernicusForecast(Forecast):
    def __init__(
        self,
        name: str,
        dataset: str,
        variables: Sequence[str],
        date: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        time_unit: str = "s",
        verbose: bool = True,
        compression_level: int = 1,
        engine: str = "netcdf4",
    ):
        self.__USER = _CMEMS_USER
        self.__PWD = _CMEMS_PWD
        
        self.dataset = dataset
        self.variables = variables
        
        self.f99 = end
        
        self._compression_level = compression_level
        self.engine = engine
        
        # TODO how to handle depth properly?
        self.min_depth = 0.49402499198913574
        self.max_depth = 0.49402499198913574
        
        self.output_path = os.path.join(_HOME, "cmems")
        
        super().__init__(name, date, None, min_lon, max_lon, min_lat, max_lat, time_unit, verbose)
        
    def _find_latest(self):
        print(f"📅 Date is not specified. Retrieving latest {self.dataset} {ANSI.orange}NetCDF4 files.{ANSI.reset}")
        return pd.Timestamp.today().normalize()
        
    def _download_data(self):
        
        req = copernicusmarine.subset(
            username=self.__USER,
            password=self.__PWD,
            dataset_id=self.dataset,
            variables=self.variables,
            minimum_longitude=self.min_lon,
            maximum_longitude=self.max_lon,
            minimum_latitude=self.min_lat,
            maximum_latitude=self.max_lat,
            minimum_depth=self.min_depth,
            maximum_depth=self.max_depth,
            start_datetime=self.f00,
            end_datetime=self.f99,
            coordinates_selection_method="strict-inside",
            netcdf_compression_level=self._compression_level,
            disable_progress_bar=not(self.verbose),
            output_directory=self.output_path,
            skip_existing=True, # do not download a new file if already downloaded
            # **kwargs,
        )
        
        self.path = req.file_path
        
    def _read_data(self):
        self.data = xr.open_dataset(self.path, engine=self.engine)
        
    def _convert_data(self):
        self.data["time"] = self.data["time"].astype(f"datetime64[{self.time_unit}]").astype(float)
        
        time = self.data["time"].to_numpy()
        expanded_time = np.append(time, [time.max()+pd.Timedelta(1, unit="h").total_seconds(), 1e10])

        self.data = self.data.reindex(
            {"time": expanded_time},
            fill_value=0.
        )
        
        self.data = self.data.rename({"time": "valid_time"})
        
        
# for images and data not reachable Herbie or another API
# TODO generalize to RasterForecast?
class ECMWFForecast(Forecast):
    def __init__(
        self,
        name: str,
        date: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
    ):
        
        super().__init__(name, date, min_lon, max_lon, min_lat, max_lat)


# TODO: see if it has any interest
class AtmosphericForecast(Forecast):
    def __init__(
        self,
    ):
        super().__init__()
        
        
# TODO: see if it has any interest
class OceanographicForecast(Forecast):
    def __init__(
        self,
    ):
        super().__init__()


if __name__ == "__main__":
    
    # IFS atmospheric data
    fh = DeterministicHerbieForecast("test_herbie", model="ifs", product="oper", regex=r":10[u|v]:", fxx=[0, 3, 6])
    fh.load_data()
    
    fh.add_interpolator("u10", "valid_time", "latitude", "longitude", fac=1.)
    fh("u10", [[fh.data.valid_time[1], 0., 0.]])
    fh.remove_interpolator("u10")
    
    # Mercator SMOC data
    fc = CopernicusForecast("test_copernicus", dataset="cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", variables=["uo"], min_lon=0., max_lon=1., min_lat=0., max_lat=1.,)
    fc.load_data()
    fc.add_interpolator("uo", "valid_time", "latitude", "longitude", latitude_slice=slice(None, None, 2))
    
    # Topography
    t = Topography("topo", min_lon=-80., max_lon=0., min_lat=30., max_lat=60., depth_offset=10.)
    t.load_data()
    t.add_interpolator(
        "distance_to_iso0",
        "latitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
        "longitude_topography_earth2014_egm2008_lmax_2048_lmax_2048",
        var_key="z"
    )

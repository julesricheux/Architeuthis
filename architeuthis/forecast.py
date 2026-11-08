# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 14:02:43 2026

@author: jrich
"""

from __future__ import annotations

import os
import logging

import cdsapi
import requests
import copernicusmarine

import xarray as xr
import pandas as pd
import architeuthis.numpy as np

from herbie.misc import ANSI
from matplotlib.path import Path
from typing import Sequence, Union
from herbie import Herbie, HerbieLatest, FastHerbie
from scipy.ndimage import distance_transform_edt
from architeuthis.toolbox.string_formatting import get_request_id
from architeuthis.common import ArchiteuthisSpatialData, Datetime, _CMEMS_USER, _CMEMS_PWD, _HOME, _TOPOGRAPHY_URL, ensure_cdsapirc, status


logging.getLogger("cdsapi").handlers.clear()
logging.getLogger("copernicusmarine").handlers.clear()


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
        exclusion_zones: Sequence = [], # ExclusionZone objects or lists of [lat, lon] points
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
            "ETOPO_2022_v1_60s_N90W180_surface.nc"
        )
        
    def _download_data(self):
        url = _TOPOGRAPHY_URL
        
        if os.path.exists(self.path):
            status("🗺️ Topography already downloaded.")
        else:
            status("🗺️ Downloading topography...")
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
                status(f"💔 Topography could not be downloaded {e}")

    def _read_data(self):
        self.data = xr.open_dataset(self.path)[["z",]]

    def _convert_data(self):
        # =====================================================================
        # INITIAL CONVERSION
        # =====================================================================
        
        suffix = "z"
        lat = "lat"
        lon = "lon"
    
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
            if len(polygon_coords) < 3:
                # e.g. the iceberg zone when no IIP bulletin could be fetched
                if self.verbose:
                    zone_name = getattr(polygon_coords, "name", "an exclusion zone")
                    status(f"⚠️ Warning: skipping {zone_name}, which has fewer than 3 points.")
                continue
            poly_path = Path(polygon_coords)
            mask_total |= poly_path.contains_points(points).reshape(LATS.shape)
        
        # Apply z value inside exclusion zones
        z_exclude = 1e3
        topo[mask_total] = z_exclude
        
        if self.verbose and mask_total.sum():
            status(f"⛔ Updated {mask_total.sum()} points inside exclusion zones.")
            
        # =====================================================================
        # COMPUTE DISTANCE TO SHORE
        # =====================================================================
        
        white = (topo >= -self.depth_offset)
        black = ~white
        
        dlat_deg = float(np.abs(np.mean(np.diff(LATS_1D))))
        dlon_deg = float(np.abs(np.mean(np.diff(LONS_1D))))
        mean_lat = float(np.mean(LATS_1D))

        NM_PER_DEG_LAT = 60.
        
        # Anisotropic sampling (nm per grid step) so the "which pixel is
        # nearest" search isn't fooled by longitude cells shrinking at
        # higher latitude.
        sampling = (
            dlat_deg * NM_PER_DEG_LAT,
            dlon_deg * NM_PER_DEG_LAT * np.cos(np.radians(mean_lat)),
        )
    
        # dist_to_black = np.sqrt(distance_transform_edt(white))
        dist_to_black = distance_transform_edt(white, sampling=sampling)
        dist_to_white = distance_transform_edt(black, sampling=sampling)
    
        signed_dist_np = np.where(
            white,
            dist_to_black,
            -dist_to_white
        ) + self.z_margin
        
        # signed_dist_np = np.fmax(signed_dist_np, 0.)
    
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
        status(f"📅 Date is not specified. Retrieving latest {self.model.upper()} {ANSI.orange}GRIB2 files.{ANSI.reset}")
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
        status(f"⬇️ Downloading {self.name} data ...")
        self.path = self.__FH.download(self.regex,)
        status("✅ Download completed.")
        
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
        
        
def _regrid_to_lat_lon(data: xr.Dataset, crs, latitude, longitude, skip: int = 5) -> xr.Dataset:
    """
    A dataset on a projected `x`, `y` grid, with 2D `latitude` and `longitude` coordinates,
    interpolated on a regular latitude and longitude grid.

    Args:
        data: The dataset, with `x` and `y` dimensions.
        crs: Coordinate reference system of the projected grid.
        latitude, longitude: The target coordinates.
        skip: Keeps one point out of `skip` of the 2D coordinates to find the extent of the grid.
    """
    import pyproj

    # Geographic lat/lon towards the projected grid
    transformer = pyproj.Transformer.from_crs(pyproj.CRS("EPSG:4326"), crs, always_xy=True)

    x_raw, y_raw = transformer.transform(
        data.longitude[::skip, ::skip],
        data.latitude[::skip, ::skip],
    )

    lon2d, lat2d = np.meshgrid(longitude, latitude)
    x_target, y_target = transformer.transform(lon2d, lat2d)

    # Target points in grid indices
    x_target = (x_target - x_raw.min()) / (x_raw.max() - x_raw.min()) * data.sizes["x"]
    y_target = (y_target - y_raw.min()) / (y_raw.max() - y_raw.min()) * data.sizes["y"]

    coords = {"lat_new": latitude, "lon_new": longitude}
    regridded = data.interp(
        x=xr.DataArray(x_target, dims=("lat_new", "lon_new"), coords=coords),
        y=xr.DataArray(y_target, dims=("lat_new", "lon_new"), coords=coords),
        method="linear",
    )

    return (
        regridded
        .drop_vars(["latitude", "longitude"], errors="ignore")
        .rename({"lat_new": "latitude", "lon_new": "longitude"})
        .transpose("valid_time", "latitude", "longitude")
    )


class HRDPSForecast(DeterministicHerbieForecast):
    """
    The 10 m wind of HRDPS continental, regridded from its rotated grid on a regular latitude
    and longitude grid, as routing requires.

    The positions and the wind speed are right, but not yet the wind direction: the components
    of the files are relative to the rotated grid (`uvRelativeToGrid` = 1) and are not rotated
    here, about 45 deg off around Saint-Pierre-et-Miquelon.

    Args:
        name: Name of the forecast.
        date: Forecast base time. The latest run by default.
        fxx: Lead times, in hours.
        min_lon, max_lon, min_lat, max_lat: Area to keep, inside the area of the model.
        resolution: Step of the regular grid, in degrees. About 2.5 km by default.
    """

    VARIABLES = ("UGRD", "VGRD")
    LEVEL = "AGL-10m"

    def __init__(
        self,
        name: str = "wind_hrdps",
        date: Union[Datetime, list[Datetime]] = None,
        fxx: Union[int, list[int]] = tuple(range(0, 49)),
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        resolution: float = 0.0225,
        time_unit: str = "s",
        verbose: bool = True,
    ):
        self.resolution = resolution

        super().__init__(
            name,
            model="hrdps",
            product="continental",
            date=date,
            fxx=list(fxx),
            min_lon=min_lon,
            max_lon=max_lon,
            min_lat=min_lat,
            max_lat=max_lat,
            time_unit=time_unit,
            verbose=verbose,
        )

    def _find_latest(self):
        # HerbieLatest only looks on AWS and NOMADS by default, and HRDPS is only on the MSC Datamart.
        return HerbieLatest(
            model=self.model,
            product=self.product,
            priority=["msc"],
            variable="TMP",
            level="AGL-2m",
        ).valid_date

    def _locate_data(self):
        pass

    def _download_data(self):
        status(f"⬇️ Downloading {self.name} data ...")
        self.path = [
            FastHerbie(
                [self.f00],
                model=self.model,
                product=self.product,
                fxx=self.fxx,
                variable=variable,
                level=self.LEVEL,
            ).download()
            for variable in self.VARIABLES
        ]
        status("✅ Download completed.")

    def _read_data(self):
        data = xr.merge([
            xr.open_mfdataset(
                paths,
                engine="cfgrib",
                decode_timedelta=False,
                decode_times=True,
                combine="nested",
                concat_dim=["valid_time"],
                coords="different",
                compat="no_conflicts",
            )
            for paths in self.path
        ])

        # The files of the wind do not give the projection of the grid: it is read from another field.
        crs = Herbie(
            self.f00,
            model=self.model,
            product=self.product,
            fxx=0,
            variable="TMP",
            level="AGL-2m",
        ).xarray().herbie.crs

        self.data = _regrid_to_lat_lon(
            data,
            crs,
            np.arange(self.min_lat, self.max_lat + self.resolution, self.resolution),
            np.arange(self.min_lon, self.max_lon + self.resolution, self.resolution),
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
        time_dim: str,
        member_dim: str,
        latitude_dim: str,
        longitude_dim: str,
        var_key: str = None,
        time_slice: slice = slice(None, None, None),
        member_slice: slice = slice(None, None, None),
        latitude_slice: slice = slice(None, None, None),
        longitude_slice: slice = slice(None, None, None),
        method: str = "linear",
        fac: float = 1.0,
    ):
        from casadi import interpolant
        
        if var_key is None:
            var_key = var_dim
        
        # The array is positional: this order must be the one of the data, and of the
        # queries of RoutingAnalysis, (time, member, lat, lon).
        coord_dims = [time_dim, member_dim, latitude_dim, longitude_dim]
        coord_slices = [time_slice, member_slice, latitude_slice, longitude_slice]
        
        if var_key in self.var_keys:
            status(f"🟦 {var_key} already in {self.name} interpolators.")
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
            
            status(f"➕ Added {var_key}: {var_dim} to {self.name} interpolators.")

          
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
        status(f"📅 Date is not specified. Retrieving latest {self.dataset} {ANSI.orange}NetCDF4 files.{ANSI.reset}")
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
        expanded_time = np.append(time, [time.max()+1e6, time.max()+1e7])

        self.data = self.data.reindex(
            {"time": expanded_time},
            fill_value=0.
        )
        
        self.data = self.data.rename({"time": "valid_time"})


class CDSForecast(Forecast):
    def __init__(
        self,
        name: str,
        dataset: str,
        products: Union[str, Sequence[str]],
        variables: Sequence[str],
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        freq: str = "h",
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        time_unit: str = "s",
        verbose: bool = True,
        compression_level: int = 1,
        file_format: str = "grib",
    ):
        if file_format == "netcdf":
            self._ext = "nc"
            self.engine = "netcdf4"
        elif file_format == "grib":
            self._ext = "grib"
            self.engine = "cfgrib"
        else:
            raise(ValueError, f"{name} file_format is {file_format} but should be in ['netcdf', 'grib']")
        
        if type(products) == str:
            products = [products]
        
        self.file_format = file_format
        
        self.dataset = dataset
        self.products = products
        self.variables = variables
        
        self.freq = freq
        
        super().__init__(name, start, None, min_lon, max_lon, min_lat, max_lat, time_unit, verbose)
        
        if end == None:
            self.f99 = self.f00 + pd.Timedelta(1, unit="h")
        else:
            self.f99 = end
        
    def _find_latest(self):
        status(f"📅 Date is not specified. Retrieving latest {self.dataset} {ANSI.orange}NetCDF4 files{ANSI.reset}.")
        return (pd.Timestamp.today() - pd.Timedelta("5d")).floor("6h").normalize()
    
    def _generate_request(self):
        DATE_RANGE = pd.date_range(
            self.f00.floor("h"),
            self.f99.ceil("h"),
            freq=self.freq
        )
        
        self.request = {
            "product_type": self.products,
            "variable": self.variables,
            "year":  sorted(DATE_RANGE.strftime("%Y").unique().tolist()),
            "month": sorted(DATE_RANGE.strftime("%m").unique().tolist()),
            "day":   sorted(DATE_RANGE.strftime("%d").unique().tolist()),
            "time":  sorted(DATE_RANGE.strftime("%H:%M").unique().tolist()),
            "data_format": self.engine,
            "download_format": "unarchived",
            "area": [
                self.max_lat,
                self.min_lon,
                self.min_lat,
                self.max_lon
            ]
        }
    
    def _download_data(self):
        self._generate_request()
        
        local_filename = f"cds_{get_request_id(self.request)}.{self._ext}"
        directory = os.path.join(_HOME, "cds")
        path = os.path.join(directory, local_filename)

        # Check existence locally
        if os.path.exists(path):
            status(f"💾 {self.name} data already downloaded.")
        else:
            status(f"⬇️ Downloading {self.name} data ...")
            # Talk to the server
            os.makedirs(directory, exist_ok=True)
            
            ensure_cdsapirc()
            client = cdsapi.Client()
            client.retrieve(self.dataset, self.request).download(target=path)
            
            status("✅ Download completed.")
            
        self.path = path
        
    def _read_data(self):
        self.data = xr.open_dataset(self.path, engine=self.engine)

    def _convert_data(self):
        self.data = self.data.drop_vars(["valid_time", "step"], errors="ignore")
        self.data["time"] = self.data["time"].astype(f"datetime64[{self.time_unit}]").astype(float)
        
        self.data["longitude"] = ((self.data["longitude"] + 180.) % 360.) - 180.
        self.data = self.data.sortby("time")
        self.data = self.data.sortby("latitude")
        self.data = self.data.sortby("longitude")
        
        self.data = self.data.rename({"time": "valid_time"})
        
    # def _extend_data(self):
    #     time = self.data["valid_time"].to_numpy()
    #     expanded_time = np.append(time, [time.max()+1e6, time.max()+1e7])

    #     self.data = self.data.reindex(
    #         {"valid_time": expanded_time},
    #         fill_value=0.
    #     )
        
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

#%%
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
    t = Topography("topo", min_lon=-80., max_lon=0., min_lat=30., max_lat=60., depth_offset=0.)
    t.load_data()
    t.add_interpolator(
        "distance_to_iso0",
        "lat",
        "lon",
        var_key="z"
    )
    
    # ERA5 Reanalysis
    era5 = CDSForecast(
        "test_era5",
        "reanalysis-era5-single-levels",
        "reanalysis",
        variables=["10m_u_component_of_wind"],
        min_lon=-80.,
        max_lon=0.,
        min_lat=30.,
        max_lat=60.
    )
    era5.load_data()
    
    era5.add_interpolator("u10", "valid_time", "latitude", "longitude",)
    
# -*- coding: utf-8 -*-
"""
Satellite observations, to validate forecasts against them.

ASCAT winds come from EUMETSAT (`EUMETSATASCATData`, the latest swaths)
or from Copernicus Marine (`CopernicusASCATData`, daily gridded swaths,
about a day behind). `ASCATData` takes them in a chosen order and falls
back on the next source when one fails. Both give the same variables.

Geostationary IR images come rendered from map services, with no
account: Meteosat from EUMETView (`EUMETViewData`), GOES and Himawari
from NASA GIBS (`GIBSData`). Their colours are turned back into
brightness temperatures, the common scale, and `GeostationaryImagery`
joins them into one continuous layer.

Created on Thu Jan 29 16:15:59 2026

@author: jrich
"""

import os
import tqdm
import eumdac
import shutil
import zipfile

import requests

import numpy as np
import pandas as pd
import xarray as xr

from typing import Optional, Sequence, Union
from urllib.parse import urlparse
from architeuthis.common import ArchiteuthisSpatialData, Datetime, _HOME, status, to_timestamp
from architeuthis.copernicus import CopernicusMarineData
from architeuthis.credentials import require_credentials
from architeuthis.toolbox import image_utils, wms_utils
from architeuthis.toolbox.geo_utils import central_angle
from architeuthis.toolbox.image_utils import values_to_rgba


class ArchiteuthisSatelliteData(ArchiteuthisSpatialData):
    """
    Base class of the satellite data, over a period and a domain.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        verbose: bool = True,
    ):
        self.start = start
        self.end = end

        super().__init__(name, min_lon, max_lon, min_lat, max_lat, verbose)

    def _inside(self, latitude: xr.DataArray, longitude: xr.DataArray) -> xr.DataArray:
        """
        Whether positions are inside the domain.

        Args:
            latitude: Latitudes, in degrees.
            longitude: Longitudes, in degrees, in [-180, 180).

        Returns:
            Boolean array of the shape of the positions.
        """
        return (
            (latitude >= self.min_lat)
            & (latitude <= self.max_lat)
            & (longitude >= self.min_lon)
            & (longitude <= self.max_lon)
        )


class EUMETSATData(ArchiteuthisSatelliteData):
    """
    Satellite data downloaded from the EUMETSAT Data Store.

    Only the products crossing the domain during the period are
    downloaded, once: their files are kept in `~/data/eumetsat/`.

    Credentials come from `EUMDAC_KEY` and `EUMDAC_SECRET`, the Consumer
    Key and Secret, read from the environment or the credential store
    when downloading (see `architeuthis.credentials`). `EUMDAC_USER`
    and `EUMDAC_PWD` are still read as their former names.

    Args:
        name: Name of this object, used in status messages.
        dataset: Identifier of the EUMETSAT collection.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        dataset: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        verbose: bool = True,
    ):
        self.dataset = dataset

        self.f99 = end

        self.output_path = os.path.join(_HOME, "eumetsat")
        os.makedirs(self.output_path, exist_ok=True)

        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, verbose)

    def _locate_data(self):
        # Read here and not kept on the object, unlike the token, which
        # expires.
        credentials = require_credentials("EUMDAC_KEY", "EUMDAC_SECRET", provider="EUMETSAT")
        self.token = eumdac.AccessToken(credentials)

        self.datastore = eumdac.DataStore(self.token)

        self.collection = self.datastore.get_collection(
            self.dataset
        )

    def _download_data(self):
        self.products = list(self.collection.search(
            bbox=f"{self.min_lon}, {self.min_lat}, {self.max_lon}, {self.max_lat}",
            dtstart=self.start,
            dtend=self.end,
        ))
        if not self.products:
            raise FileNotFoundError(
                f"No product of {self.dataset} over the domain "
                f"between {self.start} and {self.end}."
            )

        self.info(f"🛰️ Download of {len(self.products)} product(s)...")
        downloads = []
        for product in tqdm.tqdm(self.products, disable=not self.verbose):
            with product.open() as source:
                path = os.path.join(self.output_path, source.name)
                if os.path.exists(path):
                    self.info(f"🟦 {source.name} already downloaded.")
                else:
                    # Written aside first, so that an interrupted download
                    # is not taken for a complete one by the next run.
                    with open(path + ".part", "wb") as destination:
                        shutil.copyfileobj(source, destination)
                    os.replace(path + ".part", path)
            downloads.append(path)
        self.info("✅ Downloads completed.")

        self.info("📦 Unzipping downloaded files...")
        self.path = []
        for path in downloads:
            if not zipfile.is_zipfile(path):
                self.path.append(path)
                continue
            with zipfile.ZipFile(path, "r") as archive:
                for member in archive.namelist():
                    if not member.endswith(".nc"):
                        continue
                    out_path = os.path.join(self.output_path, os.path.basename(member))
                    if not os.path.exists(out_path):
                        with archive.open(member) as source, open(out_path, "wb") as destination:
                            shutil.copyfileobj(source, destination)
                    self.path.append(out_path)
        self.info("✅ Finished unzipping.")


class EUMETSATASCATData(EUMETSATData):
    """
    ASCAT winds of EUMETSAT, collection `EO:EUM:DAT:METOP:OSI-104`.

    The OSI SAF coastal winds at 12.5 km of Metop-B and -C, along their
    swaths, a couple of hours after sensing. See `ASCATData` for the
    variables, and to fall back on Copernicus Marine.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        verbose: bool = True,
    ):
        dataset = "EO:EUM:DAT:METOP:OSI-104"

        super().__init__(name, dataset, start, end, min_lon, max_lon, min_lat, max_lat, verbose)

    def _read_data(self):
        self.data = xr.open_mfdataset(
            self.path,
            combine="nested",          # explicit concatenation
            concat_dim="NUMROWS",      # stack along track
            parallel=True,             # use dask
        )

    def _convert_data(self):
        self.data["lon"] = ((self.data["lon"] + 180.) % 360.) - 180.
        self.data["valid_time"] = _epoch_seconds(self.data["time"])

        inside = self._inside(self.data["lat"], self.data["lon"])
        self.data = self.data.where(inside).load()


# TODO find a better class name?
class PoseidonData(EUMETSATData):
    """
    Poseidon-4 Level 2P wind and wave data, `EO:EUM:DAT:0142`.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        verbose: bool = True,
    ):
        dataset = "EO:EUM:DAT:0142"  # Poseidon-4 Level 2P Wind/Wave Products Low Resolution in NRT - Sentinel-6

        super().__init__(name, dataset, start, end, min_lon, max_lon, min_lat, max_lat, verbose)

    def _read_data(self):
        self.data = xr.open_mfdataset(
            self.path
        )

    def _convert_data(self):
        self.data["longitude"] = ((self.data["longitude"] + 180.) % 360.) - 180.

        inside = self._inside(self.data["latitude"], self.data["longitude"])
        self.data = self.data.where(inside).load()


class CopernicusSatelliteData(CopernicusMarineData, ArchiteuthisSatelliteData):
    """
    Satellite data downloaded from Copernicus Marine (CMEMS).

    Only the domain, the period and the variables asked for are
    downloaded, by the server, once: the files are kept in
    `~/data/cmems/`. Each dataset is read as it is.

    Credentials come from `CMEMS_USER` and `CMEMS_PWD`, read from the
    environment or the credential store when downloading (see
    `architeuthis.credentials`), else from `copernicusmarine login`.

    Args:
        name: Name of this object, used in status messages.
        datasets: Identifiers of the CMEMS datasets, or one.
        variables: Variables to download from each dataset.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        verbose: Whether to report progress.
        engine: The xarray engine that reads the files.
    """

    def __init__(
        self,
        name: str,
        datasets: Union[str, Sequence[str]],
        variables: Sequence[str],
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        verbose: bool = True,
        engine: str = "netcdf4",
    ):
        self.datasets = [datasets] if isinstance(datasets, str) else list(datasets)
        self.variables = list(variables)
        self.engine = engine

        self.output_path = os.path.join(_HOME, "cmems")

        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, verbose)

    def _period(self) -> tuple:
        """
        Period to download, as UTC timestamps.

        Returns:
            (start, end), timezone-aware: the toolbox takes naive
            dates as local times.
        """
        return tuple(
            pd.Timestamp(to_timestamp(value), unit="s", tz="UTC")
            for value in (self.start, self.end)
        )

    def _download_data(self):
        start, end = self._period()
        self.info(f"⬇️ Download of {len(self.datasets)} Copernicus Marine dataset(s)...")
        # "inside": observations often stop before the end of the period
        self.path = [
            str(self._subset(dataset, self.variables, start, end, selection="inside"))
            for dataset in self.datasets
        ]

    def _read_data(self):
        self.data = []
        for path in self.path:
            with xr.open_dataset(path, engine=self.engine) as data:
                self.data.append(data.load())


ASCAT_CMEMS_DATASET = "cmems_obs-wind_glo_phy_nrt_l3-{satellite}-ascat-{orbit}-{resolution}deg_P1D-i"


class CopernicusASCATData(CopernicusSatelliteData):
    """
    ASCAT winds of Copernicus Marine, WIND_GLO_PHY_L3_NRT_012_002.

    The swaths of each Metop and orbit direction on a regular grid, one
    dataset each, with one time step per day: the latest day is about
    one day behind, and each cell has its own measurement time. Cells
    measured outside the period are left out. See `ASCATData` for the
    variables.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        verbose: Whether to report progress.
        satellites: Metop satellites, among "metopb" and "metopc".
        orbits: Orbit directions, among "asc" and "des".
        resolution: Grid step, 0.125 or 0.25 deg.
        engine: The xarray engine that reads the files.
    """

    VARIABLES = ["wind_speed", "wind_to_dir", "measurement_time"]

    def __init__(
        self,
        name: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        verbose: bool = True,
        satellites: Sequence[str] = ("metopb", "metopc"),
        orbits: Sequence[str] = ("asc", "des"),
        resolution: float = 0.125,
        engine: str = "netcdf4",
    ):
        datasets = [
            ASCAT_CMEMS_DATASET.format(satellite=satellite, orbit=orbit, resolution=resolution)
            for satellite in satellites
            for orbit in orbits
        ]
        super().__init__(
            name, datasets, self.VARIABLES, start, end,
            min_lon, max_lon, min_lat, max_lat, verbose, engine,
        )

    def _period(self) -> tuple:
        start, end = super()._period()
        # Daily time steps, stamped at midnight
        return start.floor("D"), end

    def _convert_data(self):
        start, end = super()._period()
        swaths = []
        for data in self.data:
            data = data.rename({"time": "day"})
            swaths.append(xr.Dataset({
                "time": data["measurement_time"],
                "wind_speed": data["wind_speed"],
                "wind_dir": data["wind_to_dir"],
            }))
        data = xr.concat(swaths, dim="swath", join="outer")
        data = data.assign_coords(swath=self.datasets)

        # Positions on every cell, in the order of the winds, so that
        # flattened variables match
        dims = data["wind_speed"].dims
        data["lat"] = data["latitude"].broadcast_like(data["wind_speed"]).transpose(*dims)
        data["lon"] = data["longitude"].broadcast_like(data["wind_speed"]).transpose(*dims)
        data["lon"] = ((data["lon"] + 180.) % 360.) - 180.

        start, end = (np.datetime64(value.tz_convert(None)) for value in (start, end))
        measured = (data["time"] >= start) & (data["time"] <= end)
        data = data.where(measured & self._inside(data["lat"], data["lon"]))
        data["valid_time"] = _epoch_seconds(data["time"])
        self.data = data


def _epoch_seconds(time: xr.DataArray) -> xr.DataArray:
    """
    Times as float epoch seconds, NaN where missing.

    Args:
        time: Times, datetime64.

    Returns:
        Float array of the same shape.
    """
    return (time - np.datetime64(0, "s")) / np.timedelta64(1, "s")


ASCAT_SOURCES = {
    "eumetsat": EUMETSATASCATData,
    "cmems": CopernicusASCATData,
}


class ASCATData(ArchiteuthisSatelliteData):
    """
    ASCAT scatterometer winds, from the first source that works.

    The sources are tried in order, among `ASCAT_SOURCES`: by default
    EUMETSAT, the latest swaths, then Copernicus Marine, about a day
    behind, when EUMETSAT fails (missing credentials, server errors, no
    product...). Give `sources="cmems"` to use Copernicus Marine only.
    After `load_data`, `source` is the source used, and `data` holds,
    on dimensions that depend on it:

    - `lat`, `lon`: positions, in degrees, longitudes in [-180, 180).
    - `time`, `valid_time`: measurement times, datetime64 and float
      epoch seconds.
    - `wind_speed`: 10 m equivalent neutral wind speed, in m/s.
    - `wind_dir`: direction the wind blows to, in degrees (not the
      meteorological direction it comes from).

    Measurements outside the domain are NaN.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        verbose: Whether to report progress.
        sources: Keys of `ASCAT_SOURCES` to try, in order, or one.

    Example:
        ascat = ASCATData("ascat", start, end, sources="cmems")
        ascat.load_data()
    """

    def __init__(
        self,
        name: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        verbose: bool = True,
        sources: Union[str, Sequence[str]] = ("eumetsat", "cmems"),
    ):
        self.sources = [sources] if isinstance(sources, str) else list(sources)
        unknown = [source for source in self.sources if source not in ASCAT_SOURCES]
        if unknown or not self.sources:
            raise ValueError(
                f"Unknown ASCAT source(s) {unknown}: choose among {list(ASCAT_SOURCES)}."
            )
        self.source = None

        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, verbose)

    def load_data(self):
        """
        Load the data of the first source that works.

        Raises:
            Exception: The error of the last source, when all fail.
        """
        for index, source in enumerate(self.sources):
            data = ASCAT_SOURCES[source](
                self.name,
                start=self.start,
                end=self.end,
                min_lon=self.min_lon,
                max_lon=self.max_lon,
                min_lat=self.min_lat,
                max_lat=self.max_lat,
                verbose=self.verbose,
            )
            try:
                data.load_data()
            except Exception as error:
                following = self.sources[index + 1:]
                status(
                    f"⚠️ ASCAT from {source} failed ({type(error).__name__}: {error})"
                    + (f", trying {following[0]}." if following else ".")
                )
                if not following:
                    raise
                continue
            self.source = source
            self.path = data.path
            self.data = data.data
            self.info(f"✅ ASCAT from {source}.")
            return


# ------------------------------------------------------------------------------
# Geostationary imagery
# ------------------------------------------------------------------------------

EUMETVIEW_URL = "https://view.eumetsat.int/geoserver/ows"
GIBS_URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
GIBS_COLORMAP_URL = "https://gibs.earthdata.nasa.gov/colormaps/v1.3/{}.xml"

# The common scale of the IR images: brightness temperature, in K, drawn
# from white (cold cloud tops) to black (warm surfaces)
IR_COLORMAP = "gray_r"
IR_RANGE = (200.0, 300.0)

# Grey level g of EUMETView IR images to brightness temperature,
# BT = offset + slope * g, in K. FCI IR 10.5: fitted on 2026-11-19 16:50
# UTC against the FCI L1c radiances of the same scan (EUMETSAT Data
# Tailor), 1.6 million pixels over France: correlation 0.991, residual
# 2 K, from 301 K (black) to 192 K (white).
EUMETVIEW_CALIBRATIONS = {
    "mtg_fd:ir105_hrfi": (301.2, -0.428),
}

# GIBS colormap of each layer (all band 13 layers share it)
GIBS_COLORMAPS = {
    "GOES-East_ABI_Band13_Clean_Infrared": "Clean_Longwave_Infrared_Window_Band",
    "GOES-West_ABI_Band13_Clean_Infrared": "Clean_Longwave_Infrared_Window_Band",
    "Himawari_AHI_Band13_Clean_Infrared": "Clean_Longwave_Infrared_Window_Band",
}

# The GIBS IR colormap draws 195-203 K in the greys of 261-328 K: these
# entries (greys colder than this, in K) are read from their context
GIBS_SECONDARY_BELOW = 210.0

# Longitude of the satellite of each layer, in degrees, by name prefix
SUBSATELLITE_LONGITUDES = {
    "mtg_fd:": 0.0,         # MTG-I1 (Meteosat-12)
    "msg_fes:": 0.0,        # MSG, full Earth scan
    "msg_iodc:": 45.5,      # MSG, Indian Ocean
    "GOES-East_": -75.2,    # GOES-19
    "GOES-West_": -137.0,   # GOES-18
    "Himawari_": 140.7,     # Himawari-9
}


class SatelliteImagery(ArchiteuthisSatelliteData):
    """
    Base class of satellite images on a latitude-longitude grid.

    After `load_data`, `data` holds `bt`, the brightness temperature in
    K, on `valid_time` (float epoch seconds), `latitude` (ascending) and
    `longitude`. Images of every source are thus on one physical scale,
    and `image` draws them on one colour scale.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        resolution: Pixel size, in degrees.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        resolution: float = 0.05,
        verbose: bool = True,
    ):
        self.resolution = resolution

        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, verbose)

    @property
    def size(self) -> tuple[int, int]:
        """
        Size of the images, (width, height) in pixels.
        """
        width = max(1, int(round((self.max_lon - self.min_lon) / self.resolution)))
        height = max(1, int(round((self.max_lat - self.min_lat) / self.resolution)))
        return width, height

    def grid(self) -> tuple[np.ndarray, np.ndarray]:
        """
        Pixel centres of the images.

        Returns:
            (latitude, longitude), in degrees, latitude ascending.
        """
        width, height = self.size
        step_lon = (self.max_lon - self.min_lon) / width
        step_lat = (self.max_lat - self.min_lat) / height
        longitude = self.min_lon + step_lon * (np.arange(width) + 0.5)
        latitude = self.min_lat + step_lat * (np.arange(height) + 0.5)
        return latitude, longitude

    @property
    def bounds(self) -> list[list[float]]:
        """
        Corners `[[south, west], [north, east]]`, as Leaflet takes them.
        """
        return [[self.min_lat, self.min_lon], [self.max_lat, self.max_lon]]

    def times(self) -> pd.DatetimeIndex:
        """
        Times of the loaded images.

        Returns:
            UTC times.
        """
        return pd.to_datetime(self.data["valid_time"].values, unit="s", utc=True)

    def image(
        self,
        time: Union[int, Datetime] = -1,
        colormap: str = IR_COLORMAP,
        vmin: float = IR_RANGE[0],
        vmax: float = IR_RANGE[1],
        transparent_above: Optional[float] = None,
        fade: float = 10.0,
    ) -> np.ndarray:
        """
        One image drawn on the common colour scale, north up.

        Args:
            time: Index of the image, or a time (the nearest image).
            colormap: Matplotlib colormap or its name.
            vmin: Temperature of the first colour, in K.
            vmax: Temperature of the last colour, in K.
            transparent_above: Temperature above which pixels fade out,
                for a cloud layer over a map; None to keep them opaque.
            fade: Range of the fading, in K.

        Returns:
            RGBA array of shape (height, width, 4), uint8, first row
            north, as `imshow` and map overlays take it.
        """
        if not isinstance(time, (int, np.integer)):
            target = to_timestamp(time)
            time = int(np.abs(self.data["valid_time"].values - target).argmin())
        values = self.data["bt"].isel(valid_time=time).values[::-1]
        return values_to_rgba(values, colormap, vmin, vmax, transparent_above, fade)


class WMSImageryData(SatelliteImagery):
    """
    Images of a WMS layer, turned back into the values they show.

    The server crops and renders each image at the requested box,
    resolution and time; the times are those of the layer within the
    period. Images are kept in `~/data/wms/`, downloaded once. Their
    pixels are in `rgba` and, given the palette of the layer, its
    values in `bt` (see `image_utils.invert_palette`).

    Args:
        name: Name of this object, used in status messages.
        url: Endpoint of the WMS server.
        layer: Name of the layer.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        resolution: Pixel size, in degrees.
        time_step: Keep only the times on multiples of this step ("1h"
            for example), None for all the times of the layer.
        palette: (colours, values) of the layer, None if unknown.
        subsatellite_lon: Longitude of the satellite, in degrees, None
            to guess it from the layer name (`SUBSATELLITE_LONGITUDES`).
        style: Style of the layer, "" for its default.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        url: str,
        layer: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        resolution: float = 0.05,
        time_step: Optional[str] = None,
        palette: Optional[tuple] = None,
        subsatellite_lon: Optional[float] = None,
        style: str = "",
        verbose: bool = True,
    ):
        self.url = url
        self.layer = layer
        self.time_step = time_step
        self.palette = palette
        self.secondary = None
        self.style = style
        if subsatellite_lon is None:
            subsatellite_lon = next(
                (lon for prefix, lon in SUBSATELLITE_LONGITUDES.items() if layer.startswith(prefix)),
                None,
            )
        self.subsatellite_lon = subsatellite_lon

        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, resolution, verbose)

        folder = f"{self.min_lon:g}_{self.min_lat:g}_{self.max_lon:g}_{self.max_lat:g}_{self.resolution:g}"
        self.output_path = os.path.join(
            _HOME, "wms", urlparse(url).hostname or "server", layer.replace(":", "_"), folder,
        )

    def _time_extent(self) -> list[str]:
        """
        Time extent of the layer, from the capabilities of the server.

        Returns:
            The values of its time dimension.
        """
        return wms_utils.time_extent(wms_utils.capabilities(self.url), self.layer)

    def _locate_data(self):
        times = wms_utils.available_times(self._time_extent(), self.start, self.end)
        if self.time_step is not None:
            times = times[times == times.floor(self.time_step)]
        if times.empty:
            raise FileNotFoundError(
                f"No image of {self.layer} between {self.start} and {self.end}."
            )
        self.available = times

    def _download_data(self):
        os.makedirs(self.output_path, exist_ok=True)
        bounds = (self.min_lon, self.min_lat, self.max_lon, self.max_lat)
        self.path, kept = [], []
        downloaded = 0
        self.info(f"🛰️ {len(self.available)} image(s) of {self.layer}...")
        for time in tqdm.tqdm(self.available, disable=not self.verbose):
            path = os.path.join(self.output_path, f"{time:%Y%m%dT%H%M%S}.png")
            if not os.path.exists(path):
                content = wms_utils.get_map(self.url, self.layer, bounds, self.size, time, self.style)
                if not image_utils.decode_png(content)[..., 3].any():
                    # Not produced yet, or nothing over the domain: not
                    # cached, so that a later run asks again
                    status(f"⚠️ Empty image of {self.layer} at {time:%Y-%m-%d %H:%M}, left out.")
                    continue
                with open(path + ".part", "wb") as file:
                    file.write(content)
                os.replace(path + ".part", path)
                downloaded += 1
            self.path.append(path)
            kept.append(time)
        if not kept:
            raise FileNotFoundError(f"Every image of {self.layer} is empty over the domain.")
        self.available = pd.DatetimeIndex(kept)
        self.info(f"✅ {downloaded} downloaded, {len(self.path) - downloaded} already there.")

    def _read_data(self):
        frames = []
        for path in self.path:
            with open(path, "rb") as file:
                frames.append(image_utils.decode_png(file.read())[::-1])  # south first
        latitude, longitude = self.grid()
        self.data = xr.Dataset(
            {"rgba": (("valid_time", "latitude", "longitude", "band"), np.stack(frames))},
            coords={
                "valid_time": np.array([time.timestamp() for time in self.available]),
                "latitude": latitude,
                "longitude": longitude,
                "band": list("RGBA"),
            },
        )

    def _convert_data(self):
        if self.palette is None:
            status(f"⚠️ No palette for {self.layer}: its pixels are in rgba only.")
            return
        self.data["bt"] = (
            ("valid_time", "latitude", "longitude"),
            image_utils.invert_palette(self.data["rgba"].values, *self.palette, secondary=self.secondary).astype(np.float32),
        )


class EUMETViewData(WMSImageryData):
    """
    Meteosat images of EUMETView, the map service of EUMETSAT.

    No account. The default layer is MTG FCI IR 10.5 um, every 10 min
    since 2024-09, a few minutes after the scan, covering 70 deg around
    the satellite at 0 deg. Its grey levels are turned into brightness
    temperatures with `EUMETVIEW_CALIBRATIONS`; a layer without one
    gives `rgba` only.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        resolution: Pixel size, in degrees.
        time_step: Keep only the times on multiples of this step, None
            for every image.
        layer: Name of the EUMETView layer.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        resolution: float = 0.05,
        time_step: Optional[str] = None,
        layer: str = "mtg_fd:ir105_hrfi",
        verbose: bool = True,
    ):
        calibration = EUMETVIEW_CALIBRATIONS.get(layer)
        palette = None if calibration is None else image_utils.linear_gray_palette(*calibration)
        super().__init__(
            name, EUMETVIEW_URL, layer, start, end, min_lon, max_lon, min_lat, max_lat,
            resolution, time_step, palette, verbose=verbose,
        )


class GIBSData(WMSImageryData):
    """
    GOES and Himawari images of NASA GIBS.

    GIBS (Global Imagery Browse Services) needs no account. The default
    layer is GOES-East ABI band 13 (10.3 um), every 10 min over about
    90 days, at 2 km, with an hour or so of delay; GIBS has no
    Meteosat. The published colormap of the layer
    (`GIBS_COLORMAPS`) turns its colours into brightness temperatures.
    GIBS resamples with interpolation, so a tenth of the pixels blend
    two colours: exact enough on the grey part of the scale (above
    about 250 K), approximate on the coloured cloud tops. The colormap
    draws 195-203 K in the greys of 261-328 K: such pixels take the
    reading closest to their neighbours (`GIBS_SECONDARY_BELOW`). The
    times come from the DescribeDomains of GIBS, more up to date than
    its WMS capabilities.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        resolution: Pixel size, in degrees.
        time_step: Keep only the times on multiples of this step, None
            for every image.
        layer: Name of the GIBS layer.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        resolution: float = 0.05,
        time_step: Optional[str] = None,
        layer: str = "GOES-East_ABI_Band13_Clean_Infrared",
        verbose: bool = True,
    ):
        super().__init__(
            name, GIBS_URL, layer, start, end, min_lon, max_lon, min_lat, max_lat,
            resolution, time_step, verbose=verbose,
        )

    def _time_extent(self) -> list[str]:
        """
        Time extent of the layer over the period, from DescribeDomains.

        Falls back on the capabilities, which may lag, if it fails or if
        the period is open.

        Returns:
            The values of its time dimension.
        """
        if self.start is None or self.end is None:
            return super()._time_extent()
        try:
            return wms_utils.gibs_time_domain(self.layer, self.start, self.end)
        except requests.RequestException as error:
            status(f"⚠️ GIBS DescribeDomains failed ({error}), reading the capabilities.")
            return super()._time_extent()

    def _locate_data(self):
        super()._locate_data()
        colormap = GIBS_COLORMAPS.get(self.layer)
        if colormap is not None and self.palette is None:
            response = requests.get(GIBS_COLORMAP_URL.format(colormap), timeout=wms_utils.TIMEOUT)
            response.raise_for_status()
            self.palette = wms_utils.parse_gibs_colormap(response.text)
            colours, values = self.palette
            grey = np.ptp(colours.astype(int), axis=1) == 0
            self.secondary = grey & (values < GIBS_SECONDARY_BELOW)


class GeostationaryImagery(SatelliteImagery):
    """
    One continuous IR image from several geostationary satellites.

    Each pixel is taken from the satellite that sees it the most
    directly (the smallest angle from its sub-satellite point), and the
    images are blended over a few degrees along the seams, so that the
    layer has no visible edge. Where a satellite has no value, outside
    its disk say, the others fill in. By default, Meteosat (EUMETView,
    MTG FCI at 0 deg) and GOES-East (GIBS, at 75.2 W) cover the North
    Atlantic from the Americas to Europe, every 10 min.

    `data` then holds `bt` on the times of every source (`complete`) or
    of any, and `weight`, the share of each source in each pixel. A
    source that fails to load is left out, with a warning.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        resolution: Pixel size, in degrees.
        time_step: Keep only the times on multiples of this step, None
            for every image.
        sources: `WMSImageryData` objects to combine, None for
            EUMETView and GIBS over this domain and period.
        seam_width: Width of the blending along the seams, in degrees of
            viewing angle.
        complete: Keep only the times every source has, so that no
            image misses a part; else the times any source has.
        verbose: Whether to report progress.

    Example:
        clouds = GeostationaryImagery("clouds", start, end,
                                      -75, 5, 35, 60)
        clouds.load_data()
        rgba = clouds.image(-1, transparent_above=270)
    """

    def __init__(
        self,
        name: str,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        resolution: float = 0.05,
        time_step: Optional[str] = None,
        sources: Optional[Sequence[WMSImageryData]] = None,
        seam_width: float = 2.0,
        complete: bool = True,
        verbose: bool = True,
    ):
        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, resolution, verbose)

        if sources is None:
            common = dict(
                start=start, end=end, min_lon=min_lon, max_lon=max_lon, min_lat=min_lat,
                max_lat=max_lat, resolution=resolution, time_step=time_step, verbose=verbose,
            )
            sources = [EUMETViewData(f"{name}_eumetview", **common), GIBSData(f"{name}_gibs", **common)]
        self.sources = list(sources)
        self.seam_width = seam_width
        self.complete = complete

    def _download_data(self):
        loaded = []
        for index, source in enumerate(self.sources):
            try:
                source.load_data()
                if "bt" not in source.data:
                    raise ValueError(f"{source.layer} has no brightness temperature.")
            except Exception as error:
                status(f"⚠️ Imagery from {source.name} left out ({type(error).__name__}: {error}).")
                if not loaded and index == len(self.sources) - 1:
                    raise
                continue
            loaded.append(source)
        self.loaded = loaded

    def _convert_data(self):
        times = [set(source.data["valid_time"].values) for source in self.loaded]
        times = set.intersection(*times) if self.complete else set.union(*times)
        if not times:
            raise ValueError("The sources have no time in common: try complete=False.")
        times = np.array(sorted(times))

        latitude, longitude = self.grid()
        layers = []
        for source in self.loaded:
            bt = source.data["bt"].reindex(valid_time=times)
            if bt.sizes["latitude"] != latitude.size or not np.allclose(bt["longitude"], longitude):
                bt = bt.interp(latitude=latitude, longitude=longitude, method="nearest")
            layers.append(bt.values)

        lat, lon = np.meshgrid(latitude, longitude, indexing="ij")
        angles = [
            np.zeros_like(lat) if source.subsatellite_lon is None
            else central_angle(lat, lon, 0.0, source.subsatellite_lon)
            for source in self.loaded
        ]
        weights = image_utils.softmin_weights(angles, self.seam_width)

        self.data = xr.Dataset(
            {
                "bt": (
                    ("valid_time", "latitude", "longitude"),
                    image_utils.blend(layers, weights[:, None]).astype(np.float32),
                ),
                "weight": (("source", "latitude", "longitude"), weights.astype(np.float32)),
            },
            coords={
                "valid_time": times,
                "latitude": latitude,
                "longitude": longitude,
                "source": [source.name for source in self.loaded],
            },
        )


if __name__=="__main__":
    import datetime
    import numpy as np
    import matplotlib.pyplot as plt
    
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    
    # TODO concatenate into Architeuthis class
    
    dataset = "EO:EUM:DAT:METOP:OSI-104" # ASCAT
    # dataset = "EO:EUM:DAT:0142" # Poseidon-4 Level 2P Wind/Wave Products Low Resolution in NRT - Sentinel-6
    # dataset = "EO:EUM:DAT:0143" # Poseidon-4 Level 3 Wind/Wave Products Low Resolution in NRT - Sentinel-6 NOT WORKING

    # You can also use a bounding box (W, S, E, N) instead of geometry
    # bounding_box = '-80, 30, 0, 60'
    
    end = datetime.datetime.now()
    start = end - datetime.timedelta(hours=12)
    
    # sat = EUMETSATData(
    #     "sat_test", dataset, start=start, end=end,
    #     min_lon=-80., max_lon=0., min_lat=30., max_lat=60.,
    # )
    # sat.load_data()
    
    altimetry = PoseidonData(
        "alti_test", start=start, end=end,
        min_lon=-80., max_lon=0., min_lat=30., max_lat=60.,
    )
    altimetry.load_data()
    
    ascat = ASCATData(
        "ascat_test", start=start, end=end,
        min_lon=-80., max_lon=0., min_lat=30., max_lat=60.,
    )
    ascat.load_data()

    
    #%%
    
    # ds = sat.data
    
    ascat_ds = ascat.data
    
    
    lat = ascat_ds["lat"].values
    lon = ascat_ds["lon"].values
    tim = ascat_ds["time"].values
    
    
    wind_speed = ascat_ds["wind_speed"].values       # m/s
    wind_dir = ascat_ds["wind_dir"].values           # degrees, where the wind goes
    
    # -----------------------------
    # Convert wind direction to u, v
    # -----------------------------
    theta = np.deg2rad(wind_dir)
    
    u = wind_speed * np.sin(theta)   # eastward
    v = wind_speed * np.cos(theta)   # northward
    
    
    # -----------------------------
    # Subsample to avoid clutter
    # -----------------------------
    step = 8   # adjust depending on density
    
    lat_q = lat[::step, ::step]
    lon_q = lon[::step, ::step]
    u_q   = u[::step, ::step]
    v_q   = v[::step, ::step]
    spd_q = wind_speed[::step, ::step]
    
    
    # -----------------------------
    # Plot
    # -----------------------------
    fig = plt.figure(figsize=(10, 10))
    ax = plt.axes(projection=ccrs.PlateCarree())
    
    ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
    ax.add_feature(cfeature.BORDERS, linewidth=0.5)
    ax.gridlines(draw_labels=True)
    
    q = ax.quiver(
    # q = ax.barbs(
        lon_q,
        lat_q,
        u_q,
        v_q,
        spd_q,
        transform=ccrs.PlateCarree(),
        scale=700,
        cmap="viridis",
        # length=3.5,  
        width=0.002
    )
    

    # cb = plt.colorbar(q, ax=ax, orientation="vertical", pad=0.02)
    # cb.set_label("Wind speed [m s$^{-1}$]")
    
    ax.set_title(f"ASCAT winds from {ascat.source}")
    
    ax.set_extent([ascat.min_lon, ascat.max_lon, ascat.min_lat, ascat.max_lat], crs=ccrs.PlateCarree())

    
    # plt.show()
    
    alti_ds = altimetry.data
    
    # -----------------------------
    # Extract variables (1D track)
    # -----------------------------
    lat = alti_ds["latitude"].values[::step]
    lon = alti_ds["longitude"].values[::step]
    swh = alti_ds["swh"].values[::step]
    time = alti_ds["time"].values[::step]

    # -----------------------------
    # Optional quality filtering
    # -----------------------------
    if "validation_flag" in alti_ds:
        good = alti_ds["validation_flag"].values[::step] == 0
        lat = lat[good]
        lon = lon[good]
        swh = swh[good]

    # -----------------------------
    # Plot
    # -----------------------------
    # fig = plt.figure(figsize=(10, 10))
    # ax = plt.axes(projection=ccrs.PlateCarree())

    ax.add_feature(cfeature.COASTLINE, linewidth=0.8)
    ax.add_feature(cfeature.BORDERS, linewidth=0.5)
    gl = ax.gridlines(draw_labels=True)
    gl.top_labels = False
    gl.right_labels = False

    sc = ax.scatter(
        lon,
        lat,
        c=swh,
        s=8,
        cmap="plasma",
        transform=ccrs.PlateCarree(),
    )

    # cb = plt.colorbar(sc, ax=ax, pad=0.02)
    # cb.set_label("Significant Wave Height [m]")

    # a = alti_ds.attrs
    # ax.set_title(
    #     f"SWH (Altimeter L2P)\n"
    #     f"{a.get('platform', '')} | "
    #     f"{a.get('first_meas_time', '')} – {a.get('last_meas_time', '')}"
    # )

    plt.show()

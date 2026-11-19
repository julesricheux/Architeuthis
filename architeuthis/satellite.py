# -*- coding: utf-8 -*-
"""
Satellite observations, to validate forecasts against them.

ASCAT winds come from EUMETSAT (`EUMETSATASCATData`, the latest swaths)
or from Copernicus Marine (`CopernicusASCATData`, daily gridded swaths,
about a day behind). `ASCATData` takes them in a chosen order and falls
back on the next source when one fails. Both give the same variables.

Geostationary infrared and visible images come rendered from map
services, with no account: Meteosat from EUMETView (`EUMETViewData`),
GOES and Himawari from NASA GIBS (`GIBSData`). Their colours are turned
back into a common scale, brightness temperatures for the infrared and
a brightness from 0 to 1 for the visible, `GeostationaryImagery` joins
them into one continuous layer. The channels to download are chosen as
the variables of a forecast, "ir" or "visible" (`IMAGERY_CHANNELS`),
and `image` draws one with a colour scale of Windy chosen when drawing
(`windy_colormaps.SATELLITE_STOPS`).

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
from architeuthis.toolbox.windy_colormaps import get_satellite_cmap


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

# Channels to choose from, as the variables of a forecast: the infrared,
# day and night, and the visible, by day. They are the only single
# channels that both EUMETView and GIBS serve (2026-11): EUMETView also
# has the MSG water vapour (msg_fes:wv062) but GIBS none of GOES, and the
# other layers of both are colour composites (GeoColor, dust, fire, air
# mass). Quantity of each channel in `data`, on a scale common to every
# source: brightness temperature in K, brightness from 0 (black) to 1.
IMAGERY_CHANNELS = {
    "ir": "bt",
    "visible": "brightness",
}

# Colour scale drawing each channel by default, among those of its
# quantity (`windy_colormaps.SATELLITE_QUANTITIES`): Infra+ for the
# infrared ("blue" is the other), the camera image for the visible
IMAGERY_COLORMAPS = {
    "ir": "infra",
    "visible": "visible",
}

# Layer of each source per channel, on its map server
EUMETVIEW_LAYERS = {
    "ir": "mtg_fd:ir105_hrfi",       # MTG FCI 10.5 um, 2 km
    "visible": "mtg_fd:vis06_hrfi",  # MTG FCI 0.6 um, 1 km
}
GIBS_LAYERS = {
    "ir": "GOES-East_ABI_Band13_Clean_Infrared",       # ABI 10.3 um, 2 km
    "visible": "GOES-East_ABI_Band2_Red_Visible_1km",  # ABI 0.64 um, 1 km
}

# Grey level g of EUMETView images to their value, offset + slope * g.
# FCI IR 10.5, in K: fitted on 2026-11-19 16:50 UTC against the FCI L1c
# radiances of the same scan (EUMETSAT Data Tailor), 1.6 million pixels
# over France: correlation 0.991, residual 2 K, from 301 K (black) to
# 192 K (white). Visible: the grey level itself, from 0 to 1.
EUMETVIEW_CALIBRATIONS = {
    "mtg_fd:ir105_hrfi": (301.2, -0.428),
    "mtg_fd:vis06_hrfi": (0.0, 1.0 / 255.0),
}

# GIBS colormap of each IR layer (all band 13 layers share it); the
# visible layers are grey levels, read from 0 to 1
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

# Pixels that both sources weigh at least this much in a composite: the
# band along the seam where their levels are matched
MATCH_WEIGHT = 0.05


def imagery_channels(channels: Union[str, Sequence[str]]) -> list[str]:
    """
    Imagery channels, checked, in order and without duplicates.

    Args:
        channels: A key of `IMAGERY_CHANNELS` or a list of them.

    Returns:
        The list of channels.

    Example:
        imagery_channels(["ir", "visible"])
    """
    channels = [channels] if isinstance(channels, str) else list(channels)
    unknown = [channel for channel in channels if channel not in IMAGERY_CHANNELS]
    if unknown or not channels:
        raise ValueError(f"Unknown imagery channel(s) {unknown}: choose among {list(IMAGERY_CHANNELS)}.")
    return list(dict.fromkeys(channels))


class SatelliteImagery(ArchiteuthisSatelliteData):
    """
    Base class of satellite images on a latitude-longitude grid.

    The channels to load are chosen as the variables of a forecast: "ir",
    "visible" (`IMAGERY_CHANNELS`). After `load_data`, `data` holds the
    quantity of each (`variables`): `bt`, the brightness temperature in
    K, for "ir", and `brightness`, from 0 to 1, for "visible", on
    `valid_time` (float epoch seconds), `latitude` (ascending) and
    `longitude`. Images of every source are thus on one scale. How they
    look is chosen when drawing: `image` draws a channel with a colour
    scale of Windy.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        resolution: Pixel size, in degrees.
        channels: Channel or channels: "ir" (day and night), "visible"
            (by day).
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
        channels: Union[str, Sequence[str]] = "ir",
        verbose: bool = True,
    ):
        self.resolution = resolution
        self.channels = imagery_channels(channels)

        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, verbose)

    @property
    def variables(self) -> list[str]:
        """
        Names of the quantities of the channels in `data`.
        """
        return [IMAGERY_CHANNELS[channel] for channel in self.channels]

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
        channel: Optional[str] = None,
        colormap: Optional[str] = None,
        transparent_above: Optional[float] = None,
        transparent_below: Optional[float] = None,
        fade: Optional[float] = None,
    ) -> np.ndarray:
        """
        One image of a channel, with a colour scale of Windy, north up.

        Args:
            time: Index of the image, or a time (the nearest image).
            channel: "ir" or "visible", among the loaded ones; None for
                the first of `channels`.
            colormap: Colour scale of the quantity of the channel
                (`windy_colormaps.SATELLITE_STOPS`): "infra" (Infra+)
                or "blue" (Blue, clear sky transparent) for "ir",
                "visible" for "visible"; None for the default of the
                channel (`IMAGERY_COLORMAPS`).
            transparent_above: Value above which pixels fade out, the
                warm clear sky of an infrared cloud layer over a map;
                None to keep the transparency of the colour scale.
            transparent_below: Value below which pixels fade out, the
                dark sea of a visible cloud layer; None to keep the
                transparency of the colour scale.
            fade: Range of the fading, None for a tenth of the scale.

        Returns:
            RGBA array of shape (height, width, 4), uint8, first row
            north, as `imshow` and map overlays take it.

        Example:
            rgba = clouds.image(-1, "ir", colormap="blue")
        """
        channel = self.channels[0] if channel is None else imagery_channels(channel)[0]
        variable = IMAGERY_CHANNELS[channel]
        if variable not in self.data:
            raise ValueError(f"The {channel} channel is not loaded: add it to the channels.")
        colormap = IMAGERY_COLORMAPS[channel] if colormap is None else colormap
        colormap, norm = get_satellite_cmap(colormap, quantity=variable)
        if not isinstance(time, (int, np.integer)):
            target = to_timestamp(time)
            time = int(np.abs(self.data["valid_time"].values - target).argmin())
        values = self.data[variable].isel(valid_time=time).values[::-1]
        fade = (norm.vmax - norm.vmin) / 10.0 if fade is None else fade
        return values_to_rgba(values, colormap, norm.vmin, norm.vmax, transparent_above, fade, transparent_below)


class WMSImageryData(SatelliteImagery):
    """
    Images of a WMS server, turned back into the values they show.

    One server layer per channel (`wms_layers`).
    The server crops and renders each image at the requested box,
    resolution and time; the times are those every channel has within
    the period. Images are kept in `~/data/wms/`, downloaded once; an
    empty image, not produced yet, is left out. Their pixels are in
    `rgba_<channel>` and, given the palette of the server layer, their
    values in the quantity of the channel (see
    `image_utils.invert_palette`).

    Args:
        name: Name of this object, used in status messages.
        url: Endpoint of the WMS server.
        wms_layers: Name of the server layer of each channel, as
            `{"ir": ..., "visible": ...}`.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        resolution: Pixel size, in degrees.
        time_step: Keep only the times on multiples of this step ("1h"
            for example), None for all the times of the layer.
        channels: Channel or channels, "ir", "visible".
        palettes: (colours, values) of each channel, None if unknown.
        subsatellite_lon: Longitude of the satellite, in degrees, None
            to guess it from the server layer names
            (`SUBSATELLITE_LONGITUDES`).
        style: Style of the server layers, "" for their default.
        verbose: Whether to report progress.
    """

    def __init__(
        self,
        name: str,
        url: str,
        wms_layers: dict,
        start: Union[Datetime, list[Datetime]] = None,
        end: Union[Datetime, list[Datetime]] = None,
        min_lon: float = -180.,
        max_lon: float = 180.,
        min_lat: float = -90.,
        max_lat: float = 90.,
        resolution: float = 0.05,
        time_step: Optional[str] = None,
        channels: Union[str, Sequence[str]] = "ir",
        palettes: Optional[dict] = None,
        subsatellite_lon: Optional[float] = None,
        style: str = "",
        verbose: bool = True,
    ):
        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, resolution, channels, verbose)

        missing = [channel for channel in self.channels if channel not in wms_layers]
        if missing:
            raise ValueError(f"{name} has no server layer for the {missing} channel(s).")
        self.url = url
        self.wms_layers = {channel: wms_layers[channel] for channel in self.channels}
        self.time_step = time_step
        self.palettes = {channel: (palettes or {}).get(channel) for channel in self.channels}
        self.secondary = {channel: None for channel in self.channels}
        self.style = style
        if subsatellite_lon is None:
            subsatellite_lon = next(
                (
                    lon for prefix, lon in SUBSATELLITE_LONGITUDES.items()
                    for layer in self.wms_layers.values() if layer.startswith(prefix)
                ),
                None,
            )
        self.subsatellite_lon = subsatellite_lon
        self.output_path = os.path.join(_HOME, "wms", urlparse(url).hostname or "server")

    def _folder(self, channel: str) -> str:
        """
        Folder of the images of a channel, by server layer and box.

        Args:
            channel: "ir" or "visible".

        Returns:
            The path.
        """
        box = f"{self.min_lon:g}_{self.min_lat:g}_{self.max_lon:g}_{self.max_lat:g}_{self.resolution:g}"
        return os.path.join(self.output_path, self.wms_layers[channel].replace(":", "_"), box)

    def _time_extent(self, channel: str) -> list[str]:
        """
        Time extent of a server layer, from the capabilities.

        Args:
            channel: "ir" or "visible".

        Returns:
            The values of its time dimension.
        """
        if getattr(self, "_capabilities", None) is None:
            self._capabilities = wms_utils.capabilities(self.url)
        return wms_utils.time_extent(self._capabilities, self.wms_layers[channel])

    def _locate_data(self):
        self._capabilities = None
        self.available = {}
        for channel, layer in self.wms_layers.items():
            times = wms_utils.available_times(self._time_extent(channel), self.start, self.end)
            if self.time_step is not None:
                times = times[times == times.floor(self.time_step)]
            if times.empty:
                raise FileNotFoundError(f"No image of {layer} between {self.start} and {self.end}.")
            self.available[channel] = times

    def _download_data(self):
        bounds = (self.min_lon, self.min_lat, self.max_lon, self.max_lat)
        kept = {}
        for channel, layer in self.wms_layers.items():
            folder = self._folder(channel)
            os.makedirs(folder, exist_ok=True)
            kept[channel] = {}
            downloaded = 0
            self.info(f"🛰️ {len(self.available[channel])} image(s) of {layer}...")
            for time in tqdm.tqdm(self.available[channel], disable=not self.verbose):
                path = os.path.join(folder, f"{time:%Y%m%dT%H%M%S}.png")
                if not os.path.exists(path):
                    content = wms_utils.get_map(self.url, layer, bounds, self.size, time, self.style)
                    if not image_utils.decode_png(content)[..., 3].any():
                        # Not produced yet, or nothing over the domain: not
                        # cached, so that a later run asks again
                        status(f"⚠️ Empty image of {layer} at {time:%Y-%m-%d %H:%M}, left out.")
                        continue
                    with open(path + ".part", "wb") as file:
                        file.write(content)
                    os.replace(path + ".part", path)
                    downloaded += 1
                kept[channel][time] = path
            if not kept[channel]:
                raise FileNotFoundError(f"Every image of {layer} is empty over the domain.")
            self.info(f"✅ {downloaded} downloaded, {len(kept[channel]) - downloaded} already there.")

        # The times every channel has
        times = sorted(set.intersection(*(set(paths) for paths in kept.values())))
        if not times:
            raise FileNotFoundError(f"The channels of {self.name} have no time in common.")
        self.times_kept = pd.DatetimeIndex(times)
        self.path = {channel: [paths[time] for time in times] for channel, paths in kept.items()}

    def _read_data(self):
        latitude, longitude = self.grid()
        variables = {}
        for channel, paths in self.path.items():
            frames = []
            for path in paths:
                with open(path, "rb") as file:
                    frames.append(image_utils.decode_png(file.read())[::-1])  # south first
            variables[f"rgba_{channel}"] = (("valid_time", "latitude", "longitude", "band"), np.stack(frames))
        self.data = xr.Dataset(
            variables,
            coords={
                "valid_time": np.array([time.timestamp() for time in self.times_kept]),
                "latitude": latitude,
                "longitude": longitude,
                "band": list("RGBA"),
            },
        )

    def _convert_data(self):
        for channel, layer in self.wms_layers.items():
            palette = self.palettes[channel]
            if palette is None:
                status(f"⚠️ No palette for {layer}: its pixels are in rgba_{channel} only.")
                continue
            values = image_utils.invert_palette(
                self.data[f"rgba_{channel}"].values, *palette, secondary=self.secondary[channel],
            )
            self.data[IMAGERY_CHANNELS[channel]] = (("valid_time", "latitude", "longitude"), values.astype(np.float32))


class EUMETViewData(WMSImageryData):
    """
    Meteosat images of EUMETView, the map service of EUMETSAT.

    No account. The server layers are those of MTG FCI
    (`EUMETVIEW_LAYERS`): IR 10.5 um and visible 0.6 um, every 10 min
    since 2024-09, a few minutes after the scan, covering 70 deg around
    the satellite at 0 deg. Their grey levels are turned into values
    with `EUMETVIEW_CALIBRATIONS`; a layer without one gives its pixels
    only.

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
        channels: Channel or channels, "ir", "visible".
        wms_layers: Server layer of each channel, None for
            `EUMETVIEW_LAYERS`.
        verbose: Whether to report progress.

    Example:
        meteosat = EUMETViewData("meteosat", start, end,
                                 -20, 10, 40, 55,
                                 channels=["ir", "visible"])
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
        channels: Union[str, Sequence[str]] = "ir",
        wms_layers: Optional[dict] = None,
        verbose: bool = True,
    ):
        wms_layers = EUMETVIEW_LAYERS | (wms_layers or {})
        palettes = {
            channel: image_utils.linear_gray_palette(*EUMETVIEW_CALIBRATIONS[layer])
            for channel, layer in wms_layers.items() if layer in EUMETVIEW_CALIBRATIONS
        }
        super().__init__(
            name, EUMETVIEW_URL, wms_layers, start, end, min_lon, max_lon, min_lat, max_lat,
            resolution, time_step, channels, palettes, verbose=verbose,
        )


class GIBSData(WMSImageryData):
    """
    GOES and Himawari images of NASA GIBS.

    GIBS (Global Imagery Browse Services) needs no account. The server
    layers are those of GOES-East ABI (`GIBS_LAYERS`): band 13 (IR 10.3
    um, 2 km) and band 2 (visible 0.64 um, 1 km), every 10 min over
    about 90 days, with an hour or so of delay; GIBS has no Meteosat.
    The visible layers are grey levels, read from 0 to 1. The published
    colormap of an IR layer (`GIBS_COLORMAPS`) turns its colours into
    brightness temperatures. GIBS resamples with interpolation, so a
    tenth of the pixels blend two colours: exact enough on the grey
    part of the scale (above about 250 K), approximate on the coloured
    cloud tops. The colormap draws 195-203 K in the greys of 261-328 K:
    such pixels take the reading closest to their neighbours
    (`GIBS_SECONDARY_BELOW`). The times come from the DescribeDomains
    of GIBS, more up to date than its WMS capabilities.

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
        channels: Channel or channels, "ir", "visible".
        wms_layers: Server layer of each channel, None for
            `GIBS_LAYERS`; GOES-West or Himawari for example.
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
        channels: Union[str, Sequence[str]] = "ir",
        wms_layers: Optional[dict] = None,
        verbose: bool = True,
    ):
        wms_layers = GIBS_LAYERS | (wms_layers or {})
        palettes = {"visible": image_utils.linear_gray_palette(0.0, 1.0 / 255.0)}
        super().__init__(
            name, GIBS_URL, wms_layers, start, end, min_lon, max_lon, min_lat, max_lat,
            resolution, time_step, channels, palettes, verbose=verbose,
        )

    def _time_extent(self, channel: str) -> list[str]:
        """
        Time extent of a server layer, from GIBS DescribeDomains.

        Falls back on the capabilities, which may lag, if it fails or if
        the period is open.

        Args:
            channel: "ir" or "visible".

        Returns:
            The values of its time dimension.
        """
        if self.start is None or self.end is None:
            return super()._time_extent(channel)
        try:
            return wms_utils.gibs_time_domain(self.wms_layers[channel], self.start, self.end)
        except requests.RequestException as error:
            status(f"⚠️ GIBS DescribeDomains failed ({error}), reading the capabilities.")
            return super()._time_extent(channel)

    def _locate_data(self):
        super()._locate_data()
        for channel, layer in self.wms_layers.items():
            colormap = GIBS_COLORMAPS.get(layer)
            if colormap is None or self.palettes[channel] is not None:
                continue
            response = requests.get(GIBS_COLORMAP_URL.format(colormap), timeout=wms_utils.TIMEOUT)
            response.raise_for_status()
            colours, values = wms_utils.parse_gibs_colormap(response.text)
            self.palettes[channel] = (colours, values)
            grey = np.ptp(colours.astype(int), axis=1) == 0
            self.secondary[channel] = grey & (values < GIBS_SECONDARY_BELOW)


class GeostationaryImagery(SatelliteImagery):
    """
    One continuous image from several geostationary satellites.

    The channels are chosen as the variables of a forecast: "ir" or
    "visible", or both (`IMAGERY_CHANNELS`). Each pixel is
    taken from the satellite that sees it the most directly (the
    smallest angle from its sub-satellite point), and the images are
    blended over a few degrees along the seams, so that the layer has
    no visible edge. Where a satellite has no value, outside its disk
    say, the others fill in. By default, Meteosat (EUMETView, MTG FCI
    at 0 deg) and GOES-East (GIBS, at 75.2 W) cover the North Atlantic
    from the Americas to Europe, every 10 min.

    Infrared images agree as they are, in K. Visible ones do not: the
    brightness of a scene depends on the angles of the sun and of the
    satellite, so each image of the other sources is put on the levels
    of the first one along the seam (`match`,
    `image_utils.quantile_fit`), giving `gain` and `offset`.

    `data` then holds the quantity of each channel (`variables`) on the
    times of every source (`complete`) or of any, `weight`, the share
    of each source in each pixel, and `gain` and `offset`. A source
    that fails to load is left out, with a warning.

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
        channels: Channel or channels: "ir" (day and night), "visible"
            (by day).
        sources: `WMSImageryData` objects to combine, None for
            EUMETView and GIBS over this domain, period and channels.
        seam_width: Width of the blending along the seams, in degrees of
            viewing angle.
        complete: Keep only the times every source has, so that no
            image misses a part; else the times any source has.
        match: Match the levels of the sources along the seam, None for
            the visible only.
        verbose: Whether to report progress.

    Example:
        clouds = GeostationaryImagery("clouds", start, end,
                                      -75, 5, 35, 60,
                                      channels=["ir", "visible"])
        clouds.load_data()
        rgba = clouds.image(-1, "ir", colormap="blue")
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
        channels: Union[str, Sequence[str]] = "ir",
        sources: Optional[Sequence[WMSImageryData]] = None,
        seam_width: float = 2.0,
        complete: bool = True,
        match: Optional[bool] = None,
        verbose: bool = True,
    ):
        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, resolution, channels, verbose)

        if sources is None:
            common = dict(
                start=start, end=end, min_lon=min_lon, max_lon=max_lon, min_lat=min_lat,
                max_lat=max_lat, resolution=resolution, time_step=time_step, channels=self.channels,
                verbose=verbose,
            )
            sources = [EUMETViewData(f"{name}_eumetview", **common), GIBSData(f"{name}_gibs", **common)]
        self.sources = list(sources)
        for channel in self.channels:
            if not any(channel in source.channels for source in self.sources):
                raise ValueError(f"No source gives the {channel} channel.")
        self.seam_width = seam_width
        self.complete = complete
        if match is None:
            self.matched = [channel for channel in self.channels if channel == "visible"]
        else:
            self.matched = list(self.channels) if match else []

    def _download_data(self):
        loaded = []
        for index, source in enumerate(self.sources):
            try:
                source.load_data()
                missing = [variable for variable in source.variables if variable not in source.data]
                if missing:
                    raise ValueError(f"{source.name} has no {missing}.")
            except Exception as error:
                status(f"⚠️ Imagery from {source.name} left out ({type(error).__name__}: {error}).")
                if not loaded and index == len(self.sources) - 1:
                    raise
                continue
            loaded.append(source)
        for channel in self.channels:
            if not any(channel in source.channels for source in loaded):
                raise FileNotFoundError(f"No source of the {channel} channel could be loaded.")
        self.loaded = loaded

    def _convert_data(self):
        times = [set(source.data["valid_time"].values) for source in self.loaded]
        times = set.intersection(*times) if self.complete else set.union(*times)
        if not times:
            raise ValueError("The sources have no time in common: try complete=False.")
        times = np.array(sorted(times))

        latitude, longitude = self.grid()
        lat, lon = np.meshgrid(latitude, longitude, indexing="ij")
        angles = [
            np.zeros_like(lat) if source.subsatellite_lon is None
            else central_angle(lat, lon, 0.0, source.subsatellite_lon)
            for source in self.loaded
        ]
        weights = image_utils.softmin_weights(angles, self.seam_width)

        gain = np.ones((len(self.channels), len(self.loaded), len(times)))
        offset = np.zeros_like(gain)
        variables = {}
        for row, channel in enumerate(self.channels):
            variable = IMAGERY_CHANNELS[channel]
            images = []
            for source in self.loaded:
                if variable not in source.data:
                    images.append(np.full((len(times), latitude.size, longitude.size), np.nan))
                    continue
                values = source.data[variable].reindex(valid_time=times)
                if values.sizes["latitude"] != latitude.size or not np.allclose(values["longitude"], longitude):
                    values = values.interp(latitude=latitude, longitude=longitude, method="nearest")
                images.append(values.values.astype(float))

            if channel in self.matched:
                for index in range(1, len(images)):
                    seam = (weights[0] >= MATCH_WEIGHT) & (weights[index] >= MATCH_WEIGHT)
                    for step in range(len(times)):
                        # A dark reference (night) has nothing to match
                        gain[row, index, step], offset[row, index, step] = image_utils.quantile_fit(
                            images[index][step], images[0][step], seam, min_spread=0.02,
                        )
                    images[index] = gain[row, index][:, None, None] * images[index] + offset[row, index][:, None, None]

            variables[variable] = (
                ("valid_time", "latitude", "longitude"),
                image_utils.blend(images, weights[:, None]).astype(np.float32),
            )

        self.data = xr.Dataset(
            variables | {
                "weight": (("source", "latitude", "longitude"), weights.astype(np.float32)),
                "gain": (("channel", "source", "valid_time"), gain),
                "offset": (("channel", "source", "valid_time"), offset),
            },
            coords={
                "valid_time": times,
                "latitude": latitude,
                "longitude": longitude,
                "source": [source.name for source in self.loaded],
                "channel": self.channels,
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

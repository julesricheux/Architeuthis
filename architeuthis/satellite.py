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
import json
import time as clock
import tqdm
import eumdac
import shutil
import zipfile

import requests

import numpy as np
import pandas as pd
import xarray as xr

from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Sequence, Union
from urllib.parse import urlparse
from architeuthis.common import ArchiteuthisSpatialData, Datetime, _HOME, status, to_timestamp
from architeuthis.copernicus import CopernicusMarineData
from architeuthis.credentials import require_credentials
from architeuthis.toolbox import image_utils, wms_utils
from architeuthis.toolbox.geo_utils import central_angle, geostationary_zenith
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

# Layer of each source per channel on its map server, by native resolution
# (pixel size at the sub-satellite point), finest first: `native_resolution`
# chooses among them. EUMETView serves Meteosat at 0 deg twice: MTG FCI HRFI
# (every 10 min) and MSG SEVIRI (every 15 min); GIBS one layer per channel.
EUMETVIEW_LAYERS = {
    "ir": {
        "1km": "mtg_fd:ir105_hrfi",  # MTG FCI 10.5 um
        "3km": "msg_fes:ir108",      # MSG SEVIRI 10.8 um
    },
    "visible": {
        "0.5km": "mtg_fd:vis06_hrfi",  # MTG FCI 0.6 um
        "3km": "msg_fes:vis006",       # MSG SEVIRI 0.6 um
    },
}
GIBS_LAYERS = {
    "ir": {"2km": "GOES-East_ABI_Band13_Clean_Infrared"},           # ABI 10.3 um
    "visible": {"1km": "GOES-East_ABI_Band2_Red_Visible_1km"},  # ABI 0.64 um
}

# Grey level g of EUMETView images to their value, offset + slope * g.
# FCI IR 10.5, in K: fitted on 2026-11-19 16:50 UTC against the FCI L1c
# radiances of the same scan (EUMETSAT Data Tailor), 1.6 million pixels
# over France: correlation 0.991, residual 2 K, from 301 K (black) to
# 192 K (white). SEVIRI IR 10.8, in K: fitted on 2026-11-19 21:30 UTC
# against the FCI IR 10.5 so calibrated, over 40 W - 20 E, 30 - 60 N at
# 0.25 deg: correlation 0.984, residual 3 K, from 299 K (black) to 215 K
# (white). Visible: the grey level itself, from 0 to 1.
EUMETVIEW_CALIBRATIONS = {
    "mtg_fd:ir105_hrfi": (301.2, -0.428),
    "mtg_fd:vis06_hrfi": (0.0, 1.0 / 255.0),
    "msg_fes:ir108": (298.7, -0.3274),
    "msg_fes:vis006": (0.0, 1.0 / 255.0),
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

# Limb cooling of the infrared: a satellite that sees a place obliquely
# looks through more atmosphere, and at the sides of the clouds, so it
# reads it colder, LIMB_COOLING * (zenith / 90)**LIMB_EXPONENT in K.
# Fitted on 2026-11-19 and 20, 6 times by day and night, comparing
# quantiles of Meteosat MTG FCI 10.5 um and GOES-East ABI 10.3 um in
# boxes of 2 x 5 deg over 75 W - 5 E, 35 - 60 N at 0.1 deg: their
# difference, up to 15 K, is 1.0 K + cooling of one - cooling of the
# other, with one law for both (16.8 and 19.8 K fitted apart). Residual
# 4.1 K rather than 9.2 K; 4.5 K rather than 9.7 K at 4 other times. A
# dependence on the temperature fits a little better but corrects cold
# tops the most, up to 15 K at 60 deg: their larger extent seen from the
# side, not a cooling, so it is left out. Parallax is not corrected.
LIMB_COOLING = 18.4  # K, at a zenith angle of 90 deg
LIMB_EXPONENT = 4

# Images requested at once from a map server
DOWNLOAD_WORKERS = 4

# An image still empty this long after its time will stay so (outside the
# disk of the satellite, say): it is recorded and not asked again. Before,
# it may not be produced yet, and a later run asks again.
EMPTY_FINAL_AFTER = 3 * 3600.0  # s

# Grid resolution, in degrees, that shows all the detail of the finest
# server layers over the North Atlantic (2026-11), where their pixels are
# larger than at the sub-satellite point; a finer one only enlarges them,
# a coarser one loses detail. The grid resolution sets the size of each
# requested image, so its download time: about 1 s for 1600 x 500 pixels,
# 2-3 s for 4000 x 1250, 5-7 s for 8000 x 2500, four at a time. Fine ones
# suit small domains; `image(scale=...)` smooths any of them for display.
DETAIL_RESOLUTIONS = {
    "ir": 0.02,
    "visible": 0.01,
}


def native_layers(
    layers: dict,
    native_resolution: Union[str, dict] = "finest",
) -> dict:
    """
    Server layer of each channel at a chosen native resolution.

    Args:
        layers: Server layers of each channel by native resolution,
            finest first (`EUMETVIEW_LAYERS`, `GIBS_LAYERS`).
        native_resolution: "finest", "coarsest", or a key of the
            layers ("3km" say); or such a value per channel, as
            `{"ir": "3km"}`, the others the finest.

    Returns:
        `{channel: server layer}`.

    Example:
        native_layers(EUMETVIEW_LAYERS, {"ir": "3km"})
    """
    chosen = {}
    for channel, options in layers.items():
        choice = native_resolution.get(channel, "finest") if isinstance(native_resolution, dict) else native_resolution
        names = list(options)
        if choice in ("finest", "coarsest"):
            choice = names[0] if choice == "finest" else names[-1]
        if choice not in options:
            raise ValueError(f"No {channel} layer at {choice}: choose among {['finest', 'coarsest'] + names}.")
        chosen[channel] = options[choice]
    return chosen


def limb_cooling(zenith) -> np.ndarray:
    """
    Cooling of infrared brightness temperatures seen obliquely.

    Empirical (`LIMB_COOLING`, `LIMB_EXPONENT`): about 2 K at a zenith
    angle of 50 deg, 4 K at 60, 7 K at 70, 12 K at 80, 18 K at 90. Add
    it to estimate what the satellite would read straight above.

    Args:
        zenith: Zenith angles of the satellite, in degrees
            (`geo_utils.geostationary_zenith`).

    Returns:
        The cooling, in K.

    Example:
        bt + limb_cooling(geostationary_zenith(lat, lon, -75.2))
    """
    zenith = np.clip(np.asarray(zenith, dtype=float), 0.0, 90.0)
    return LIMB_COOLING * (zenith / 90.0) ** LIMB_EXPONENT


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

    The channels to load are chosen as the variables of a forecast:
    "ir", "visible" (`IMAGERY_CHANNELS`). After `load_data`, `data`
    holds the quantity of each (`variables`): `bt`, the brightness
    temperature in K, for "ir", and `brightness`, from 0 to 1, for
    "visible", on `valid_time` (float epoch seconds), `latitude`
    (ascending) and `longitude`. Images of every source are thus on one
    scale. How they look is chosen when drawing: `image` draws a
    channel with a colour scale of Windy.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        resolution: Pixel size, in degrees. It sets the size of the
            downloaded images, hence their time: about 1 s an image of
            1600 x 500 pixels (0.05 over the North Atlantic), 2-3 s
            of 4000 x 1250. 0.02 shows all the detail of the infrared,
            0.01 of the visible (`DETAIL_RESOLUTIONS`): best kept for
            a small domain.
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
        box: Optional[Sequence[float]] = None,
        scale: float = 1.0,
        order: int = 1,
    ) -> np.ndarray:
        """
        One image of a channel, with a colour scale of Windy, north up.

        With `scale`, the values are interpolated before being coloured
        (`image_utils.rescale`): the pixels of a zoom no longer show,
        and the steps of the colour scale stay sharp. `box` draws only
        a part of the domain, which keeps a large upscale light;
        `extent(box)` gives where to place it.

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
            box: `(min_lon, max_lon, min_lat, max_lat)` of the part to
                draw, in degrees, None for the whole domain.
            scale: Factor on the size of the image: 4 draws each pixel
                as 4 x 4 smoothly interpolated ones; below 1, a smaller
                image.
            order: Order of the interpolation: 1 (bilinear, smooth, no
                overshoot), 3 (bicubic, smoother) or 0 (nearest).

        Returns:
            RGBA array of shape (height, width, 4), uint8, first row
            north, as `imshow` and map overlays take it.

        Example:
            rgba = clouds.image(-1, "ir", colormap="blue")
            zoom = clouds.image(-1, box=(-62, -50, 42, 50), scale=4)
            plt.imshow(zoom, extent=clouds.extent((-62, -50, 42, 50)))
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
        rows, columns = self._crop(box)
        values = self.data[variable].isel(valid_time=time, latitude=rows, longitude=columns).values[::-1]
        values = image_utils.rescale(values, scale, order)
        fade = (norm.vmax - norm.vmin) / 10.0 if fade is None else fade
        return values_to_rgba(values, colormap, norm.vmin, norm.vmax, transparent_above, fade, transparent_below)

    def _crop(self, box: Optional[Sequence[float]] = None) -> tuple[slice, slice]:
        """
        Rows and columns of the pixels whose centre is inside a box.

        Args:
            box: `(min_lon, max_lon, min_lat, max_lat)`, in degrees,
                None for the whole domain.

        Returns:
            (rows, columns) slices, rows from the south.
        """
        if box is None:
            return slice(None), slice(None)
        min_lon, max_lon, min_lat, max_lat = box
        latitude, longitude = self.grid()
        rows = np.flatnonzero((latitude >= min_lat) & (latitude <= max_lat))
        columns = np.flatnonzero((longitude >= min_lon) & (longitude <= max_lon))
        if rows.size == 0 or columns.size == 0:
            raise ValueError(f"No pixel of {self.name} inside {box}.")
        return slice(rows[0], rows[-1] + 1), slice(columns[0], columns[-1] + 1)

    def extent(self, box: Optional[Sequence[float]] = None) -> list[float]:
        """
        Where `image(box=box)` lies, as `imshow` takes it.

        The edges of its pixels, close to the box but on the grid.

        Args:
            box: `(min_lon, max_lon, min_lat, max_lat)`, in degrees,
                None for the whole domain.

        Returns:
            `[west, east, south, north]`, in degrees.

        Example:
            rgba = clouds.image(-1, box=box)
            plt.imshow(rgba, extent=clouds.extent(box))
        """
        rows, columns = self._crop(box)
        latitude, longitude = self.grid()
        latitude, longitude = latitude[rows], longitude[columns]
        half_lat = (self.max_lat - self.min_lat) / self.size[1] / 2.0
        half_lon = (self.max_lon - self.min_lon) / self.size[0] / 2.0
        return [
            float(longitude[0] - half_lon),
            float(longitude[-1] + half_lon),
            float(latitude[0] - half_lat),
            float(latitude[-1] + half_lat),
        ]


class WMSImageryData(SatelliteImagery):
    """
    Images of a WMS server, turned back into the values they show.

    One server layer per channel (`wms_layers`).
    The server crops and renders each image at the requested box,
    resolution and time; the times are those every channel has within
    the period.

    Files are managed as those of the forecasts: nothing on disk is
    downloaded again. Each image (server layer, box, resolution, time)
    is a PNG in `~/data/wms/<host>/<layer>/<box>/`, opened if it is
    there. The times the server listed for a layer, and the periods
    they cover, are kept in `<layer>/times.json`: a period already
    covered is answered from it, so that loading it again asks the
    server nothing. An empty image is left out; one empty for good
    (`EMPTY_FINAL_AFTER`) is recorded there too. If the server cannot
    be reached, the images on disk are used, with a warning.

    Images are requested `workers` at a time (`DOWNLOAD_WORKERS`), and
    in tiles when larger than `wms_utils.MAX_SIZE` pixels a side. Their
    pixels are in `rgba_<channel>` and, given the palette of the server
    layer, their values in the quantity of the channel (see
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
        resolution: Pixel size, in degrees. It sets the size of the
            downloaded images, hence their time: about 1 s an image of
            1600 x 500 pixels (0.05 over the North Atlantic), 2-3 s
            of 4000 x 1250. 0.02 shows all the detail of the infrared,
            0.01 of the visible (`DETAIL_RESOLUTIONS`): best kept for
            a small domain.
        time_step: Keep only the times on multiples of this step ("1h"
            for example), None for all the times of the layer.
        channels: Channel or channels, "ir", "visible".
        palettes: (colours, values) of each channel, None if unknown.
        subsatellite_lon: Longitude of the satellite, in degrees, None
            to guess it from the server layer names
            (`SUBSATELLITE_LONGITUDES`).
        style: Style of the server layers, "" for their default.
        limb_correction: Add to the infrared the cooling of an oblique
            view (`limb_cooling`), to estimate what the satellite would
            read straight above; needs the longitude of the satellite.
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
        limb_correction: bool = False,
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
        if limb_correction and subsatellite_lon is None:
            raise ValueError(f"{name}: the limb correction needs the longitude of the satellite (subsatellite_lon).")
        self.limb_correction = limb_correction
        self.output_path = os.path.join(_HOME, "wms", urlparse(url).hostname or "server")
        self.workers = DOWNLOAD_WORKERS

    def _folder(self, channel: str) -> str:
        """
        Folder of the images of a channel, by server layer and box.

        Args:
            channel: "ir" or "visible".

        Returns:
            The path.
        """
        return os.path.join(self.output_path, self.wms_layers[channel].replace(":", "_"), self._box())

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

    def _image_path(self, channel: str, time: pd.Timestamp) -> str:
        """
        Path of one image on disk.

        Args:
            channel: "ir" or "visible".
            time: Time of the image.

        Returns:
            The path, whether the image is there or not.
        """
        return os.path.join(self._folder(channel), f"{time:%Y%m%dT%H%M%S}.png")

    def _index_path(self, channel: str) -> str:
        """
        Path of the time index of a server layer.

        Args:
            channel: "ir" or "visible".

        Returns:
            The path of its `times.json`, shared by every box.
        """
        return os.path.join(self.output_path, self.wms_layers[channel].replace(":", "_"), "times.json")

    def _read_index(self, channel: str) -> dict:
        """
        Time index of a server layer, empty if there is none.

        Args:
            channel: "ir" or "visible".

        Returns:
            `{"covered": [[start, end], ...], "times": [...], "empty":
            {box: [...]}}`, in epoch seconds: the periods whose times
            the server listed, those times, and the images empty for
            good, by box.
        """
        index = {"covered": [], "times": [], "empty": {}}
        try:
            with open(self._index_path(channel), encoding="utf-8") as file:
                index.update(json.load(file))
        except (OSError, ValueError):
            pass
        return index

    def _write_index(self, channel: str, index: dict):
        """
        Save the time index of a server layer, merging its periods.

        Args:
            channel: "ir" or "visible".
            index: As `_read_index` gives it.
        """
        covered = []
        for first, last in sorted(index["covered"]):
            if covered and first <= covered[-1][1]:
                covered[-1][1] = max(covered[-1][1], last)
            else:
                covered.append([first, last])
        index["covered"] = covered
        index["times"] = sorted(set(index["times"]))
        path = self._index_path(channel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "w", encoding="utf-8") as file:
            json.dump(index, file)
        os.replace(path + ".part", path)

    def _box(self) -> str:
        """
        Name of the box and resolution in the folders and the index.
        """
        return f"{self.min_lon:g}_{self.min_lat:g}_{self.max_lon:g}_{self.max_lat:g}_{self.resolution:g}"

    def _times(self, channel: str) -> pd.DatetimeIndex:
        """
        Times of a server layer within the period, from disk if known.

        Args:
            channel: "ir" or "visible".

        Returns:
            Sorted UTC times, before `time_step`.
        """
        index = self._read_index(channel)
        layer = self.wms_layers[channel]
        if self.start is not None and self.end is not None:
            start, end = to_timestamp(self.start), to_timestamp(self.end)
            if any(first <= start and end <= last for first, last in index["covered"]):
                self.info(f"💾 Times of {layer} already known.")
                times = [time for time in index["times"] if start <= time <= end]
                return pd.to_datetime(times, unit="s", utc=True)
        try:
            times = wms_utils.available_times(self._time_extent(channel), self.start, self.end)
        except requests.RequestException as error:
            # Offline: the images of the period already on disk
            times = self._times_on_disk(channel)
            if times.empty:
                raise
            status(f"⚠️ {layer} unreachable ({type(error).__name__}): {len(times)} image(s) on disk used.")
            return times
        if self.start is not None and not times.empty:
            # The server lists every time up to its latest: later ones
            # may come, earlier ones will not
            last = min(to_timestamp(self.end), times[-1].timestamp()) if self.end is not None else times[-1].timestamp()
            index["covered"].append([to_timestamp(self.start), last])
            index["times"].extend(time.timestamp() for time in times)
            self._write_index(channel, index)
        return times

    def _times_on_disk(self, channel: str) -> pd.DatetimeIndex:
        """
        Times of the images of a channel on disk, within the period.

        Args:
            channel: "ir" or "visible".

        Returns:
            Sorted UTC times.
        """
        folder = self._folder(channel)
        names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
        times = pd.to_datetime(
            [name[:-4] for name in names if name.endswith(".png")], format="%Y%m%dT%H%M%S", utc=True,
        )
        if self.start is not None:
            times = times[times >= pd.Timestamp(to_timestamp(self.start), unit="s", tz="UTC")]
        if self.end is not None:
            times = times[times <= pd.Timestamp(to_timestamp(self.end), unit="s", tz="UTC")]
        return times

    def _locate_data(self):
        self._capabilities = None
        self.available = {}
        for channel, layer in self.wms_layers.items():
            times = self._times(channel)
            if self.time_step is not None:
                times = times[times == times.floor(self.time_step)]
            # Images empty for good are not asked again
            empty = set(self._read_index(channel)["empty"].get(self._box(), []))
            times = times[[time.timestamp() not in empty for time in times]]
            if times.empty:
                raise FileNotFoundError(f"No image of {layer} between {self.start} and {self.end}.")
            self.available[channel] = times

    def _download_image(self, channel: str, time: pd.Timestamp) -> Optional[str]:
        """
        Path of one image, downloaded unless it is there already.

        Args:
            channel: "ir" or "visible".
            time: Time of the image.

        Returns:
            The path, or None if the image is empty (not produced yet,
            or nothing over the domain), which is not cached so that a
            later run asks again.
        """
        path = self._image_path(channel, time)
        if os.path.exists(path):
            return path
        bounds = (self.min_lon, self.min_lat, self.max_lon, self.max_lat)
        layer = self.wms_layers[channel]
        if max(self.size) <= wms_utils.MAX_SIZE:
            # One request: its PNG kept as it came
            content = wms_utils.get_map(self.url, layer, bounds, self.size, time, self.style)
            rgba = image_utils.decode_png(content)
        else:
            rgba = wms_utils.get_map_array(self.url, layer, bounds, self.size, time, self.style)
            content = image_utils.encode_png(rgba)
        if not rgba[..., 3].any():
            return None
        with open(path + ".part", "wb") as file:
            file.write(content)
        os.replace(path + ".part", path)
        return path

    def _download_data(self):
        kept = {}
        for channel, layer in self.wms_layers.items():
            os.makedirs(self._folder(channel), exist_ok=True)
            times = self.available[channel]
            missing = [time for time in times if not os.path.exists(self._image_path(channel, time))]
            if not missing:
                self.info(f"💾 {len(times)} image(s) of {layer} already downloaded.")
                paths = [self._image_path(channel, time) for time in times]
            else:
                width, height = self.size
                self.info(
                    f"⬇️ Downloading {len(missing)} image(s) of {layer}, {width} x {height} pixels "
                    f"({len(times) - len(missing)} already downloaded)..."
                )
                # Several images at once: the server renders each in seconds
                with ThreadPoolExecutor(max_workers=self.workers) as pool:
                    paths = list(tqdm.tqdm(
                        pool.map(lambda time: self._download_image(channel, time), times),
                        total=len(times), disable=not self.verbose,
                    ))
                self.info("✅ Download completed.")
            kept[channel] = {}
            empty = []
            for time, path in zip(times, paths):
                if path is None:
                    status(f"⚠️ Empty image of {layer} at {time:%Y-%m-%d %H:%M}, left out.")
                    if clock.time() - time.timestamp() > EMPTY_FINAL_AFTER:
                        empty.append(time.timestamp())
                else:
                    kept[channel][time] = path
            if empty:
                index = self._read_index(channel)
                index["empty"][self._box()] = sorted(set(index["empty"].get(self._box(), [])) | set(empty))
                self._write_index(channel, index)
            if not kept[channel]:
                raise FileNotFoundError(f"Every image of {layer} is empty over the domain.")

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
            # Image by image, to keep the memory of large images low
            pixels = self.data[f"rgba_{channel}"].values
            values = np.empty(pixels.shape[:-1], dtype=np.float32)
            for step, frame in enumerate(pixels):
                values[step] = image_utils.invert_palette(frame, *palette, secondary=self.secondary[channel])
            if channel == "ir" and self.limb_correction:
                lat, lon = np.meshgrid(self.data["latitude"].values, self.data["longitude"].values, indexing="ij")
                values += limb_cooling(geostationary_zenith(lat, lon, self.subsatellite_lon)).astype(np.float32)
            self.data[IMAGERY_CHANNELS[channel]] = (("valid_time", "latitude", "longitude"), values)


class EUMETViewData(WMSImageryData):
    """
    Meteosat images of EUMETView, the map service of EUMETSAT.

    No account. The server layers (`EUMETVIEW_LAYERS`) are those of
    Meteosat at 0 deg, covering 70 deg around it, a few minutes after
    the scan, at two native resolutions: MTG FCI HRFI by default (IR
    10.5 um at 1 km, visible 0.6 um at 0.5 km, every 10 min since
    2024-09), or MSG SEVIRI (IR 10.8 um and visible 0.6 um at 3 km,
    every 15 min) with `native_resolution="coarsest"` or "3km". Their
    grey levels are turned into values with `EUMETVIEW_CALIBRATIONS`;
    a layer without one gives its pixels only.

    Args:
        name: Name of this object, used in status messages.
        start: Start of the period.
        end: End of the period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
        resolution: Pixel size, in degrees. It sets the size of the
            downloaded images, hence their time: about 1 s an image of
            1600 x 500 pixels (0.05 over the North Atlantic), 2-3 s
            of 4000 x 1250. 0.02 shows all the detail of the infrared,
            0.01 of the visible (`DETAIL_RESOLUTIONS`): best kept for
            a small domain.
        time_step: Keep only the times on multiples of this step, None
            for every image.
        channels: Channel or channels, "ir", "visible".
        native_resolution: Native resolution of the server layers,
            "finest" (MTG FCI), "coarsest" or "3km" (MSG SEVIRI), or
            one per channel (`native_layers`).
        wms_layers: Server layer of each channel, overriding the
            native resolution, None for none.
        limb_correction: Add to the infrared the cooling of an oblique
            view (`limb_cooling`).
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
        native_resolution: Union[str, dict] = "finest",
        wms_layers: Optional[dict] = None,
        limb_correction: bool = False,
        verbose: bool = True,
    ):
        wms_layers = native_layers(EUMETVIEW_LAYERS, native_resolution) | (wms_layers or {})
        palettes = {
            channel: image_utils.linear_gray_palette(*EUMETVIEW_CALIBRATIONS[layer])
            for channel, layer in wms_layers.items() if layer in EUMETVIEW_CALIBRATIONS
        }
        super().__init__(
            name, EUMETVIEW_URL, wms_layers, start, end, min_lon, max_lon, min_lat, max_lat,
            resolution, time_step, channels, palettes,
            limb_correction=limb_correction,
            verbose=verbose,
        )


class GIBSData(WMSImageryData):
    """
    GOES and Himawari images of NASA GIBS.

    GIBS (Global Imagery Browse Services) needs no account. The server
    layers are those of GOES-East ABI (`GIBS_LAYERS`), one native
    resolution each: band 13 (IR 10.3 um, 2 km) and band 2 (visible
    0.64 um, 1 km), every 10 min over
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
        resolution: Pixel size, in degrees. It sets the size of the
            downloaded images, hence their time: about 1 s an image of
            1600 x 500 pixels (0.05 over the North Atlantic), 2-3 s
            of 4000 x 1250. 0.02 shows all the detail of the infrared,
            0.01 of the visible (`DETAIL_RESOLUTIONS`): best kept for
            a small domain.
        time_step: Keep only the times on multiples of this step, None
            for every image.
        channels: Channel or channels, "ir", "visible".
        native_resolution: Native resolution of the server layers,
            "finest", "coarsest", "2km" (IR) or "1km" (visible): one
            each for now (`native_layers`).
        wms_layers: Server layer of each channel, overriding the
            native resolution, None for none; GOES-West or Himawari
            for example.
        limb_correction: Add to the infrared the cooling of an oblique
            view (`limb_cooling`).
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
        native_resolution: Union[str, dict] = "finest",
        wms_layers: Optional[dict] = None,
        limb_correction: bool = False,
        verbose: bool = True,
    ):
        wms_layers = native_layers(GIBS_LAYERS, native_resolution) | (wms_layers or {})
        palettes = {"visible": image_utils.linear_gray_palette(0.0, 1.0 / 255.0)}
        super().__init__(
            name, GIBS_URL, wms_layers, start, end, min_lon, max_lon, min_lat, max_lat,
            resolution, time_step, channels, palettes,
            limb_correction=limb_correction,
            verbose=verbose,
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

    def _colormap_document(self, colormap: str) -> str:
        """
        The XML of a GIBS colormap, downloaded once.

        Args:
            colormap: Name of the colormap (`GIBS_COLORMAPS`).

        Returns:
            The document, from `~/data/wms/<host>/colormaps/`.
        """
        path = os.path.join(self.output_path, "colormaps", f"{colormap}.xml")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                return file.read()
        response = requests.get(GIBS_COLORMAP_URL.format(colormap), timeout=wms_utils.TIMEOUT)
        response.raise_for_status()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "w", encoding="utf-8") as file:
            file.write(response.text)
        os.replace(path + ".part", path)
        return response.text

    def _locate_data(self):
        super()._locate_data()
        for channel, layer in self.wms_layers.items():
            colormap = GIBS_COLORMAPS.get(layer)
            if colormap is None or self.palettes[channel] is not None:
                continue
            colours, values = wms_utils.parse_gibs_colormap(self._colormap_document(colormap))
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

    Infrared images agree in K, within about 1 K where both satellites
    see at the same angle; each reads colder towards its limb, up to
    15 K over the North Atlantic, which `limb_correction` makes up for.
    Visible ones do not agree: the
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
        resolution: Pixel size, in degrees. It sets the size of the
            downloaded images, hence their time: about 1 s an image of
            1600 x 500 pixels (0.05 over the North Atlantic), 2-3 s
            of 4000 x 1250. 0.02 shows all the detail of the infrared,
            0.01 of the visible (`DETAIL_RESOLUTIONS`): best kept for
            a small domain.
        time_step: Keep only the times on multiples of this step, None
            for every image.
        channels: Channel or channels: "ir" (day and night), "visible"
            (by day).
        native_resolution: Native resolution of the server layers of
            the default sources, "finest" or "coarsest" for each, or
            one per channel (`native_layers`); a source without the one
            asked raises.
        sources: `WMSImageryData` objects to combine, None for
            EUMETView and GIBS over this domain, period and channels.
        seam_width: Width of the blending along the seams, in degrees of
            viewing angle.
        complete: Keep only the times every source has, so that no
            image misses a part; else the times any source has.
        match: Match the levels of the sources along the seam, None for
            the visible only.
        limb_correction: Add to the infrared of the default sources the
            cooling of an oblique view (`limb_cooling`).
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
        native_resolution: Union[str, dict] = "finest",
        sources: Optional[Sequence[WMSImageryData]] = None,
        seam_width: float = 2.0,
        complete: bool = True,
        match: Optional[bool] = None,
        limb_correction: bool = False,
        verbose: bool = True,
    ):
        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, resolution, channels, verbose)

        if sources is None:
            common = dict(
                start=start, end=end, min_lon=min_lon, max_lon=max_lon, min_lat=min_lat,
                max_lat=max_lat, resolution=resolution, time_step=time_step, channels=self.channels,
                native_resolution=native_resolution,
                limb_correction=limb_correction,
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
                    images.append(None)
                    continue
                values = source.data[variable].reindex(valid_time=times)
                if values.sizes["latitude"] != latitude.size or not np.allclose(values["longitude"], longitude):
                    values = values.interp(latitude=latitude, longitude=longitude, method="nearest")
                images.append(values.values)
            empty = np.full(lat.shape, np.nan, dtype=np.float32)

            # Image by image, to keep the memory of large images low
            joined = np.empty((len(times), latitude.size, longitude.size), dtype=np.float32)
            for step in range(len(times)):
                frames = [empty if image is None else image[step].astype(np.float32) for image in images]
                if channel in self.matched:
                    for index in range(1, len(frames)):
                        seam = (weights[0] >= MATCH_WEIGHT) & (weights[index] >= MATCH_WEIGHT)
                        # A dark reference (night) has nothing to match
                        gain[row, index, step], offset[row, index, step] = image_utils.quantile_fit(
                            frames[index], frames[0], seam, min_spread=0.02,
                        )
                        frames[index] = gain[row, index, step] * frames[index] + offset[row, index, step]
                joined[step] = image_utils.blend(frames, weights)
            variables[variable] = (("valid_time", "latitude", "longitude"), joined)

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

# -*- coding: utf-8 -*-
"""
Satellite observations, to validate forecasts against them.

ASCAT winds come from EUMETSAT (`EUMETSATASCATData`, the latest swaths)
or from Copernicus Marine (`CopernicusASCATData`, daily gridded swaths,
about a day behind). `ASCATData` takes them in a chosen order and falls
back on the next source when one fails. Both give the same variables.

Created on Thu Jan 29 16:15:59 2026

@author: jrich
"""

import os
import tqdm
import eumdac
import shutil
import zipfile

import numpy as np
import pandas as pd
import xarray as xr

from typing import Sequence, Union
from architeuthis.common import ArchiteuthisSpatialData, Datetime, _HOME, status, to_timestamp
from architeuthis.copernicus import CopernicusMarineData
from architeuthis.credentials import require_credentials


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

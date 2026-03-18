# -*- coding: utf-8 -*-
"""
Created on Thu Jan 29 16:15:59 2026

@author: jrich
"""

import os
import tqdm
import eumdac
import shutil
import zipfile

import xarray as xr

from typing import Union
from architeuthis.common import ArchiteuthisSpatialData, Datetime, _EUMDAC_CREDENTIALS, _HOME


class ArchiteuthisSatelliteData(ArchiteuthisSpatialData):
    
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
        

class EUMETSATData(ArchiteuthisSatelliteData):
    
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
        self.__EUMDAC_CREDENTIALS = _EUMDAC_CREDENTIALS
        
        self.dataset = dataset
        
        self.f99 = end
        
        # TODO how to handle depth properly?
        self.min_depth = 0.49402499198913574
        self.max_depth = 0.49402499198913574
        
        self.output_path = os.path.join(_HOME, "eumetsat")
        os.makedirs(self.output_path, exist_ok=True)
        
        super().__init__(name, start, end, min_lon, max_lon, min_lat, max_lat, verbose)
       
        
    def _locate_data(self):
        self.token = eumdac.AccessToken(self.__EUMDAC_CREDENTIALS)

        self.datastore = eumdac.DataStore(self.token)
        
        self.collection = self.datastore.get_collection(
            self.dataset
        )


    def _download_data(self):
        
        # find products
        self.products = self.collection.search(
            # geo='POLYGON(({}))'.format(','.join(["{} {}".format(*coord) for coord in geometry])),
            # bbox=bounding_box,
            dtstart=self.start, 
            dtend=self.end,
            # sat=satellite
        )
        
        # download products
        zipfiles=[]
        
        
        print(f'🛰️ Download of {len(self.products)} product(s)...')
        for product in tqdm.tqdm(self.products):
            with product.open() as fsrc, \
                    open(os.path.join(self.output_path, fsrc.name), mode='wb') as fdst:
                if not os.path.exists(fdst.name[-4:]+".nc"):
                # if not os.path.exists(fdst.name):
                    shutil.copyfileobj(fsrc, fdst)
                    zipfiles.append(fdst.name) # add distant file path to path storage
                    # print(f'Download of product {product} finished.')
                # else:
                #     print("Already in memory")
        print('✅ Downloads completed.')

    
        # Unzip products
        print('📦 Unzipping downloaded files...')
        nc_files = []

        for zip_path in zipfiles:
            extracted_nc = []

            with zipfile.ZipFile(zip_path, "r") as z:
                for member in z.namelist():
                    if member.endswith(".nc"):
                        out_path = os.path.join(
                            self.output_path,
                            os.path.basename(member),
                        )

                        if not os.path.exists(out_path):
                            z.extract(member, self.output_path)
                            os.rename(
                                os.path.join(self.output_path, member),
                                out_path,
                            )

                        extracted_nc.append(out_path)
                        nc_files.append(out_path)

            # # Delete ZIP only if extraction succeeded
            # if extracted_nc:
            #     os.remove(zip_path)
        print('✅ Finished unzipping.')
        
        self.path = nc_files
        
        
class ASCATData(EUMETSATData):
    
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
            # chunks={"NUMROWS": 1000, "NUMCELLS": 82}  # adjust chunking for memory
        )
        
    def _convert_data(self):
        
        self.data["lon"] = ((self.data["lon"] + 180.) % 360.) - 180.
        self.data["valid_time"] = self.data["time"].astype("datetime64[s]").astype(float)
        
        slicing = (
            (self.data["lat"] >= self.min_lat) &
            (self.data["lat"] <= self.max_lat) &
            (self.data["lon"] >= self.min_lon) &
            (self.data["lon"] <= self.max_lon)
        )
        
        self.data = self.data.where(slicing).load()
        
# TODO find a better class name?
class PoseidonData(EUMETSATData):
    
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
        
        dataset = "EO:EUM:DAT:0142" # Poseidon-4 Level 2P Wind/Wave Products Low Resolution in NRT - Sentinel-6
        
        super().__init__(name, dataset, start, end, min_lon, max_lon, min_lat, max_lat, verbose)
    
    
    def _read_data(self):
        
        self.data = xr.open_mfdataset(
            self.path
        )
    
    def _convert_data(self):
        
        self.data["longitude"] = ((self.data["longitude"] + 180.) % 360.) - 180.
        
        slicing = (
            (self.data["latitude"] >= self.min_lat) &
            (self.data["latitude"] <= self.max_lat) &
            (self.data["longitude"] >= self.min_lon) &
            (self.data["longitude"] <= self.max_lon)
        )
        
        self.data = self.data.where(slicing).load()



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
    wind_dir = ascat_ds["wind_dir"].values           # degrees, meteorological
    
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
    
    a = ascat_ds.attrs
    
    # cb = plt.colorbar(q, ax=ax, orientation="vertical", pad=0.02)
    # cb.set_label("Wind speed [m s$^{-1}$]")
    
    ax.set_title(f"ASCAT Level-2 Ocean Surface Wind / {a['source']} {a['start_date']} {a['start_time']}")
    
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

# -*- coding: utf-8 -*-
"""
Latest MTG FCI IR 10.5 um image over France at about 1 km, with eumdac.

The full disk (about 1 GB in 40 chunks) is never downloaded: the
EUMETSAT Data Tailor crops, reprojects and resamples it on the server,
and only the result is downloaded. The Architeuthis wrapper
`EUMETSATData` still provides the credentials, the token and the
collection (`_locate_data`); only `_download_data` changes.

Not working yet: with the current EUMETSAT key, every download of
Meteosat imagery (FCI and SEVIRI) is refused with 403 Unauthorised, by
eumdac directly and by the Data Tailor, while ASCAT downloads work. The
NetCDF the Data Tailor returns has therefore never been seen: `to_bt`
below assumes a latitude/longitude grid and is untested.

Run from the repository root:
    python temp-experimental/eumdac_fci_ir.py
"""

import os
import sys
import time
import datetime

import eumdac
import numpy as np
import xarray as xr
from eumdac.tailor_models import Chain, RegionOfInterest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repository root

from architeuthis.common import status
from architeuthis.satellite import EUMETSATData
from summary import IR_NSWE, OUTPUT, RESOLUTION, folder_size, ir_dataset, report

NSWE = IR_NSWE
# FCI IR 10.5 channel: central wavenumber (cm-1), for radiance to BT
WAVENUMBER = 931.7


class TailoredEUMETSATData(EUMETSATData):
    """
    EUMETSAT image cropped and resampled by the Data Tailor.

    Args:
        name: Name of this object, used in status messages.
        dataset: Identifier of the EUMETSAT collection.
        tailor_product: Data Tailor identifier of the product.
        bands: Bands to keep.
        resolution: Grid step of the output, in degrees.
        start: Start of the search period.
        end: End of the search period.
        min_lon: Western bound of the domain, in degrees.
        max_lon: Eastern bound of the domain, in degrees.
        min_lat: Southern bound of the domain, in degrees.
        max_lat: Northern bound of the domain, in degrees.
    """

    def __init__(
        self,
        name,
        dataset,
        tailor_product,
        bands,
        resolution,
        start,
        end,
        min_lon,
        max_lon,
        min_lat,
        max_lat,
    ):
        self.tailor_product = tailor_product
        self.bands = bands
        self.resolution = resolution
        super().__init__(
            name, dataset, start, end, min_lon, max_lon, min_lat, max_lat
        )
        self.output_path = os.path.join(OUTPUT, "eumdac")
        os.makedirs(self.output_path, exist_ok=True)

    def _download_data(self):
        # Latest product only; FCI full disks always cover France
        products = self.collection.search(dtstart=self.start, dtend=self.end)
        product = next(iter(products))
        self.product = product
        status(f"🛰️ Latest product: {product} ({product.size / 1e3:.0f} MB)")

        chain = Chain(
            product=self.tailor_product,
            format="netcdf4",
            filter={"bands": self.bands},
            projection="geographic",
            roi=RegionOfInterest(
                NSWE=[self.max_lat, self.min_lat, self.min_lon, self.max_lon]
            ),
            resample_method="near",
            resample_resolution=[self.resolution, self.resolution],
        )
        datatailor = eumdac.DataTailor(self.token)
        customisation = datatailor.new_customisation(product, chain)
        status(f"⬇️ Data Tailor job {customisation}...")

        tic = time.time()
        while customisation.status in ("QUEUED", "RUNNING", "INACTIVE"):
            time.sleep(5)
        status(f"✅ Job {customisation.status} in {time.time() - tic:.0f} s")
        if customisation.status != "DONE":
            raise RuntimeError(customisation.logfile)

        self.path = []
        for output in customisation.outputs:
            path = os.path.join(self.output_path, os.path.basename(output))
            with customisation.stream_output(output) as src, \
                    open(path, "wb") as dst:
                dst.write(src.read())
            status(f"✅ {path} ({os.path.getsize(path) / 1e6:.2f} MB)")
            self.path.append(path)
        customisation.delete()  # frees the 20 GB Data Tailor quota

    def _read_data(self):
        # h5netcdf: netCDF4 fails on Windows paths with accents
        self.data = xr.open_dataset(self.path[0], engine="h5netcdf")


def to_bt(data):
    """
    Brightness temperature from the Data Tailor output (untested).

    Args:
        data: Dataset returned by the Data Tailor.

    Returns:
        Dataset from `summary.ir_dataset`.
    """
    name = next(n for n in data.data_vars if data[n].ndim == 2)
    field = data[name].squeeze()
    lat = next(c for c in field.dims if "lat" in c or c == "y")
    lon = next(c for c in field.dims if "lon" in c or c == "x")
    values = field.transpose(lat, lon).values
    if np.nanmax(values) < 200:  # effective radiance, mW m-2 sr-1 (cm-1)-1
        c1, c2 = 1.191042e-5, 1.4387752
        values = c2 * WAVENUMBER / np.log1p(c1 * WAVENUMBER**3 / values)
    return ir_dataset(values, data[lat].values, data[lon].values)


if __name__ == "__main__":
    tic = time.time()
    end = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    fci = TailoredEUMETSATData(
        "fci_ir_france",
        dataset="EO:EUM:DAT:0662",  # FCI L1c normal resolution (FDHSI)
        tailor_product="FCIL1FDHSI",
        bands=["ir_105_effective_radiance"],
        resolution=RESOLUTION,
        start=end - datetime.timedelta(hours=1),
        end=end,
        min_lon=NSWE[2],
        max_lon=NSWE[3],
        min_lat=NSWE[1],
        max_lat=NSWE[0],
    )
    fci.load_data()
    print(fci.data)

    report(
        case="ir",
        library="eumdac",
        source="MTG FCI IR 10.5 um (geostationary)",
        image_time=f"{fci.product.sensing_start:%Y-%m-%d %H:%M} UTC",
        downloaded=folder_size(fci.path),
        full_product=fci.product.size * 1e3,
        seconds=time.time() - tic,
        data=to_bt(fci.data),
        notes="Data Tailor: server-side crop and resampling",
    )

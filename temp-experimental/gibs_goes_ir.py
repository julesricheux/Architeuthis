# -*- coding: utf-8 -*-
"""
Latest GOES-East IR image over the NW Atlantic, from NASA GIBS by WMS.

GIBS (Global Imagery Browse Services) serves NASA imagery as map tiles
and WMS, with no account and no library. The geostationary layers
(GOES-East, GOES-West, Himawari) are every 10 min, at 2 km, on a rolling
window of about 90 days; there is no Meteosat. As with EUMETView, the
result is a rendered picture, cropped and reprojected on the server:
an animation layer for `ui.py`, not data.

Run from the repository root:
    python temp-experimental/gibs_goes_ir.py
"""

import time

from summary import ATLANTIC_NSWE, image_dataset, report, wms_image, wms_times

URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
LAYER = "GOES-East_ABI_Band13_Clean_Infrared"  # 10.3 um


if __name__ == "__main__":
    tic = time.time()
    last = wms_times(URL, LAYER)[1]
    image, size = wms_image(URL, LAYER, ATLANTIC_NSWE, time=last, resolution=0.02)
    report(
        case="goes",
        library="gibs",
        source="GOES-East ABI 10.3 um (rendered)",
        image_time=last.replace("T", " ")[:16] + " UTC",
        downloaded=size,
        full_product=None,
        seconds=time.time() - tic,
        data=image_dataset(image, ATLANTIC_NSWE),
        notes=f"WMS {LAYER}, rendered PNG",
    )

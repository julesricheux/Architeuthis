# -*- coding: utf-8 -*-
"""
EUMETView, the public map service of EUMETSAT: rendered images by WMS.

No account and no library: plain WMS 1.3.0 requests to GeoServer, which
crops, reprojects and renders on the server, at any extent, size and
time. The result is a picture (PNG), not measurements: fine for a map
layer or an animation, not for computing. Three layers:

- `mtg_fd:ir105_hrfi`: MTG FCI IR 10.5 um, 1 km, every 10 min, archive
  since 2024-09, the latest image a few minutes old (no NRT licence).
- `mumi:worldcloudmap_ir108`: IR 10.8 um mosaic of the geostationary
  ring (Meteosat, GOES, Himawari...), every 3 h, global.
- `eps:m01_ascat_wind` and `m03` (Metop-B and -C): ASCAT coastal winds
  per pass. The time of a request selects the pass whose interval holds
  it, so the script steps back to the latest one crossing the area.

The same requests work from a Leaflet WMS layer in `ui.py`, with a
`time` parameter for animations.

Run from the repository root:
    python temp-experimental/eumetview_wms.py
"""

import time
import datetime

from summary import (
    ATLANTIC_NSWE, IR_NSWE, WIND_NSWE, image_dataset, report, wms_image, wms_times,
)

URL = "https://view.eumetsat.int/geoserver/ows"


def latest_image(case, layer, nswe, source, resolution=0.01):
    """
    Latest image of a layer over an area, reported as one run.

    Args:
        case: Key of `summary.CASES`.
        layer: WMS layer name.
        nswe: Bounds as [north, south, west, east].
        source: Description for the figure.
        resolution: Pixel size, in degrees.
    """
    tic = time.time()
    last = wms_times(URL, layer)[1]
    image, size = wms_image(URL, layer, nswe, time=last, resolution=resolution)
    report(
        case=case,
        library="eumetview",
        source=source,
        image_time=last.replace("T", " ")[:16] + " UTC",
        downloaded=size,
        full_product=None,
        seconds=time.time() - tic,
        data=image_dataset(image, nswe),
        notes=f"WMS {layer}, rendered PNG",
    )


def latest_ascat(hours=12, step_minutes=20):
    """
    Latest ASCAT pass over the Bay of Biscay, of Metop-B or -C.

    Args:
        hours: How far back to look.
        step_minutes: Time step of the search.
    """
    tic = time.time()
    # Times beyond the last pass of a layer are refused: start from it
    layers = {}
    for layer, satellite in [("eps:m01_ascat_wind", "B"), ("eps:m03_ascat_wind", "C")]:
        last = datetime.datetime.fromisoformat(wms_times(URL, layer)[1].replace("Z", "+00:00"))
        layers[layer] = (satellite, last)
    newest = max(last for _, last in layers.values())
    size = 0
    for back in range(0, hours * 60, step_minutes):
        when = newest - datetime.timedelta(minutes=back)
        moment = when.strftime("%Y-%m-%dT%H:%M:00Z")
        for layer, (satellite, last) in layers.items():
            if when > last:
                continue
            # Coarse probe first, to keep the search light
            probe, probe_size = wms_image(URL, layer, WIND_NSWE, time=moment, resolution=0.1)
            size += probe_size
            if (probe[..., 3] > 0).mean() > 0.1:  # a pass, not a corner
                image, image_size = wms_image(URL, layer, WIND_NSWE, time=moment, resolution=0.025)
                report(
                    case="wind",
                    library="eumetview",
                    source=f"Metop-{satellite} ASCAT coastal winds (rendered)",
                    image_time=f"pass covering {moment[:16].replace('T', ' ')} UTC",
                    downloaded=size + image_size,
                    full_product=None,
                    seconds=time.time() - tic,
                    data=image_dataset(image, WIND_NSWE),
                    notes=f"WMS {layer}; {back // step_minutes + 1} time steps probed",
                )
                return
    raise RuntimeError(f"No ASCAT pass over the area in {hours} h")


if __name__ == "__main__":
    latest_image("ir", "mtg_fd:ir105_hrfi", IR_NSWE, "MTG FCI IR 10.5 um (rendered)")
    latest_image(
        "goes", "mumi:worldcloudmap_ir108", ATLANTIC_NSWE,
        "Geostationary ring IR 10.8 um (rendered)", resolution=0.02,
    )
    latest_ascat()

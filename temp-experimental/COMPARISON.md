# Satellite clouds and ASCAT winds: which source, which library

Goal: geostationary cloud images (first, for animated layers in
`ui.py`), ASCAT winds, and polar-orbit scans as a second choice, each
downloaded for a given time, extent and resolution only.

Three test cases, last run on 2026-11-19 between 18:40 and 19:15 local
time (17:40-18:15 UTC):

- **IR clouds, France**: N 51.5, S 41, W -5.5, E 10, at 0.01 deg (~1 km).
  Meteosat territory.
- **IR clouds, NW Atlantic**: N 51.5, S 41, W -64, E -48.5 (Nova Scotia,
  Newfoundland, Saint-Pierre), same size, at 0.02 deg (the 2 km of the
  GOES IR band). GOES territory, at the limb of Meteosat.
- **ASCAT winds, Bay of Biscay**: N 52, S 40, W -20, E 0.

Run from the repository root (`python temp-experimental/<script>.py`).
Each script writes its figure to `output/` (the only files to commit)
and its data, metrics and raw downloads to `downloads/`, which the
repository's `.gitignore` already ignores. `compare.py` then draws
`output/comparison.png` from `downloads/`.

| Script | Case | Kind | Status |
| --- | --- | --- | --- |
| `eumdac_fci_ir.py` | France | MTG FCI data, Data Tailor | works, **1 h behind** without an NRT licence |
| `eumetview_wms.py` | all three | EUMETSAT rendered images (WMS) | works, no account |
| `gibs_goes_ir.py` | Atlantic | NASA GIBS rendered GOES images (WMS) | works, no account |
| `goes2go_goes_ir.py` | Atlantic | GOES ABI data, NOAA on AWS | works, no account |
| `eumdac_ascat_wind.py` | Biscay | ASCAT data, existing `ASCATData` + bbox, latest covering pass | works |
| `cmems_ascat_wind.py` | Biscay | ASCAT L3 data, Copernicus Marine | works, ~1 day behind |
| `earthaccess_ascat_wind.py` | Biscay | ASCAT data, NASA PO.DAAC | search only: no Earthdata login here |
| `openeo_slstr_ir.py` | France | Sentinel-3 SLSTR, polar | works (daily mosaic) |
| `phidown_slstr_ir.py` | France | Sentinel-3 SLSTR, polar | works (needs `~/.s5cfg`) |
| `phidown_s1_wind.py` | Biscay | Sentinel-1 SAR winds (no ASCAT on CDSE) | works |

## Geostationary clouds

| | eumdac + Data Tailor | EUMETView WMS | NASA GIBS WMS | goes2go |
| --- | --- | --- | --- | --- |
| Satellites | Meteosat (MTG FCI, MSG SEVIRI) | Meteosat; global ring mosaic | GOES-East/West, Himawari; **no Meteosat** | GOES-East/West |
| What you get | **data** (radiance, converted to K) | **picture** (PNG, fixed palette) | **picture** (PNG) | **data** (K) |
| Time step | 10 min (FCI), 15 min (SEVIRI) | 10 min (FCI), 15 min (SEVIRI), 3 h (ring) | 10 min | 10 min full disk (5 min CONUS) |
| Latest image | ~1 h old without an NRT licence (403 before), minutes with it | **~20 min old** | **~30 min old** | ~15 min old |
| Archive | years | FCI since 2024-09 | ~90 days rolling (geostationary layers) | years (AWS) |
| Subsetting | server: crop, band, grid, projection | server: any bbox, size, time | server: any bbox, size, time | none: whole full disk |
| Volume, this case | 6.6 MB of 833 MB | 0.2-0.4 MB | 0.2 MB | 24.6 MB (the whole disk) |
| Wall time | 160 s (asynchronous job, 115 s queue + processing) | 1-2 s | 5 s | 5 s |
| Account | EUMETSAT (in Architeuthis already) | none | none | none |
| Extra dependency | none (eumdac already) | none (`requests`) | none (`requests`) | goes2go (pins s3fs, boto3) |

**EUMETView WMS** (https://view.eumetsat.int/geoserver/ows) is the
answer for the UI layer. One HTTP request per frame, any extent and
size, no account, ~20 min latency, 10 min steps, and `TIME` is a
standard WMS dimension: `dash-leaflet` can show it as a `WMSTileLayer`
whose `time` parameter is animated. Useful layers:

- `mtg_fd:ir105_hrfi`: MTG FCI IR 10.5 um, 10 min, 0 deg position.
  Covers out to about 70 deg from the sub-satellite point, so Saint-Pierre
  is seen at the limb (large, stretched pixels).
- `msg_fes:ir108`: MSG SEVIRI IR 10.8 um, 15 min.
- `mumi:worldcloudmap_ir108`: IR mosaic of the whole geostationary ring
  (Meteosat, GOES, Himawari), every 3 h: the only single layer covering
  a full Atlantic crossing, but too coarse in time for a smooth animation.

**NASA GIBS WMS** (https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi)
is the same thing for the western Atlantic:
`GOES-East_ABI_Band13_Clean_Infrared` every 10 min, also with WTMS tiles
for Leaflet. With EUMETView FCI east of ~35 W and GIBS GOES-East west of
it, a whole Atlantic crossing is covered at 10 min. The palettes differ,
so the two layers will not blend seamlessly.

Both are pictures: they cannot feed a computation (cloud cover along a
route, validation of forecasts). For that:

- **eumdac + Data Tailor** on `EO:EUM:DAT:0662` (FCI) gives exactly the
  requested grid, 99 % lighter than the full disk, through the existing
  `EUMETSATData`. The catch: **without an NRT licence, EUMETSAT refuses
  Meteosat imagery for about 45 min after sensing** (403 Unauthorised,
  for SEVIRI and FCI, directly or through the Data Tailor; measured:
  refused 35 min after the end of the scan, accepted from 45 min, always
  accepted from 2 h). The script therefore asks for images at least 1 h
  old (`NRT_DELAY`). The NRT licence can be requested from the EUMETSAT
  User Portal and would remove the delay. Data Tailor jobs are
  asynchronous (here 115 s), and must be deleted after download, failed
  ones included, or they eat the 20 GB quota.
- **goes2go** reads NOAA's AWS bucket anonymously and fast, but only
  whole files: 25 MB per full-disk IR image, whatever the area, and the
  geostationary projection must be resampled locally (done with
  `pyproj`). `goes_latest` fails for the first minutes of each hour,
  because it only lists the folder of the current hour; the script falls
  back to `goes_nearesttime(..., ignore_missing=True)`. On first import
  it writes `~/.config/goes2go/config.toml`. Installing it moved `s3fs`
  and `boto3`; `pip install "s3fs==2026.2.0" "boto3<1.43.118,>=1.43.115"`
  restored a consistent environment.

Other NASA libraries were considered: **earthaccess** has no
geostationary imagery (NASA's GOES products are NOAA's, on AWS), and
GIBS needs no library.

## ASCAT winds

| | eumdac | CMEMS (`copernicusmarine`) | EUMETView WMS | earthaccess (PO.DAAC) |
| --- | --- | --- | --- | --- |
| Product | OSI SAF coastal 12.5 km, L2 swath | WIND_GLO_PHY_L3_NRT_012_002, L3 0.125 deg grid | rendered arrows of the coastal product | OSI SAF coastal 12.5 km, L2 swath (same files as eumdac) |
| What you get | data | data | picture | data |
| Newest orbit at 18:08 UTC | starting 15:03 (~1.5 h after its end) | the previous day (daily files) | starting 13:21 | starting 13:21 |
| Latest pass covering Biscay | 10:11 (12:14 only clipped a corner) | 20:41 the day before | 11:01 | not downloaded |
| Subsetting | search by bbox, whole orbit files (Data Tailor possible: `OASWC12`) | server: bbox, days, variables (ARCO) | server: bbox, size, time | whole orbit files; bbox search barely filters |
| Volume, this case | 9.5 MB (3 orbits) of 44 MB (14 orbits) in 12 h | 3.0 MB (4 datasets x 3 days, uncompressed) | 0.1 MB | ~3 MB per orbit |
| Account | EUMETSAT (in Architeuthis) | CMEMS (in Architeuthis) | none | NASA Earthdata (none here) |

Metop passes cross the Bay of Biscay around 10-12 and 20-22 UTC, so
"latest" can mean up to 12 h old whatever the source.

**eumdac** stays the source for the latest passes, with the existing
wrapper once its search gets the bounding box and its cache is fixed
(below). **CMEMS** is the simplest for anything not urgent (hindcasts,
validation): the grid is regular, the subsetting server-side, the
credentials already in Architeuthis, but it lags by a day. Note that
version 202311 of these datasets retires on 2027-01-12. The
**EUMETView** ASCAT layers (`eps:m01_ascat_wind` Metop-B,
`eps:m03_ascat_wind` Metop-C) give a light map layer; their time values
stop at the last archived pass, about 5 h old, and a request after it
fails with "No nearest match", so the script steps back from that last
time until a pass covers 10 % of the area. **earthaccess** brings the same
OSI SAF files as eumdac, later and with an extra account: no reason to
use it for ASCAT.

No ASCAT on CDSE (openEO, phidown), nor on GIBS.

## Polar-orbit scans (secondary)

| | openEO | phidown |
| --- | --- | --- |
| Source | Sentinel-3 SLSTR S8 (10.85 um) | same |
| Latest image | daily mosaic, passes hours apart stitched together | latest pass, whatever its coverage of the area |
| Subsetting | server-side, exact grid | whole files of a product (S8 + geolocation only) |
| Volume | ~3-6 MB | 10-23 MB of 0.4-0.9 GB |
| Account | CDSE, browser login once, refresh token kept | search none; download CDSE S3 keys in plain text |

A polar orbiter covers a given area a few times a day at best, in strips:
this is why these images do not cover the whole map. For a scan on
demand, openEO is the better of the two (exact grid, no regridding).
phidown is only useful for its anonymous search and for Sentinel-1 SAR
winds (~1 km, not ASCAT).

## Recommendation

1. **UI cloud animation**: WMS layers, no download, no account:
   EUMETView `mtg_fd:ir105_hrfi` (Europe, eastern Atlantic) and GIBS
   `GOES-East_ABI_Band13_Clean_Infrared` (western Atlantic), with
   `mumi:worldcloudmap_ir108` as a 3-hourly global fallback. Next step:
   a `leaflet_wrapper` function returning these layers, and a time
   slider in `ui.py`.
2. **Cloud data for computation**: eumdac + Data Tailor on FCI, in
   `satellite.py` (the `TailoredEUMETSATData` of `eumdac_fci_ir.py`),
   with images 1 h old until an NRT licence is granted; goes2go if GOES
   data is ever needed west of 35 W.
3. **ASCAT**: eumdac with the existing wrapper, fixed; CMEMS L3 for
   non-urgent uses.
4. **Scans**: openEO if needed; phidown and earthaccess not needed.

## Issues found in `architeuthis/satellite.py`

- `EUMETSATData._download_data` searches by time only (`bbox` commented
  out), so it downloads every pass around the globe: 14 instead of 3
  here.
- Its cache never works: it opens the target file for writing (which
  truncates it) before testing `os.path.exists(fdst.name[-4:] + ".nc")`,
  which tests the extension rather than the file. Every run downloads
  again, and the zip files are never deleted.
- `netCDF4` fails on Windows paths with accents (this repository's path):
  the scripts read and write with `engine="h5netcdf"`. `ASCATData` and
  `PoseidonData` would fail the same way if `ARCHITEUTHIS_HOME` had
  accents.
- ASCAT `wind_dir` is `wind_to_direction` (where the wind goes), unlike
  the meteorological convention of models and Sentinel-1.

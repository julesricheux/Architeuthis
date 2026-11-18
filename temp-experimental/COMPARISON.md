# Satellite data: eumdac vs openEO vs phidown

Two test cases, run on 2026-11-18 around 11:00-13:00 UTC:

- **IR image**: latest IR image over France (N 51.5, S 41, W -5.5, E 10)
  on a 0.01 deg (~1 km) grid.
- **Winds**: latest ASCAT winds over the Bay of Biscay (N 52, S 40,
  W -20, E 0).

Run from the repository root; each script writes its data, metrics and
figure to `output/`, and `compare.py` draws `output/comparison.png`:

| Script | Case | Status |
| --- | --- | --- |
| `eumdac_fci_ir.py` | IR, MTG FCI via the Data Tailor | **403**: no access to Meteosat imagery with this key |
| `openeo_slstr_ir.py` | IR, Sentinel-3 SLSTR | works |
| `phidown_slstr_ir.py` | IR, Sentinel-3 SLSTR | works (needs `~/.s5cfg`, format in its docstring) |
| `eumdac_ascat_wind.py` | ASCAT, existing `ASCATData` + bbox | works when the EUMETSAT API is up |
| `phidown_s1_wind.py` | Sentinel-1 SAR winds (no ASCAT on CDSE) | works |
| (none) | winds with openEO | impossible: no wind collection on CDSE openEO |

## Results

| | eumdac | openEO | phidown |
| --- | --- | --- | --- |
| **IR source** | MTG FCI, geostationary, every 10 min | Sentinel-3 SLSTR S8, polar orbit | Sentinel-3 SLSTR S8, polar orbit |
| IR latest image | (no access) | 2026-11-17, daily mosaic: passes hours apart stitched together | 2026-11-18 09:17 UTC, published within ~3 h, but that pass only covers eastern France |
| IR downloaded | (no access; full disk 1 GB) | **3.4 MB**, ready grid | 23 MB of 924 MB (S8 + geolocation files of 3 granules), regridded locally |
| IR wall time | | 24-57 s | 15-20 s |
| **Wind source** | **ASCAT** coastal winds 12.5 km (OSI-104) | none | Sentinel-1 SAR winds ~1 km (not ASCAT) |
| Wind latest | 08:54 UTC pass | | 07:21 UTC acquisition, far offshore |
| Wind downloaded | 9.6 MB (3 passes) instead of 43 MB (14 passes) | | 83 MB of 321 MB (wind file of 2 products) |
| Wind wall time | 103 s, then 304 s and a 504 failure (API unstable) | | 10 s |
| **Subsetting** | server-side with the Data Tailor (crop, band, grid); search by bbox otherwise | server-side, any process graph | none: whole files of a product |
| **Credentials** | in Architeuthis already (keyring) | CDSE account, browser login once, refresh token kept | search: none; download: CDSE S3 keys in a plain-text file |
| **Reliability today** | API 500/504 for about an hour, retries of 3 min | fine | fine, fast S3 |

## Findings

**eumdac** is the only one with ASCAT, and the only one with
geostationary imagery, so the only one for a *latest* cloud image: SLSTR
covers France only a few times a day. The existing `ASCATData` worked
with one change (a bbox in the search). But Meteosat imagery downloads
are refused with this key (403 for SEVIRI and FCI, directly and through
the Data Tailor), which must be solved before the IR case can be judged.
The Data Tailor would then crop and resample on the server; it runs
asynchronous jobs to poll, download and delete (20 GB quota). The API was
the least reliable of the three during the tests.

**openEO** gives the cleanest result for the IR case: the exact grid,
3.4 MB, no regridding. Its limits are those of the CDSE catalogue (no
geostationary, no ASCAT, no winds at all) and the daily time step of its
SLSTR collection, which hides the overpass times and lags the catalogue
by about a day. First use needs a browser login, then it is unattended.

**phidown** is a search and file-download tool. Its anonymous search is
handy for discovery and sizes, and its S3 downloads are the fastest.
Downloading single files of a product avoids most of the volume (98 % for
SLSTR, 74 % for Sentinel-1) but not all, and the swaths must be
regridded locally. It sees new passes before openEO does. Its keys are
stored in plain text, and it has no ASCAT either.

## Recommendation

1. **Winds (ASCAT)**: keep eumdac and the existing wrapper. Pass the
   bounding box to the search (78 % less data here) and fix its cache
   (below). The Data Tailor also lists ASCAT products (`OASWC12`) if a
   finer cut is ever needed.
2. **Cloud images**: eumdac + Data Tailor on MTG FCI, once Meteosat
   imagery access is granted to the EUMETSAT account (check the
   account's data licences in the EUMETSAT Data Store). Until then,
   openEO on SLSTR is the best fallback when the overpass time matters
   less.
3. **phidown**: not needed; openEO covers the same data with server-side
   subsetting, and CDSE has no ASCAT.

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

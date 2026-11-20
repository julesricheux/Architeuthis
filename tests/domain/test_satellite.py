"""
Satellite observations, offline: ASCAT from EUMETSAT or Copernicus Marine,
and geostationary imagery from EUMETView and NASA GIBS.
"""
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import requests
import xarray as xr
from PIL import Image

from architeuthis.credentials import MissingCredentialError
from architeuthis.satellite import (
    ASCAT_SOURCES,
    EUMETVIEW_CALIBRATIONS,
    EUMETVIEW_LAYERS,
    ASCATData,
    CopernicusASCATData,
    CopernicusSatelliteData,
    EUMETSATASCATData,
    EUMETViewData,
    GeostationaryImagery,
    GIBSData,
    IMAGERY_CHANNELS,
    IMAGERY_COLORMAPS,
    native_layers,
    WMSImageryData,
)
from architeuthis.toolbox import image_utils, wms_utils
from architeuthis.toolbox.geo_utils import central_angle
from architeuthis.toolbox.windy_colormaps import SATELLITE_QUANTITIES, SATELLITE_STOPS, get_satellite_cmap

DOMAIN = dict(min_lon=-20.0, max_lon=0.0, min_lat=40.0, max_lat=52.0)
START, END = "2026-11-17 06:00", "2026-11-18 12:00"
ASCAT_VARIABLES = {"lat", "lon", "time", "valid_time", "wind_speed", "wind_dir"}


@pytest.fixture
def cmems_credentials(monkeypatch):
    monkeypatch.setenv("CMEMS_USER", "my-user")
    monkeypatch.setenv("CMEMS_PWD", "my-password")


# ------------------------------------------------------------------------------
# Copernicus Marine
# ------------------------------------------------------------------------------


def cmems_grid(times):
    """One CMEMS L3 dataset: two days on a 2 x 3 grid, as the server sends it."""
    latitude = np.array([41.0, 45.0])
    longitude = np.array([-15.0, -10.0, -5.0])
    days = pd.to_datetime(["2026-11-17", "2026-11-18"])
    measurement = np.full((2, 2, 3), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    for day, time in enumerate(times):
        measurement[day, :, :2] = np.datetime64(time)  # the swath misses the last column
    speed = np.where(np.isnat(measurement), np.nan, 10.0)
    dims = ("time", "latitude", "longitude")
    return xr.Dataset(
        {
            "wind_speed": (dims, speed),
            "wind_to_dir": (dims, np.where(np.isnat(measurement), np.nan, 90.0)),
            "measurement_time": (dims, measurement),
        },
        coords={"time": days, "latitude": latitude, "longitude": longitude},
    )


@patch("architeuthis.copernicus.copernicusmarine.subset")
def test_copernicus_ascat_downloads_each_metop_and_orbit_from_the_first_day(subset, cmems_credentials):
    subset.return_value.file_path = "dummy.nc"
    ascat = CopernicusASCATData("ascat", start=START, end=END, **DOMAIN)

    ascat._download_data()

    datasets = [call.kwargs["dataset_id"] for call in subset.call_args_list]
    assert datasets == [
        "cmems_obs-wind_glo_phy_nrt_l3-metopb-ascat-asc-0.125deg_P1D-i",
        "cmems_obs-wind_glo_phy_nrt_l3-metopb-ascat-des-0.125deg_P1D-i",
        "cmems_obs-wind_glo_phy_nrt_l3-metopc-ascat-asc-0.125deg_P1D-i",
        "cmems_obs-wind_glo_phy_nrt_l3-metopc-ascat-des-0.125deg_P1D-i",
    ]
    kwargs = subset.call_args.kwargs
    assert kwargs["username"] == "my-user"
    assert kwargs["password"] == "my-password"
    # Daily steps are stamped at midnight, in UTC: naive dates are local to the toolbox
    assert kwargs["start_datetime"] == pd.Timestamp("2026-11-17", tz="UTC")
    assert kwargs["end_datetime"] == pd.Timestamp(END, tz="UTC")
    assert kwargs["coordinates_selection_method"] == "inside"
    assert "minimum_depth" not in kwargs
    assert kwargs["minimum_longitude"] == DOMAIN["min_lon"]
    assert ascat.path == ["dummy.nc"] * 4
    assert "my-password" not in repr(vars(ascat))


@patch("architeuthis.copernicus.copernicusmarine.subset")
def test_copernicus_satellite_without_credentials_stops_before_downloading(subset):
    data = CopernicusSatelliteData("cmems", "dummy-dataset", ["wind_speed"], start=START, end=END)

    with pytest.raises(MissingCredentialError, match="CMEMS_USER, CMEMS_PWD"):
        data._download_data()

    subset.assert_not_called()


def test_copernicus_ascat_keeps_the_measurements_of_the_period():
    ascat = CopernicusASCATData("ascat", start=START, end=END, satellites=["metopb"], orbits=["asc", "des"])
    ascat.data = [
        cmems_grid(["2026-11-17 05:00", "2026-11-18 10:00"]),  # first one before the start
        cmems_grid(["2026-11-17 20:00", "2026-11-18 21:00"]),  # last one after the end
    ]

    ascat._convert_data()

    data = ascat.data
    assert ASCAT_VARIABLES <= set(data.data_vars)
    assert {data[name].dims for name in ASCAT_VARIABLES} == {("swath", "day", "latitude", "longitude")}
    kept = np.isfinite(data["wind_speed"].values)
    assert kept.sum() == 2 * 4  # two swaths of four cells
    assert np.all(np.isfinite(data["valid_time"].values) == kept)
    assert set(data["time"].values[kept].astype("datetime64[h]").astype(str)) == {"2026-11-18T10", "2026-11-17T20"}
    assert data["valid_time"].values[kept].min() == pd.Timestamp("2026-11-17 20:00", tz="UTC").timestamp()
    assert np.all(data["wind_dir"].values[kept] == 90.0)  # wind_to_dir, where the wind goes
    # Positions match the winds cell by cell once flattened
    assert np.all(data["lon"].values.ravel()[kept.ravel()] <= -10.0)


def test_copernicus_ascat_masks_the_cells_outside_the_domain():
    ascat = CopernicusASCATData("ascat", start=START, end=END, satellites=["metopb"], orbits=["asc"], min_lat=43.0)
    ascat.data = [cmems_grid(["2026-11-17 20:00", "2026-11-18 10:00"])]

    ascat._convert_data()

    kept = np.isfinite(ascat.data["wind_speed"].values)
    assert kept.sum() == 2 * 2
    assert np.all(ascat.data["lat"].values[kept] == 45.0)


# ------------------------------------------------------------------------------
# EUMETSAT
# ------------------------------------------------------------------------------


def eumetsat_product(name, content=b"swath"):
    """A Data Store product whose download is a zip holding one NetCDF file."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(f"folder/{name}.nc", content)
    product = MagicMock()
    stream = io.BytesIO(archive.getvalue())
    stream.name = f"{name}.zip"
    product.open.return_value.__enter__.return_value = stream
    return product


def eumetsat_ascat(tmp_path, products):
    ascat = EUMETSATASCATData("ascat", start=START, end=END, verbose=False, **DOMAIN)
    ascat.output_path = str(tmp_path)
    ascat.collection = MagicMock()
    ascat.collection.search.return_value = products
    return ascat


def test_eumetsat_searches_the_domain_and_unzips_the_products(tmp_path):
    ascat = eumetsat_ascat(tmp_path, [eumetsat_product("a"), eumetsat_product("b")])

    ascat._download_data()

    kwargs = ascat.collection.search.call_args.kwargs
    assert kwargs["bbox"] == "-20.0, 40.0, 0.0, 52.0"
    assert kwargs["dtstart"] == START
    assert sorted(ascat.path) == [str(tmp_path / "a.nc"), str(tmp_path / "b.nc")]
    assert (tmp_path / "a.nc").read_bytes() == b"swath"


def test_eumetsat_does_not_download_a_product_again(tmp_path):
    eumetsat_ascat(tmp_path, [eumetsat_product("a", b"first")])._download_data()
    ascat = eumetsat_ascat(tmp_path, [eumetsat_product("a", b"second")])

    ascat._download_data()

    assert ascat.path == [str(tmp_path / "a.nc")]
    assert (tmp_path / "a.nc").read_bytes() == b"first"
    assert not list(tmp_path.glob("*.part"))


def test_eumetsat_without_product_raises(tmp_path):
    ascat = eumetsat_ascat(tmp_path, [])

    with pytest.raises(FileNotFoundError, match="No product"):
        ascat._download_data()


def test_eumetsat_ascat_gives_the_same_variables_as_copernicus():
    ascat = EUMETSATASCATData("ascat", start=START, end=END, **DOMAIN)
    dims = ("NUMROWS", "NUMCELLS")
    ascat.data = xr.Dataset({
        "lat": (dims, [[45.0, 45.0], [60.0, 45.0]]),
        "lon": (dims, [[350.0, 345.0], [350.0, 100.0]]),
        "time": (dims, np.full((2, 2), np.datetime64("2026-11-18T10:00", "ns"))),
        "wind_speed": (dims, np.full((2, 2), 8.0)),
        "wind_dir": (dims, np.full((2, 2), 45.0)),
    })

    ascat._convert_data()

    assert ASCAT_VARIABLES <= set(ascat.data.data_vars)
    assert np.isfinite(ascat.data["wind_speed"].values).tolist() == [[True, True], [False, False]]
    assert ascat.data["lon"].values[0].tolist() == [-10.0, -15.0]
    assert ascat.data["valid_time"].values[0, 0] == pd.Timestamp("2026-11-18 10:00", tz="UTC").timestamp()


# ------------------------------------------------------------------------------
# Source selection
# ------------------------------------------------------------------------------


def loads(data):
    """A `load_data` replacement that fills an object with `data`."""

    def load_data(self):
        self.data = data
        self.path = [self.name]

    return load_data


def fails(error):
    def load_data(self):
        raise error

    return load_data


def test_ascat_comes_from_eumetsat_first():
    with (
        patch.object(EUMETSATASCATData, "load_data", loads("eumetsat data")),
        patch.object(CopernicusASCATData, "load_data", fails(AssertionError("not needed"))),
    ):
        ascat = ASCATData("ascat", start=START, end=END, **DOMAIN)
        ascat.load_data()

    assert ascat.source == "eumetsat"
    assert ascat.data == "eumetsat data"


def test_ascat_falls_back_on_copernicus_when_eumetsat_fails(capsys):
    with (
        patch.object(EUMETSATASCATData, "load_data", fails(ConnectionError("504 Gateway Timeout"))),
        patch.object(CopernicusASCATData, "load_data", loads("cmems data")),
    ):
        ascat = ASCATData("ascat", start=START, end=END, verbose=False, **DOMAIN)
        ascat.load_data()

    assert ascat.source == "cmems"
    assert ascat.data == "cmems data"
    output = capsys.readouterr().out
    assert "⚠️ ASCAT from eumetsat failed (ConnectionError: 504 Gateway Timeout), trying cmems." in output


def test_ascat_from_copernicus_only_never_asks_eumetsat():
    with (
        patch.object(EUMETSATASCATData, "load_data", fails(AssertionError("not asked"))),
        patch.object(CopernicusASCATData, "load_data", loads("cmems data")),
    ):
        ascat = ASCATData("ascat", start=START, end=END, sources="cmems")
        ascat.load_data()

    assert ascat.source == "cmems"


def test_ascat_raises_the_last_error_when_every_source_fails(capsys):
    with (
        patch.object(EUMETSATASCATData, "load_data", fails(ConnectionError("down"))),
        patch.object(CopernicusASCATData, "load_data", fails(MissingCredentialError("CMEMS_USER"))),
        pytest.raises(MissingCredentialError),
    ):
        ASCATData("ascat", start=START, end=END).load_data()

    assert capsys.readouterr().out.count("⚠️ ASCAT from") == 2


def test_ascat_passes_its_period_and_domain_to_the_source():
    seen = {}

    def load_data(self):
        seen.update(vars(self))
        self.data = None

    with patch.object(CopernicusASCATData, "load_data", load_data):
        ASCATData("ascat", start=START, end=END, verbose=False, sources=["cmems"], **DOMAIN).load_data()

    assert {key: seen[key] for key in ("start", "end", "verbose", *DOMAIN)} == {
        "start": START, "end": END, "verbose": False, **DOMAIN,
    }


def test_ascat_refuses_an_unknown_source():
    with pytest.raises(ValueError, match="Unknown ASCAT source"):
        ASCATData("ascat", sources=["eumetsat", "noaa"])
    assert set(ASCAT_SOURCES) == {"eumetsat", "cmems"}


# ------------------------------------------------------------------------------
# Geostationary imagery: map service helpers
# ------------------------------------------------------------------------------

CAPABILITIES = """<WMS_Capabilities><Capability><Layer>
<Layer><Name>other</Name><Dimension name="time">2020-01-01T00:00:00Z</Dimension></Layer>
<Layer><Name>mtg_fd:ir105_hrfi</Name>
<Dimension name="time" units="ISO8601">2026-11-19T15:00:00Z/2026-11-19T16:00:00Z/PT10M,2026-11-19T16:20:00Z</Dimension>
</Layer></Layer></Capability></WMS_Capabilities>"""


def test_time_extent_reads_the_dimension_of_the_layer():
    assert wms_utils.time_extent(CAPABILITIES, "mtg_fd:ir105_hrfi") == [
        "2026-11-19T15:00:00Z/2026-11-19T16:00:00Z/PT10M", "2026-11-19T16:20:00Z",
    ]
    with pytest.raises(KeyError):
        wms_utils.time_extent(CAPABILITIES, "missing")


def test_available_times_expand_intervals_over_the_period_only():
    extent = wms_utils.time_extent(CAPABILITIES, "mtg_fd:ir105_hrfi")

    times = wms_utils.available_times(extent, "2026-11-19 15:45", "2026-11-19 17:00")

    assert list(times.strftime("%H:%M")) == ["15:50", "16:00", "16:20"]
    assert str(times.tz) == "UTC"
    assert wms_utils.available_times(extent, "2026-11-20", "2026-11-21").empty


def test_gibs_time_domain_asks_the_period_of_the_layer(monkeypatch):
    seen = {}

    def get(url, timeout):
        seen["url"] = url
        return SimpleNamespace(
            text="<Domains><Domain>2026-11-19T16:00:00Z/2026-11-19T16:30:00Z/PT10M</Domain></Domains>",
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(wms_utils.requests, "get", get)
    extent = wms_utils.gibs_time_domain("GOES-East_ABI_Band13_Clean_Infrared", "2026-11-19 16:00", "2026-11-19 17:00")

    assert extent == ["2026-11-19T16:00:00Z/2026-11-19T16:30:00Z/PT10M"]
    assert "/GOES-East_ABI_Band13_Clean_Infrared/default/2km/all/" in seen["url"]
    assert seen["url"].endswith("2026-11-19T16:00:00Z--2026-11-19T17:00:00Z.xml")


def test_get_map_asks_latitude_first_and_refuses_an_exception(monkeypatch):
    seen = {}

    def get(url, params, timeout):
        seen.update(params)
        return SimpleNamespace(
            headers={"content-type": "text/xml"}, text="<ServiceException>no</ServiceException>",
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(wms_utils.requests, "get", get)
    with pytest.raises(RuntimeError, match="ServiceException"):
        wms_utils.get_map("https://server", "layer", (-10.0, 40.0, 0.0, 45.0), (10, 5), "2026-11-19 16:00")

    assert seen["BBOX"] == "40.0,-10.0,45.0,0.0"
    assert seen["TIME"] == "2026-11-19T16:00:00Z"
    assert (seen["WIDTH"], seen["HEIGHT"], seen["CRS"]) == (10, 5, "EPSG:4326")


GIBS_COLORMAP = """<ColorMaps><ColorMap title="Brightness Temperature" units="&#176;C">
<Entries>
<ColorMapEntry rgb="0,0,0" transparent="true" sourceValue="[0]" nodata="true"/>
<ColorMapEntry rgb="255,0,0" transparent="false" value="[-100,-90)"/>
<ColorMapEntry rgb="100,100,100" transparent="false" value="[-78,-77)"/>
<ColorMapEntry rgb="100,100,100" transparent="false" value="[20,21)"/>
</Entries></ColorMap></ColorMaps>"""


def test_gibs_colormap_gives_the_middle_of_each_interval_in_kelvins():
    colours, values = wms_utils.parse_gibs_colormap(GIBS_COLORMAP)

    assert colours.tolist() == [[255, 0, 0], [100, 100, 100], [100, 100, 100]]
    np.testing.assert_allclose(values, [-95.0 + 273.15, -77.5 + 273.15, 20.5 + 273.15])


# ------------------------------------------------------------------------------
# Geostationary imagery: image treatment
# ------------------------------------------------------------------------------


def grey_image(levels, alpha=255):
    """RGBA pixels of grey levels, one per value of `levels`."""
    levels = np.asarray(levels, dtype=np.uint8)
    return np.stack([levels, levels, levels, np.full_like(levels, alpha)], axis=-1)


def test_png_round_trip():
    rgba = grey_image(np.arange(12).reshape(3, 4))

    np.testing.assert_array_equal(image_utils.decode_png(image_utils.encode_png(rgba)), rgba)


def test_a_linear_palette_is_inverted_exactly_and_transparency_is_nan():
    palette = image_utils.linear_gray_palette(301.2, -0.428)
    rgba = grey_image([[0, 100], [255, 100]])
    rgba[1, 1, 3] = 0

    bt = image_utils.invert_palette(rgba, *palette)

    np.testing.assert_allclose(bt[0], [301.2, 301.2 - 42.8])
    assert bt[1, 0] == pytest.approx(301.2 - 0.428 * 255)
    assert np.isnan(bt[1, 1])


def ambiguous_palette():
    """Greys 90-110 for 290-310 K and red for 190 K; grey 100 again for 195 K, white for 182 K."""
    greys = np.arange(90, 111)
    colours = np.vstack([np.repeat(greys[:, None], 3, axis=1), [[255, 0, 0], [100, 100, 100], [250, 250, 250]]])
    values = np.concatenate([200.0 + greys, [190.0, 195.0, 182.0]])
    secondary = np.zeros(len(values), dtype=bool)
    secondary[-2:] = True
    return colours.astype(np.uint8), values, secondary


def test_a_repeated_colour_takes_the_reading_of_its_neighbours():
    colours, values, secondary = ambiguous_palette()
    warm = grey_image(np.full((9, 9), 95))
    warm[4, 4, :3] = 100  # among warm greys: 300 K
    cold = np.zeros((9, 9, 4), dtype=np.uint8)
    cold[..., 0] = cold[..., 3] = 255  # red
    cold[4, 4, :3] = 100  # among cold cloud tops: 195 K

    bt = image_utils.invert_palette(np.stack([warm, cold]), colours, values, secondary=secondary)

    assert bt[0, 4, 4] == 300.0
    assert bt[1, 4, 4] == 195.0
    assert bt[0, 0, 0] == 295.0 and bt[1, 0, 0] == 190.0


def test_a_colour_only_the_secondary_part_has_is_read_from_it():
    colours, values, secondary = ambiguous_palette()

    bt = image_utils.invert_palette(grey_image(np.full((3, 3), 250)), colours, values, secondary=secondary)

    assert (bt == 182.0).all()


def test_values_are_drawn_on_a_colour_scale_with_clear_sky_fading_out():
    rgba = image_utils.values_to_rgba(np.array([200.0, 300.0, np.nan, 270.0, 285.0]), transparent_above=270.0, fade=10.0)

    assert rgba[0, :3].tolist() == [255, 255, 255]  # gray_r: cold is white
    assert rgba[1, :3].tolist() == [0, 0, 0]
    assert rgba[:, 3].tolist() == [255, 0, 0, 255, 0]


def test_softmin_weights_split_evenly_on_the_seam_and_sum_to_one():
    weights = image_utils.softmin_weights([np.array([10.0, 40.0, 60.0]), np.array([60.0, 40.0, 10.0])], width=2.0)

    np.testing.assert_allclose(weights.sum(axis=0), 1.0)
    np.testing.assert_allclose(weights[:, 1], [0.5, 0.5])
    assert weights[0, 0] > 0.999 and weights[1, 2] > 0.999


def test_blend_lets_the_other_layers_fill_a_missing_value():
    blended = image_utils.blend(
        [np.array([280.0, np.nan, np.nan]), np.array([260.0, 250.0, np.nan])], np.array([[0.5], [0.5]]),
    )

    np.testing.assert_allclose(blended[:2], [270.0, 250.0])
    assert np.isnan(blended[2])


def test_save_animation_writes_every_frame(tmp_path):
    frames = [grey_image(np.full((4, 6), level)) for level in (0, 128, 255)]

    path = image_utils.save_animation(frames, str(tmp_path / "frames.gif"))

    with Image.open(path) as gif:
        assert gif.n_frames == 3
        assert gif.size == (6, 4)


def test_central_angle_from_the_sub_satellite_point():
    assert central_angle(0.0, -75.2, 0.0, -75.2) == pytest.approx(0.0)
    assert central_angle(0.0, 15.0, 0.0, 0.0) == pytest.approx(15.0)
    assert central_angle(90.0, 30.0, 0.0, 0.0) == pytest.approx(90.0)


# ------------------------------------------------------------------------------
# Geostationary imagery: sources
# ------------------------------------------------------------------------------

IMAGERY_DOMAIN = dict(min_lon=-10.0, max_lon=0.0, min_lat=40.0, max_lat=45.0, resolution=1.0)
IMAGERY_PERIOD = dict(start="2026-11-19 15:45", end="2026-11-19 16:30")


def server_image(layer, size, time):
    """The image a replaced server sends: grey 100 with a black north-west corner for the
    infrared, grey 51 for the visible; empty at 16:00, and for the visible at 16:20 too."""
    width, height = size
    visible = "vis" in layer
    empty = time.minute == 0 or (visible and time.minute == 20)
    rgba = grey_image(np.full((height, width), 51 if visible else 100), alpha=0 if empty else 255)
    if not visible:
        rgba[0, 0, :3] = 0
    return image_utils.encode_png(rgba)


@pytest.fixture
def eumetview(tmp_path, monkeypatch):
    """EUMETView over 10 x 5 pixels, its server replaced (`server_image`), at 15:50, 16:00
    and 16:20, of the infrared."""
    asked = []

    def get_map(url, layer, bounds, size, time=None, style="", timeout=None):
        asked.append((layer, time))
        return server_image(layer, size, time)

    capabilities = CAPABILITIES.replace("</Layer></Layer>", """</Layer>
<Layer><Name>mtg_fd:vis06_hrfi</Name>
<Dimension name="time">2026-11-19T15:00:00Z/2026-11-19T16:30:00Z/PT10M</Dimension>
</Layer></Layer>""")
    monkeypatch.setattr(wms_utils, "capabilities", lambda url: capabilities)
    monkeypatch.setattr(wms_utils, "get_map", get_map)
    imagery = EUMETViewData("eumetview", verbose=False, **IMAGERY_PERIOD, **IMAGERY_DOMAIN)
    imagery.output_path = str(tmp_path)
    imagery.asked = asked
    return imagery


def test_eumetview_gives_brightness_temperatures_on_the_grid(eumetview):
    eumetview.load_data()
    offset, slope = EUMETVIEW_CALIBRATIONS["mtg_fd:ir105_hrfi"]
    bt = eumetview.data["bt"]

    assert eumetview.size == (10, 5)
    assert eumetview.variables == ["bt"]
    assert bt.dims == ("valid_time", "latitude", "longitude")
    np.testing.assert_allclose(bt["latitude"], eumetview.grid()[0])
    np.testing.assert_allclose(bt["latitude"], [40.5, 41.5, 42.5, 43.5, 44.5])
    # The first row of the PNG is the north
    assert float(bt.sel(latitude=44.5, longitude=-9.5)[0]) == pytest.approx(offset)
    assert float(bt.sel(latitude=40.5, longitude=-0.5)[0]) == pytest.approx(offset + slope * 100, abs=1e-4)
    assert eumetview.subsatellite_lon == 0.0
    # And image() draws it north up again, the warmest pixel the darkest grey
    image = eumetview.image(0)
    assert image[0, 0, 0] < image[-1, -1, 0]
    assert image[0, 0, 0] == image[0, 0, 1] == image[0, 0, 2]


def test_an_empty_image_is_left_out_and_not_cached(eumetview, tmp_path, capsys):
    eumetview.load_data()

    assert list(eumetview.times().strftime("%H:%M")) == ["15:50", "16:20"]
    assert "⚠️ Empty image of mtg_fd:ir105_hrfi at 2026-11-19 16:00, left out." in capsys.readouterr().out
    assert sorted(path.name for path in tmp_path.rglob("*.png")) == ["20261119T155000.png", "20261119T162000.png"]
    assert all(path.parent.parent.name == "mtg_fd_ir105_hrfi" for path in tmp_path.rglob("*.png"))

    # A later run asks again for the empty image only
    eumetview.asked.clear()
    eumetview.load_data()
    assert [time.strftime("%H:%M") for _, time in eumetview.asked] == ["16:00"]


def test_several_channels_take_the_times_every_channel_has(eumetview):
    eumetview = EUMETViewData("eumetview", verbose=False, channels=["visible", "ir", "visible"], **IMAGERY_PERIOD, **IMAGERY_DOMAIN)
    eumetview.output_path = str(Path(eumetview.output_path).parent / "tests")
    eumetview.load_data()

    assert eumetview.channels == ["visible", "ir"]
    assert eumetview.variables == ["brightness", "bt"]
    assert set(eumetview.wms_layers.values()) == {"mtg_fd:vis06_hrfi", "mtg_fd:ir105_hrfi"}
    # 16:20 has no visible image: only 15:50 is in both
    assert list(eumetview.times().strftime("%H:%M")) == ["15:50"]
    np.testing.assert_allclose(eumetview.data["brightness"], 0.2)
    assert eumetview.data["bt"].shape == eumetview.data["brightness"].shape
    for channel, colormap in (("ir", None), ("ir", "infra"), ("ir", "blue"), ("visible", None)):
        assert eumetview.image(0, channel, colormap=colormap).shape == (5, 10, 4)


def test_the_colour_scale_is_chosen_when_drawing(eumetview):
    eumetview.load_data()

    # One channel, several colour scales: Infra+ by default, Blue on demand
    np.testing.assert_array_equal(eumetview.image(0), eumetview.image(0, "ir", colormap="infra"))
    assert not np.array_equal(eumetview.image(0, colormap="blue"), eumetview.image(0))
    with pytest.raises(ValueError, match="does not draw bt"):
        eumetview.image(0, colormap="visible")
    with pytest.raises(ValueError, match="visible channel is not loaded"):
        eumetview.image(0, "visible")
    with pytest.raises(ValueError, match="Unknown imagery channel"):
        eumetview.image(0, "blue")


def test_every_image_empty_raises(eumetview, monkeypatch):
    empty = image_utils.encode_png(grey_image(np.zeros((5, 10)), alpha=0))
    monkeypatch.setattr(wms_utils, "get_map", lambda *args, **kwargs: empty)

    with pytest.raises(FileNotFoundError, match="empty"):
        eumetview.load_data()


def test_time_step_keeps_the_times_on_its_multiples(eumetview):
    eumetview.end = "2026-11-19 16:00"
    eumetview.time_step = "30min"

    with pytest.raises(FileNotFoundError, match="empty"):
        eumetview.load_data()  # 16:00 only, empty
    assert [time.strftime("%H:%M") for _, time in eumetview.asked] == ["16:00"]


def test_no_time_in_the_period_raises(eumetview):
    eumetview.start, eumetview.end = "2026-11-20", "2026-11-21"

    with pytest.raises(FileNotFoundError, match="No image"):
        eumetview.load_data()


@pytest.fixture
def gibs_server(monkeypatch):
    """GIBS replaced: its times, its colormap, and images of grey 100 (51 for the visible)."""

    def get(url, timeout):
        assert url.endswith("Clean_Longwave_Infrared_Window_Band.xml")
        return SimpleNamespace(text=GIBS_COLORMAP, raise_for_status=lambda: None)

    def get_map(url, layer, bounds, size, time=None, style="", timeout=None):
        level = 51 if "Visible" in layer else 100
        return image_utils.encode_png(grey_image(np.full((size[1], size[0]), level)))

    monkeypatch.setattr("architeuthis.satellite.requests.get", get)
    monkeypatch.setattr(wms_utils, "gibs_time_domain", lambda layer, start, end: ["2026-11-19T16:00:00Z/2026-11-19T16:20:00Z/PT10M"])
    monkeypatch.setattr(wms_utils, "get_map", get_map)


def test_gibs_reads_its_colormap_and_its_repeated_greys_from_their_context(gibs_server, tmp_path):
    gibs = GIBSData("gibs", verbose=False, **IMAGERY_PERIOD, **IMAGERY_DOMAIN)
    gibs.output_path = str(tmp_path)
    gibs.load_data()

    assert gibs.secondary["ir"].tolist() == [False, True, False]  # the cold grey
    assert list(gibs.times().strftime("%H:%M")) == ["16:00", "16:10", "16:20"]
    # Uniform grey 100: no cold neighbour, so the warm reading
    np.testing.assert_allclose(gibs.data["bt"].values, 20.5 + 273.15)
    assert gibs.subsatellite_lon == -75.2


def test_gibs_reads_the_capabilities_when_describe_domains_fails(gibs_server, monkeypatch, tmp_path, capsys):
    def unavailable(layer, start, end):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(wms_utils, "gibs_time_domain", unavailable)
    monkeypatch.setattr(wms_utils, "capabilities", lambda url: CAPABILITIES.replace("mtg_fd:ir105_hrfi", "GOES-East_ABI_Band13_Clean_Infrared"))
    gibs = GIBSData("gibs", verbose=False, **IMAGERY_PERIOD, **IMAGERY_DOMAIN)
    gibs.output_path = str(tmp_path)
    gibs.load_data()

    assert list(gibs.times().strftime("%H:%M")) == ["15:50", "16:00", "16:20"]
    assert "⚠️ GIBS DescribeDomains failed (down), reading the capabilities." in capsys.readouterr().out


def test_gibs_visible_needs_no_colormap(gibs_server, monkeypatch, tmp_path):
    def get(url, timeout):
        raise AssertionError("no colormap to download")

    monkeypatch.setattr("architeuthis.satellite.requests.get", get)
    goes = GIBSData("goes", channels="visible", verbose=False, **IMAGERY_PERIOD, **IMAGERY_DOMAIN)
    goes.output_path = str(tmp_path)
    goes.load_data()

    np.testing.assert_allclose(goes.data["brightness"], 0.2)
    assert "bt" not in goes.data


def test_a_source_without_a_server_layer_for_a_channel_is_refused():
    with pytest.raises(ValueError, match="no server layer"):
        WMSImageryData("server", "https://server", {"ir": "infrared"}, channels=["ir", "visible"])


# ------------------------------------------------------------------------------
# Geostationary imagery: one layer from several satellites
# ------------------------------------------------------------------------------

COMPOSITE_DOMAIN = dict(min_lon=-75.0, max_lon=5.0, min_lat=35.0, max_lat=60.0, resolution=5.0)


def source(cls, name, times, values, error=None, channels="ir", resolution=5.0):
    """A source of the composite domain whose `load_data` gives, for each of its channels,
    uniform `values` (or a function of latitude and longitude, or a dict of either by
    quantity), or fails."""
    imagery = cls(name, verbose=False, channels=channels, **IMAGERY_PERIOD, **(COMPOSITE_DOMAIN | {"resolution": resolution}))
    latitude, longitude = imagery.grid()

    def load_data():
        if error is not None:
            raise error
        lat, lon = np.meshgrid(latitude, longitude, indexing="ij")
        variables = {}
        for variable in imagery.variables:
            value = values[variable] if isinstance(values, dict) else values
            field = value(lat, lon) if callable(value) else np.full(lat.shape, value)
            variables[variable] = (("valid_time", "latitude", "longitude"), np.repeat(field[None], len(times), axis=0).astype(np.float32))
        imagery.data = xr.Dataset(
            variables,
            coords={"valid_time": np.array(times, dtype=float), "latitude": latitude, "longitude": longitude},
        )

    imagery.load_data = load_data
    return imagery


def composite(*sources, **options):
    options = {"channels": sources[0].channels} | options
    domain = COMPOSITE_DOMAIN | {"resolution": sources[0].resolution}
    clouds = GeostationaryImagery("clouds", sources=sources, verbose=False, **IMAGERY_PERIOD, **domain, **options)
    clouds.load_data()
    return clouds


def test_each_pixel_comes_from_the_satellite_that_sees_it_best():
    clouds = composite(source(EUMETViewData, "meteosat", [0.0, 600.0], 280.0), source(GIBSData, "goes", [600.0, 1200.0], 260.0))
    bt = clouds.data["bt"].sel(latitude=47.5, method="nearest")
    weight = clouds.data["weight"]

    assert clouds.data["valid_time"].values.tolist() == [600.0]  # the times both have
    assert list(clouds.data["source"].values) == ["meteosat", "goes"]
    np.testing.assert_allclose(weight.sum("source"), 1.0, rtol=1e-6)
    assert float(bt.sel(longitude=2.5)[0]) == pytest.approx(280.0, abs=0.01)  # Europe: Meteosat
    assert float(bt.sel(longitude=-72.5)[0]) == pytest.approx(260.0, abs=0.01)  # Americas: GOES-East
    # Smooth across the seam, halfway between both sub-satellite points
    across = bt.sel(longitude=slice(-50.0, -25.0))[0].values
    assert np.all(np.diff(across) > 0)
    assert 260.0 < across.min() and across.max() < 280.0
    assert clouds.image(0).shape == (5, 16, 4)


def test_the_times_of_any_source_when_incomplete_layers_are_allowed():
    clouds = composite(
        source(EUMETViewData, "meteosat", [0.0, 600.0], 280.0), source(GIBSData, "goes", [600.0], 260.0), complete=False,
    )

    assert clouds.data["valid_time"].values.tolist() == [0.0, 600.0]
    # Only Meteosat at 0 s: it fills the whole layer
    np.testing.assert_allclose(clouds.data["bt"].isel(valid_time=0), 280.0)


def test_a_source_that_fails_is_left_out(capsys):
    clouds = composite(
        source(EUMETViewData, "meteosat", [0.0], 280.0), source(GIBSData, "goes", [0.0], 260.0, error=requests.ConnectionError("down")),
    )

    assert list(clouds.data["source"].values) == ["meteosat"]
    np.testing.assert_allclose(clouds.data["bt"], 280.0)
    assert "⚠️ Imagery from goes left out (ConnectionError: down)." in capsys.readouterr().out


def test_the_composite_raises_when_every_source_fails():
    with pytest.raises(FileNotFoundError):
        composite(
            source(EUMETViewData, "meteosat", [0.0], 280.0, error=ValueError("bad")),
            source(GIBSData, "goes", [0.0], 260.0, error=FileNotFoundError("none")),
        )


def test_the_default_sources_are_eumetview_and_gibs_over_the_same_domain_and_channels():
    clouds = GeostationaryImagery("clouds", time_step="1h", channels=["ir", "visible"], **IMAGERY_PERIOD, **COMPOSITE_DOMAIN)

    assert [type(source) for source in clouds.sources] == [EUMETViewData, GIBSData]
    assert clouds.channels == ["ir", "visible"]
    assert clouds.variables == ["bt", "brightness"]
    for source_ in clouds.sources:
        assert (source_.min_lon, source_.max_lat, source_.resolution, source_.time_step) == (-75.0, 60.0, 5.0, "1h")
        assert source_.size == clouds.size
        assert source_.channels == ["ir", "visible"]
    meteosat, goes = clouds.sources
    assert meteosat.wms_layers == {"ir": "mtg_fd:ir105_hrfi", "visible": "mtg_fd:vis06_hrfi"}
    assert goes.wms_layers == {"ir": "GOES-East_ABI_Band13_Clean_Infrared", "visible": "GOES-East_ABI_Band2_Red_Visible_1km"}
    for imagery in (meteosat, goes):
        colours, values = imagery.palettes["visible"]
        assert values[0] == 0.0 and values[-1] == pytest.approx(1.0)


def scene(lat, lon):
    """A visible scene: brightness varying over the domain, from 0.1 to 0.7."""
    return 0.4 + 0.3 * np.sin(np.radians(lat * 20.0)) * np.cos(np.radians(lon * 9.0))


def test_visible_levels_of_the_other_sources_are_matched_along_the_seam():
    meteosat = source(EUMETViewData, "meteosat", [0.0, 600.0], scene, channels="visible", resolution=1.0)
    goes = source(GIBSData, "goes", [0.0, 600.0], lambda lat, lon: 0.5 * scene(lat, lon) + 0.1, channels="visible", resolution=1.0)

    daylight = composite(meteosat, goes)

    assert daylight.variables == ["brightness"]
    assert daylight.matched == ["visible"]
    gain = daylight.data["gain"].sel(channel="visible")
    np.testing.assert_allclose(gain.sel(source="goes"), 2.0, rtol=1e-3)
    np.testing.assert_allclose(daylight.data["offset"].sel(channel="visible", source="goes"), -0.2, atol=1e-3)
    np.testing.assert_allclose(gain.sel(source="meteosat"), 1.0)
    # Matched, both give the scene of Meteosat everywhere
    lat, lon = np.meshgrid(*daylight.grid(), indexing="ij")
    np.testing.assert_allclose(daylight.data["brightness"].isel(valid_time=0), scene(lat, lon), atol=1e-3)


def test_infrared_and_visible_together_only_the_visible_matched():
    values = {"bt": lambda lat, lon: 250.0 + lon / 10.0, "brightness": scene}
    goes_values = {"bt": lambda lat, lon: 260.0 + lon / 10.0, "brightness": lambda lat, lon: 0.5 * scene(lat, lon) + 0.1}
    channels = ["ir", "visible"]
    clouds = composite(
        source(EUMETViewData, "meteosat", [0.0], values, channels=channels, resolution=1.0),
        source(GIBSData, "goes", [0.0], goes_values, channels=channels, resolution=1.0),
    )

    assert clouds.matched == ["visible"]
    assert list(clouds.data["channel"].values) == ["ir", "visible"]
    np.testing.assert_allclose(clouds.data["gain"].sel(channel="ir"), 1.0)
    np.testing.assert_allclose(clouds.data["gain"].sel(channel="visible", source="goes"), 2.0, rtol=1e-3)
    # The infrared of each satellite as it is: 10 K apart from one side to the other
    bt = clouds.data["bt"].isel(valid_time=0).sel(latitude=47.5, method="nearest")
    assert float(bt.sel(longitude=4.5, method="nearest")) == pytest.approx(250.45, abs=0.05)
    assert float(bt.sel(longitude=-74.5, method="nearest")) == pytest.approx(252.55, abs=0.05)


def test_a_dark_visible_reference_is_not_matched():
    night = composite(
        source(EUMETViewData, "meteosat", [0.0], 0.0, channels="visible", resolution=1.0),
        source(GIBSData, "goes", [0.0], scene, channels="visible", resolution=1.0),
    )

    np.testing.assert_allclose(night.data["gain"], 1.0)


def test_the_sources_of_a_composite_give_its_channels():
    with pytest.raises(ValueError, match="No source gives the ir channel"):
        GeostationaryImagery("clouds", sources=[source(EUMETViewData, "meteosat", [0.0], scene, channels="visible")])
    with pytest.raises(ValueError, match="Unknown imagery channel"):
        GeostationaryImagery("clouds", channels=["ir", "water_vapour"])


# ------------------------------------------------------------------------------
# Geostationary imagery: colour scales
# ------------------------------------------------------------------------------


def colour_of(name, value):
    """RGBA of a value in a colour scale, 0-255."""
    colormap, norm = get_satellite_cmap(name)
    return np.round(np.array(colormap(norm(value))) * 255).astype(int).tolist()


def test_infra_follows_the_infra_plus_legend_of_windy():
    colormap, norm = get_satellite_cmap("infra")

    assert (norm.vmin, norm.vmax) == (182.0, 321.0)
    assert colour_of("infra", 321.0) == [24, 24, 24, 255]
    assert colour_of("infra", 182.0) == [48, 0, 0, 255]
    # The step at 240 K: grey above, coloured cloud tops below
    assert np.allclose(colour_of("infra", 240.1), [240, 240, 240, 255], atol=3)
    assert np.allclose(colour_of("infra", 239.9), [64, 64, 163, 255], atol=3)
    assert np.allclose(colour_of("infra", 220.0), [163, 253, 61, 255], atol=3)
    assert np.allclose(colour_of("infra", 210.0), [251, 128, 34, 255], atol=3)


def test_blue_is_white_clouds_over_a_transparent_clear_sky():
    assert colour_of("blue", 290.0)[3] == 0
    assert colour_of("blue", 300.0)[3] == 0  # warmer than the scale: still clear
    assert np.allclose(colour_of("blue", 270.0), [255, 255, 255, 128], atol=1)
    assert colour_of("blue", 250.0) == [255, 255, 255, 255]
    # Colder tops darker, down to dark grey at 190 K
    assert colour_of("blue", 190.0) == [64, 64, 64, 255]
    assert 64 < colour_of("blue", 220.0)[0] < 255
    # And values_to_rgba keeps that transparency
    colormap, norm = get_satellite_cmap("blue")
    rgba = image_utils.values_to_rgba(np.array([200.0, 280.0, 295.0, np.nan]), colormap, norm.vmin, norm.vmax)
    assert rgba[0, 3] == 255 and 0 < rgba[1, 3] < 128 and rgba[2:, 3].tolist() == [0, 0]


def test_each_channel_draws_with_the_colour_scales_of_its_quantity():
    assert set(SATELLITE_STOPS) == set(SATELLITE_QUANTITIES)
    assert set(SATELLITE_QUANTITIES.values()) == set(IMAGERY_CHANNELS.values())
    for channel, colormap in IMAGERY_COLORMAPS.items():
        assert SATELLITE_QUANTITIES[colormap] == IMAGERY_CHANNELS[channel]
    assert get_satellite_cmap("visible", quantity="brightness")[1].vmax == 1.0
    with pytest.raises(ValueError, match="Unknown satellite colour scale"):
        get_satellite_cmap("rainbow")
    with pytest.raises(ValueError, match=r"does not draw brightness: choose among \['visible'\]"):
        get_satellite_cmap("blue", quantity="brightness")


def test_dark_pixels_fade_out_below_a_value():
    rgba = image_utils.values_to_rgba(np.array([0.0, 0.1, 0.5]), "gray", 0.0, 1.0, fade=0.1, transparent_below=0.2)

    assert rgba[:, 3].tolist() == [0, 0, 255]


def test_quantile_fit_finds_the_transform_between_two_distributions():
    rng = np.random.default_rng(1)
    reference = rng.uniform(0.0, 1.0, 1000)
    values = rng.permutation((reference - 0.1) / 0.8)  # same distribution, other pixels

    gain, offset = image_utils.quantile_fit(values, reference)

    assert gain == pytest.approx(0.8, rel=1e-6) and offset == pytest.approx(0.1, abs=1e-6)
    assert image_utils.quantile_fit(values[:10], reference[:10]) == (1.0, 0.0)
    assert image_utils.quantile_fit(values, np.zeros(1000), min_spread=0.02) == (1.0, 0.0)
    mask = np.zeros(1000, dtype=bool)
    assert image_utils.quantile_fit(values, reference, mask) == (1.0, 0.0)


# ------------------------------------------------------------------------------
# Resolution: tiled requests and smooth upscaling
# ------------------------------------------------------------------------------


def test_a_large_map_is_requested_in_tiles_that_join_on_the_pixel_grid(monkeypatch):
    asked = []

    def get_map(url, layer, bounds, size, time=None, style="", timeout=None):
        asked.append((bounds, size))
        min_lon, min_lat, max_lon, max_lat = bounds
        width, height = size
        # Each pixel tells the longitude and latitude of its centre
        lon = min_lon + (max_lon - min_lon) * (np.arange(width) + 0.5) / width
        lat = max_lat - (max_lat - min_lat) * (np.arange(height) + 0.5) / height
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[..., 0] = np.round(lon + 100)[None, :]
        rgba[..., 1] = np.round(lat + 100)[:, None]
        rgba[..., 3] = 255
        return image_utils.encode_png(rgba)

    monkeypatch.setattr(wms_utils, "get_map", get_map)
    rgba = wms_utils.get_map_array("https://server", "layer", (-10.0, 40.0, 0.0, 45.0), (10, 5), max_size=4)

    assert [size for _, size in asked] == [(4, 4), (4, 4), (2, 4), (4, 1), (4, 1), (2, 1)]
    assert asked[0][0] == (-10.0, 41.0, -6.0, 45.0)
    assert rgba.shape == (5, 10, 4)
    # The same pixels as one request: longitudes west to east, latitudes north to south
    np.testing.assert_array_equal(rgba[0, :, 0], np.round(np.arange(-9.5, 0.0, 1.0) + 100))
    np.testing.assert_array_equal(rgba[:, 0, 1], np.round(np.arange(44.5, 40.0, -1.0) + 100))


def test_rescale_interpolates_smoothly_and_keeps_nan_in_place():
    values = np.array([[0.0, 10.0], [20.0, 30.0]], dtype=np.float32)

    fine = image_utils.rescale(values, 4)
    assert fine.shape == (8, 8)
    # Bilinear: no overshoot, monotonic, the mean kept
    assert fine.min() >= 0.0 and fine.max() <= 30.0
    assert np.all(np.diff(fine, axis=1) >= 0) and np.all(np.diff(fine, axis=0) >= 0)
    assert fine.mean() == pytest.approx(15.0, abs=1e-4)
    assert np.unique(image_utils.rescale(values, 4, order=0)).tolist() == [0.0, 10.0, 20.0, 30.0]
    assert image_utils.rescale(values, 1) is not None and image_utils.rescale(values, 0.5).shape == (1, 1)

    holed = values.copy()
    holed[0, 0] = np.nan
    fine = image_utils.rescale(holed, 4)
    assert np.isnan(fine[:2, :2]).all() and np.isfinite(fine[4:, 4:]).all()
    assert np.nanmin(fine) >= 10.0  # NaN neither spreads nor drags the values
    assert np.isnan(image_utils.rescale(np.full((2, 2), np.nan), 2)).all()


def test_an_image_can_be_cropped_and_upscaled_for_display(eumetview):
    eumetview.load_data()
    box = (-8.0, -4.0, 42.0, 44.0)

    assert eumetview.extent() == [-10.0, 0.0, 40.0, 45.0]
    assert eumetview.extent(box) == [-8.0, -4.0, 42.0, 44.0]
    assert eumetview.image(0, box=box).shape == (2, 4, 4)
    zoom = eumetview.image(0, box=(-10.0, -8.0, 43.0, 45.0), scale=4)
    assert zoom.shape == (8, 8, 4)
    # The black north-west pixel of the server, smoothed into its neighbours
    assert len(np.unique(zoom[..., 0])) > 2
    with pytest.raises(ValueError, match="No pixel"):
        eumetview.image(0, box=(20.0, 30.0, 0.0, 10.0))


def test_a_repeated_grey_reads_warm_in_a_warm_area_and_cold_among_cold_tops():
    # Greys 100 and 102 are warm, grey 101 a cold entry between them (as grey 155 of GIBS
    # between 270.8 K and 270.3 K); red, a cold top of the main part
    colours = np.array([[100, 100, 100], [102, 102, 102], [200, 0, 0], [101, 101, 101]])
    values = np.array([270.0, 269.0, 210.0, 196.0])
    secondary = np.array([False, False, False, True])
    grey = np.where(np.arange(80)[:, None] % 2 == 0, 100, 102) * np.ones((1, 80), dtype=int)
    rgba = np.stack([grey, grey, grey, np.full_like(grey, 255)], axis=-1).astype(np.uint8)
    rgba[70, 40:60, :3] = 101  # a streak in a warm area, far from any known pixel
    rgba[5:20, 5:20, :3] = [200, 0, 0]  # a cold cloud top...
    rgba[10:15, 10:15, :3] = 101  # ...with a colder core

    bt = image_utils.invert_palette(rgba, colours, values, secondary=secondary)

    assert bt[70, 40:60].min() >= 269.0
    np.testing.assert_allclose(bt[10:15, 10:15], 196.0)
    np.testing.assert_allclose(bt[60:, :], np.clip(bt[60:, :], 269.0, 270.0))


def test_the_native_resolution_of_the_server_layers_is_chosen():
    assert native_layers(EUMETVIEW_LAYERS) == {"ir": "mtg_fd:ir105_hrfi", "visible": "mtg_fd:vis06_hrfi"}
    assert native_layers(EUMETVIEW_LAYERS, "coarsest") == {"ir": "msg_fes:ir108", "visible": "msg_fes:vis006"}
    assert native_layers(EUMETVIEW_LAYERS, {"ir": "3km"}) == {"ir": "msg_fes:ir108", "visible": "mtg_fd:vis06_hrfi"}
    with pytest.raises(ValueError, match=r"No visible layer at 1km: choose among \['finest', 'coarsest', '0.5km', '3km'\]"):
        native_layers(EUMETVIEW_LAYERS, "1km")

    meteosat = EUMETViewData("meteosat", channels=["ir", "visible"], native_resolution="3km", verbose=False, **IMAGERY_PERIOD, **IMAGERY_DOMAIN)
    assert meteosat.wms_layers == {"ir": "msg_fes:ir108", "visible": "msg_fes:vis006"}
    assert set(meteosat.palettes) == {"ir", "visible"} and meteosat.palettes["ir"] is not None
    assert meteosat.subsatellite_lon == 0.0
    # An explicit server layer still wins
    meteosat = EUMETViewData("meteosat", native_resolution="3km", wms_layers={"ir": "mtg_fd:ir105_hrfi"}, verbose=False)
    assert meteosat.wms_layers == {"ir": "mtg_fd:ir105_hrfi"}

    clouds = GeostationaryImagery("clouds", native_resolution="coarsest", **IMAGERY_PERIOD, **COMPOSITE_DOMAIN)
    assert [source.wms_layers["ir"] for source in clouds.sources] == ["msg_fes:ir108", "GOES-East_ABI_Band13_Clean_Infrared"]
    with pytest.raises(ValueError, match="No ir layer at 3km"):
        GeostationaryImagery("clouds", native_resolution="3km", **IMAGERY_PERIOD, **COMPOSITE_DOMAIN)

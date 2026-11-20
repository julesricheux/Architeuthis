# -*- coding: utf-8 -*-
"""
Web Map Service (WMS 1.3.0) requests: times of a layer, maps, colormaps.

Used by the satellite imagery of `architeuthis.satellite`, and usable by
any map layer: the server crops, reprojects and renders, and sends an
image of the requested box, size and time.

Created on Thu Nov 19 2026

@author: jrich
"""

import re

import numpy as np
import pandas as pd
import requests

from typing import Optional, Sequence

from architeuthis.toolbox.image_utils import decode_png

TIMEOUT = 120  # s
# Largest width or height of one map request, in pixels: GIBS takes up
# to 20000, EUMETView answered 8000 x 2500 in 5 s (2026-11)
MAX_SIZE = 4096


def capabilities(url: str, timeout: float = TIMEOUT) -> str:
    """
    The GetCapabilities document of a WMS server.

    Args:
        url: Endpoint of the server.
        timeout: Timeout of the request, in seconds.

    Returns:
        The XML text.
    """
    response = requests.get(
        url,
        params={"SERVICE": "WMS", "REQUEST": "GetCapabilities", "VERSION": "1.3.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def time_extent(document: str, layer: str) -> list[str]:
    """
    The time dimension of a layer, as the server writes it.

    Args:
        document: GetCapabilities XML.
        layer: Name of the layer.

    Returns:
        Its values: single times or `start/end/period` intervals.

    Raises:
        KeyError: If the layer or its time dimension is missing.
    """
    match = re.search(f"<Name>{re.escape(layer)}</Name>", document)
    if match is None:
        raise KeyError(f"No layer {layer} in the capabilities.")
    block = document[match.end():]
    block = block[:block.find("</Layer>")]
    dimension = re.search(r'<Dimension[^>]*name="time"[^>]*>([^<]*)<', block)
    if dimension is None:
        raise KeyError(f"Layer {layer} has no time dimension.")
    return [value.strip() for value in dimension.group(1).split(",") if value.strip()]


def available_times(
    extent: Sequence[str],
    start=None,
    end=None,
) -> pd.DatetimeIndex:
    """
    The times of a time extent within a period.

    Intervals are expanded only over the period, so that a long archive
    at 10 min stays cheap.

    Args:
        extent: Values from `time_extent`.
        start: Start of the period, None for no limit.
        end: End of the period, None for no limit.

    Returns:
        Sorted UTC times, without duplicates.
    """
    start = None if start is None else _utc(start)
    end = None if end is None else _utc(end)
    times = []
    for value in extent:
        parts = value.split("/")
        if len(parts) == 1:
            times.append(_utc(parts[0]))
            continue
        # An ISO 8601 period such as PT10M: pd.Timedelta of a string warns
        # with NumPy 2.5, not pd.to_timedelta of a list
        first, last, period = _utc(parts[0]), _utc(parts[1]), pd.to_timedelta([parts[2]])[0]
        low = first if start is None else max(first, first + np.ceil((start - first) / period) * period)
        high = last if end is None else min(last, end)
        if low <= high:
            times.extend(pd.date_range(low, high, freq=period))
    times = pd.DatetimeIndex(sorted(set(times)), tz="UTC")
    if start is not None:
        times = times[times >= start]
    if end is not None:
        times = times[times <= end]
    return times


def gibs_time_domain(
    layer: str,
    start,
    end,
    tile_matrix_set: str = "2km",
    timeout: float = TIMEOUT,
) -> list[str]:
    """
    Times of a NASA GIBS layer within a period, from DescribeDomains.

    Small and up to date, whereas the WMS capabilities of GIBS may lag
    by an hour or more, depending on the server that answers.

    Args:
        layer: Name of the GIBS layer.
        start: Start of the period.
        end: End of the period.
        tile_matrix_set: Tile matrix set of the layer, "2km" for the
            geostationary layers.
        timeout: Timeout of the request, in seconds.

    Returns:
        The time extent, as `time_extent` gives it.
    """
    period = "--".join(_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ") for value in (start, end))
    url = (
        "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/1.0.0/"
        f"{layer}/default/{tile_matrix_set}/all/{period}.xml"
    )
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    domain = re.search(r"<Domain>([^<]*)</Domain>", response.text)
    if domain is None:
        return []
    return [value.strip() for value in domain.group(1).split(",") if value.strip()]


def get_map(
    url: str,
    layer: str,
    bounds: Sequence[float],
    size: Sequence[int],
    time=None,
    style: str = "",
    timeout: float = TIMEOUT,
) -> bytes:
    """
    A map of a layer as a transparent PNG, in latitude and longitude.

    Args:
        url: Endpoint of the server.
        layer: Name of the layer.
        bounds: `(min_lon, min_lat, max_lon, max_lat)`, in degrees.
        size: `(width, height)`, in pixels.
        time: Time of the map, None for the default of the layer.
        style: Style of the layer, "" for its default.
        timeout: Timeout of the request, in seconds.

    Returns:
        The PNG file, as bytes.

    Raises:
        RuntimeError: If the server answers with an exception rather
            than an image.
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": style,
        "CRS": "EPSG:4326",
        # WMS 1.3.0 in EPSG:4326: latitude first
        "BBOX": f"{min_lat},{min_lon},{max_lat},{max_lon}",
        "WIDTH": int(size[0]),
        "HEIGHT": int(size[1]),
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE",
    }
    if time is not None:
        params["TIME"] = _utc(time).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    if not response.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"{layer} at {params.get('TIME')}: {response.text[:300]}")
    return response.content


def get_map_array(
    url: str,
    layer: str,
    bounds: Sequence[float],
    size: Sequence[int],
    time=None,
    style: str = "",
    max_size: int = MAX_SIZE,
    timeout: float = TIMEOUT,
) -> np.ndarray:
    """
    The pixels of a map of any size, requested in tiles if needed.

    Tiles of at most `max_size` pixels a side are cut on the pixel grid
    of the whole map, so that they join without a seam.

    Args:
        url: Endpoint of the server.
        layer: Name of the layer.
        bounds: `(min_lon, min_lat, max_lon, max_lat)`, in degrees.
        size: `(width, height)`, in pixels.
        time: Time of the map, None for the default of the layer.
        style: Style of the layer, "" for its default.
        max_size: Largest width or height of one request, in pixels.
        timeout: Timeout of each request, in seconds.

    Returns:
        RGBA array of shape (height, width, 4), uint8, first row north.

    Example:
        rgba = get_map_array(url, layer, (-75, 35, 5, 60), (8000, 2500))
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    width, height = int(size[0]), int(size[1])
    step_lon = (max_lon - min_lon) / width
    step_lat = (max_lat - min_lat) / height
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    for top in range(0, height, max_size):
        bottom = min(top + max_size, height)
        for left in range(0, width, max_size):
            right = min(left + max_size, width)
            tile_bounds = (
                min_lon + left * step_lon,
                max_lat - bottom * step_lat,
                min_lon + right * step_lon,
                max_lat - top * step_lat,
            )
            content = get_map(url, layer, tile_bounds, (right - left, bottom - top), time, style, timeout=timeout)
            rgba[top:bottom, left:right] = decode_png(content)
    return rgba


def parse_gibs_colormap(document: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Colours and values of a NASA GIBS colormap (format v1.3).

    Each opaque entry gives the colour of an interval of values, taken
    at its middle; values in degrees Celsius are converted to kelvins.

    Args:
        document: XML of the colormap.

    Returns:
        (colours, values): RGB array of shape (n, 3), and values (n,).
    """
    colormap = re.search(r"<ColorMap\b[^>]*>(.*?)</ColorMap>", document, flags=re.S)
    header = re.search(r"<ColorMap\b[^>]*>", document).group(0)
    offset = 273.15 if "°C" in header or "&#176;C" in header else 0.0
    colours, values = [], []
    for entry in re.finditer(r"<ColorMapEntry\b([^>]*)/>", colormap.group(1)):
        attributes = dict(re.findall(r'(\w+)="([^"]*)"', entry.group(1)))
        if attributes.get("transparent") == "true" or "value" not in attributes:
            continue
        bounds = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", attributes["value"])]
        if not bounds:
            continue
        colours.append([int(c) for c in attributes["rgb"].split(",")])
        values.append(np.mean(bounds) + offset)
    return np.array(colours, dtype=np.uint8), np.array(values, dtype=float)


def _utc(value) -> pd.Timestamp:
    """
    A time as a UTC timestamp; naive times are UTC.

    Args:
        value: Any time pandas reads, or float epoch seconds.

    Returns:
        A timezone-aware timestamp.
    """
    if isinstance(value, (int, float, np.floating, np.integer)):
        return pd.Timestamp(float(value), unit="s", tz="UTC")
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")

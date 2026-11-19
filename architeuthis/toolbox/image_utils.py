# -*- coding: utf-8 -*-
"""
Image treatment: palettes, rendering on a colour scale, compositing.

Rendered images (satellite pictures of a map service, for example) are
turned back into the values they show by inverting their palette, so
that images of different sources can be compared, combined, and drawn
again on one colour scale.

Created on Thu Nov 19 2026

@author: jrich
"""

import io

import numpy as np
import matplotlib

from PIL import Image
from scipy.ndimage import uniform_filter
from scipy.spatial import cKDTree
from typing import Optional, Sequence, Union


def decode_png(content: bytes) -> np.ndarray:
    """
    Pixels of a PNG file.

    Args:
        content: The file, as bytes.

    Returns:
        RGBA array of shape (height, width, 4), uint8.
    """
    with Image.open(io.BytesIO(content)) as image:
        return np.asarray(image.convert("RGBA"))


def encode_png(rgba: np.ndarray) -> bytes:
    """
    A PNG file of pixels.

    Args:
        rgba: RGBA array of shape (height, width, 4), uint8.

    Returns:
        The file, as bytes.
    """
    buffer = io.BytesIO()
    Image.fromarray(np.asarray(rgba, dtype=np.uint8), mode="RGBA").save(buffer, format="PNG")
    return buffer.getvalue()


def linear_gray_palette(offset: float, slope: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Palette of a grey ramp whose level is linear in the value.

    Args:
        offset: Value of black (level 0).
        slope: Change of the value per grey level.

    Returns:
        (colours, values): the 256 grey levels as RGB, and their values.
    """
    levels = np.arange(256)
    colours = np.repeat(levels[:, None], 3, axis=1).astype(np.uint8)
    return colours, offset + slope * levels


def invert_palette(
    rgba: np.ndarray,
    colours: np.ndarray,
    values: np.ndarray,
    max_distance: Optional[float] = None,
    secondary: Optional[np.ndarray] = None,
    tolerance: float = 3.0,
    window: int = 9,
) -> np.ndarray:
    """
    Values shown by an image, from the palette that rendered it.

    Each pixel takes the value of the nearest palette colour (RGB
    distance). Transparent pixels are NaN. Servers that resample with
    interpolation blend neighbouring colours: on a ramp, the nearest
    colour is then a neighbouring value; elsewhere it may be farther.

    Some palettes use the same colours twice, for distant values: give
    the entries of the less common part as `secondary`. A pixel whose
    colour both parts explain as well (within `tolerance`) takes the
    reading nearest to the mean of its unambiguous neighbours, over
    `window` pixels along the last two axes of the image.

    Args:
        rgba: RGBA pixels, uint8, of shape (..., height, width, 4).
        colours: RGB colours of the palette, shape (n, 3).
        values: Values of the colours, shape (n,).
        max_distance: Pixels farther than this from any palette colour
            are NaN; None to keep them all.
        secondary: Boolean mask of the palette entries that repeat the
            colours of another part, None if none does.
        tolerance: RGB distance under which both parts explain a pixel.
        window: Size of the neighbourhood of an ambiguous pixel.

    Returns:
        Float array of the shape of the pixels without the last axis.
    """
    rgba = np.asarray(rgba)
    colours = np.asarray(colours, dtype=float)
    values = np.asarray(values, dtype=float)
    opaque = rgba[..., 3] > 0
    if secondary is None or not np.any(secondary):
        result, distance = _nearest_colour(rgba, colours, values)
    else:
        secondary = np.asarray(secondary, dtype=bool)
        result, distance = _nearest_colour(rgba, colours[~secondary], values[~secondary])
        other, other_distance = _nearest_colour(rgba, colours[secondary], values[secondary])
        clearly_other = other_distance + tolerance < distance
        ambiguous = ~clearly_other & (other_distance < distance + tolerance)

        # Context: the mean of the unambiguous neighbours of each pixel
        known = opaque & ~ambiguous
        reading = np.where(clearly_other, other, result)
        size = (1,) * (rgba.ndim - 3) + (window, window)
        total = uniform_filter(np.where(known, reading, 0.0), size=size, mode="nearest")
        count = uniform_filter(known.astype(float), size=size, mode="nearest")
        with np.errstate(invalid="ignore", divide="ignore"):
            context = total / count
        closer = np.abs(other - context) < np.abs(result - context)

        result = np.where(clearly_other | (ambiguous & (count > 0) & closer), other, result)
        distance = np.where(clearly_other, other_distance, distance)

    if max_distance is not None:
        result = np.where(distance <= max_distance, result, np.nan)
    return np.where(opaque, result, np.nan)


def _nearest_colour(
    rgba: np.ndarray,
    colours: np.ndarray,
    values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Value and distance of the nearest palette colour of each pixel.

    Args:
        rgba: RGBA pixels, of shape (..., 4).
        colours: RGB colours of the palette, shape (n, 3).
        values: Values of the colours, shape (n,).

    Returns:
        (values, distances), of the shape of the pixels without the
        last axis.
    """
    rgb = rgba[..., :3].reshape(-1, 3).astype(np.int32)
    # Each distinct colour once: images have far fewer colours than pixels
    codes = (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]
    unique, inverse = np.unique(codes, return_inverse=True)
    unique_rgb = np.stack([(unique >> 16) & 255, (unique >> 8) & 255, unique & 255], axis=1)

    distance, index = cKDTree(colours).query(unique_rgb)
    shape = rgba.shape[:-1]
    inverse = inverse.ravel()
    return values[index][inverse].reshape(shape), distance[inverse].reshape(shape)


def values_to_rgba(
    values: np.ndarray,
    colormap: Union[str, matplotlib.colors.Colormap] = "gray_r",
    vmin: float = 200.0,
    vmax: float = 300.0,
    transparent_above: Optional[float] = None,
    fade: float = 10.0,
) -> np.ndarray:
    """
    Pixels of values drawn on a colour scale.

    NaN is transparent. With `transparent_above`, values fade out above
    it, over `fade`: warm clear skies vanish from a cloud layer, so that
    the map below shows through.

    Args:
        values: Values, any shape.
        colormap: Matplotlib colormap or its name.
        vmin: Value of the first colour.
        vmax: Value of the last colour.
        transparent_above: Value above which pixels fade out, None to
            keep them opaque.
        fade: Range of the fading, in the units of the values.

    Returns:
        RGBA array of shape (..., 4), uint8.
    """
    values = np.asarray(values, dtype=float)
    colormap = matplotlib.colormaps[colormap] if isinstance(colormap, str) else colormap
    rgba = colormap(np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0))
    alpha = np.where(np.isnan(values), 0.0, 1.0)
    if transparent_above is not None:
        alpha = alpha * np.clip((transparent_above + fade - values) / fade, 0.0, 1.0)
    rgba[..., 3] = np.nan_to_num(alpha)
    return np.round(rgba * 255).astype(np.uint8)


def softmin_weights(distances: Sequence[np.ndarray], width: float) -> np.ndarray:
    """
    Weights favouring the smallest distance, smoothly.

    Where two distances are equal, both weigh half; a difference of a
    few `width` gives almost all the weight to the smaller one. Used to
    join images along a seam without a visible edge.

    Args:
        distances: One array per image, all of the same shape.
        width: Distance over which the weights change.

    Returns:
        Array of shape (n_images, ...), summing to 1 on the first axis.
    """
    distances = np.stack([np.asarray(d, dtype=float) for d in distances])
    exponent = -(distances - distances.min(axis=0)) / width
    weights = np.exp(exponent)
    return weights / weights.sum(axis=0)


def blend(layers: Sequence[np.ndarray], weights: np.ndarray) -> np.ndarray:
    """
    Weighted mean of layers, ignoring their NaN.

    Where a layer has no value, the others share its weight; where none
    has, the result is NaN.

    Args:
        layers: Arrays of the same shape, (..., height, width) say.
        weights: Weights of each layer, of shape (n_layers, ...) that
            broadcasts against the layers (`softmin_weights`, say).

    Returns:
        The blended array.
    """
    layers = np.stack([np.asarray(layer, dtype=float) for layer in layers])
    weights = np.broadcast_to(weights, layers.shape) * np.isfinite(layers)
    total = weights.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(total > 0, (weights * np.nan_to_num(layers)).sum(axis=0) / total, np.nan)


def save_animation(frames: Sequence[np.ndarray], path: str, duration: float = 200.0) -> str:
    """
    An animated GIF of RGBA images, transparency kept.

    Args:
        frames: RGBA arrays of the same shape, uint8, in order.
        path: Path of the GIF file.
        duration: Display time of each frame, in milliseconds.

    Returns:
        The path.
    """
    images = [Image.fromarray(np.asarray(frame, dtype=np.uint8), mode="RGBA") for frame in frames]
    images[0].save(path, save_all=True, append_images=images[1:], duration=duration, loop=0, disposal=2)
    return path

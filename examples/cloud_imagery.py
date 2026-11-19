# -*- coding: utf-8 -*-
"""
One continuous cloud layer over the North Atlantic, from two geostationary satellites.

Meteosat (MTG FCI at 0 deg, from EUMETView) sees Europe and the eastern Atlantic,
GOES-East (at 75.2 W, from NASA GIBS) the Americas and the western Atlantic.
Both are rendered by their map service with their own colours; Architeuthis turns
these back into one common scale and joins them where each satellite sees the most
directly, blended over a few degrees along the seam.

The data layers are chosen as the variables of a forecast, with `layers`:

- "ir": the infrared, day and night, brightness temperatures in K, drawn in the
  colours of Windy's Infra+;
- "blue": the same infrared, drawn in the manner of Windy's Blue;
- "visible": the visible, by day only, a brightness from 0 to 1, the levels of
  GOES matched to those of Meteosat along the seam, image by image.

The script loads the infrared of the last hours every 10 min, and the three
layers around the latest midday over the Atlantic. It checks that both satellites
agree where they overlap, draws each source and the combined layer, the three
layers at the same time, the clouds over a map, and writes the animation that a
map layer of ui.py would show.

Needs no credentials. Run from the repository root, cell by cell (#%%) or as a
script. Writes cloud_imagery.png, cloud_imagery_layers.png, cloud_imagery_map.png
and cloud_imagery.gif to the current folder.

Created on Thu Nov 19 2026

@author: jrich
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from architeuthis.satellite import GeostationaryImagery
from architeuthis.toolbox.image_utils import save_animation
from architeuthis.toolbox.windy_colormaps import get_satellite_cmap

# A crossing from Brittany to Saint-Pierre-et-Miquelon and New York
domain = {"min_lon": -75.0, "max_lon": 5.0, "min_lat": 35.0, "max_lat": 60.0}
# domain = {"min_lon": -64.0, "max_lon": -48.5, "min_lat": 41.0, "max_lat": 51.5}  # Saint-Pierre only, GOES-East alone
# domain = {"min_lon": -20.0, "max_lon": 10.0, "min_lat": 40.0, "max_lat": 55.0}  # France and Biscay, Meteosat alone

# Infrared: the last 3 hours, every 10 min. GIBS is about an hour behind
# EUMETView, and only the times both have are kept, so the latest image is
# about an hour old.
now = pd.Timestamp("now", tz="UTC")
end = now
start = end - pd.Timedelta(hours=3)
# start, end = "2026-11-19 12:00Z", "2026-11-19 15:00Z"

# Daylight: 3 hours around the latest midday over the mid-Atlantic (14 UTC),
# at least an hour ago so that GIBS has it, for the visible
midday = now.floor("1D") + pd.Timedelta(hours=14)
if midday > now - pd.Timedelta(hours=2, minutes=30):
    midday -= pd.Timedelta(days=1)
visible_start, visible_end = midday - pd.Timedelta(hours=1.5), midday + pd.Timedelta(hours=1.5)

resolution = 0.05  # deg, about 5 km: 1600 x 500 pixels here
time_step = None  # every image; "30min" or "1h" for fewer
clear_sky = 275.0  # K: warmer pixels fade out of the cloud layer

#%% INFRARED: COMBINED LAYER

# "ir" and "blue" draw the same channel: it is downloaded once
clouds = GeostationaryImagery("clouds", start, end, resolution=resolution, time_step=time_step, layers=["ir", "blue"], **domain)
# clouds = GeostationaryImagery("clouds", start, end, resolution=resolution, complete=False, **domain)  # every time of either satellite
clouds.load_data()

times = clouds.times()
print(f"Infrared: {len(times)} images from {times[0]:%d %H:%M} to {times[-1]:%d %H:%M} UTC, sources {list(clouds.data.source.values)}")

#%% INFRARED: BOTH SATELLITES ON THE SAME SCALE

# Where both see the ocean (50 W to 20 W), their temperatures should agree
meteosat, goes = clouds.loaded
overlap = {"longitude": slice(-50.0, -20.0)}
a = meteosat.data["bt"].sel(valid_time=clouds.data.valid_time, **overlap).values.ravel()
b = goes.data["bt"].sel(valid_time=clouds.data.valid_time, **overlap).values.ravel()
both = np.isfinite(a) & np.isfinite(b)
difference = b[both] - a[both]
print(
    f"GOES-East minus Meteosat over {both.sum()} pixels: median {np.median(difference):+.1f} K, "
    f"median absolute deviation {np.median(np.abs(difference - np.median(difference))):.1f} K"
)

#%% DAYLIGHT: THE THREE LAYERS

daylight = GeostationaryImagery(
    "daylight", visible_start, visible_end, resolution=resolution, time_step=time_step,
    layers=["ir", "blue", "visible"], **domain,
)
# daylight = GeostationaryImagery("daylight", visible_start, visible_end, layers="visible", **domain)  # the visible only
daylight.load_data()

visible_times = daylight.times()
print(f"Daylight: {len(visible_times)} images from {visible_times[0]:%d %H:%M} to {visible_times[-1]:%d %H:%M} UTC, variables {daylight.variables}")
# GOES levels put on those of Meteosat: they change with the sun
gain = daylight.data["gain"].sel(channel="visible").isel(source=1).values
print(f"Visible levels of GOES-East matched to Meteosat: gain from {gain.min():.2f} to {gain.max():.2f}")

#%% FIGURE: EACH SOURCE AND THE COMBINED LAYER

extent = [domain["min_lon"], domain["max_lon"], domain["min_lat"], domain["max_lat"]]
latest = times[-1]


def colour_bar(fig, axes, layer, label):
    """A colour bar of a data layer beside some axes."""
    colormap, norm = get_satellite_cmap(layer)
    fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=colormap), ax=axes, shrink=0.8, label=label)


# One panel per row: the domain is about three times wider than tall
fig, axes = plt.subplots(4, 1, figsize=(11, 15), subplot_kw={"projection": ccrs.PlateCarree()}, layout="constrained")
panels = [
    (meteosat, "Meteosat MTG FCI 10.5 um (EUMETView)"),
    (goes, "GOES-East ABI 10.3 um (NASA GIBS)"),
    (clouds, "Combined layer"),
]
for ax, (imagery, title) in zip(axes, panels):
    ax.imshow(imagery.image(latest), extent=extent, origin="upper", transform=ccrs.PlateCarree())
    ax.coastlines(linewidth=0.5, color="tab:orange")
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    ax.set_title(f"{title}, {latest:%Y-%m-%d %H:%M} UTC")
colour_bar(fig, axes[:3], "ir", "Brightness temperature (K), Windy Infra+")

# The share of Meteosat in each pixel: the seam where both satellites see alike
share = axes[3].imshow(
    clouds.data["weight"].isel(source=0).values[::-1], extent=extent, origin="upper",
    cmap="coolwarm", vmin=0.0, vmax=1.0, transform=ccrs.PlateCarree(),
)
axes[3].coastlines(linewidth=0.5)
axes[3].set_extent(extent, crs=ccrs.PlateCarree())
axes[3].set_title("Share of Meteosat (red) and GOES-East (blue)")
fig.colorbar(share, ax=axes[3], shrink=0.9, label="Share of Meteosat")
fig.savefig("cloud_imagery.png", dpi=90)

#%% FIGURE: THE THREE LAYERS AT MIDDAY

fig, axes = plt.subplots(3, 1, figsize=(11, 11.5), subplot_kw={"projection": ccrs.PlateCarree()}, layout="constrained")
midday_image = visible_times[len(visible_times) // 2]
panels = [
    ("ir", "Infrared (Windy Infra+)", "Brightness temperature (K)"),
    ("blue", "Infrared (in the manner of Windy Blue)", "Brightness temperature (K)"),
    ("visible", "Visible", "Brightness"),
]
for ax, (layer, title, label) in zip(axes, panels):
    ax.imshow(daylight.image(midday_image, layer=layer), extent=extent, origin="upper", transform=ccrs.PlateCarree())
    ax.coastlines(linewidth=0.5, color="tab:orange")
    ax.set_extent(extent, crs=ccrs.PlateCarree())
    ax.set_title(f"{title}, {midday_image:%Y-%m-%d %H:%M} UTC")
    colour_bar(fig, ax, layer, label)
fig.savefig("cloud_imagery_layers.png", dpi=90)

#%% FIGURE: THE CLOUD LAYER OVER A MAP

fig = plt.figure(figsize=(12, 5))
ax = fig.add_subplot(projection=ccrs.PlateCarree())
ax.add_feature(cfeature.OCEAN, color="#1f4e79")
ax.add_feature(cfeature.LAND, color="#6b8e4e")
ax.imshow(clouds.image(latest, layer="blue", transparent_above=clear_sky), extent=extent, origin="upper", transform=ccrs.PlateCarree())
ax.set_extent(extent, crs=ccrs.PlateCarree())
ax.set_title(f"Clouds colder than {clear_sky:.0f} K, {latest:%Y-%m-%d %H:%M} UTC")
fig.savefig("cloud_imagery_map.png", dpi=90, bbox_inches="tight")

#%% ANIMATION

# The frames a map layer would show, clear sky transparent
frames = [clouds.image(index, transparent_above=clear_sky) for index in range(len(times))]
save_animation(frames, "cloud_imagery.gif", duration=300)
print(f"cloud_imagery.gif: {len(frames)} frames of {frames[0].shape[1]} x {frames[0].shape[0]} pixels")

plt.show()

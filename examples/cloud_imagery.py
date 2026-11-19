# -*- coding: utf-8 -*-
"""
One continuous cloud layer over the North Atlantic, from two geostationary satellites.

Meteosat (MTG FCI at 0 deg, from EUMETView) sees Europe and the eastern Atlantic,
GOES-East (at 75.2 W, from NASA GIBS) the Americas and the western Atlantic.
Both are rendered by their map service with their own colours; Architeuthis turns
these back into brightness temperatures, the common scale, and joins them where
each satellite sees the most directly, blended over a few degrees along the seam.

The script loads the last hours every 10 min, checks that both satellites give the
same temperatures where they overlap, draws the latest image of each source and of
the combined layer on one colour scale, then the combined layer as clouds over a
map, and writes the animation that a map layer of ui.py would show.

Needs no credentials. Run from the repository root, cell by cell (#%%) or as a
script. Writes cloud_imagery.png, cloud_imagery_map.png and cloud_imagery.gif
to the current folder.

Created on Thu Nov 19 2026

@author: jrich
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

from architeuthis.satellite import IR_RANGE, GeostationaryImagery
from architeuthis.toolbox.image_utils import save_animation

# A crossing from Brittany to Saint-Pierre-et-Miquelon and New York
domain = {"min_lon": -75.0, "max_lon": 5.0, "min_lat": 35.0, "max_lat": 60.0}
# domain = {"min_lon": -64.0, "max_lon": -48.5, "min_lat": 41.0, "max_lat": 51.5}  # Saint-Pierre only, GOES-East alone
# domain = {"min_lon": -20.0, "max_lon": 10.0, "min_lat": 40.0, "max_lat": 55.0}  # France and Biscay, Meteosat alone

# The last 3 hours, every 10 min. GIBS is about an hour behind EUMETView, and
# only the times both have are kept, so the latest image is about an hour old.
end = pd.Timestamp("now", tz="UTC")
start = end - pd.Timedelta(hours=3)
# start, end = "2026-11-19 12:00Z", "2026-11-19 15:00Z"

resolution = 0.05  # deg, about 5 km: 1600 x 500 pixels here
time_step = None  # every image; "30min" or "1h" for fewer
clear_sky = 275.0  # K: warmer pixels fade out of the cloud layer

#%% COMBINED LAYER

clouds = GeostationaryImagery("clouds", start, end, resolution=resolution, time_step=time_step, **domain)
clouds.load_data()

times = clouds.times()
print(f"{len(times)} images from {times[0]:%d %H:%M} to {times[-1]:%d %H:%M} UTC, sources {list(clouds.data.source.values)}")

#%% BOTH SATELLITES ON THE SAME SCALE

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

#%% FIGURE: EACH SOURCE AND THE COMBINED LAYER

extent = [domain["min_lon"], domain["max_lon"], domain["min_lat"], domain["max_lat"]]
latest = times[-1]

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
scale = plt.cm.ScalarMappable(norm=plt.Normalize(*IR_RANGE), cmap="gray_r")
fig.colorbar(scale, ax=axes[:3], shrink=0.6, label="Brightness temperature (K), common scale")

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

#%% FIGURE: THE CLOUD LAYER OVER A MAP

fig = plt.figure(figsize=(12, 5))
ax = fig.add_subplot(projection=ccrs.PlateCarree())
ax.add_feature(cfeature.OCEAN, color="#1f4e79")
ax.add_feature(cfeature.LAND, color="#6b8e4e")
ax.imshow(clouds.image(latest, transparent_above=clear_sky), extent=extent, origin="upper", transform=ccrs.PlateCarree())
ax.set_extent(extent, crs=ccrs.PlateCarree())
ax.set_title(f"Clouds colder than {clear_sky:.0f} K, {latest:%Y-%m-%d %H:%M} UTC")
fig.savefig("cloud_imagery_map.png", dpi=90, bbox_inches="tight")

#%% ANIMATION

# The frames a map layer would show, clear sky transparent
frames = [clouds.image(index, transparent_above=clear_sky) for index in range(len(times))]
save_animation(frames, "cloud_imagery.gif", duration=300)
print(f"cloud_imagery.gif: {len(frames)} frames of {frames[0].shape[1]} x {frames[0].shape[0]} pixels")

plt.show()

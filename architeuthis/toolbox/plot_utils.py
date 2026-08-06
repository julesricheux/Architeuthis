# -*- coding: utf-8 -*-
"""
Created on Mon Dec 15 22:36:04 2025

@author: jrich
"""

import matplotlib

import seaborn as sns
import cartopy.crs as ccrs
import architeuthis.numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import cartopy.feature as cfeature
# import cartopy.mpl.ticker as cticker

from architeuthis.toolbox.geo_utils import great_circle_route, midpoints

sns.set_theme(palette="viridis")

import matplotlib as mpl

mpl.rcParams.update({
    "font.size": 13,
    "axes.titlesize": 14,
    "axes.labelsize": 13,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 12
})


#%%

def plot_route(lon, lat, clon, clat, tws, twd, barbs, sails_contribution=None, sails_threshold=1.):
    plt.clf()
    # fig = plt.figure(dpi=300)
    ax = plt.axes(projection=ccrs.PlateCarree())
    
    assert len(lat)==len(lon), f"latitudes and longitudes collections must have the same length. Got {len(lat)} and {len(lon)}."
    
    n = len(lat)
    cmap = sns.color_palette("Spectral", as_cmap=True)
    # cmap = plt.get_cmap("Spectral", n)
    
    # Add background features
    # ax.add_feature(cfeature.LAND, facecolor="palegoldenrod")
    ax.add_feature(cfeature.LAND, facecolor="khaki")
    # ax.add_feature(cfeature.LAND, facecolor="sandybrown")
    ax.add_feature(cfeature.OCEAN, facecolor="lavender")
    # ax.add_feature(cfeature.OCEAN, facecolor="lightsteelblue")
    ax.add_feature(cfeature.COASTLINE, linewidth=0.3)
    # ax.add_feature(cfeature.BORDERS, linestyle=":")
    gl = ax.gridlines(draw_labels=False, dms=True, x_inline=False, y_inline=False, linewidth=0.5)
    
    # Gridlines at round degrees only
    # gl.xtick(1.0)
    gl.xlabel_style = {"size": 10}
    gl.ylabel_style = {"size": 10}
    
    orthoy, orthox, dist0 = great_circle_route([lat[0][0], lon[0][0]], [lat[0][-1], lon[0][-1]], 100)
    
    # Plot the route
    ax.plot(orthox, orthoy, color="grey", transform=ccrs.PlateCarree(), ms=0.75, lw=0.5)
        
    for i, (la, lo, s, d) in enumerate(zip(lat, lon, tws, twd)):
        assert len(la)==len(lo), f"latitudes and longitudes arrays must have the same length. Got {len(la)} and {len(lo)}."
        
        if sails_contribution is not None:
            
            sci = np.array(sails_contribution[i])
            
            sails_up = (sci > sails_threshold).astype("float")
            
            ax.plot(lo, la, color=cmap(i/n), transform=ccrs.PlateCarree(), ms=1.5, lw=1.0)
            ax.scatter(midpoints(lo), midpoints(la), s=sails_up*1.5, marker="o", color=cmap(i/n), transform=ccrs.PlateCarree())
        else:
            ax.plot(lo, la, "-o", color=cmap(i/n), transform=ccrs.PlateCarree(), ms=1.5, lw=1.0)
        # ax.plot(lo, la, "-o", color=cmap((i+1)/(n+6)), transform=ccrs.PlateCarree(), ms=0.75, lw=0.8)
        # ax.plot(lo, la, "-o", color=cmap((i+1)/), transform=ccrs.PlateCarree(), ms=0.75, lw=0.8)
      
    if barbs:
        for i, (cla, clo, s, d) in enumerate(zip(clat, clon, tws, twd)):
            u = s *- np.sin(np.radians(d))
            v = s * -np.cos(np.radians(d))
            
            ax.barbs(
                clo, cla, u, v, s,
                cmap="plasma_r",
                # sizes={
                #     "spacing": 0.25,
                #     "height": 0.4,
                #     "width": 0.2,
                #     "emptybarb": 0.15,
                # },
                length=5,                     # overall scaling (important)
                # linewidth=0.6,
            )
    # plt.tight_layout()
    
    plt.show()


def plot_routing_report(cvtim, stw, sog, tws, twa, swh, wa, avg_bhp, max_bhp, sol, maxBHP):
    # ------------------------------------------------------------------
    # Prepare data
    # ------------------------------------------------------------------
    
    TIME = cvtim
    
    STW = sol(stw)
    SOG = sol(sog)
    
    AVG_BHP = sol(avg_bhp)
    MAX_BHP_SERIES = sol(max_bhp)
    MAX_BHP = maxBHP
    
    TWS = sol(tws)
    SWH = sol(swh)
    
    MEAN_SOG = np.mean(SOG)

    # ------------------------------------------------------------------
    # Create figure and subplots
    # ------------------------------------------------------------------
    
    fig, axs = plt.subplots(
        nrows=4,
        ncols=1,
        sharex=True,
        figsize=(6, 10),
        constrained_layout=True,
        
    )
    
    # ------------------------------------------------------------------
    # 1. STW / SOG
    # ------------------------------------------------------------------
    
    cmap = sns.color_palette("viridis", 5)
    
    axs[0].plot(TIME, STW, label="STW", linewidth=1.8, color=cmap[1])
    axs[0].plot(TIME, SOG, label="SOG", linewidth=1.8, color=cmap[-1])
    
    axs[0].axhline(
        MEAN_SOG,
        linestyle=":",
        linewidth=1.5
    )
    
    axs[0].text(
        TIME[len(TIME)//20],
        MEAN_SOG,
        f"avg SOG = {MEAN_SOG:.2f} kts",
        va="bottom",
        ha="left"
    )
    
    axs[0].set_ylabel("SPEED / TWS")
    axs[0].legend()
    axs[0].grid(True, alpha=0.7)
    
    # ------------------------------------------------------------------
    # 2. BHP
    # ------------------------------------------------------------------
    
    axs[1].plot(TIME, AVG_BHP, label="avg BHP", linewidth=1.8, color=cmap[2])
    axs[1].fill_between(TIME, MAX_BHP_SERIES, AVG_BHP - (MAX_BHP_SERIES-AVG_BHP), label="pumping amplitude", linewidth=1.8, color=cmap[2], alpha=0.3)
    
    axs[1].axhline(
        MAX_BHP,
        linestyle=":",
        linewidth=1.5
    )
    
    axs[1].text(
        TIME[len(TIME)//20],
        MAX_BHP,
        f"BHP limit = {MAX_BHP:.0f} kW",
        va="bottom",
        ha="left"
    )
    
    # axs[1].set_ylim(0, None)
    axs[1].set_ylabel("Propulsion power / kW")
    axs[1].legend()
    axs[1].grid(True, alpha=0.7)
    
    # ------------------------------------------------------------------
    # 3. TWS
    # ------------------------------------------------------------------
    
    axs[2].plot(TIME, TWS, linewidth=1.8, color=cmap[3])
    axs[2].set_ylim(0, None)
    axs[2].set_ylabel("TWS / kts")
    axs[2].grid(True, alpha=0.7)
    
    ax_twa = axs[2].twinx()
    ax_twa.plot(TIME, np.abs(sol(twa)), linestyle="--", linewidth=1.5, color=cmap[3], label="SWH")
    ax_twa.set_ylabel("TWA / deg")
    ax_twa.set_ylim(0, 180)
    # ax_twa.set_yticks([-180, -90, 0, 90, 180])
    ax_twa.set_yticks([0, 45, 90, 135, 180])
    
    # Optional: improve readability
    ax_twa.tick_params(axis="y")
    
    # ------------------------------------------------------------------
    # 4. SWH
    # ------------------------------------------------------------------
    
    axs[3].plot(TIME, SWH, linewidth=1.8, color=cmap[0], label="SWH")
    axs[3].set_ylim(0, None)
    axs[3].set_ylabel("SWH / m")
    axs[3].grid(True, alpha=0.7)
    
    ax_wa = axs[3].twinx()
    ax_wa.plot(TIME, np.abs(sol(wa)), linestyle="--", linewidth=1.5, color=cmap[0], label="WA")
    ax_wa.set_ylabel("WA / deg")
    ax_wa.set_ylim(0, 180)
    ax_wa.set_yticks([0, 45, 90, 135, 180])
    # ax_wa.set_yticks([-180, -90, 0, 90, 180])
    
    # ------------------------------------------------------------------
    # Time axis formatting
    # ------------------------------------------------------------------
    
    axs[3].xaxis.set_major_locator(
        mdates.HourLocator(byhour=[0, 12])
    )
    axs[3].xaxis.set_major_formatter(
        mdates.DateFormatter("%Y-%m-%d %H:%M")
    )
    
    plt.setp(
        axs[3].get_xticklabels(),
        rotation=45,
        ha="right"
    )
    
    # axs.set
    
    for ax in axs:
        ax.grid(linewidth=1, color="white")
        ax.margins(x=0.000, y=0.02)
    
    plt.show()

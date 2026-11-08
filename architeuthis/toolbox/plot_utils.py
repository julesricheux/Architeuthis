# -*- coding: utf-8 -*-
"""
Created on Mon Dec 15 22:36:04 2025

@author: jrich
"""

import os
from contextlib import contextmanager

import matplotlib

import numpy as onp
import pandas as pd
import seaborn as sns
import cartopy.crs as ccrs
import architeuthis.numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import cartopy.feature as cfeature
# import cartopy.mpl.ticker as cticker
from matplotlib.colors import to_rgba
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.text import Text

from architeuthis.toolbox.geo_utils import great_circle_route, midpoints

import matplotlib as mpl
from cycler import cycler

_FONT_SIZES = {
    "font.size": 13,
    "axes.titlesize": 14,
    "axes.labelsize": 13,
    "xtick.labelsize": 12,
    "ytick.labelsize": 12,
    "legend.fontsize": 12
}

A4_PORTRAIT = (8.27, 11.69)  # inches, true A4

# Quantile bands: (lower, upper, opacity, label) and their common color.
_QUANTILE_BANDS = (
    (0.01, 0.99, 0.1, "1–99%"),
    (0.05, 0.95, 0.25, "05–95%"),
    (0.25, 0.75, 0.4, "25–75%"),
)
_BAND_COLOR = "limegreen"


#%% STYLE

def set_plot_style():
    """
    Apply the Architeuthis figure style to every figure from now on, for scripts drawing their
    own figures. Importing this module does not change anything: an application keeps its style.
    """
    sns.set_theme(palette="viridis")
    mpl.rcParams.update(_FONT_SIZES)


@contextmanager
def plot_style():
    """Apply the Architeuthis figure style inside a `with` block only. The plots of this module use it."""
    rc = dict(sns.plotting_context("notebook"))
    rc.update(sns.axes_style("darkgrid"))
    rc["font.family"] = ["sans-serif"]
    rc["axes.prop_cycle"] = cycler("color", sns.color_palette("viridis"))
    rc.update(_FONT_SIZES)
    with mpl.rc_context(rc):
        yield


def _fix_style(fig):
    """
    Build the ticks of a figure, and set their size and its fonts, now. Matplotlib otherwise
    looks them up when it draws, which may be after the end of the `plot_style` block: in
    Spyder, in a GUI or with a later `savefig`, the figure would then take the style in effect
    at that time, even for the number of ticks, which follows their size.
    """
    for ax in fig.axes:
        ax.tick_params(axis="x", which="both", labelsize=mpl.rcParams["xtick.labelsize"])
        ax.tick_params(axis="y", which="both", labelsize=mpl.rcParams["ytick.labelsize"])
        for axis in (ax.xaxis, ax.yaxis):
            axis.get_major_ticks()
            axis.get_minor_ticks()

    font = FontProperties(fname=findfont(FontProperties())).get_name()
    for text in fig.findobj(Text):
        text.set_fontfamily(font)


def _finish(fig, save_as=None, show=True):
    """Save and display a finished figure, and return it."""
    _fix_style(fig)
    if save_as:
        extension = os.path.splitext(str(save_as))[1].lstrip(".").lower()
        fig.savefig(save_as, format=extension or "pdf")
    if show:
        plt.show()
    return fig


#%% HELPERS SHARED BY THE PLOTS

def _times(values):
    """Float epoch seconds as dates."""
    return pd.to_datetime(onp.ravel(values), unit="s")


def get_steps(report, quantity):
    """
    Times and values of a per-segment quantity, to plot it as steps with
    `plt.plot(*get_steps(report, "avg_bhp"))`: each value is held from one node to the next.
    """
    tim = pd.to_datetime(report["tim"], unit="s")

    X = []
    Y = []
    for i in range(len(report["ctim"])):
        X.append(tim[i])
        X.append(tim[i+1])
        Y.append(report[quantity][i])
        Y.append(report[quantity][i])

    return onp.asarray(X), onp.asarray(Y)


def add_map_background(ax):
    """Land, ocean, coastline and gridlines of the maps of this module."""
    # Add background features
    # ax.add_feature(cfeature.LAND, facecolor="palegoldenrod")
    ax.add_feature(cfeature.LAND, facecolor="khaki")
    # ax.add_feature(cfeature.LAND, facecolor="sandybrown")
    ax.add_feature(cfeature.OCEAN, facecolor="lavender")
    # ax.add_feature(cfeature.OCEAN, facecolor="lightsteelblue")
    ax.add_feature(cfeature.COASTLINE, linewidth=0.3)
    # ax.add_feature(cfeature.BORDERS, linestyle=":")
    # Cartopy reads the color and the line style when it draws: they are given now, see _fix_style.
    gl = ax.gridlines(
        draw_labels=False,
        dms=True,
        x_inline=False,
        y_inline=False,
        linewidth=0.5,
        color=mpl.rcParams["grid.color"],
        linestyle=mpl.rcParams["grid.linestyle"],
    )

    # Gridlines at round degrees only
    # gl.xtick(1.0)
    gl.xlabel_style = {"size": 10}
    gl.ylabel_style = {"size": 10}

    return gl


def _quantile_bands(ax, x, quantiles, prefix="", **median_kwargs):
    """Bands of `quantiles`, a `{q: values}` dict, around the median."""
    for lower, upper, alpha, label in _QUANTILE_BANDS:
        ax.fill_between(x, quantiles[lower], quantiles[upper], alpha=alpha, label=f"{prefix}{label}", color=_BAND_COLOR)
    ax.plot(x, quantiles[0.50], label="Median", **median_kwargs)


#%% ROUTES ON A MAP

def plot_route(lon, lat, clon, clat, tws, twd, barbs, sails_contribution=None, sails_threshold=1., ax=None, save_as=None, show=True):
    """
    Routes on a map, one color per route, over the great circle of the first one (in grey).

    Args:
        lon, lat: Node positions, one array per route.
        clon, clat: Segment centers, one array per route.
        tws, twd: True wind speed (kt) and direction (deg) at segment centers, one array per route.
        barbs: Whether wind barbs are drawn at segment centers.
        sails_contribution: Sails contribution (%) at segment centers, one array per route. If
            given, a dot marks the segments above `sails_threshold` instead of every node.
        ax: Cartopy axes to draw in. By default, the current figure is cleared.
        save_as: File to write. Its extension gives the format, PDF if it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    with plot_style():
        return _plot_route(lon, lat, clon, clat, tws, twd, barbs, sails_contribution, sails_threshold, ax, save_as, show)


def _plot_route(lon, lat, clon, clat, tws, twd, barbs, sails_contribution, sails_threshold, ax, save_as, show):
    if ax is None:
        plt.clf()
        # fig = plt.figure(dpi=300)
        ax = plt.axes(projection=ccrs.PlateCarree())

    assert len(lat)==len(lon), f"latitudes and longitudes collections must have the same length. Got {len(lat)} and {len(lon)}."
    
    n = len(lat)
    cmap = sns.color_palette("Spectral", as_cmap=True)
    # cmap = plt.get_cmap("Spectral", n)
    
    add_map_background(ax)

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

    return _finish(ax.figure, save_as, show)


def draw(reports, barbs=True, sails_threshold=None, ax=None, save_as=None, show=True):
    """
    Routes of several reports on a map. See `plot_route`.

    Args:
        reports: The reports to draw.
        barbs: Whether wind barbs are drawn at segment centers.
        sails_threshold: If given, a dot marks the segments whose sails contribution is above
            this value, in %, instead of every node.
        ax: Cartopy axes to draw in. By default, the current figure is cleared.
        save_as: File to write. Its extension gives the format, PDF if it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    # cvtim = pd.to_datetime(self.report["ctim"], unit="s")
    # vtim = pd.to_datetime(self.report["tim"], unit="s")

    lons = [r["lon"] for r in reports]
    lats = [r["lat"] for r in reports]
    clons = [r["clon"] for r in reports]
    clats = [r["clat"] for r in reports]
    tws = [r["tws"] for r in reports]
    twd = [r["twd"] for r in reports]

    kwargs = dict(ax=ax, save_as=save_as, show=show)
    if sails_threshold is not None:
        kwargs |= dict(sails_contribution=[r["sails_contribution"] for r in reports], sails_threshold=sails_threshold)

    return plot_route(lons, lats, clons, clats, tws, twd, barbs, **kwargs)


#%% A4 PAGE OF A ROUTE

# Panels of the A4 page, from top to bottom, in the order of `fig.axes`.
REPORT_PANELS = ("sog", "sails", "bhp", "swh", "tws", "aws")

_AWS_COLOR = "#e57373"  # light red


def _plot_gust_panel(ax, ctim, report, key, color, fill_alpha):
    """A wind speed, and its gust as a dashed line with the band between them, if the report has it."""
    step_kw = dict(where="mid")
    speed = onp.asarray(report[key], dtype=float)
    ax.step(ctim, speed, color=color, label="Average", **step_kw)

    gust_key = f"{key}_gust"
    if gust_key in report:
        gust = onp.asarray(report[gust_key], dtype=float)
        ax.step(ctim, gust, color=color, label="Gust", ls="--", **step_kw)
        ax.fill_between(ctim, speed, gust, step="mid", alpha=fill_alpha, color=color)
        ax.legend(loc="upper right", fontsize=8)


def plot_report(report, save_as=None, show=True, figsize=A4_PORTRAIT, dpi=300, ylim=None):
    """
    One route on an A4 page: six stacked panels sharing a time axis in UTC.

    The panels are, from top to bottom, with the report entries they use:

    ========= ========================== ==================================================
    Panel     Entries                    Content
    ========= ========================== ==================================================
    `sog`     `sog`                      Speed over ground, kt
    `sails`   `sails_contribution`       Sails contribution, % (axis from 0 to 100)
    `bhp`     `avg_bhp`, `max_bhp`       Average BHP, kW, with load fluctuations: dashed
                                         lines and a band at average +/- (max - average)
    `swh`     `swh`                      Significant wave height, m
    `tws`     `tws`, `tws_gust`          True wind, kt, average and gust
    `aws`     `aws`, `aws_gust`          Apparent wind, kt, average and gust
    ========= ========================== ==================================================

    Values are per segment and drawn as steps centered on `ctim`. The time axis runs from the
    first to the last node of `tim`. The gust lines are left out if the report has no gust,
    which happens with `options={"include_gusts": False}`.

    Args:
        report: A report of `RoutingAnalysis.run` or `evaluate`, or the same dict reloaded from JSON.
        save_as: File to write. Its extension gives the format, PDF if it has none. The page
            size is kept exactly, so a PDF is a true A4 page.
        show: Whether to call `plt.show()`. Pass False in a GUI or to save pages in a loop, and
            close the figure with `plt.close(fig)` when done.
        figsize: Page size in inches. `A4_PORTRAIT` by default.
        dpi: Resolution in dots per inch.
        ylim: Vertical limits by panel name, replacing the defaults, for example
            `{"sog": (6., 13.), "bhp": (0., 3084.)}`. By default, `sails` runs from 0 to 100,
            `sog` is automatic and the others start at 0.

    Returns:
        The figure. `fig.axes` holds the panels in the order of `REPORT_PANELS`, for further
        customization.
    """
    ctim = _times(report["ctim"])
    tim = _times(report["tim"])

    with plot_style():
        fig, axes = plt.subplots(
            nrows=len(REPORT_PANELS),
            ncols=1,
            figsize=figsize,
            dpi=dpi,
            sharex=True,
            gridspec_kw={"height_ratios": [1, 1, 1.3, 1, 1, 1], "hspace": 0.12},
        )
        panels = dict(zip(REPORT_PANELS, axes))

        step_kw = dict(where="mid")

        # Colors of the palette, read now: a name like "C0" would be looked up when drawing.
        C0, C1, C2, C3, C4 = (to_rgba(f"C{i}") for i in range(5))

        # 1. SOG
        panels["sog"].step(ctim, onp.asarray(report["sog"], dtype=float), color=C0, **step_kw)
        panels["sog"].set_ylabel("SOG / kts")

        # 2. Sails contribution (0-100 %)
        panels["sails"].step(ctim, onp.asarray(report["sails_contribution"], dtype=float), color=C2, **step_kw)
        panels["sails"].set_ylabel("Sails contribution / %")
        panels["sails"].set_ylim(0., 100.)

        # 3. BHP with load fluctuations
        avg_bhp = onp.asarray(report["avg_bhp"], dtype=float)
        max_bhp = onp.asarray(report["max_bhp"], dtype=float)
        osc = max_bhp - avg_bhp
        panels["bhp"].step(ctim, avg_bhp, color=C0, label="Average BHP", **step_kw)
        panels["bhp"].step(ctim, max_bhp, color=C1, ls="--", lw=0.8, label="Load fluctuations", **step_kw)
        panels["bhp"].step(ctim, avg_bhp - osc, color=C1, ls="--", lw=0.8, **step_kw)
        panels["bhp"].fill_between(ctim, avg_bhp - osc, avg_bhp + osc, step="mid", alpha=0.15, color=C1)
        panels["bhp"].set_ylabel("BHP / kW")
        panels["bhp"].set_ylim(0., None)
        panels["bhp"].legend(loc="upper right", fontsize=8)

        # 4. SWH
        panels["swh"].step(ctim, onp.asarray(report["swh"], dtype=float), color=C3, **step_kw)
        panels["swh"].set_ylabel("SWH / m")
        panels["swh"].set_ylim(0., None)

        # 5. TWS
        _plot_gust_panel(panels["tws"], ctim, report, "tws", color=C4, fill_alpha=0.15)
        panels["tws"].set_ylabel("TWS / kts")
        panels["tws"].set_ylim(0., None)

        # 6. AWS
        _plot_gust_panel(panels["aws"], ctim, report, "aws", color=_AWS_COLOR, fill_alpha=0.2)
        panels["aws"].set_ylabel("AWS / kts")
        panels["aws"].set_ylim(0., None)

        for key, limits in (ylim or {}).items():
            panels[key].set_ylim(*limits)

        # Shared x-axis formatting (only the bottom panel carries the time labels)
        for ax in axes:
            ax.grid(alpha=1.0)
        axes[-1].set_xlim(tim[0], tim[-1])
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
        axes[-1].set_xlabel("Time (UTC)")

        fig.align_ylabels(axes)
        fig.subplots_adjust(left=0.10, right=0.97, top=0.98, bottom=0.07, hspace=0.12)

        return _finish(fig, save_as, show)


#%% SEVERAL REPORTS

def plot_fuel_vs_etd(reports, models_colors=None, ylim=None, figsize=(10, 3.5), show=True):
    """
    Total fuel against ETD: one figure per vessel, one color per model, crosses for the
    reference routes (`solve` 0) and dots for the optimized ones (`solve` 1).

    Args:
        reports: Reports with `solve`, `vessel` and `model` entries.
        models_colors: Color by model name. A viridis color each by default.
        ylim: Vertical limits, common to the figures. By default, rounded to 2 t around the
            lowest and highest fuel of the reports.
        figsize: Size of each figure in inches.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The list of figures.
    """
    frame = pd.DataFrame(reports)
    fuel_reports = frame.groupby(["solve", "vessel", "model"], as_index=False)[["etd", "fuel"]].agg(list)

    if ylim is None:
        ylim = ((frame["fuel"].min() // 2 - 1) * 2., (frame["fuel"].max() // 2 + 1) * 2.)

    models = fuel_reports["model"].unique()
    colors = models_colors or dict(zip(models, sns.color_palette("viridis", len(models))))
    markers = {0: "x", 1: "o"}
    names = {0: "ortho cst speed", 1: "optimised"}

    figures = []
    with plot_style():
        for eff in fuel_reports["vessel"].unique():
            fig, ax = plt.subplots(figsize=figsize)
            for _, fr in fuel_reports[fuel_reports["vessel"] == eff].iterrows():
                ax.scatter(
                    _times(fr["etd"]), fr["fuel"],
                    marker=markers[fr["solve"]],
                    color=colors[fr["model"]],
                    label=f"{fr['model'].upper()} / {names[fr['solve']]}",
                )
            ax.tick_params(axis="x", rotation=45.)
            ax.set_xlabel("ETD (UTC)")
            ax.set_ylabel("Total fuel consumption / tons")
            ax.set_title(f"Sails efficiency {str(eff).removeprefix('eff')} %")
            ax.set_ylim(ylim)
            ax.legend()
            _fix_style(fig)
            figures.append(fig)
        if show:
            plt.show()
    return figures


def plot_variable(reports, variable, unit="", labels=None, ylim=(0., None), legend=False, figsize=(12, 6), dpi=300, save_as=None, show=True):
    """
    A per-segment quantity of several reports against time, as steps.

    Args:
        reports: The reports to compare, one viridis color each.
        variable: Report entry, for example `sog`, `tws`, `swh`, `sails_contribution`, `avg_bhp`.
        unit: Unit shown in the axis label.
        labels: Legend text by `init_fac`, for example `{-1.: "North", 0.: "Ortho", 1.: "South"}`.
        ylim: Vertical limits.
        legend: Whether to draw the legend.
        figsize, dpi: Size in inches and resolution.
        save_as: File to write. Its extension gives the format, PDF if it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    labels = labels or {}
    colors = sns.color_palette(palette="viridis", n_colors=len(reports))

    with plot_style():
        fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
        for color, report in zip(colors, reports):
            x, y = get_steps(report, variable)
            ax.plot(x, y, label=labels.get(report["init_fac"], f"Route {report['init_fac']}"), color=color)
            ax.set_xlim((x.min(), x.max()))
        ax.set_ylim(ylim)
        if legend:
            ax.legend()
        ax.tick_params(axis="x", rotation=45)
        ax.set_xlabel("Time (UTC)")
        ax.set_ylabel(f"{variable.upper()} / {unit}")
        fig.tight_layout()
        return _finish(fig, save_as, show)


def plot_power_and_weather(reports, labels=None, max_bhp=False, figsize=(12, 10), dpi=300, save_as=None, show=True):
    """
    Average BHP, SWH and TWS of several reports on three stacked panels, as steps.

    Args:
        reports: The reports to compare, one viridis color each.
        labels: Legend text by `init_fac`, for example `{-1.: "North", 0.: "Ortho", 1.: "South"}`.
        max_bhp: Whether to add `max_bhp` as dashed lines on the top panel.
        figsize, dpi: Size in inches and resolution.
        save_as: File to write. Its extension gives the format, PDF if it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure, with the panels in `fig.axes` from top to bottom.
    """
    labels = labels or {}
    colors = sns.color_palette(palette="viridis", n_colors=len(reports))

    with plot_style():
        fig, axes = plt.subplots(nrows=3, ncols=1, figsize=figsize, dpi=dpi, sharex=True)
        for color, report in zip(colors, reports):
            label = labels.get(report["init_fac"], f"Route {report.get('init_fac')}")
            axes[0].plot(*get_steps(report, "avg_bhp"), label=label, color=color)
            if max_bhp:
                axes[0].plot(*get_steps(report, "max_bhp"), ls="--", color=color)
            axes[1].plot(*get_steps(report, "swh"), label=label, color=color)
            axes[2].plot(*get_steps(report, "tws"), label=label, color=color)

        axes[0].set_ylabel("AVG_BHP / kW")
        axes[0].legend(loc="upper right")
        axes[1].set_ylabel("SWH / m")
        axes[2].set_ylabel("TWS / kts")
        for ax in axes:
            ax.set_ylim((0., None))

        axes[2].set_xlabel("Time (UTC)")
        plt.setp(axes[2].xaxis.get_majorticklabels(), rotation=45)

        fig.tight_layout()
        return _finish(fig, save_as, show)


def plot_quantiles(reports, variable, unit="", prefix="", title=None, ylim=None, daily_ticks=False, figsize=(10, 4), save_as=None, show=True):
    """
    Spread of a per-segment quantity over reports on the same time grid: bands between the
    quantiles 1-99 %, 5-95 % and 25-75 %, and the median. This is the ensemble meteogram.

    Args:
        reports: Reports on the same `ctim`, typically ensemble members.
        variable: Report entry, for example `avg_bhp`, `tws`, `swh`, `sog`.
        unit: Unit shown in the axis label.
        prefix: Text before the band labels, for example `"IFS ensemble "`.
        title: Figure title.
        ylim: Vertical limits.
        daily_ticks: Whether to mark every day on the time axis.
        figsize: Size in inches.
        save_as: File to write. Its extension gives the format, PDF if it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    values = onp.array([report[variable] for report in reports], dtype=float)
    quantiles = {q: onp.quantile(values, q, axis=0) for q in (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)}
    ctim = _times(reports[0]["ctim"])

    with plot_style():
        fig, ax = plt.subplots(figsize=figsize)
        if daily_ticks:
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))   # every 24 h
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        _quantile_bands(ax, ctim, quantiles, prefix=prefix, marker="o", ms=3.)
        ax.legend()
        if ylim is not None:
            ax.set_ylim(ylim)
        ax.tick_params(axis="x", rotation=45)
        ax.set_ylabel(f"{variable.upper()} / {unit}")
        if title:
            ax.set_title(title)
        fig.tight_layout()
        return _finish(fig, save_as, show)


def plot_fuel_quantiles(reports, daily=False, converged_only=True, figsize=(8, 4), save_as=None, show=True):
    """
    Spread of the fuel over reports, against ETA: bands between the quantiles 1-99 %, 5-95 %
    and 25-75 %, and the median.

    Args:
        reports: Reports with several ETA, typically an ETA sweep or ensemble members.
        daily: Whether to show tons per day of transit instead of the total.
        converged_only: Whether to leave out the reports with `status` other than 1.
        figsize: Size in inches.
        save_as: File to write. Its extension gives the format, PDF if it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    frame = pd.DataFrame(reports)
    frame["daily_fuel"] = frame["fuel"] / frame["transit_time"] * 24.
    if converged_only:
        frame = frame[frame["status"] == 1]

    quantity = "daily_fuel" if daily else "fuel"
    quantiles = frame.groupby("eta")[quantity].quantile(
        [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
    ).unstack()
    x = _times(quantiles.index.values)

    with plot_style():
        fig, ax = plt.subplots(figsize=figsize)
        _quantile_bands(ax, x, {q: quantiles[q].values for q in quantiles.columns}, marker="o")
        ax.legend()
        ax.tick_params(axis="x", rotation=45)
        ax.set_xlabel("ETA")
        ax.set_ylabel("DAILY FUEL CONS. / tons/day" if daily else "TOTAL FUEL CONS. / tons")
        fig.tight_layout()
        return _finish(fig, save_as, show)


def plot_convergence(reports, figsize=(8, 4), save_as=None, show=True):
    """
    Share of the reports that converged (`status` 1) for each ETA: the probability that this
    ETA is possible, when the reports are ensemble members.

    Args:
        reports: Reports with several ETA.
        figsize: Size in inches.
        save_as: File to write. Its extension gives the format, PDF if it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    ratio = pd.DataFrame(reports).groupby("eta")["status"].apply(lambda s: (s == 1).mean())

    with plot_style():
        fig, ax = plt.subplots(figsize=figsize)
        ax.plot(_times(ratio.index.values), ratio.values * 100, marker="o")
        ax.set_xlabel("ETA")
        ax.set_ylabel("Probability of possible ETA / %")
        ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
        return _finish(fig, save_as, show)


def plot_fuel_distribution(groups, figsize=(8, 3), save_as=None, show=True):
    """
    Fuel distributions side by side, as violins with box plots.

    Args:
        groups: Reports by label, for example
            `{"Eff. 45%": reports.select(vessel="eff45"), "Eff. 60%": reports.select(vessel="eff60")}`.
        figsize: Size in inches.
        save_as: File to write. Its extension gives the format, PDF if it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    data = [[report["fuel"] for report in group] for group in groups.values()]

    with plot_style():
        fig, ax = plt.subplots(figsize=figsize)
        ax.violinplot(data, showextrema=False)
        boxes = ax.boxplot(data, patch_artist=True)
        for box in boxes["boxes"]:
            box.set(facecolor=_BAND_COLOR)
        ax.set_xticks(list(range(1, len(data)+1)))
        ax.set_xticklabels(list(groups.keys()))
        ax.set_ylabel("Fuel / tons")
        return _finish(fig, save_as, show)


#%% FORMER FIGURES

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

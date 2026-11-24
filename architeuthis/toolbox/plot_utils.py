# -*- coding: utf-8 -*-
"""
Figures of routes and routing reports.

They are documented in `docs/user_guide.md`.

Created on Mon Dec 15 22:36:04 2025

@author: jrich
"""

import os
from contextlib import contextmanager
from types import SimpleNamespace

import matplotlib
import matplotlib.collections

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
    Apply the Architeuthis figure style to every figure from now on.

    This is for scripts drawing their own figures. Importing this module
    does not change anything: an application keeps its style.
    """
    sns.set_theme(palette="viridis")
    mpl.rcParams.update(_FONT_SIZES)


@contextmanager
def plot_style():
    """
    Apply the Architeuthis figure style inside a `with` block only.

    The plots of this module use it.
    """
    rc = dict(sns.plotting_context("notebook"))
    rc.update(sns.axes_style("darkgrid"))
    rc["font.family"] = ["sans-serif"]
    rc["axes.prop_cycle"] = cycler("color", sns.color_palette("viridis"))
    rc.update(_FONT_SIZES)
    with mpl.rc_context(rc):
        yield


def _fix_style(fig):
    """
    Build the ticks of a figure, and set their size and its fonts, now.

    Matplotlib otherwise looks them up when it draws, which may be after
    the end of the `plot_style` block: in Spyder, in a GUI or with a
    later `savefig`, the figure would then take the style in effect at
    that time, even for the number of ticks, which follows their size.
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
    """
    Save and display a finished figure, and return it.
    """
    _fix_style(fig)
    if save_as:
        extension = os.path.splitext(str(save_as))[1].lstrip(".").lower()
        fig.savefig(save_as, format=extension or "pdf")
    if show:
        plt.show()
    return fig


#%% HELPERS SHARED BY THE PLOTS

def _times(values):
    """
    Float epoch seconds as dates.
    """
    return pd.to_datetime(onp.ravel(values), unit="s")


def get_steps(report, quantity):
    """
    Times and values of a per-segment quantity, to plot it as steps.

    Use it with `plt.plot(*get_steps(report, "bhp"))`: each value is
    held from one node to the next.
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
    """
    Land, ocean, coastline and gridlines of the maps of this module.
    """
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
    """
    Bands of `quantiles`, a `{q: values}` dict, around the median.
    """
    for lower, upper, alpha, label in _QUANTILE_BANDS:
        ax.fill_between(x, quantiles[lower], quantiles[upper], alpha=alpha, label=f"{prefix}{label}", color=_BAND_COLOR)
    ax.plot(x, quantiles[0.50], label="Median", **median_kwargs)


#%% ROUTES ON A MAP

def plot_route(lon, lat, clon, clat, tws, twd, barbs, sails_contribution=None, sails_threshold=1., ax=None, save_as=None, show=True):
    """
    Routes on a map, one color per route.

    They are drawn over the great circle of the first one (in grey).

    Args:
        lon, lat: Node positions, one array per route.
        clon, clat: Segment centers, one array per route.
        tws, twd: True wind speed (kt) and direction (deg) at segment
            centers, one array per route.
        barbs: Whether wind barbs are drawn at segment centers.
        sails_contribution: Sails contribution (%) at segment centers,
            one array per route. If given, a dot marks the segments
            above `sails_threshold` instead of every node.
        ax: Cartopy axes to draw in. By default, the current figure is
            cleared.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
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
        sails_threshold: If given, a dot marks the segments whose sails
            contribution is above this value, in %, instead of every
            node. It needs `sails_contribution` in every report.
        ax: Cartopy axes to draw in. By default, the current figure is
            cleared.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
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
    # The sails contribution is in reports when the routing lists it in its variables
    if sails_threshold is not None and all("sails_contribution" in r for r in reports):
        kwargs |= dict(sails_contribution=[r["sails_contribution"] for r in reports], sails_threshold=sails_threshold)

    return plot_route(lons, lats, clons, clats, tws, twd, barbs, **kwargs)


def plot_route_set(route_set, n=50, ax=None, save_as=None, show=True):
    """
    The reference routes of a `RouteSet` on a map.

    This checks them before routing: ortho in solid black, minus in
    dashed red and plus in dashed green.

    Args:
        route_set: The `RouteSet`.
        n: Number of points drawn per route.
        ax: Cartopy axes to draw in. By default, a new figure.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    s = onp.linspace(0., 1., n)
    styles = (
        (route_set.ortho, {"color": "black"}),
        (route_set.minus, {"color": "red", "ls": "--"}),
        (route_set.plus, {"color": "green", "ls": "--"}),
    )

    with plot_style():
        if ax is None:
            ax = plt.figure().add_subplot(projection=ccrs.PlateCarree())

        add_map_background(ax)

        for route, style in styles:
            lat, lon = route(s)
            ax.plot(lon, lat, lw=1, label=route.name, transform=ccrs.PlateCarree(), **style)
        ax.legend(loc="lower left", fontsize=8)

        return _finish(ax.figure, save_as, show)


#%% A4 PAGE OF A ROUTE

# Panels of the A4 page, from top to bottom, in the order of `fig.axes`.
REPORT_PANELS = ("sog", "sails", "bhp", "swh", "tws", "aws")

_AWS_COLOR = "#e57373"  # light red


def _plot_gust_panel(ax, ctim, report, key, color, fill_alpha):
    """
    A wind speed, and its gust if the report has it.

    The gust is a dashed line, with the band between them.
    """
    step_kw = dict(where="mid")
    speed = onp.asarray(report[key], dtype=float)
    ax.step(ctim, speed, color=color, label="Average", **step_kw)

    gust_key = f"{key}_gust"
    if gust_key in report:
        gust = onp.asarray(report[gust_key], dtype=float)
        ax.step(ctim, gust, color=color, label="Gust", ls="--", **step_kw)
        ax.fill_between(ctim, speed, gust, step="mid", alpha=fill_alpha, color=color)
        ax.legend(loc="upper right", fontsize=8)


def _not_in_report(ax, key):
    """
    Say on a panel that the report has no `key`.
    """
    ax.text(
        0.5, 0.5, f"No {key} in this report: list it in the variables",
        transform=ax.transAxes, ha="center", va="center", fontsize=8, color="grey",
    )


def plot_report(report, save_as=None, show=True, figsize=A4_PORTRAIT, dpi=300, ylim=None):
    """
    One route on an A4 page.

    It has six stacked panels sharing a time axis in UTC.

    The panels are, from top to bottom, with the report entries they
    use:

    ======= ==================== ===================================
    Panel   Entries              Content
    ======= ==================== ===================================
    `sog`   `sog`                Speed over ground, kt
    `sails` `sails_contribution` Sails contribution, % (axis from 0
                                 to 100)
    `bhp`   `bhp`, `max_bhp`     Average BHP, kW, with load
                                 fluctuations: dashed lines and a
                                 band at average +/- (max - average)
    `swh`   `swh`                Significant wave height, m
    `tws`   `tws`, `tws_gust`    True wind, kt, average and gust
    `aws`   `aws`, `aws_gust`    Apparent wind, kt, average and gust
    ======= ==================== ===================================

    Values are per segment and drawn as steps centered on `ctim`. The
    time axis runs from the first to the last node of `tim`. The gust
    lines are left out if the report has no gust, which happens with
    `options={}` without `"gust"` in `variables`. Likewise, the load
    fluctuations need `max_bhp` in `variables`, and the `sails` panel
    `sails_contribution`, else it says so. Without `bhp`, the
    `bhp` panel draws `total_power`, else `hourly_consumption`.

    Args:
        report: A report of `RoutingAnalysis.run` or `evaluate`, or the
            same dict reloaded from JSON.
        save_as: File to write. Its extension gives the format, PDF if
            it has none. The page size is kept exactly, so a PDF is a
            true A4 page.
        show: Whether to call `plt.show()`. Pass False in a GUI or to
            save pages in a loop, and close the figure with
            `plt.close(fig)` when done.
        figsize: Page size in inches. `A4_PORTRAIT` by default.
        dpi: Resolution in dots per inch.
        ylim: Vertical limits by panel name, replacing the defaults, for
            example `{"sog": (6., 13.), "bhp": (0., 3084.)}`. By
            default, `sails` runs from 0 to 100, `sog` is automatic and
            the others start at 0.

    Returns:
        The figure. `fig.axes` holds the panels in the order of
        `REPORT_PANELS`, for further customization.
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
        if "sails_contribution" in report:
            panels["sails"].step(ctim, onp.asarray(report["sails_contribution"], dtype=float), color=C2, **step_kw)
        else:
            _not_in_report(panels["sails"], "sails_contribution")
        panels["sails"].set_ylabel("Sails contribution / %")
        panels["sails"].set_ylim(0., 100.)

        # 3. BHP with load fluctuations, else the power or the consumption
        if "bhp" in report:
            bhp = onp.asarray(report["bhp"], dtype=float)
            panels["bhp"].step(ctim, bhp, color=C0, label="Average BHP", **step_kw)
            if "max_bhp" in report:
                max_bhp = onp.asarray(report["max_bhp"], dtype=float)
                osc = max_bhp - bhp
                panels["bhp"].step(ctim, max_bhp, color=C1, ls="--", lw=0.8, label="Load fluctuations", **step_kw)
                panels["bhp"].step(ctim, bhp - osc, color=C1, ls="--", lw=0.8, **step_kw)
                panels["bhp"].fill_between(ctim, bhp - osc, bhp + osc, step="mid", alpha=0.15, color=C1)
            panels["bhp"].set_ylabel("BHP / kW")
            panels["bhp"].legend(loc="upper right", fontsize=8)
        elif "total_power" in report:
            panels["bhp"].step(ctim, onp.asarray(report["total_power"], dtype=float), color=C0, **step_kw)
            panels["bhp"].set_ylabel("Total power / kW")
        else:
            panels["bhp"].step(ctim, onp.asarray(report["hourly_consumption"], dtype=float), color=C0, **step_kw)
            panels["bhp"].set_ylabel("Consumption / L/h")
        panels["bhp"].set_ylim(0., None)

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
    Total fuel against ETD.

    There is one figure per vessel, one color per model, crosses for the
    reference routes (`solve` 0) and dots for the optimized ones
    (`solve` 1).

    Args:
        reports: Reports with `solve`, `vessel` and `model` entries.
        models_colors: Color by model name. A viridis color each by
            default.
        ylim: Vertical limits, common to the figures. By default,
            rounded to 2 t around the lowest and highest fuel of the
            reports.
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
        variable: Report entry, for example `sog`, `tws`, `swh`,
            `sails_contribution`, `bhp`.
        unit: Unit shown in the axis label.
        labels: Legend text by `init_fac`, for example `{-1.: "North",
            0.: "Ortho", 1.: "South"}`.
        ylim: Vertical limits.
        legend: Whether to draw the legend.
        figsize, dpi: Size in inches and resolution.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
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
    Average BHP, SWH and TWS of several reports.

    They are on three stacked panels, as steps.

    Args:
        reports: The reports to compare, one viridis color each.
        labels: Legend text by `init_fac`, for example `{-1.: "North",
            0.: "Ortho", 1.: "South"}`.
        max_bhp: Whether to add `max_bhp` as dashed lines on the top
            panel, for the reports that have it.
        figsize, dpi: Size in inches and resolution.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
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
            axes[0].plot(*get_steps(report, "bhp"), label=label, color=color)
            if max_bhp and "max_bhp" in report:
                axes[0].plot(*get_steps(report, "max_bhp"), ls="--", color=color)
            axes[1].plot(*get_steps(report, "swh"), label=label, color=color)
            axes[2].plot(*get_steps(report, "tws"), label=label, color=color)

        axes[0].set_ylabel("BHP / kW")
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
    Spread of a per-segment quantity over reports.

    The reports are on the same time grid. The figure has bands between
    the quantiles 1-99 %, 5-95 % and 25-75 %, and the median. This is
    the ensemble meteogram.

    Args:
        reports: Reports on the same `ctim`, typically ensemble members.
        variable: Report entry, for example `bhp`, `tws`, `swh`,
            `sog`.
        unit: Unit shown in the axis label.
        prefix: Text before the band labels, for example `"IFS ensemble
            "`.
        title: Figure title.
        ylim: Vertical limits.
        daily_ticks: Whether to mark every day on the time axis.
        figsize: Size in inches.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
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


def _members_along_route(report, forecast, key):
    """
    A field of an ensemble forecast at the segment centers of a route.

    Its shape is (members, segments).
    """
    ctim, clat, clon = (onp.ravel(report[entry]) for entry in ("ctim", "clat", "clon"))
    members = forecast.data["number"].values

    query = {
        "valid_time": onp.repeat(ctim, members.size),
        "member": onp.tile(members, ctim.size),
        "latitude": onp.repeat(clat, members.size),
        "longitude": onp.repeat(clon, members.size),
    }

    return onp.asarray(forecast(key, query), dtype=float).reshape((members.size, ctim.size), order="F")


def plot_ensemble_along_route(report, atmosphere, wave, ylim=None, figsize=(10, 8), save_as=None, show=True):
    """
    The weather spread along one route, on three stacked panels.

    This holds whatever the member it was optimized for: BHP with load
    fluctuations, then SWH and TWS with their quantile bands over the
    members of an ensemble.

    Args:
        report: The report of the route.
        atmosphere: Ensemble forecast with the `u10` and `v10`
            interpolators, for example an `EnsembleHerbieForecast`.
        wave: Ensemble forecast with the `swh` interpolator, for example
            an `EnsembleHerbieForecast`.
        ylim: Vertical limits by panel name, `bhp`, `swh` or `tws`, for
            example `{"bhp": (0., 2700.), "swh": (0., 7.), "tws": (0.,
            40.)}`. They start at 0 by default.
        figsize: Size in inches.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure, with the panels in `fig.axes` from top to bottom.
    """
    ctim = _times(report["ctim"])
    tim = _times(report["tim"])

    u10 = _members_along_route(report, atmosphere, "u10")
    v10 = _members_along_route(report, atmosphere, "v10")
    weather = {
        "swh": (_members_along_route(report, wave, "swh"), "SWH / m"),
        "tws": (onp.sqrt(u10**2. + v10**2.) * 3600. / 1852., "TWS / kts"),
    }

    bhp = onp.asarray(report["bhp"], dtype=float)

    with plot_style():
        fig, axes = plt.subplots(nrows=3, ncols=1, figsize=figsize, sharex=True)
        panels = dict(zip(("bhp", "swh", "tws"), axes))

        C0, C1, C2 = (to_rgba(f"C{i}") for i in range(3))
        panels["bhp"].plot(ctim, bhp, color=C0, label="Average BHP")
        if "max_bhp" in report:
            max_bhp = onp.asarray(report["max_bhp"], dtype=float)
            osc = max_bhp - bhp
            panels["bhp"].plot(ctim, max_bhp, color=C1, ls="--", label="Load fluctuations")
            panels["bhp"].plot(ctim, bhp - osc, color=C2, ls="--")
            panels["bhp"].fill_between(ctim, bhp - osc, bhp + osc, alpha=0.1, color=C0)
        panels["bhp"].set_ylabel("BHP / kW")
        panels["bhp"].set_xlim((tim[0], tim[-1]))
        panels["bhp"].legend(loc="upper right")

        for key, (values, label) in weather.items():
            quantiles = {q: onp.quantile(values, q, axis=0) for q in (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)}
            _quantile_bands(panels[key], ctim, quantiles, color=C0)
            panels[key].set_ylabel(label)
            panels[key].legend(loc="upper right")

        for key, panel in panels.items():
            panel.set_ylim((ylim or {}).get(key, (0., None)))

        axes[-1].set_xlabel("Time (UTC)")
        plt.setp(axes[-1].xaxis.get_majorticklabels(), rotation=45)

        fig.tight_layout()
        return _finish(fig, save_as, show)


def plot_fuel_quantiles(reports, daily=False, converged_only=True, figsize=(8, 4), save_as=None, show=True):
    """
    Spread of the fuel over reports, against ETA.

    The figure has bands between the quantiles 1-99 %, 5-95 % and 25-75
    %, and the median.

    Args:
        reports: Reports with several ETA, typically an ETA sweep or
            ensemble members.
        daily: Whether to show tons per day of transit instead of the
            total.
        converged_only: Whether to leave out the reports with `status`
            other than 1.
        figsize: Size in inches.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    frame = pd.DataFrame(reports)
    frame["daily_fuel"] = frame["fuel"] / frame["transit_time"] * 24.
    if converged_only:
        frame = frame[frame["status"] == 1]

    quantity = "daily_fuel" if daily else "fuel"
    levels = [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
    # Every column even without reports, when none converged for example: the axes stay empty.
    quantiles = frame.groupby("eta")[quantity].quantile(levels).unstack().reindex(columns=levels)
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
    Share of the reports that converged (`status` 1) for each ETA.

    This is the probability that this ETA is possible, when the reports
    are ensemble members.

    Args:
        reports: Reports with several ETA.
        figsize: Size in inches.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
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


def plot_fuel_distribution(groups, horizontal=False, figsize=(8, 3), save_as=None, show=True):
    """
    Fuel distributions side by side, as violins with box plots.

    Args:
        groups: Reports by label, for example `{"Eff. 45%":
            reports.select(vessel="eff45"), "Eff. 60%":
            reports.select(vessel="eff60")}`.
        horizontal: Whether the fuel runs along the horizontal axis.
        figsize: Size in inches.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.

    Raises:
        ValueError: A group holds no report.
    """
    empty = [label for label, group in groups.items() if len(group) == 0]
    if empty:
        raise ValueError(f"No report to plot in {', '.join(map(str, empty))}.")
    data = [[report["fuel"] for report in group] for group in groups.values()]

    with plot_style():
        fig, ax = plt.subplots(figsize=figsize)
        orientation = {"orientation": "horizontal"} if horizontal else {}
        ax.violinplot(data, showextrema=False, **orientation)
        boxes = ax.boxplot(data, patch_artist=True, **orientation)
        for box in boxes["boxes"]:
            box.set(facecolor=_BAND_COLOR)
        positions = list(range(1, len(data)+1))
        if horizontal:
            ax.set_yticks(positions)
            ax.set_yticklabels(list(groups.keys()))
            ax.set_xlabel("Fuel / tons")
        else:
            ax.set_xticks(positions)
            ax.set_xticklabels(list(groups.keys()))
            ax.set_ylabel("Fuel / tons")
        return _finish(fig, save_as, show)


#%% SKY

# Rows of the étages, of equal heights: the low étage to scale, 2 km
# for the row, the middle and high ones schematic, since the model
# covers give no heights.
SKY_ETAGE_ROWS = {"low": (0.0, 1.0), "middle": (1.0, 2.0), "high": (2.0, 3.0)}
SKY_STYLES = ("cells", "smooth")
_LOW_ETAGE_KM = 2.0
# Heights (km) at the bounds of the rows, for the smooth style.
_ROW_KM = (0.0, 2.0, 6.0, 12.0)
# Color of the genus labels, by form of the genus.
_SKY_FORM_COLORS = {
    "cumuliform": "#1f4e79",
    "stratocumuliform": "#2e7d32",
    "stratiform": "#424242",
    "cirriform": "#7b1fa2",
}
_RAIN_COLOR = "#1e88e5"
_SNOW_COLOR = "#90caf9"
_FOG_HEIGHT = 0.15  # part of the low row
_SKY_CMAP = matplotlib.colors.ListedColormap(plt.get_cmap("Greys")(onp.linspace(0.0, 0.8, 256)))

# Smooth style: sky by day and by night, top and horizon, and clouds lit
# and in shade. The night is only a hint: a darker blue, from the Sun at
# _TWILIGHT[0] deg (civil twilight) to day at _TWILIGHT[1] (sunset), and
# the clouds keep _NIGHT_CLOUD_LIGHT of their brightness in it.
_DAY_SKY = ((0.18, 0.44, 0.73), (0.74, 0.87, 0.96))
_NIGHT_SKY = ((0.13, 0.29, 0.50), (0.50, 0.61, 0.75))
_TWILIGHT = (-6.0, 0.0)
_NIGHT_CLOUD_LIGHT = 0.85
_CLOUD_LIT = onp.array([1.0, 1.0, 1.0])
_CLOUD_SHADE = onp.array([0.33, 0.36, 0.42])
_LIGHTNING_COLOR = "#ffd54f"

# Smooth style, per genus: bottom and top (km, "base" for the cloud
# base, "cape" for a depth growing with the CAPE), opacity, darkness and
# texture.
_SKY_LAYERS = {
    "St": ("base", 0.45, 0.95, 0.45, "flat"),
    "Sc": ("base", 0.9, 0.9, 0.35, "rolls"),
    "Cu": ("base", "cape", 0.95, 0.2, "puffs"),
    "Cb": ("base", 11.0, 1.0, 0.75, "tower"),
    "Ns": (0.6, 6.5, 1.0, 0.8, "flat"),
    "As": (3.0, 6.0, 0.85, 0.5, "flat"),
    "Ac": (3.2, 4.6, 0.8, 0.15, "rolls"),
    "Cs": (7.0, 10.0, 0.6, 0.05, "veil"),
    "Ci": (8.0, 10.5, 0.75, 0.0, "fibres"),
}


def _cell_edges(seconds):
    """
    Edges of the columns centered on each time, in epoch seconds.
    """
    seconds = onp.asarray(seconds, dtype=float)
    if seconds.size == 1:
        return onp.array([seconds[0] - 5400.0, seconds[0] + 5400.0])
    middles = 0.5 * (seconds[1:] + seconds[:-1])
    return onp.concatenate((
        [seconds[0] - (middles[0] - seconds[0])],
        middles,
        [seconds[-1] + (seconds[-1] - middles[-1])],
    ))


def _km_to_row(km):
    """
    Height in km to the vertical coordinate of the meteogram.
    """
    return onp.interp(km, _ROW_KM, [0.0, 1.0, 2.0, 3.0])


def _row_to_km(row):
    """
    Vertical coordinate of the meteogram to height in km.
    """
    return onp.interp(row, [0.0, 1.0, 2.0, 3.0], _ROW_KM)


def _smoothstep(edge0, edge1, x):
    """
    Smooth step from 0 at `edge0` to 1 at `edge1`.
    """
    t = onp.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def sun_elevation(seconds, latitude, longitude):
    """
    Elevation of the Sun above the horizon, to shade the nights.

    A low-precision almanac, within a few tenths of a degree.

    Args:
        seconds: Times in epoch seconds.
        latitude: Latitudes in degrees.
        longitude: Longitudes in degrees.

    Returns:
        The elevation in degrees.
    """
    days = onp.asarray(seconds, dtype=float) / 86400.0 - 10957.5  # since J2000
    anomaly = onp.radians(357.529 + 0.98560028 * days)
    mean_longitude = 280.459 + 0.98564736 * days
    ecliptic = onp.radians(mean_longitude + 1.915 * onp.sin(anomaly) + 0.020 * onp.sin(2.0 * anomaly))
    obliquity = onp.radians(23.439 - 0.00000036 * days)
    right_ascension = onp.degrees(onp.arctan2(onp.cos(obliquity) * onp.sin(ecliptic), onp.cos(ecliptic)))
    declination = onp.arcsin(onp.sin(obliquity) * onp.sin(ecliptic))
    sidereal = (18.697374558 + 24.06570982441908 * days) * 15.0
    hour_angle = onp.radians(sidereal + onp.asarray(longitude, dtype=float) - right_ascension)
    latitude = onp.radians(onp.asarray(latitude, dtype=float))
    return onp.degrees(onp.arcsin(
        onp.sin(latitude) * onp.sin(declination)
        + onp.cos(latitude) * onp.cos(declination) * onp.cos(hour_angle)
    ))


def _sky_data(sky, valid_time):
    """
    Columns of a sky mapping, with their times and the genera present.
    """
    from architeuthis import sky as sky_module

    seconds = onp.atleast_1d(onp.asarray(valid_time, dtype=float)).ravel()
    count = seconds.size

    def column(key, default=onp.nan):
        if key not in sky:
            return onp.full(count, default)
        return onp.atleast_1d(onp.asarray(sky[key])).ravel()

    codes = {etage: column(f"cloud_{etage}", sky_module.NONE).astype(int) for etage in sky_module.ETAGES}
    present = {}
    for etage in sky_module.ETAGES:
        key = f"cloud_{etage}_genera"
        if key in sky:
            masks = column(key, 0).astype(int)
        else:
            masks = onp.where(codes[etage] >= 0, onp.left_shift(1, onp.maximum(codes[etage], 0)), 0)
        present[etage] = [sky_module.genera_present(mask, main) for mask, main in zip(masks, codes[etage])]

    return SimpleNamespace(
        module=sky_module,
        genera=sky_module.load_genera()["genera"],
        limits=sky_module.THRESHOLDS,
        seconds=seconds,
        count=count,
        centers=mdates.date2num(_times(seconds)),
        edges=mdates.date2num(_times(_cell_edges(seconds))),
        covers={"low": column("lcc", 0.0), "middle": column("mcc", 0.0), "high": column("hcc", 0.0)},
        codes=codes,
        present=present,
        base=column("cloud_base"),
        cape=onp.nan_to_num(column("cape", 0.0)),
        rate=column("prate") if "prate" in sky else None,
        t2m=column("t2m"),
        fog=column("fog", False).astype(bool),
        oktas=column("cloud_oktas", 0).astype(int),
        column=column,
    )


def plot_sky(sky, valid_time, style="cells", title=None, labels=True, latitude=None, longitude=None, figsize=(12, 6), dpi=300, save_as=None, show=True):
    """
    Clouds over the air column along a route, as in a meteogram.

    Two styles. "cells" has one row per étage, shaded by its cloud
    cover, with the genera of `sky.diagnose` written in each column,
    colored by their form, and "/" where the clouds below hide them; a
    frame marks the genera that rise through the three étages (Cb,
    Ns), dashes the cloud base, dots the fog, and the oktas run along
    the top. "smooth" paints the sky and its clouds, drawn after their
    genus: puffs of Cu, towers and anvils of Cb, rolls of Sc and Ac,
    veils, fibres of Ci, rain and snow under them, lightning in the
    storms, nights shaded when the positions are given, and the cover
    in okta symbols along the top. Both have the precipitation rate in
    a bottom panel, as rain or snow.

    Args:
        sky: Mapping holding the fields of `sky.SKY_VARIABLES` and the
            result of `sky.diagnose`, as `fields | diagnose(fields)`.
            Without `prate`, there is no bottom panel.
        valid_time: Time of each point, in epoch seconds.
        style: "cells" or "smooth".
        title: Title of the figure.
        labels: Whether to write the genera, and the oktas of "cells".
        latitude, longitude: Position of each point, in degrees, to
            shade the nights in the "smooth" style.
        figsize, dpi: Size in inches and resolution.
        save_as: File to write. Its extension gives the format, PDF if
            it has none.
        show: Whether to call `plt.show()`. Pass False in a GUI.

    Returns:
        The figure.
    """
    if style not in SKY_STYLES:
        raise ValueError(f"Unknown sky style {style!r}: give one of {SKY_STYLES}.")
    data = _sky_data(sky, valid_time)

    with plot_style():
        if data.rate is None:
            fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
            axes = [ax]
        else:
            fig, axes = plt.subplots(
                2, 1, figsize=figsize, dpi=dpi, sharex=True, gridspec_kw={"height_ratios": [3, 1]},
            )
            ax = axes[0]
        ax.grid(False)

        if style == "cells":
            handles = _draw_sky_cells(fig, ax, data, labels)
        else:
            handles = _draw_sky_smooth(ax, data, labels, latitude, longitude)

        ax.set_xlim(data.edges[0], data.edges[-1])
        ax.set_ylim(0.0, 3.3)
        ax.set_facecolor(to_rgba("white"))
        if title:
            ax.set_title(title)

        if data.rate is not None:
            handles += _draw_precipitation(axes[1], data)

        bottom_axis = axes[-1]
        # Beside the bottom panel, or beyond the colorbar of "cells" without one.
        anchor = (1.01, 1.0) if data.rate is not None or style == "smooth" else (1.09, 1.0)
        bottom_axis.legend(handles=handles, loc="upper left", bbox_to_anchor=anchor, fontsize=9, frameon=False)
        bottom_axis.xaxis.set_major_formatter(mdates.DateFormatter("%d %HZ"))
        bottom_axis.tick_params(axis="x", rotation=45)
        bottom_axis.set_xlabel("Time (UTC)")
        fig.tight_layout()
        return _finish(fig, save_as, show)


def _form_handles():
    """
    Legend entries of the colors of the genus forms.
    """
    return [
        plt.Line2D([], [], color=to_rgba(color), marker="s", linestyle="", label=form)
        for form, color in _SKY_FORM_COLORS.items()
    ]


def _draw_precipitation(ax, data):
    """
    Precipitation rate as bars, rain or snow, and their legend entries.
    """
    snow = data.t2m < data.limits["snow_temperature"]
    widths = 0.8 * onp.diff(data.edges)
    ax.bar(data.centers[~snow], data.rate[~snow], width=widths[~snow], color=to_rgba(_RAIN_COLOR), label="Rain")
    ax.bar(data.centers[snow], data.rate[snow], width=widths[snow], color=to_rgba(_SNOW_COLOR), label="Snow")
    ax.set_ylim(0.0, max(1.0, 1.15 * float(onp.nanmax(data.rate, initial=0.0))))
    ax.set_ylabel("Rate / mm/h")
    return [
        plt.Rectangle((0, 0), 1, 1, color=to_rgba(_RAIN_COLOR), label="Rain"),
        plt.Rectangle((0, 0), 1, 1, color=to_rgba(_SNOW_COLOR), label="Snow"),
    ]


def _draw_sky_cells(fig, ax, data, labels):
    """
    The "cells" style: one shaded row per étage and its genera.
    """
    genera, edges, centers = data.genera, data.edges, data.centers

    # Cover of each étage, white to dark grey.
    for etage, (bottom, top) in SKY_ETAGE_ROWS.items():
        mesh = ax.pcolormesh(
            edges,
            [bottom, top],
            onp.clip(data.covers[etage], 0.0, 1.0)[None, :],
            cmap=_SKY_CMAP,
            vmin=0.0,
            vmax=1.0,
            shading="flat",
        )
    for height in (1.0, 2.0):
        ax.axhline(height, color=to_rgba("0.6"), linewidth=0.8)

    # Genera rising through every étage, even hidden: a frame from their base up.
    tall = {i for i, genus in enumerate(genera) if len(genus["spans"]) == len(SKY_ETAGE_ROWS)}
    # Cloud base in the low row, to scale.
    base_row = onp.minimum(data.base / 1000.0 / _LOW_ETAGE_KM, 1.0)
    for i in range(data.count):
        for etage in ("low", "middle"):
            rising = [code for code in data.present[etage][i] if code in tall]
            if rising:
                bottom = base_row[i] if etage == "low" and onp.isfinite(base_row[i]) else SKY_ETAGE_ROWS[etage][0]
                ax.add_patch(plt.Rectangle(
                    (edges[i], bottom),
                    edges[i + 1] - edges[i],
                    SKY_ETAGE_ROWS["high"][1] - bottom,
                    fill=False,
                    edgecolor=to_rgba(_SKY_FORM_COLORS[genera[rising[0]]["form"]]),
                    linewidth=1.5,
                ))
                break

    # Cloud base of the low clouds, and fog at the surface.
    low = data.codes["low"] >= 0
    ax.scatter(centers[low], base_row[low], marker="_", s=120, color=to_rgba("black"), label="Cloud base", zorder=3)
    for i in onp.flatnonzero(data.fog):
        ax.add_patch(plt.Rectangle(
            (edges[i], 0.0),
            edges[i + 1] - edges[i],
            _FOG_HEIGHT,
            facecolor=to_rgba("0.85"),
            edgecolor=to_rgba("0.4"),
            hatch="...",
            linewidth=0.0,
        ))

    if labels:
        for etage, (bottom, top) in SKY_ETAGE_ROWS.items():
            # Above the cloud base in the low row.
            middle_height = bottom + (0.72 if etage == "low" else 0.5) * (top - bottom)
            for i in range(data.count):
                if data.codes[etage][i] == data.module.HIDDEN:
                    texts = [("/", to_rgba("0.55"), "normal")]
                else:
                    texts = [
                        (genera[code]["abbreviation"], to_rgba(_SKY_FORM_COLORS[genera[code]["form"]]), "bold")
                        for code in data.present[etage][i]
                    ]
                # Several genera stacked in the cell, the main one on top.
                spacing = 0.24
                for rank, (text, color, weight) in enumerate(texts):
                    ax.text(
                        centers[i],
                        middle_height + spacing * ((len(texts) - 1) / 2.0 - rank),
                        text,
                        ha="center",
                        va="center",
                        fontsize=8 if len(texts) == 1 else 7,
                        fontweight=weight,
                        bbox={"boxstyle": "round,pad=0.15", "facecolor": to_rgba("white", 0.75), "edgecolor": "none"},
                        color=color,
                    )
        for i, oktas in enumerate(data.oktas):
            ax.text(centers[i], 3.06, str(oktas), ha="center", va="bottom", fontsize=8)
        ax.text(1.005, 3.06, "N", transform=ax.get_yaxis_transform(), va="bottom", fontsize=8)

    ax.set_yticks([0.0, 0.5, 1.0, 1.5, 2.5])
    ax.set_yticklabels(["0", "1", "2 km", "Middle", "High"])
    ax.set_ylabel("Étage")

    colorbar_axes = ax.inset_axes([1.03, 0.0, 0.015, 0.9])
    fig.colorbar(mesh, cax=colorbar_axes, label="Cover", ticks=[0.0, 0.5, 1.0])
    handles = _form_handles()
    handles.append(plt.Line2D([], [], color=to_rgba("black"), marker="_", linestyle="", markersize=10, label="Cloud base"))
    if data.fog.any():
        handles.append(plt.Rectangle((0, 0), 1, 1, facecolor=to_rgba("0.85"), edgecolor=to_rgba("0.4"), hatch="...", label="Fog"))
    return handles


def _genus_layers(data):
    """
    Weight, bottom and top in km of each genus of the smooth style.

    The weight is the cover of the étage where the genus is present,
    else 0. Bottom and top are carried over the points without the
    genus, so that it fades in and out without jumping in height.
    """
    etage_of = {genus["abbreviation"]: genus["etage"] for genus in data.genera}
    index_of = {genus["abbreviation"]: i for i, genus in enumerate(data.genera)}
    base_km = onp.clip(onp.nan_to_num(data.base / 1000.0, nan=0.6), 0.05, 2.5)
    layers = {}
    for abbreviation, (bottom, top, opacity, darkness, texture) in _SKY_LAYERS.items():
        etage = etage_of[abbreviation]
        here = onp.array([index_of[abbreviation] in codes for codes in data.present[etage]])
        if not here.any():
            continue
        bottoms = base_km if bottom == "base" else onp.full(data.count, float(bottom))
        if top == "cape":
            # Humilis about 1 km thick, congestus up to the middle étage.
            tops = bottoms + onp.clip(0.5 + data.cape / 600.0, 0.5, 5.0)
        elif abbreviation in ("St", "Sc"):
            tops = bottoms + top
        else:
            tops = onp.full(data.count, float(top))
        cover = data.covers[etage]
        if abbreviation == "Cb":
            cover = onp.maximum(cover, 0.6)
        weight = onp.where(here, onp.clip(cover, 0.0, 1.0), 0.0)
        # Carry the heights over the gaps, from the nearest point with the genus.
        nearest = onp.flatnonzero(here)[onp.abs(onp.arange(data.count)[:, None] - onp.flatnonzero(here)[None, :]).argmin(axis=1)]
        layers[abbreviation] = SimpleNamespace(
            weight=weight,
            bottom=bottoms[nearest],
            top=onp.maximum(tops[nearest], bottoms[nearest] + 0.2),
            opacity=opacity,
            darkness=darkness,
            texture=texture,
            form=data.genera[index_of[abbreviation]]["form"],
            here=here,
        )
    return layers


def _noise(phase, seed, scale=1.0):
    """
    Smooth noise in [-1, 1] along the route, from a few random waves.
    """
    rng = onp.random.default_rng(seed)
    noise = onp.zeros_like(phase)
    for frequency in (0.7, 1.9, 4.3):
        noise += onp.sin(2.0 * onp.pi * frequency * phase / scale + rng.uniform(0.0, 2.0 * onp.pi)) / frequency
    return noise / 1.9


def _over(field, opacity, darkness):
    """
    Lay a cloud of some opacity and darkness over the field.
    """
    field.shade += opacity * darkness
    field.weight += opacity
    field.transmitted *= 1.0 - onp.clip(opacity, 0.0, 1.0)


def _dome(field, phase, rows, center, half_width, base, top, opacity, darkness):
    """
    One heaped cloud: flat base, rounded top, darker underneath.
    """
    columns = onp.abs(phase - center) < half_width * 1.4
    if not columns.any():
        return
    dx = (phase[columns][None, :] - center) / half_width
    height = max(top - base, 1e-3)
    rel = (rows[:, None] - base) / height
    # A main dome and two lower lobes, as cauliflower.
    distance = onp.minimum.reduce([
        onp.hypot(dx, onp.maximum(rel, 0.0)),
        onp.hypot((dx + 0.55) / 0.6, onp.maximum(rel, 0.0) / 0.75),
        onp.hypot((dx - 0.5) / 0.65, onp.maximum(rel, 0.0) / 0.8),
    ])
    inside = (1.0 - _smoothstep(0.88, 1.0, distance)) * _smoothstep(-0.02, 0.01, rel)
    sub = SimpleNamespace(shade=field.shade[:, columns], weight=field.weight[:, columns], transmitted=field.transmitted[:, columns])
    _over(sub, opacity * inside, darkness + 0.4 * (1.0 - onp.clip(rel, 0.0, 1.0)))
    field.shade[:, columns], field.weight[:, columns], field.transmitted[:, columns] = sub.shade, sub.weight, sub.transmitted


def _cloud_field(layers, data, x, rows):
    """
    Opacity and darkness of the clouds on the grid of the smooth style.

    Layers of stratiform clouds have bumpy edges and gaps where their
    cover is broken; Cu are separate domes and Cb towers with an anvil.
    The genera are laid over each other, each letting through the
    light the others leave. Ci are drawn apart, as strokes.
    """
    from scipy.ndimage import gaussian_filter, gaussian_filter1d

    column_width = float(onp.median(onp.diff(data.edges)))
    phase = (x - data.edges[0]) / column_width  # in columns
    centers = (data.centers - data.edges[0]) / column_width
    shape = (rows.size, x.size)
    field = SimpleNamespace(shade=onp.zeros(shape), weight=onp.zeros(shape), transmitted=onp.ones(shape))
    rng = onp.random.default_rng(1)

    for seed, (abbreviation, layer) in enumerate(layers.items()):
        if layer.texture in ("puffs", "tower", "fibres"):
            continue
        weight = onp.interp(x, data.centers, layer.weight)
        # Ends of the layer rounded and irregular rather than cut.
        spread = gaussian_filter1d(weight, sigma=0.35 * x.size / max(data.count, 1))
        present = _smoothstep(0.15, 0.5, spread + 0.15 * _noise(phase, seed + 30, 2.0))
        bottom = _km_to_row(onp.interp(x, data.centers, layer.bottom))
        top = _km_to_row(onp.interp(x, data.centers, layer.top))
        crisp = layer.texture != "veil"
        if layer.texture == "rolls":
            # Broken into rolls where the cover is below 1.
            gaps = _smoothstep(1.0 - 1.5 * weight - 0.1, 1.0 - 1.5 * weight + 0.1, 0.5 + 0.5 * _noise(phase, seed, 2.5))
            presence = present * gaps
            top = top + 0.035 * _noise(phase, seed + 10, 1.5)
            bottom = bottom + 0.01 * _noise(phase, seed + 20, 2.0)
        else:
            presence = present
            top = top + (0.025 if crisp else 0.01) * _noise(phase, seed + 10, 2.0)
            # Ragged base of the rain clouds.
            bottom = bottom + (0.035 if abbreviation == "Ns" else 0.008) * _noise(phase, seed + 20, 1.0)
        # Thinner towards the ends.
        top = bottom + (top - bottom) * (0.35 + 0.65 * present)
        edge = 0.02 if crisp else 0.12
        height = onp.maximum(top - bottom, 1e-3)
        rel = (rows[:, None] - bottom[None, :]) / height[None, :]
        profile = _smoothstep(0.0, edge / height, rel)[...] * (1.0 - _smoothstep(1.0 - edge / height, 1.0, rel))
        opacity = layer.opacity * (0.55 + 0.45 * weight)[None, :] * presence[None, :] * profile
        darkness = layer.darkness + 0.3 * (1.0 - onp.clip(rel, 0.0, 1.0))
        _over(field, opacity, darkness)

    for abbreviation, layer in layers.items():
        if layer.texture == "puffs":
            for i in onp.flatnonzero(layer.here):
                cover = layer.weight[i]
                base = float(_km_to_row(layer.bottom[i]))
                for _ in range(1 + int(round(2.0 * cover))):
                    depth_km = (layer.top[i] - layer.bottom[i]) * rng.uniform(0.55, 1.0)
                    _dome(
                        field, phase, rows,
                        center=centers[i] + rng.uniform(-0.4, 0.4),
                        half_width=rng.uniform(0.35, 0.55) * (0.75 + 0.5 * cover),
                        base=base,
                        top=float(_km_to_row(layer.bottom[i] + depth_km)),
                        opacity=layer.opacity,
                        darkness=0.08,
                    )
        elif layer.texture == "tower":
            for i in onp.flatnonzero(layer.here):
                base = float(_km_to_row(layer.bottom[i]))
                # The tower, with bulging sides, then the anvil spreading downwind.
                for lobe in range(4):
                    _dome(
                        field, phase, rows,
                        center=centers[i] + rng.uniform(-0.15, 0.15),
                        half_width=0.7 - 0.08 * lobe,
                        base=base,
                        top=float(_km_to_row(9.0 + 0.4 * lobe)),
                        opacity=layer.opacity,
                        darkness=0.35,
                    )
                anvil_center = centers[i] + 0.5
                dx = (phase - anvil_center) / 1.5
                anvil_rows = (rows - float(_km_to_row(10.3))) / 0.13
                anvil = (1.0 - _smoothstep(0.85, 1.0, onp.hypot(dx[None, :], anvil_rows[:, None])))
                anvil *= 1.0 - _smoothstep(float(_km_to_row(11.0)) - 0.02, float(_km_to_row(11.0)), rows)[:, None]
                _over(field, 0.95 * anvil, onp.full(shape, 0.15))

    alpha = 1.0 - field.transmitted
    darkness = onp.divide(field.shade, field.weight, out=onp.zeros(shape), where=field.weight > 1e-6)
    sigma = (0.8, 0.8)
    alpha = gaussian_filter(alpha, sigma)
    darkness = gaussian_filter(darkness * alpha, sigma) / onp.maximum(alpha, 1e-6)
    return onp.clip(alpha, 0.0, 1.0), onp.clip(darkness, 0.0, 1.0)


def _cirrus_strokes(layers, data, light_at):
    """
    Hooked strokes of Cirrus, as line segments with their colors.
    """
    layer = layers.get("Ci")
    if layer is None:
        return [], []
    rng = onp.random.default_rng(2)
    column_width = float(onp.median(onp.diff(data.edges)))
    lines, colors = [], []
    for i in onp.flatnonzero(layer.here):
        for _ in range(2 + int(round(5.0 * layer.weight[i]))):
            x0 = data.centers[i] + column_width * rng.uniform(-0.5, 0.3)
            y0 = float(_km_to_row(rng.uniform(layer.bottom[i], layer.top[i] - 0.5)))
            s = onp.linspace(0.0, 1.0, 12)
            # A slanted filament ending in a hook.
            xs = x0 + column_width * 0.55 * s
            ys = y0 + 0.07 * s + 0.05 * _smoothstep(0.7, 1.0, s) ** 2
            lines.append(onp.column_stack((xs, ys)))
            colors.append(to_rgba("white", 0.75 * (_NIGHT_CLOUD_LIGHT + (1.0 - _NIGHT_CLOUD_LIGHT) * light_at(x0))))
    return lines, colors


def _okta_marker(oktas):
    """
    Vertices of the filled part of a WMO sky cover symbol.
    """
    if oktas <= 0:
        return None
    angles = onp.linspace(onp.pi / 2.0, onp.pi / 2.0 - 2.0 * onp.pi * min(oktas, 8) / 8.0, 40)
    return [(0.0, 0.0)] + [(onp.cos(a), onp.sin(a)) for a in angles] + [(0.0, 0.0)]


def _draw_oktas(ax, data):
    """
    WMO sky cover symbols along the top of the smooth style.

    A circle filled by eighths, crossed when fog hides the sky.
    """
    step = max(1, int(onp.ceil(data.count / 40)))
    for i in range(0, data.count, step):
        x, oktas = data.centers[i], int(data.oktas[i])
        ax.scatter([x], [3.15], s=60, marker="o", facecolor=to_rgba("white"), edgecolor=to_rgba("0.2"), linewidth=0.8, zorder=5, clip_on=False)
        if oktas == 9:
            ax.scatter([x], [3.15], s=40, marker="x", color=to_rgba("0.2"), linewidth=1.0, zorder=6, clip_on=False)
        elif oktas > 0:
            ax.scatter([x], [3.15], s=60, marker=_okta_marker(oktas), color=to_rgba("0.2"), linewidth=0.0, zorder=6, clip_on=False)
    ax.text(1.005, 3.15, "N", transform=ax.get_yaxis_transform(), va="center", fontsize=8)


def _draw_sky_smooth(ax, data, labels, latitude, longitude):
    """
    The "smooth" style: the sky and its clouds painted along the route.
    """
    width = max(400, min(1600, 16 * data.count))
    x = onp.linspace(data.edges[0], data.edges[-1], width)
    rows = onp.linspace(0.0, 3.0, 300)
    km = _row_to_km(rows)

    # Sky: day or night, darker towards the top.
    if latitude is not None and longitude is not None:
        seconds = onp.interp(x, data.centers, data.seconds)
        elevation = sun_elevation(
            seconds,
            onp.interp(x, data.centers, onp.ravel(latitude)),
            onp.interp(x, data.centers, onp.ravel(longitude)),
        )
        from scipy.ndimage import gaussian_filter1d

        daylight = gaussian_filter1d(_smoothstep(*_TWILIGHT, elevation), sigma=width / max(data.count, 1) * 0.1)
    else:
        daylight = onp.ones(width)
    vertical = (rows / 3.0)[:, None, None]
    day = onp.array(_DAY_SKY[1]) * (1.0 - vertical) + onp.array(_DAY_SKY[0]) * vertical
    night = onp.array(_NIGHT_SKY[1]) * (1.0 - vertical) + onp.array(_NIGHT_SKY[0]) * vertical
    light = daylight[None, :, None]
    background = night * (1.0 - light) + day * light

    layers = _genus_layers(data)
    alpha, darkness = _cloud_field(layers, data, x, rows)
    color = _CLOUD_LIT * (1.0 - darkness[..., None]) + _CLOUD_SHADE * darkness[..., None]
    dimmed = _NIGHT_CLOUD_LIGHT + (1.0 - _NIGHT_CLOUD_LIGHT) * light
    color = color * dimmed
    opacity = (alpha ** 0.85)[..., None]
    image = background * (1.0 - opacity) + color * opacity

    # Fog: haze rising from the sea.
    fog = onp.interp(x, data.centers, data.fog.astype(float))
    haze = (fog[None, :] * (1.0 - _smoothstep(0.0, 0.25, rows))[:, None])[..., None]
    image = image * (1.0 - 0.85 * haze) + onp.array([0.86, 0.87, 0.88]) * dimmed * 0.85 * haze

    ax.imshow(
        onp.clip(image, 0.0, 1.0),
        extent=(x[0], x[-1], 0.0, 3.0),
        origin="lower",
        aspect="auto",
        interpolation="bilinear",
        zorder=0,
    )

    lines, colors = _cirrus_strokes(layers, data, lambda x_: float(onp.interp(x_, x, daylight)))
    if lines:
        ax.add_collection(matplotlib.collections.LineCollection(lines, colors=colors, linewidths=1.1, capstyle="round", zorder=1))

    handles = []
    rng = onp.random.default_rng(0)
    rate = data.rate if data.rate is not None else onp.zeros(data.count)
    snowing = data.t2m < data.limits["snow_temperature"]
    base_km = onp.clip(onp.nan_to_num(data.base / 1000.0, nan=1.0), 0.1, 2.5)
    rain_lines, snow_points = [], []
    column_width = float(onp.median(onp.diff(data.edges)))
    # Only under a column with clouds: a light rate under a clear sky is left to the bottom panel.
    clouded = onp.array([any(data.present[etage][i] for etage in data.module.ETAGES) for i in range(data.count)])
    for i in onp.flatnonzero((rate >= data.limits["rain_rate"]) & clouded):
        count = int(min(40, 4 + 6 * rate[i]))
        xs = data.centers[i] + column_width * rng.uniform(-0.5, 0.5, count)
        top = _km_to_row(base_km[i])
        if snowing[i]:
            snow_points += [(x_, rng.uniform(0.02, top)) for x_ in xs]
        else:
            for x_ in xs:
                start = rng.uniform(0.15 * top, top)
                length = rng.uniform(0.08, 0.2)
                rain_lines.append([(x_, start), (x_ - 0.12 * column_width, start - length)])
    if rain_lines:
        ax.add_collection(matplotlib.collections.LineCollection(rain_lines, colors=[to_rgba(_RAIN_COLOR, 0.75)], linewidths=0.9, zorder=2))
        handles.append(plt.Line2D([], [], color=to_rgba(_RAIN_COLOR), label="Rain under the clouds"))
    if snow_points:
        points = onp.array(snow_points)
        ax.scatter(points[:, 0], points[:, 1], s=6, marker="*", color=to_rgba("white"), edgecolor=to_rgba(_SNOW_COLOR), linewidth=0.3, zorder=2)
        handles.append(plt.Line2D([], [], color=to_rgba(_SNOW_COLOR), marker="*", linestyle="", label="Snow under the clouds"))

    # Lightning under the thunderstorms.
    storms = [i for i in range(data.count) if data.codes["low"][i] == data.module.genus_index("Cb")]
    for i in storms:
        top = _km_to_row(base_km[i])
        xs = data.centers[i] + column_width * onp.array([0.05, -0.12, 0.08, -0.1, 0.02])
        ys = onp.linspace(top, 0.05, xs.size)
        ax.plot(xs, ys, color=to_rgba(_LIGHTNING_COLOR), linewidth=1.6, zorder=3, solid_joinstyle="miter")
    if storms:
        handles.append(plt.Line2D([], [], color=to_rgba(_LIGHTNING_COLOR), linewidth=1.6, label="Thunderstorm"))

    if labels:
        _label_genera(ax, data, layers)

    _draw_oktas(ax, data)
    ticks = [0.0, 0.5, 1.0, 1.5, 2.0, 4.0, 6.0, 9.0, 12.0]
    ax.set_yticks(_km_to_row(ticks))
    ax.set_yticklabels([f"{tick:g}" for tick in ticks])
    ax.set_ylabel("Height / km")
    for height in (1.0, 2.0):
        ax.axhline(height, color=to_rgba("white", 0.35), linewidth=0.6, linestyle=(0, (4, 4)), zorder=1)
    return _form_handles() + handles


def _label_genera(ax, data, layers):
    """
    Tag each genus of the smooth style where it is.

    One tag per stretch of the route where the genus is present, at
    its height in the column, repeated on long stretches.
    """
    every = 12  # points between two tags of a long stretch
    column_width = float(onp.median(onp.diff(data.edges)))
    placed = []
    for abbreviation, layer in layers.items():
        here = layer.here
        starts = onp.flatnonzero(here & ~onp.concatenate(([False], here[:-1])))
        ends = onp.flatnonzero(here & ~onp.concatenate((here[1:], [False])))
        for start, end in zip(starts, ends):
            length = end - start + 1
            tags = max(1, int(round(length / every)))
            for k in range(tags):
                i = int(start + (k + 0.5) * length / tags)
                bottom, top = layer.bottom[i], layer.top[i]
                if layer.texture == "tower":
                    km = 9.9  # on the anvil
                elif layer.texture == "puffs":
                    km = bottom + 0.35 * (top - bottom)
                else:
                    km = 0.5 * (bottom + top)
                y = max(0.08, float(_km_to_row(km)))
                # Away from tags already placed at the same place.
                for x_other, y_other in placed:
                    if abs(x_other - i) < 1.5 and abs(y_other - y) < 0.14:
                        y = y_other - 0.16
                placed.append((i, y))
                # Inside the plot at both ends of the route.
                x_tag = onp.clip(data.centers[i], data.edges[0] + 0.5 * column_width, data.edges[-1] - 0.5 * column_width)
                ax.text(
                    x_tag,
                    y,
                    abbreviation,
                    ha="center",
                    va="center",
                    fontsize=8,
                    fontweight="bold",
                    color=to_rgba("white"),
                    bbox={
                        "boxstyle": "round,pad=0.2",
                        "facecolor": to_rgba(_SKY_FORM_COLORS[layer.form], 0.85),
                        "edgecolor": "none",
                    },
                    zorder=7,
                )


#%% FORMER FIGURES

def plot_routing_report(cvtim, stw, sog, tws, twa, swh, wa, avg_bhp, max_bhp, sol, maxBHP):
    """
    The former figure of a routing, on four stacked panels.

    `plot_report` is the current one.

    Args:
        cvtim: Times of the x axis.
        stw: Symbolic speed through water.
        sog: Symbolic speed over ground.
        tws: Symbolic true wind speed.
        twa: Symbolic true wind angle.
        swh: Symbolic significant wave height.
        wa: Symbolic wave angle.
        avg_bhp: Symbolic average brake power.
        max_bhp: Symbolic maximum brake power.
        sol: Solution that evaluates these quantities.
        maxBHP: Power limit of the vessel.
    """
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

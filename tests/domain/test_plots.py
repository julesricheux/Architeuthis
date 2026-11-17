"""
Figures of plot_utils, drawn with the Agg backend from real reports.

Maps are built but never rendered: cartopy downloads Natural Earth when it draws them.
"""

import inspect
import re
from pathlib import Path
from unittest.mock import patch

import architeuthis
import cartopy.crs as ccrs
import matplotlib as mpl
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from cycler import cycler

from architeuthis.report import ReportCollection, RoutingReport
from architeuthis.route import Route, RouteSet
from architeuthis.toolbox.plot_utils import (
    A4_PORTRAIT,
    REPORT_PANELS,
    _finish,
    add_map_background,
    draw,
    get_steps,
    plot_convergence,
    plot_ensemble_along_route,
    plot_fuel_distribution,
    plot_fuel_quantiles,
    plot_fuel_vs_etd,
    plot_power_and_weather,
    plot_quantiles,
    plot_report,
    plot_route,
    plot_route_set,
    plot_sky,
    plot_style,
    sun_elevation,
    plot_variable,
    set_plot_style,
)


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


@pytest.fixture
def members(baseline_report):
    """Reports on the same time grid, with different weather, like ensemble members."""
    reports = []
    for member in range(5):
        factor = 1.0 + 0.1 * member
        report = dict(baseline_report)
        report.update(
            member=member,
            init_fac=float(member),
            tws=baseline_report["tws"] * factor,
            avg_bhp=baseline_report["avg_bhp"] * factor,
            fuel=baseline_report["fuel"] * factor,
        )
        reports.append(RoutingReport(report))
    return ReportCollection(reports)


@pytest.fixture
def eta_sweep():
    return [
        {"eta": 3600.0 * eta, "fuel": 100.0 - eta + member, "transit_time": float(eta), "status": status}
        for eta, status in ((24, 1), (48, 1), (72, 2))
        for member in range(3)
    ]


def step_values(ax, index=0):
    return np.asarray(ax.lines[index].get_ydata(), dtype=float)


# ------------------------------------------------------------------------------
# A4 page
# ------------------------------------------------------------------------------


class TestPlotReport:
    def test_panels_are_in_the_documented_order(self, baseline_report):
        fig = plot_report(baseline_report, show=False)

        assert [ax.get_ylabel() for ax in fig.axes] == [
            "SOG / kts",
            "Sails contribution / %",
            "BHP / kW",
            "SWH / m",
            "TWS / kts",
            "AWS / kts",
        ]
        assert len(REPORT_PANELS) == len(fig.axes)

    def test_page_is_a4_at_300_dpi_by_default(self, baseline_report):
        fig = plot_report(baseline_report, show=False)

        assert tuple(fig.get_size_inches()) == pytest.approx(A4_PORTRAIT)
        assert A4_PORTRAIT == pytest.approx((8.27, 11.69))
        assert fig.dpi == 300

    def test_page_format_can_be_changed(self, baseline_report):
        fig = plot_report(baseline_report, show=False, figsize=(6.0, 8.0), dpi=100)

        assert tuple(fig.get_size_inches()) == pytest.approx((6.0, 8.0))
        assert fig.dpi == 100

    @pytest.mark.parametrize(
        "panel, entry",
        [
            ("sog", "sog"),
            ("sails", "sails_contribution"),
            ("bhp", "avg_bhp"),
            ("swh", "swh"),
            ("tws", "tws"),
            ("aws", "aws"),
        ],
    )
    def test_panels_show_the_report_values(self, baseline_report, panel, entry):
        fig = plot_report(baseline_report, show=False)

        np.testing.assert_allclose(step_values(fig.axes[REPORT_PANELS.index(panel)]), baseline_report[entry])

    def test_power_panel_shows_load_fluctuations_around_the_average(self, baseline_report):
        ax = plot_report(baseline_report, show=False).axes[REPORT_PANELS.index("bhp")]

        average = baseline_report["avg_bhp"]
        maximum = baseline_report["max_bhp"]
        np.testing.assert_allclose(step_values(ax, 1), maximum)
        np.testing.assert_allclose(step_values(ax, 2), average - (maximum - average))
        assert ax.lines[1].get_linestyle() == "--"
        assert [text.get_text() for text in ax.get_legend().get_texts()] == ["Average BHP", "Load fluctuations"]

    @pytest.mark.parametrize("key", ["tws", "aws"])
    def test_wind_panels_show_the_gust(self, baseline_report, key):
        ax = plot_report(baseline_report, show=False).axes[REPORT_PANELS.index(key)]

        np.testing.assert_allclose(step_values(ax, 1), baseline_report[f"{key}_gust"])
        assert ax.lines[1].get_linestyle() == "--"
        assert [text.get_text() for text in ax.get_legend().get_texts()] == ["Average", "Gust"]

    @pytest.mark.parametrize("key", ["tws", "aws"])
    def test_wind_panels_work_without_gust(self, routing, key):
        report = routing(solve=False, analysis_options={"options": {}})
        assert f"{key}_gust" not in report

        ax = plot_report(report, show=False).axes[REPORT_PANELS.index(key)]

        assert len(ax.lines) == 1
        assert ax.get_legend() is None

    def test_time_axis_covers_the_route_in_utc(self, baseline_report):
        fig = plot_report(baseline_report, show=False)

        low, high = fig.axes[-1].get_xlim()
        assert low == pytest.approx(mdates.date2num(baseline_report.etd_time))
        assert high == pytest.approx(mdates.date2num(baseline_report.eta_time))
        assert fig.axes[-1].get_xlabel() == "Time (UTC)"
        assert all(ax.get_shared_x_axes().joined(ax, fig.axes[0]) for ax in fig.axes)

    def test_default_vertical_limits(self, baseline_report):
        fig = plot_report(baseline_report, show=False)

        assert fig.axes[REPORT_PANELS.index("sails")].get_ylim() == (0.0, 100.0)
        for panel in ("bhp", "swh", "tws", "aws"):
            assert fig.axes[REPORT_PANELS.index(panel)].get_ylim()[0] == 0.0

    def test_vertical_limits_can_be_replaced(self, baseline_report):
        fig = plot_report(baseline_report, show=False, ylim={"sog": (6.0, 13.0), "bhp": (0.0, 3084.0)})

        assert fig.axes[REPORT_PANELS.index("sog")].get_ylim() == (6.0, 13.0)
        assert fig.axes[REPORT_PANELS.index("bhp")].get_ylim() == (0.0, 3084.0)

    def test_unknown_panel_is_refused(self, baseline_report):
        with pytest.raises(KeyError):
            plot_report(baseline_report, show=False, ylim={"unknown": (0.0, 1.0)})

    def test_report_reloaded_from_a_file_gives_the_same_page(self, baseline_report, tmp_path):
        path = ReportCollection([baseline_report]).save(str(tmp_path / "reports.json"))

        direct = plot_report(baseline_report, show=False)
        reloaded = plot_report(ReportCollection.load(path)[0], show=False)

        for first, second in zip(direct.axes, reloaded.axes):
            assert len(first.lines) == len(second.lines)
            for index in range(len(first.lines)):
                np.testing.assert_allclose(step_values(first, index), step_values(second, index))

    def test_plain_dict_is_accepted(self, baseline_report):
        assert len(plot_report(dict(baseline_report), show=False).axes) == len(REPORT_PANELS)

    def test_pdf_is_a_true_a4_page(self, baseline_report, tmp_path):
        path = tmp_path / "page.pdf"

        plot_report(baseline_report, save_as=str(path), show=False)

        boxes = re.findall(rb"/MediaBox \[ ?0 0 ([\d.]+) ([\d.]+) ?\]", path.read_bytes())
        assert len(boxes) == 1
        assert float(boxes[0][0]) == pytest.approx(8.27 * 72.0)
        assert float(boxes[0][1]) == pytest.approx(11.69 * 72.0)

    def test_show_is_called_only_when_asked(self, baseline_report):
        with patch("matplotlib.pyplot.show") as show:
            plot_report(baseline_report, show=False)
            show.assert_not_called()

            plot_report(baseline_report)
            show.assert_called_once()

    def test_page_leaves_the_global_style_alone(self, baseline_report):
        before = dict(mpl.rcParams)

        plot_report(baseline_report, show=False)

        assert dict(mpl.rcParams) == before

    def test_page_has_its_style_whatever_the_global_one(self, baseline_report):
        with mpl.rc_context({"axes.facecolor": "red", "font.size": 5.0}):
            fig = plot_report(baseline_report, show=False)

        assert mpl.colors.to_hex(fig.axes[0].get_facecolor()) == mpl.colors.to_hex("#EAEAF2")

    def test_page_looks_the_same_whenever_it_is_drawn(self, baseline_report, tmp_path):
        # A page shown in Spyder or a GUI is drawn after plot_report has returned.
        path = tmp_path / "page.png"
        saved = plot_report(baseline_report, save_as=str(path), show=False, dpi=50)
        later = plot_report(baseline_report, show=False, dpi=50)

        another_style = {
            "axes.prop_cycle": cycler("color", ["red", "green", "blue", "black", "cyan"]),
            "font.sans-serif": ["DejaVu Serif"],
            "grid.color": "red",
            "xtick.color": "blue",
            "xtick.labelsize": 5.0,
        }
        with mpl.rc_context(another_style):
            later.canvas.draw()
        drawn = np.asarray(later.canvas.buffer_rgba()) / 255.0

        np.testing.assert_allclose(plt.imread(path), drawn, atol=1.0 / 255.0)
        assert saved.axes[0].get_xlim() == later.axes[0].get_xlim()

    def test_report_method_gives_the_same_page(self, baseline_report):
        fig = baseline_report.plot(show=False, ylim={"sog": (1.0, 2.0)})

        assert len(fig.axes) == len(REPORT_PANELS)
        assert fig.axes[0].get_ylim() == (1.0, 2.0)


# ------------------------------------------------------------------------------
# Style and saving
# ------------------------------------------------------------------------------


def test_plot_style_gives_the_style_of_set_plot_style():
    with mpl.rc_context():
        mpl.rcdefaults()
        with plot_style():
            scoped = dict(mpl.rcParams)
        set_plot_style()
        applied = dict(mpl.rcParams)

    differing = {key for key in scoped if scoped[key] != applied[key]}
    assert differing == set()


def test_plot_style_is_undone_after_the_block():
    with mpl.rc_context():
        mpl.rcdefaults()
        before = dict(mpl.rcParams)
        with plot_style():
            assert mpl.rcParams["font.size"] == 13
        assert dict(mpl.rcParams) == before


@pytest.mark.parametrize(
    "file_name, signature",
    [
        ("figure.pdf", b"%PDF"),
        ("figure.PDF", b"%PDF"),
        ("figure", b"%PDF"),
        ("figure.png", b"\x89PNG"),
    ],
)
def test_format_comes_from_the_extension(tmp_path, file_name, signature):
    path = tmp_path / file_name

    _finish(plt.figure(), save_as=str(path), show=False)

    assert path.read_bytes().startswith(signature)


def test_nothing_is_written_without_a_file_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    fig = plt.figure()

    assert _finish(fig, show=False) is fig
    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------------------------------------
# Steps and maps
# ------------------------------------------------------------------------------


def test_get_steps_holds_each_value_from_node_to_node():
    report = {"tim": [0.0, 3600.0, 7200.0], "ctim": [1800.0, 5400.0], "sog": [10.0, 12.0]}

    times, values = get_steps(report, "sog")

    assert list(values) == [10.0, 10.0, 12.0, 12.0]
    assert list(times) == list(pd.to_datetime([0.0, 3600.0, 3600.0, 7200.0], unit="s"))


def test_draw_shows_each_route_over_the_great_circle(baseline_report, optimized_report):
    fig = draw([baseline_report, optimized_report], barbs=False, show=False)

    ax = fig.axes[0]
    assert isinstance(ax.projection, ccrs.PlateCarree)
    assert len(ax.lines) == 3
    np.testing.assert_allclose(ax.lines[1].get_ydata(), baseline_report["lat"])
    np.testing.assert_allclose(ax.lines[2].get_xdata(), optimized_report["lon"])
    assert ax.lines[1].get_marker() == "o"
    assert len(ax.collections) == 0 or all(not hasattr(c, "barb_increments") for c in ax.collections)


def test_draw_adds_wind_barbs_by_default(baseline_report):
    fig = draw([baseline_report], show=False)

    assert any(type(artist).__name__ == "Barbs" for artist in fig.axes[0].collections)


def test_draw_marks_the_segments_under_sail(baseline_report):
    report = dict(baseline_report)
    sails = np.zeros(len(baseline_report["ctim"]))
    sails[0] = 50.0
    report["sails_contribution"] = sails

    fig = draw([report], barbs=False, sails_threshold=10.0, show=False)

    ax = fig.axes[0]
    assert ax.lines[1].get_marker() in ("None", None, "")
    dots = [artist for artist in ax.collections if type(artist).__name__ == "PathCollection"]
    assert len(dots) == 1
    sizes = dots[0].get_sizes()
    assert sizes[0] == pytest.approx(1.5)
    assert np.all(sizes[1:] == 0.0)


def test_draw_can_use_an_existing_axes(baseline_report):
    fig = plt.figure()
    ax = fig.add_subplot(1, 2, 1, projection=ccrs.PlateCarree())
    other = fig.add_subplot(1, 2, 2)

    assert draw([baseline_report], barbs=False, ax=ax, show=False) is fig
    assert len(ax.lines) == 2
    assert len(other.lines) == 0
    assert fig.axes == [ax, other]


def test_plot_route_refuses_collections_of_different_lengths():
    with pytest.raises(AssertionError, match="same length"):
        plot_route([[0.0, 1.0]], [[0.0, 1.0], [0.0, 1.0]], [], [], [], [], False, show=False)


def test_map_gridlines_keep_the_style_whenever_they_are_drawn():
    ax = plt.axes(projection=ccrs.PlateCarree())

    with plot_style():
        expected = mpl.rcParams["grid.color"], mpl.rcParams["grid.linestyle"]
        gridlines = add_map_background(ax)

    # Cartopy would otherwise read these from the global style when it draws.
    assert (gridlines.collection_kwargs["color"], gridlines.collection_kwargs["linestyle"]) == expected


def test_map_leaves_the_global_style_alone(baseline_report):
    before = dict(mpl.rcParams)

    draw([baseline_report], show=False)

    assert dict(mpl.rcParams) == before


# ------------------------------------------------------------------------------
# Several reports
# ------------------------------------------------------------------------------


def test_fuel_against_etd_gives_one_figure_per_vessel(baseline_report, optimized_report):
    figures = plot_fuel_vs_etd([baseline_report, optimized_report], show=False)

    assert len(figures) == 2
    assert {figure.axes[0].get_title() for figure in figures} == {"Sails efficiency 45 %", "Sails efficiency 60 %"}
    assert figures[0].axes[0].get_ylim() == figures[1].axes[0].get_ylim()
    labels = {text.get_text() for figure in figures for text in figure.axes[0].get_legend().get_texts()}
    assert labels == {"IFS / ortho cst speed", "GFS / optimised"}


def test_fuel_against_etd_default_limits_contain_the_points(baseline_report, optimized_report):
    figure = plot_fuel_vs_etd([baseline_report, optimized_report], show=False)[0]

    low, high = figure.axes[0].get_ylim()
    assert low <= min(baseline_report["fuel"], optimized_report["fuel"])
    assert high >= max(baseline_report["fuel"], optimized_report["fuel"])


def test_fuel_against_etd_takes_limits_and_colors(baseline_report):
    figure = plot_fuel_vs_etd([baseline_report], models_colors={"ifs": "red"}, ylim=(1.0, 2.0), show=False)[0]

    assert figure.axes[0].get_ylim() == (1.0, 2.0)
    assert mpl.colors.to_hex(figure.axes[0].collections[0].get_edgecolor()[0]) == mpl.colors.to_hex("red") or \
        mpl.colors.to_hex(figure.axes[0].collections[0].get_facecolor()[0]) == mpl.colors.to_hex("red")


def test_plot_variable_compares_the_reports(baseline_report, optimized_report):
    fig = plot_variable(
        [baseline_report, optimized_report],
        "sog",
        unit="kts",
        labels={0.0: "Ortho"},
        legend=True,
        ylim=(0.0, 30.0),
        show=False,
    )

    ax = fig.axes[0]
    assert ax.get_ylabel() == "SOG / kts"
    assert ax.get_ylim() == (0.0, 30.0)
    assert len(ax.lines) == 2
    assert ax.get_legend().get_texts()[0].get_text() == "Ortho"
    np.testing.assert_allclose(ax.lines[1].get_ydata(), get_steps(optimized_report, "sog")[1])


def test_plot_variable_has_a_default_label_and_no_legend_by_default(baseline_report):
    ax = plot_variable([baseline_report], "swh", show=False).axes[0]

    assert ax.get_legend() is None
    assert ax.lines[0].get_label() == "Route 0.0"


def test_power_and_weather_has_three_panels(baseline_report):
    fig = plot_power_and_weather([baseline_report], labels={0.0: "Ortho"}, show=False)

    assert [ax.get_ylabel() for ax in fig.axes] == ["AVG_BHP / kW", "SWH / m", "TWS / kts"]
    assert len(fig.axes[0].lines) == 1


def test_power_and_weather_can_add_the_maximum_power(baseline_report):
    fig = plot_power_and_weather([baseline_report], max_bhp=True, show=False)

    assert len(fig.axes[0].lines) == 2
    assert fig.axes[0].lines[1].get_linestyle() == "--"


def test_quantiles_show_three_bands_and_the_median(members):
    fig = plot_quantiles(members, "tws", unit="kts", prefix="IFS ", title="Wind", ylim=(0.0, 50.0), show=False)

    ax = fig.axes[0]
    labels = [text.get_text() for text in ax.get_legend().get_texts()]
    assert set(labels) == {"IFS 1–99%", "IFS 05–95%", "IFS 25–75%", "Median"}
    assert ax.get_title() == "Wind"
    assert ax.get_ylim() == (0.0, 50.0)
    np.testing.assert_allclose(ax.lines[0].get_ydata(), members.quantiles("tws")[0.5])


def test_quantiles_can_mark_every_day(members):
    fig = plot_quantiles(members, "tws", daily_ticks=True, show=False)

    assert isinstance(fig.axes[0].xaxis.get_major_locator(), mdates.DayLocator)


def test_fuel_quantiles_leave_out_what_did_not_converge(eta_sweep):
    ax = plot_fuel_quantiles(eta_sweep, show=False).axes[0]

    assert ax.get_ylabel() == "TOTAL FUEL CONS. / tons"
    assert list(ax.lines[0].get_ydata()) == pytest.approx([77.0, 53.0])


def test_fuel_quantiles_are_empty_when_nothing_converged(eta_sweep):
    failed = [report | {"status": 2} for report in eta_sweep]
    ax = plot_fuel_quantiles(failed, show=False).axes[0]

    assert len(ax.lines[0].get_ydata()) == 0


def test_fuel_quantiles_can_keep_everything_and_show_a_daily_rate(eta_sweep):
    ax = plot_fuel_quantiles(eta_sweep, daily=True, converged_only=False, show=False).axes[0]

    assert ax.get_ylabel() == "DAILY FUEL CONS. / tons/day"
    assert len(ax.lines[0].get_ydata()) == 3
    assert ax.lines[0].get_ydata()[0] == pytest.approx(77.0)


def test_convergence_is_the_share_of_solved_reports():
    reports = [{"eta": 0.0, "status": 1}, {"eta": 0.0, "status": 2}, {"eta": 3600.0, "status": 1}]

    ax = plot_convergence(reports, show=False).axes[0]

    assert list(ax.lines[0].get_ydata()) == pytest.approx([50.0, 100.0])
    assert ax.get_ylabel() == "Probability of possible ETA / %"


def test_fuel_distribution_labels_each_group():
    groups = {
        "Eff. 45%": [{"fuel": 90.0}, {"fuel": 95.0}, {"fuel": 92.0}],
        "Eff. 60%": [{"fuel": 70.0}, {"fuel": 75.0}, {"fuel": 72.0}],
    }

    ax = plot_fuel_distribution(groups, show=False).axes[0]

    assert [label.get_text() for label in ax.get_xticklabels()] == list(groups)
    assert ax.get_ylabel() == "Fuel / tons"


# ------------------------------------------------------------------------------
# User guide
# ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def user_guide():
    root = Path(architeuthis.__file__).parent.parent
    return (root / "docs" / "user_guide.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "function",
    [
        plot_report,
        draw,
        plot_route,
        plot_route_set,
        plot_variable,
        plot_power_and_weather,
        plot_quantiles,
        plot_fuel_quantiles,
        plot_convergence,
        plot_fuel_distribution,
        plot_fuel_vs_etd,
        plot_ensemble_along_route,
        plot_sky,
    ],
)
def test_guide_gives_the_signature_of_each_figure(user_guide, function):
    documented = []
    for parameter in inspect.signature(function).parameters.values():
        if parameter.default is inspect.Parameter.empty:
            documented.append(parameter.name)
        elif parameter.default is A4_PORTRAIT:
            documented.append(f"{parameter.name}=A4_PORTRAIT")
        elif isinstance(parameter.default, str):
            documented.append(f'{parameter.name}="{parameter.default}"')
        else:
            documented.append(f"{parameter.name}={parameter.default}")

    assert f"{function.__name__}({', '.join(documented)})" in user_guide


def test_guide_gives_the_panels_of_the_page_in_their_order(user_guide):
    rows = re.findall(r"^\| (\d) \| `(\w+)` \|", user_guide, flags=re.MULTILINE)

    assert rows == [(str(i + 1), panel) for i, panel in enumerate(REPORT_PANELS)]


@pytest.mark.parametrize(
    "helper",
    ["get_steps", "add_map_background", "set_plot_style", "plot_style", "A4_PORTRAIT", "REPORT_PANELS"],
)
def test_guide_mentions_the_helpers(user_guide, helper):
    assert f"`{helper}" in user_guide


@pytest.mark.parametrize(
    "plot, arguments",
    [
        (plot_variable, ("sog",)),
        (plot_power_and_weather, ()),
        (plot_quantiles, ("sog",)),
    ],
)
def test_figures_can_be_saved(plot, arguments, members, tmp_path):
    path = tmp_path / "figure.png"

    plot(members, *arguments, save_as=str(path), show=False)

    assert path.read_bytes().startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "plot, arguments",
    [
        (plot_variable, ("sog",)),
        (plot_power_and_weather, ()),
        (plot_quantiles, ("sog",)),
        (plot_fuel_vs_etd, ()),
        (draw, ()),
    ],
)
def test_figures_are_shown_only_when_asked(plot, arguments, members):
    with patch("matplotlib.pyplot.show") as show:
        plot(members, *arguments, show=False)
        show.assert_not_called()

        plot(members, *arguments)
        show.assert_called_once()


# ------------------------------------------------------------------------------
# Figures added for the examples
# ------------------------------------------------------------------------------


def test_route_set_map_draws_each_route_with_its_style():
    ortho = Route("ortho", [[47.0, -3.0], [46.0, -50.0]], verbose=False)
    minus = Route("minus", [[47.0, -3.0], [46.0, -50.0]], divergences=[0.4], verbose=False)
    plus = Route("plus", [[47.0, -3.0], [46.0, -50.0]], divergences=[-0.4], verbose=False)

    fig = plot_route_set(RouteSet("set", ortho=ortho, minus=minus, plus=plus, verbose=False), n=20, show=False)

    lines = {line.get_label(): line for line in fig.axes[0].get_lines()}
    assert set(lines) == {"ortho", "minus", "plus"}
    assert lines["ortho"].get_color() == "black"
    assert lines["minus"].get_linestyle() == "--"
    assert lines["plus"].get_xdata().size == 20
    assert lines["minus"].get_ydata()[10] != lines["plus"].get_ydata()[10]
    plt.close(fig)


class EnsembleStub:
    """A forecast with two members, the second one twice as strong."""

    def __init__(self, **fields):
        self.fields = fields
        self.data = {"number": xr.DataArray([1, 2])}
        self.queries = []

    def __call__(self, key, query):
        self.queries.append(query)
        return (self.fields[key] * query["member"])[:, None]


def test_ensemble_along_route_reads_every_member_at_each_segment_center(baseline_report):
    atmosphere = EnsembleStub(u10=3.0, v10=4.0)
    wave = EnsembleStub(swh=2.0)

    fig = plot_ensemble_along_route(baseline_report, atmosphere, wave, show=False)

    n = baseline_report["ctim"].size
    query = wave.queries[0]
    assert set(query) == {"valid_time", "member", "latitude", "longitude"}
    assert all(values.shape == (2 * n,) for values in query.values())
    assert query["member"][:2].tolist() == [1, 2]
    assert query["valid_time"][0] == query["valid_time"][1] == baseline_report["ctim"][0]
    assert query["latitude"][0] == baseline_report["clat"][0]
    assert query["longitude"][0] == baseline_report["clon"][0]

    # Medians of the two members: 1.5 x the field of member 1, the wind converted to knots.
    swh_median = fig.axes[1].get_lines()[0].get_ydata()
    tws_median = fig.axes[2].get_lines()[0].get_ydata()
    assert swh_median == pytest.approx(np.full(n, 3.0))
    assert tws_median == pytest.approx(np.full(n, 7.5 * 3600.0 / 1852.0))
    plt.close(fig)


def test_ensemble_along_route_applies_the_limits(baseline_report):
    fig = plot_ensemble_along_route(
        baseline_report,
        EnsembleStub(u10=3.0, v10=4.0),
        EnsembleStub(swh=2.0),
        ylim={"bhp": (0.0, 2700.0), "tws": (0.0, 40.0)},
        show=False,
    )

    assert fig.axes[0].get_ylim() == (0.0, 2700.0)
    assert fig.axes[1].get_ylim()[0] == 0.0
    assert fig.axes[2].get_ylim() == (0.0, 40.0)
    plt.close(fig)


def test_fuel_distribution_can_be_horizontal(baseline_report, optimized_report):
    groups = {"Reference": [baseline_report], "Optimized": [optimized_report]}

    fig = plot_fuel_distribution(groups, horizontal=True, show=False)

    ax = fig.axes[0]
    assert ax.get_xlabel() == "Fuel / tons"
    assert [label.get_text() for label in ax.get_yticklabels()] == list(groups)
    plt.close(fig)


# ------------------------------------------------------------------------------
# Sky along a route
# ------------------------------------------------------------------------------


def sky_columns(names, **changes):
    """Fields and diagnosis of skies of tests/domain/test_sky.py, one point each."""
    from architeuthis import sky

    from .test_sky import SKIES

    fields = {key: np.array([SKIES[name][key] for name in names]) for key in sky.SKY_VARIABLES}
    fields |= {key: np.asarray(value, dtype=float) for key, value in changes.items()}
    return fields | sky.diagnose(fields), 1.8e9 + 10800.0 * np.arange(len(names))


def test_sky_shades_each_etage_by_its_cover():
    columns, times = sky_columns(["clear", "warm_front", "cirrus"])

    ax = plot_sky(columns, times, show=False).axes[0]
    meshes = [artist for artist in ax.collections if isinstance(artist, mpl.collections.QuadMesh)]

    assert len(meshes) == 3
    covers = [np.asarray(mesh.get_array()).ravel() for mesh in meshes]
    assert covers[0] == pytest.approx(columns["lcc"])
    assert covers[2] == pytest.approx(columns["hcc"])
    assert ax.get_xlim() == pytest.approx(mdates.date2num(pd.to_datetime([times[0] - 5400.0, times[-1] + 5400.0], unit="s")))


def test_sky_writes_each_genus_the_hidden_etages_and_the_oktas():
    columns, times = sky_columns(["warm_front", "trade_cumulus"])

    texts = [text.get_text() for text in plot_sky(columns, times, show=False).axes[0].texts]

    assert {"St", "Ns", "/", "Cu"} <= set(texts)
    assert {"8", "3", "N"} <= set(texts)
    assert not {"St", "Cu"} & {text.get_text() for text in plot_sky(columns, times, labels=False, show=False).axes[0].texts}


def test_sky_frames_the_clouds_that_rise_through_every_etage():
    columns, times = sky_columns(["cumulonimbus", "trade_cumulus", "warm_front"])

    ax = plot_sky(columns, times, show=False).axes[0]
    frames = [patch for patch in ax.patches if isinstance(patch, mpl.patches.Rectangle) and not patch.get_fill()]

    # The Cb from its base, the Ns from the middle étage, both up to the top.
    assert len(frames) == 2
    assert frames[0].get_y() == pytest.approx(columns["cloud_base"][0] / 2000.0)
    assert frames[1].get_y() == pytest.approx(1.0)
    assert all(frame.get_y() + frame.get_height() == pytest.approx(3.0) for frame in frames)


def test_sky_marks_the_fog_and_the_cloud_base():
    columns, times = sky_columns(["fog", "trade_cumulus", "clear"])

    ax = plot_sky(columns, times, show=False).axes[0]
    bases = ax.collections[-1].get_offsets()

    assert any(patch.get_hatch() == "..." for patch in ax.patches)
    assert len(bases) == 2
    assert bases[1][1] == pytest.approx(columns["cloud_base"][1] / 2000.0)


def test_sky_shows_rain_and_snow_below():
    columns, times = sky_columns(["warm_front", "warm_front"], t2m=[290.0, 272.0])

    fig = plot_sky(columns, times, show=False)
    bars = fig.axes[1].patches

    assert len(fig.axes) == 2  # sky and precipitation
    assert [bar.get_height() for bar in bars] == pytest.approx([3.0, 3.0])
    assert to_rgba_set(bars) == {mpl.colors.to_rgba("#1e88e5"), mpl.colors.to_rgba("#90caf9")}


def to_rgba_set(bars):
    return {tuple(bar.get_facecolor()) for bar in bars}


def test_sky_without_rate_has_no_precipitation_panel():
    columns, times = sky_columns(["cirrus"])
    del columns["prate"]

    fig = plot_sky(columns, times, show=False)

    assert len(fig.axes) == 1
    assert len(fig.axes[0].child_axes) == 1  # the colorbar


def test_sky_can_be_saved(tmp_path):
    columns, times = sky_columns(["cumulonimbus", "fog"])
    path = tmp_path / "sky.png"

    plot_sky(columns, times, save_as=str(path), show=False)

    assert path.read_bytes().startswith(b"\x89PNG")


def test_sky_stacks_the_genera_present_in_a_cell():
    columns, times = sky_columns(["warm_front", "cumulonimbus"])

    ax = plot_sky(columns, times, show=False).axes[0]
    low_row = [(text.get_text(), text.get_position()) for text in ax.texts if 0.0 < text.get_position()[1] < 1.0]
    first = sorted((y, name) for name, (x, y) in low_row if x == pytest.approx(ax.get_xlim()[0] + (ax.get_xlim()[1] - ax.get_xlim()[0]) / 4))

    # The main genus on top.
    assert [name for y, name in reversed(first)] == ["St", "Sc"]
    assert {"Cb", "Cu"} <= {name for name, position in low_row}


def test_sky_style_must_be_known():
    columns, times = sky_columns(["clear"])

    with pytest.raises(ValueError, match="watercolor"):
        plot_sky(columns, times, style="watercolor", show=False)


def test_smooth_sky_paints_the_column_as_one_image():
    columns, times = sky_columns(["clear", "trade_cumulus", "cumulonimbus", "warm_front"])

    ax = plot_sky(columns, times, style="smooth", show=False).axes[0]
    images = ax.get_images()

    assert len(images) == 1
    assert images[0].get_extent()[2:] == [0.0, 3.0]
    # Clouds are whiter than the clear sky beside them, under the Cb anvil darker.
    pixels = images[0].get_array()
    assert pixels.shape[2] == 3 and pixels.min() >= 0.0 and pixels.max() <= 1.0


def test_smooth_sky_tags_each_genus_where_it_is():
    columns, times = sky_columns(["trade_cumulus", "trade_cumulus", "cumulonimbus", "cirrus"])

    tags = {text.get_text() for text in plot_sky(columns, times, style="smooth", show=False).axes[0].texts}

    assert {"Cu", "Cb", "Ci"} <= tags
    assert not {"Cu", "Cb"} & {text.get_text() for text in plot_sky(columns, times, style="smooth", labels=False, show=False).axes[0].texts}


def test_smooth_sky_draws_rain_only_under_clouds_and_lightning_in_storms():
    columns, times = sky_columns(["cumulonimbus", "clear", "clear"], prate=[6.0, 0.0, 2.0])

    ax = plot_sky(columns, times, style="smooth", show=False).axes[0]
    rain = [
        collection
        for collection in ax.collections
        if isinstance(collection, mpl.collections.LineCollection)
        and mpl.colors.to_hex(collection.get_colors()[0]) == "#1e88e5"
    ]
    streaks = np.concatenate([np.asarray(segment)[:, 0] for collection in rain for segment in collection.get_segments()])
    bolts = [line for line in ax.get_lines() if mpl.colors.to_hex(line.get_color()) == "#ffd54f"]

    # All the streaks under the Cb, none in the clear sky that has a rate.
    assert len(streaks) > 0
    assert streaks.max() < mdates.date2num(pd.to_datetime(times[0] + 5400.0, unit="s"))
    assert len(bolts) == 1


def test_smooth_sky_shows_the_oktas_as_symbols():
    columns, times = sky_columns(["clear", "warm_front", "fog"])

    ax = plot_sky(columns, times, style="smooth", show=False).axes[0]
    tops = [collection for collection in ax.collections if np.allclose(collection.get_offsets()[:, 1], 3.15)]

    # A circle per point, a filled part for the clouds, a cross for the fog.
    assert len(tops) == 3 + 1 + 1


def test_smooth_sky_is_darker_at_night():
    # Equator at the March equinox: noon and midnight at Greenwich.
    noon = pd.Timestamp("2026-03-20 12:00").timestamp()
    columns, times = sky_columns(["clear", "clear"])
    times = np.array([noon - 12 * 3600.0, noon])

    image = plot_sky(columns, times, style="smooth", latitude=[0.0, 0.0], longitude=[0.0, 0.0], show=False).axes[0].get_images()[0]
    pixels = np.asarray(image.get_array())

    assert pixels[:, : pixels.shape[1] // 4].mean() < 0.5 * pixels[:, -pixels.shape[1] // 4:].mean()


def test_sun_elevation_at_noon_and_midnight_on_the_equinox():
    noon = pd.Timestamp("2026-03-20 12:00").timestamp()

    assert sun_elevation(noon, 0.0, 0.0) > 85.0
    assert sun_elevation(noon - 12 * 3600.0, 0.0, 0.0) < -85.0
    assert sun_elevation(noon, 0.0, 90.0) == pytest.approx(0.0, abs=2.0)


def test_smooth_sky_can_be_saved(tmp_path):
    columns, times = sky_columns(["cumulonimbus", "fog", "warm_front"])
    path = tmp_path / "sky.png"

    plot_sky(columns, times, style="smooth", save_as=str(path), show=False)

    assert path.read_bytes().startswith(b"\x89PNG")

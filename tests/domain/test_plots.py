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
from cycler import cycler

from architeuthis.report import ReportCollection, RoutingReport
from architeuthis.toolbox.plot_utils import (
    A4_PORTRAIT,
    REPORT_PANELS,
    _finish,
    add_map_background,
    draw,
    get_steps,
    plot_convergence,
    plot_fuel_distribution,
    plot_fuel_quantiles,
    plot_fuel_vs_etd,
    plot_power_and_weather,
    plot_quantiles,
    plot_report,
    plot_route,
    plot_style,
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
# README
# ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def readme():
    root = Path(architeuthis.__file__).parent.parent
    return (root / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "function",
    [
        plot_report,
        draw,
        plot_route,
        plot_variable,
        plot_power_and_weather,
        plot_quantiles,
        plot_fuel_quantiles,
        plot_convergence,
        plot_fuel_distribution,
        plot_fuel_vs_etd,
    ],
)
def test_readme_gives_the_signature_of_each_figure(readme, function):
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

    assert f"{function.__name__}({', '.join(documented)})" in readme


def test_readme_gives_the_panels_of_the_page_in_their_order(readme):
    rows = re.findall(r"^\| (\d) \| `(\w+)` \|", readme, flags=re.MULTILINE)

    assert rows == [(str(i + 1), panel) for i, panel in enumerate(REPORT_PANELS)]


@pytest.mark.parametrize(
    "helper",
    ["get_steps", "add_map_background", "set_plot_style", "plot_style", "A4_PORTRAIT", "REPORT_PANELS"],
)
def test_readme_mentions_the_helpers(readme, helper):
    assert f"`{helper}" in readme


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

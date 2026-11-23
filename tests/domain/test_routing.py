"""End-to-end routing on synthetic fields. The icebergs module is stubbed in tests/conftest.py."""

import copy

import numpy as np
import pytest
import xarray as xr

import architeuthis.numpy as anp
from architeuthis.common import GUST_DEFAULT_RATIO
from architeuthis.core import Leg, RoutingAnalysis, Schedule, Voyage
from architeuthis.toolbox.geo_utils import distances, poly_deviated_route
from architeuthis.fuels import FUELS
from architeuthis.vessel import DEFAULT_FUEL

FUEL_DENSITY = FUELS[DEFAULT_FUEL].density

HOUR = 3600.0
DEPARTURE = np.array([48.0, -35.0])
ARRIVAL = np.array([50.0, -15.0])
ETA = 60.0 * HOUR
HOTEL_LOAD = 200.0
SFC = 224.0
# 3-hourly forecast steps strictly inside (0 h, 60 h), plus one.
EXPECTED_NODES = 20

# With casadi 3.7.2 on Windows, the default spral solver crashes the process on
# problems without variables, so these tests use mumps on every casadi version.
MUMPS = {
    "ipopt": {
        "acceptable_tol": 1e9,
        "linear_solver": "mumps",
        "hessian_approximation": "limited-memory",
    },
}


def make_voyage(eta=ETA, **routes):
    return Voyage(
        name="voyage",
        etd=0.0,
        eta=eta,
        departure=DEPARTURE,
        arrival=ARRIVAL,
        verbose=False,
        **routes,
    )


@pytest.fixture
def analyse(vessel, atmosphere, wave, current):
    def _analyse(topography, voyage=None, vessel=vessel, **kwargs):
        return RoutingAnalysis(
            "analysis",
            vessel,
            voyage if voyage is not None else make_voyage(),
            atmosphere,
            wave,
            current,
            topography,
            verbose=False,
            **kwargs,
        )

    return _analyse


@pytest.fixture
def route(analyse):
    def _route(topography, voyage=None, analysis_options=None, **run_options):
        analysis = analyse(topography, voyage, **(analysis_options or {}))
        return analysis.run(**{"max_iter": 500, "solver_options": MUMPS, **run_options})

    return _route


# ------------------------------------------------------------------------------
# Voyage definition
# ------------------------------------------------------------------------------


def test_leg_measures_the_great_circle_distance():
    leg = Leg("leg", DEPARTURE, ARRIVAL, verbose=False)

    assert leg.distance == pytest.approx(
        distances(np.array([48.0, 50.0]), np.array([-35.0, -15.0]))[0]
    )


def test_schedule_computes_the_transit_time():
    assert Schedule("schedule", etd=10.0, eta=25.0, verbose=False).transit_time == 15.0


def test_voyage_derives_time_and_speed():
    voyage = make_voyage()

    assert voyage.transit_time == 60.0
    assert voyage.transit_sog == pytest.approx(voyage.distance / 60.0)
    assert voyage.etd == 0.0
    assert voyage.eta == ETA
    assert voyage.departure == pytest.approx(DEPARTURE)
    assert voyage.arrival == pytest.approx(ARRIVAL)


# ------------------------------------------------------------------------------
# Forecast validity
# ------------------------------------------------------------------------------


def test_analysis_starts_unsolved(analyse, open_sea):
    assert analyse(open_sea).status == 0


def test_voyage_inside_the_forecast_raises_no_warning(analyse, open_sea, capsys):
    analyse(open_sea).check_valid_time()

    assert "Warning" not in capsys.readouterr().out


def test_voyage_past_the_forecast_horizon_is_reported(analyse, open_sea, capsys):
    # check_valid_time treats valid_time[-3] as the last real step (66 h here).
    analyse(open_sea, make_voyage(eta=70.0 * HOUR)).check_valid_time()

    assert "ETA later" in capsys.readouterr().out


# ------------------------------------------------------------------------------
# Baseline: reference route evaluated without optimizing
# ------------------------------------------------------------------------------


@pytest.mark.integration
class TestBaseline:
    @pytest.fixture
    def report(self, route, open_sea):
        return route(open_sea, solve=False)

    def test_time_grid_follows_the_atmospheric_forecast(self, report):
        assert len(report["tim"]) == EXPECTED_NODES
        assert len(report["ctim"]) == EXPECTED_NODES - 1
        assert report["tim"][0] == 0.0
        assert report["tim"][-1] == ETA
        assert report["ctim"] == pytest.approx(np.arange(3.0, 58.0, 3.0) * HOUR)

    def test_skip_tim_thins_the_grid(self, route, open_sea):
        assert len(route(open_sea, solve=False, skip_tim=1)["tim"]) < EXPECTED_NODES

    def test_route_joins_the_end_points(self, report):
        assert [report["lat"][0], report["lon"][0]] == pytest.approx(DEPARTURE)
        assert [report["lat"][-1], report["lon"][-1]] == pytest.approx(ARRIVAL)

    def test_speed_is_roughly_constant_on_the_reference_route(self, report):
        assert np.ptp(report["sog"]) < 0.2
        assert report["dist_rel"] == pytest.approx(1.0, abs=1e-3)

    def test_fuel_is_the_integral_of_power_and_consumption(self, report):
        power = np.ravel(report["bhp"]) + HOTEL_LOAD
        duration_h = np.diff(np.ravel(report["tim"])) / HOUR

        assert report["fuel"] == pytest.approx(np.sum(power * duration_h * SFC) / 1e6)

    def test_weather_is_converted_to_knots_and_degrees(self, report):
        knots_per_mps = 3600.0 / 1852.0

        assert report["tws"] == pytest.approx(np.hypot(5.0, 2.0) * knots_per_mps)
        assert report["twd"] == pytest.approx(np.degrees(np.arctan2(5.0, 2.0)) + 180.0)
        assert report["cs"] == pytest.approx(0.1 * knots_per_mps)
        assert report["cd"] == pytest.approx(90.0)
        assert report["swh"] == pytest.approx(1.5)
        # From its components, within the bias of WAVE_COMPONENTS_OFFSET
        assert report["mwd"] == pytest.approx(270.0, abs=0.5)

    def test_wave_direction_is_continuous_across_north(self, analyse, open_sea, wave):
        # Waves from 350 and 10 deg on alternate meridians, so segment midpoints fall
        # between the two: interpolating mwd itself would give about 180 deg there.
        crossing = copy.deepcopy(wave)
        for key in ("uw", "vw", "mwd"):
            crossing.remove_interpolator(key)
        direction = xr.zeros_like(crossing.data["swh"])
        east = (np.round(crossing.data["longitude"] * 2) % 2 == 1)
        crossing.data["mwd"] = direction + xr.where(east, 10.0, 350.0)
        crossing.add_wave_components()
        for key in ("uw", "vw"):
            crossing.add_interpolator(key, "valid_time", "latitude", "longitude")

        analysis = analyse(open_sea)
        analysis.wave = crossing
        report = analysis.run(solve=False, solver_options=MUMPS)

        from_north = np.minimum(report["mwd"], 360.0 - np.asarray(report["mwd"]))
        assert np.max(from_north) < 10.5

    def test_wave_direction_needs_its_components(self, analyse, open_sea, wave):
        without = copy.deepcopy(wave)
        without.remove_interpolator("uw")
        analysis = analyse(open_sea)
        analysis.wave = without

        with pytest.raises(KeyError, match="add_wave_components"):
            analysis.run(solve=False, solver_options=MUMPS)

    def test_gusts_default_to_the_standard_ratio(self, report):
        assert report["tws_gust"] == pytest.approx(report["tws"] * GUST_DEFAULT_RATIO)

    def test_gusts_can_be_disabled(self, route, open_sea):
        report = route(open_sea, solve=False, analysis_options={"options": {}})

        assert "tws_gust" not in report
        assert "aws_gust" not in report

    def test_deviation_factor_selects_the_reference_route(self, route, open_sea):
        def deviated(divergence):
            return poly_deviated_route(
                [DEPARTURE[0], ARRIVAL[0]],
                [DEPARTURE[1], ARRIVAL[1]],
                [divergence],
            )

        voyage = make_voyage(route_minus=deviated(-0.3), route_plus=deviated(0.3))
        report = route(open_sea, voyage=voyage, solve=False, init_fac=1.0)

        curvilinear_abscissa = np.ravel(report["tim"]) / ETA
        expected_lat, expected_lon = deviated(0.3)(curvilinear_abscissa)
        assert report["lat"] == pytest.approx(expected_lat)
        assert report["lon"] == pytest.approx(expected_lon)


# ------------------------------------------------------------------------------
# Optimization
# ------------------------------------------------------------------------------


@pytest.mark.integration
class TestOptimization:
    def test_open_sea_does_not_burn_more_than_the_baseline(self, route, open_sea):
        baseline = route(open_sea, solve=False)
        optimized = route(open_sea)

        assert optimized["status"] == 1
        assert optimized["fuel"] <= baseline["fuel"] * (1.0 + 1e-6)

    def test_end_points_and_schedule_stay_fixed(self, route, open_sea):
        report = route(open_sea)

        assert [report["lat"][0], report["lon"][0]] == pytest.approx(DEPARTURE)
        assert [report["lat"][-1], report["lon"][-1]] == pytest.approx(ARRIVAL)
        assert report["tim"][-1] == ETA

    def test_route_detours_around_land(self, route, island):
        baseline = route(island, solve=False)
        optimized = route(island)

        assert np.max(baseline["z"]) > 50.0
        assert optimized["status"] == 1
        assert np.max(optimized["z"]) == pytest.approx(0.0, abs=1e-2)
        assert optimized["dist"] > baseline["dist"]
        assert optimized["fuel"] > baseline["fuel"]

    def test_constraints_callable_replaces_the_default(self, route, island):
        def keep_clear_of_land(ctx):
            return [ctx["z"] < -20.0]

        report = route(island, constraints=keep_clear_of_land)

        assert report["status"] == 1
        assert np.max(report["z"]) == pytest.approx(-20.0, abs=1e-2)

    def test_constructor_constraints_are_used(self, route, island):
        def keep_clear_of_land(ctx):
            return [ctx["z"] < -20.0]

        report = route(island, analysis_options={"constraints": keep_clear_of_land})

        assert np.max(report["z"]) == pytest.approx(-20.0, abs=1e-2)

    def test_max_power_limits_the_route(self, route, vessel, open_sea):
        power_limit = 1.2 * 14.0**3

        def limit_power(ctx):
            return [ctx["max_bhp"] < power_limit]

        report = route(open_sea, constraints=limit_power, variables=["max_bhp"])

        assert np.max(report["max_bhp"]) <= power_limit * (1.0 + 1e-6)

    def test_failed_solve_returns_the_last_iterate_with_status_two(self, analyse, open_sea):
        analysis = analyse(open_sea)

        report = analysis.run(max_iter=1, solver_options=MUMPS)

        assert report["status"] == 2
        assert analysis.status == 2
        assert "lat" in report


# ------------------------------------------------------------------------------
# Passage plans and open-loop evaluation
# ------------------------------------------------------------------------------


@pytest.mark.integration
class TestEvaluation:
    @pytest.fixture
    def optimized(self, analyse, island):
        analysis = analyse(island)
        report = analysis.run(max_iter=500, solver_options=MUMPS)
        return analysis, report

    def test_run_stores_its_report_and_passage_plan(self, optimized):
        analysis, report = optimized
        plan = analysis.passage_plan

        assert analysis.report is report
        assert plan.lat == pytest.approx(np.ravel(report["lat"]))
        assert plan.ctim == pytest.approx(np.ravel(report["ctim"]))
        assert plan.metadata["fuel"] == pytest.approx(report["fuel"])
        assert plan.metadata["vessel"]["name"] == "ship"
        assert plan.metadata["run"]["solve"] is True

    def test_evaluating_a_plan_reproduces_its_run(self, optimized):
        analysis, report = optimized

        evaluation = analysis.evaluate(analysis.passage_plan)

        assert set(report) <= set(evaluation)
        assert evaluation["status"] == 0
        assert evaluation["init_fac"] is None
        for key in ("fuel", "dist", "dist_rel", "transit_sog"):
            assert evaluation[key] == pytest.approx(report[key], rel=1e-9)
        for key in ("lat", "lon", "tim", "ctim", "bhp", "z", "sog", "tws_gust"):
            assert np.ravel(evaluation[key]) == pytest.approx(np.ravel(report[key]), rel=1e-9, abs=1e-9)

    def test_a_report_can_be_evaluated_directly(self, optimized):
        analysis, report = optimized

        assert analysis.evaluate(report)["fuel"] == pytest.approx(report["fuel"], rel=1e-9)

    def test_plan_survives_storage_and_evaluates_the_same(self, optimized, tmp_path):
        from architeuthis.voyage import PassagePlan

        analysis, report = optimized
        plan = PassagePlan.load(analysis.passage_plan.save(str(tmp_path / "plan.json")), verbose=False)

        assert analysis.evaluate(plan)["fuel"] == pytest.approx(report["fuel"], rel=1e-9)

    def test_positions_stay_fixed_under_another_vessel(self, optimized, analyse, island, polar):
        from architeuthis.vessel import Vessel

        analysis, report = optimized
        heavier = Vessel("heavier", filepath="unused.nc", sfoc=SFC, hotel_load=HOTEL_LOAD, verbose=False)
        heavier.data = polar.copy()
        for key in ("bhp", "max_bhp", "sails_contribution"):
            heavier.data[key] = heavier.data[key] * 2.0
            heavier.add_interpolator(key, "stw", "tws", "twa", "hs", "wa")

        evaluation = analyse(island, vessel=heavier).evaluate(analysis.passage_plan)

        assert np.ravel(evaluation["lat"]) == pytest.approx(np.ravel(report["lat"]))
        assert np.ravel(evaluation["bhp"]) == pytest.approx(2.0 * np.ravel(report["bhp"]), rel=1e-6)
        assert evaluation["fuel"] > report["fuel"]

    def test_constraint_violations_are_reported(self, route, analyse, open_sea, island):
        straight = analyse(open_sea)
        straight.run(solve=False, solver_options=MUMPS)

        evaluation = analyse(island).evaluate(straight.passage_plan)

        # The default constraints are bhp < max_power and z < 0.
        assert len(evaluation["constraint_violations"]) == 2
        assert evaluation["max_constraint_violation"] == pytest.approx(np.max(evaluation["z"]))
        assert evaluation["max_constraint_violation"] > 50.0

    def test_constraints_are_not_violated_by_the_optimum(self, optimized):
        analysis, _ = optimized

        assert analysis.evaluate(analysis.passage_plan)["max_constraint_violation"] < 1e-2

    def test_evaluation_takes_its_own_constraints(self, optimized):
        analysis, _ = optimized

        evaluation = analysis.evaluate(analysis.passage_plan, constraints=lambda ctx: [ctx["sog"] < 1.0])

        assert evaluation["max_constraint_violation"] == pytest.approx(np.max(evaluation["sog"]) - 1.0)


# ------------------------------------------------------------------------------
# What identifies a report, and following a run
# ------------------------------------------------------------------------------


class TestTags:
    def test_reports_are_tagged_by_default(self, route, open_sea, vessel):
        report = route(open_sea, solve=False)

        assert report["solve"] == 0
        assert report["model"] == "atmosphere"
        assert report["vessel"] == vessel.label
        assert "member" in report

    def test_optimized_reports_are_tagged_as_such(self, route, open_sea):
        assert route(open_sea, max_iter=5)["solve"] == 1

    def test_tags_are_added_to_the_report_and_can_replace_defaults(self, route, open_sea):
        report = route(open_sea, solve=False, tags={"model": "ifs", "init_fac": -1.0, "note": "first"})

        assert report["model"] == "ifs"
        assert report["init_fac"] == -1.0
        assert report["note"] == "first"

    def test_tags_are_recorded_in_the_passage_plan(self, analyse, open_sea):
        analysis = analyse(open_sea)

        analysis.run(max_iter=5, solve=False, solver_options=MUMPS, tags={"model": "ifs"})

        assert analysis.passage_plan.metadata["tags"]["model"] == "ifs"

    def test_model_tag_comes_from_the_forecast(self, analyse, open_sea, atmosphere, monkeypatch):
        monkeypatch.setattr(atmosphere, "model", "gfs", raising=False)

        report = analyse(open_sea).run(max_iter=5, solve=False, solver_options=MUMPS)

        assert report["model"] == "gfs"

    def test_evaluation_is_tagged_too(self, analyse, open_sea):
        analysis = analyse(open_sea)
        analysis.run(max_iter=5, solve=False, solver_options=MUMPS)

        report = analysis.evaluate(analysis.passage_plan, tags={"model": "other"})

        assert report["solve"] == 0
        assert report["model"] == "other"
        assert report["plan"] == analysis.passage_plan.name

    def test_analysis_describes_the_vessel_label(self, analyse, open_sea, vessel):
        assert analyse(open_sea).describe()["vessel"]["label"] == vessel.label


class TestCallback:
    def test_callback_follows_the_iterations(self, analyse, open_sea):
        iterations = []

        analyse(open_sea).run(max_iter=5, solver_options=MUMPS, callback=iterations.append)

        assert iterations
        assert iterations == sorted(iterations)

    def test_no_callback_is_needed(self, analyse, open_sea):
        assert analyse(open_sea).run(max_iter=2, solver_options=MUMPS, callback=None) is not None


class TestWithoutVoyage:
    def test_routing_needs_a_voyage(self, vessel, atmosphere, wave, current, open_sea):
        analysis = RoutingAnalysis("analysis", vessel, None, atmosphere, wave, current, open_sea, verbose=False)

        with pytest.raises(ValueError, match="needs a voyage"):
            analysis.run()

    def test_a_plan_can_be_evaluated_without_a_voyage(self, analyse, vessel, atmosphere, wave, current, open_sea):
        reference = analyse(open_sea)
        original = reference.run(max_iter=5, solve=False, solver_options=MUMPS)
        analysis = RoutingAnalysis("analysis", vessel, None, atmosphere, wave, current, open_sea, verbose=False)

        report = analysis.evaluate(reference.passage_plan)

        assert report["fuel"] == pytest.approx(original["fuel"])


def test_analysis_options_are_not_shared(analyse, open_sea):
    first = analyse(open_sea)
    second = analyse(open_sea)

    first.options["include_gusts"] = False

    assert second.options["include_gusts"] is True


def test_analysis_describes_its_exclusion_zones(analyse, open_sea):
    assert "exclusion_zones" in analyse(open_sea).describe()


# ------------------------------------------------------------------------------
# Function-based polars
# ------------------------------------------------------------------------------


POLAR_POWER_COEFFICIENT = 1.2  # as built by the `vessel` fixture


def semi_empirical_power(x, p):
    """Cubic power, corrected by the water temperature, as a fitted model would be."""
    return p["k"] * x["stw"] ** 3 * (1.0 + p["k_temperature"] * (x["water_temperature"] - 12.0))


def function_vessel():
    from architeuthis.vessel import Vessel

    # max_power as the fixture: a slack of 1e12 kW unsettles IPOPT's barrier.
    vessel = Vessel("function_ship", sfoc=SFC, hotel_load=HOTEL_LOAD, max_power=1e6, verbose=False)
    parameters = {"k": POLAR_POWER_COEFFICIENT, "k_temperature": 0.01}
    vessel.add_function("bhp", semi_empirical_power, inputs=["stw", "water_temperature"], args={"p": parameters})
    return vessel


def current_with_temperature(current, temperature):
    """A current forecast that also has the water temperature, as a function of position and time."""
    from architeuthis.forecast import Forecast

    forecast = Forecast("current", date=0.0, fxx=None, verbose=False)
    forecast.data = current.data
    for key in ("uo", "vo"):
        forecast.add_interpolator(key, "valid_time", "latitude", "longitude")
    forecast.add_function(
        "water_temperature",
        lambda x: temperature + 0.0 * x["latitude"],
        inputs=["valid_time", "latitude", "longitude"],
    )
    return forecast


@pytest.mark.integration
def test_function_polar_reads_its_inputs_from_the_forecasts(vessel, atmosphere, wave, current, open_sea):
    def baseline(ship, temperature):
        analysis = RoutingAnalysis(
            "analysis",
            ship,
            make_voyage(),
            atmosphere,
            wave,
            current_with_temperature(current, temperature),
            open_sea,
            verbose=False,
        )
        return analysis.run(solve=False, solver_options=MUMPS)

    table = baseline(vessel, 12.0)
    at_12 = baseline(function_vessel(), 12.0)
    at_22 = baseline(function_vessel(), 22.0)

    # The table interpolates the cubic law linearly between whole knots.
    assert np.ravel(at_12["bhp"]) == pytest.approx(np.ravel(table["bhp"]), rel=1e-2)
    assert np.ravel(at_22["bhp"]) == pytest.approx(1.1 * np.ravel(at_12["bhp"]), rel=1e-9)
    assert at_22["fuel"] > at_12["fuel"]


@pytest.mark.integration
def test_function_polar_can_be_optimized(atmosphere, wave, current, island):
    analysis = RoutingAnalysis(
        "analysis",
        function_vessel(),
        make_voyage(),
        atmosphere,
        wave,
        current_with_temperature(current, 12.0),
        island,
        verbose=False,
    )

    report = analysis.run(max_iter=500, solver_options=MUMPS)

    assert report["status"] in (0, 1)
    assert report["vessel"] == "function_ship"
    assert np.max(report["z"]) < 1e-2


def test_missing_forecast_variable_is_reported(atmosphere, wave, current, open_sea):
    analysis = RoutingAnalysis(
        "analysis",
        function_vessel(),
        make_voyage(),
        atmosphere,
        wave,
        current,
        open_sea,
        verbose=False,
    )

    with pytest.raises(KeyError, match="water_temperature"):
        analysis.run(solve=False, solver_options=MUMPS)


# ------------------------------------------------------------------------------
# Wind at other heights
# ------------------------------------------------------------------------------


def wind_polar(suffix):
    """A polar whose power depends on the true and apparent wind named with `suffix`."""

    def power(x):
        sails = x[f"aws{suffix}"] * (1.0 + anp.cosd(x[f"awa{suffix}"])) + x[f"tws{suffix}"] * (1.0 + anp.cosd(x[f"twa{suffix}"]))
        return 1.2 * x["stw"] ** 3 + 5.0 * sails + 0.0 * x[f"twd{suffix}"]

    return power


def wind_vessel(suffix):
    from architeuthis.vessel import Vessel

    vessel = Vessel(f"wind{suffix}", sfoc=SFC, hotel_load=HOTEL_LOAD, max_power=1e6, verbose=False)
    inputs = ["stw"] + [f"{name}{suffix}" for name in ("tws", "twd", "twa", "aws", "awa")]
    vessel.add_function("bhp", wind_polar(suffix), inputs)
    return vessel


def atmosphere_with_wind_at_100_m(factor):
    from .conftest import uniform_forecast

    return uniform_forecast("atmosphere", u10=5.0, v10=2.0, u100=5.0 * factor, v100=2.0 * factor)


@pytest.mark.integration
def test_wind_at_another_height_is_relative_to_the_vessel(wave, current, open_sea):
    def baseline(vessel, atmosphere):
        analysis = RoutingAnalysis(
            "analysis", vessel, make_voyage(), atmosphere, wave, current, open_sea, verbose=False,
        )
        return analysis.run(solve=False, solver_options=MUMPS)

    with_ten = baseline(wind_vessel(""), atmosphere_with_wind_at_100_m(1.0))
    same_wind = baseline(wind_vessel("100"), atmosphere_with_wind_at_100_m(1.0))
    stronger_wind = baseline(wind_vessel("100"), atmosphere_with_wind_at_100_m(1.5))

    # Same wind at 100 m as at 10 m: the same quantities, so the same power.
    assert np.ravel(same_wind["bhp"]) == pytest.approx(np.ravel(with_ten["bhp"]), rel=1e-9)
    assert not np.allclose(np.ravel(stronger_wind["bhp"]), np.ravel(same_wind["bhp"]))


def test_wind_at_a_height_without_its_components_is_reported(atmosphere, wave, current, open_sea):
    analysis = RoutingAnalysis(
        "analysis", wind_vessel("100"), make_voyage(), atmosphere, wave, current, open_sea, verbose=False,
    )

    with pytest.raises(KeyError, match="u100"):
        analysis.run(solve=False, solver_options=MUMPS)


# ------------------------------------------------------------------------------
# Additional variables
# ------------------------------------------------------------------------------

KNOTS = 3600.0 / 1852.0


def wave_with_period(period):
    """The wave fixture plus a mean wave period, and a wave slope computed from it."""
    from .conftest import uniform_forecast

    forecast = uniform_forecast("wave", swh=1.5, mwd=270.0, mwp=period)
    forecast.add_wave_components()
    for key in ("uw", "vw"):
        forecast.add_interpolator(key, "valid_time", "latitude", "longitude")
    forecast.add_function(
        "slope",
        lambda x: forecast("swh", x) / forecast("mwp", x),
        inputs=["valid_time", "latitude", "longitude"],
    )
    return forecast


def test_variables_take_names_lists_and_dicts():
    from architeuthis.core import normalize_variables

    def excess(ctx):
        return ctx["tws_gust"] - ctx["tws"]

    assert normalize_variables(None) == {}
    assert normalize_variables("slope") == {"slope": "slope"}
    assert normalize_variables({"pres": None, "slope": "wave.slope"}) == {"pres": "pres", "slope": "wave.slope"}
    # "gust" asks for the gusts in kt, the gust model itself is named otherwise
    assert normalize_variables("gust") == {"tws_gust": "tws_gust", "aws_gust": "aws_gust"}
    assert normalize_variables({"gust_ms": "atmosphere.gust"}) == {"gust_ms": "atmosphere.gust"}
    assert normalize_variables(["tws_gust", {"excess": excess}]) == {"tws_gust": "tws_gust", "excess": excess}
    # A source prefix picks where the model is read, and is not part of the name
    assert normalize_variables(["wave.slope"]) == {"slope": "wave.slope"}
    assert normalize_variables({"wave_slope": "wave.slope"}) == {"wave_slope": "wave.slope"}

    with pytest.raises(TypeError):
        normalize_variables([3])
    with pytest.raises(TypeError):
        normalize_variables({"gust": 3})


class TestAdditionalVariables:
    def test_gusts_can_be_asked_without_the_option(self, route, open_sea):
        report = route(open_sea, solve=False, analysis_options={"options": {}, "variables": ["tws_gust"]})

        assert report["tws_gust"] == pytest.approx(report["tws"] * GUST_DEFAULT_RATIO)
        assert "aws_gust" not in report

    def test_apparent_gusts_alone_still_come_from_the_gust(self, route, open_sea):
        report = route(open_sea, solve=False, analysis_options={"options": {}, "variables": ["aws_gust"]})
        reference = route(open_sea, solve=False)

        assert "tws_gust" not in report
        assert report["aws_gust"] == pytest.approx(reference["aws_gust"])

    def test_gust_of_the_forecast_is_read_in_knots(self, analyse, open_sea):
        from .conftest import uniform_forecast

        analysis = analyse(open_sea, options={}, variables=["tws_gust", {"gust_ms": "atmosphere.gust"}])
        analysis.atmosphere = uniform_forecast("atmosphere", u10=5.0, v10=2.0, gust=10.0)
        report = analysis.run(solve=False, solver_options=MUMPS)

        assert np.ravel(report["tws_gust"]) == pytest.approx(10.0 * KNOTS)
        # Asked by its model key, a forecast variable keeps the units of its model
        assert np.ravel(report["gust_ms"]) == pytest.approx(10.0)

    def test_gust_asks_for_the_true_and_apparent_gusts(self, route, open_sea):
        report = route(open_sea, solve=False, analysis_options={"options": {}, "variables": ["gust"]})
        reference = route(open_sea, solve=False)

        assert "gust" not in report
        assert report["tws_gust"] == pytest.approx(reference["tws_gust"])
        assert report["aws_gust"] == pytest.approx(reference["aws_gust"])

    @pytest.mark.parametrize("include_gusts", [True, False])
    def test_the_gust_option_is_deprecated(self, analyse, open_sea, include_gusts):
        with pytest.warns(DeprecationWarning, match=r"variables=\['gust'\]"):
            analyse(open_sea, options={"include_gusts": include_gusts})

    def test_without_the_gust_option_nothing_is_deprecated(self, analyse, open_sea):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            analyse(open_sea)
            analyse(open_sea, options={}, variables=["gust"])

    def test_a_forecast_function_is_computed_and_reported(self, analyse, open_sea):
        analysis = analyse(open_sea, variables=["slope", {"period": "wave.mwp"}])
        analysis.wave = wave_with_period(6.0)
        report = analysis.run(solve=False, solver_options=MUMPS)

        assert np.ravel(report["slope"]) == pytest.approx(1.5 / 6.0)
        assert np.ravel(report["period"]) == pytest.approx(6.0)
        assert len(np.ravel(report["slope"])) == len(np.ravel(report["ctim"]))
        # The gusts of the default options are still there
        assert "tws_gust" in report and "aws_gust" in report

    def test_a_callable_sees_the_variables_before_it(self, route, open_sea):
        report = route(open_sea, solve=False, analysis_options={
            "variables": {"tws_gust": None, "excess": lambda ctx: ctx["tws_gust"] - ctx["tws"]},
        })

        assert report["excess"] == pytest.approx(report["tws"] * (GUST_DEFAULT_RATIO - 1.0))

    def test_variables_are_in_the_constraint_context(self, analyse, open_sea):
        analysis = analyse(open_sea, variables=["slope"])
        analysis.wave = wave_with_period(6.0)
        baseline = analysis.run(solve=False, solver_options=MUMPS)

        report = analysis.evaluate(baseline, constraints=lambda ctx: [ctx["slope"] < 0.1])

        assert report["max_constraint_violation"] == pytest.approx(0.25 - 0.1)
        assert report["slope"] == pytest.approx(baseline["slope"])

    @pytest.mark.integration
    def test_a_constraint_on_a_variable_is_enforced(self, analyse, island):
        def keep_clear(ctx):
            return [ctx["max_bhp"] < ctx["vessel"].max_power, ctx["clearance"] < 0.0]

        analysis = analyse(
            island,
            constraints=keep_clear,
            variables={"max_bhp": None, "clearance": lambda ctx: ctx["z"]},
        )
        report = analysis.run(max_iter=500, solver_options=MUMPS)

        assert report["status"] in (0, 1)
        assert np.max(report["z"]) < 1e-2
        assert report["clearance"] == pytest.approx(report["z"])

    def test_a_vessel_model_gets_its_inputs_from_the_forecasts(self, analyse, vessel, current, open_sea):
        ship = copy.deepcopy(vessel)
        ship.add_function(
            "comfort",
            lambda x: x["tws"] + x["water_temperature"],
            inputs=["tws", "water_temperature"],
        )
        analysis = analyse(open_sea, vessel=ship, variables=["vessel.comfort"])
        analysis.current = current_with_temperature(current, 12.0)
        report = analysis.run(solve=False, solver_options=MUMPS)

        assert np.ravel(report["comfort"]) == pytest.approx(np.ravel(report["tws"]) + 12.0)

    def test_wind_at_another_height_is_reported_signed(self, analyse, open_sea):
        analysis = analyse(open_sea, variables=["tws100", "twa100", "awa100"])
        analysis.atmosphere = atmosphere_with_wind_at_100_m(1.0)
        report = analysis.run(solve=False, solver_options=MUMPS)

        assert report["tws100"] == pytest.approx(report["tws"])
        assert report["twa100"] == pytest.approx(report["twa"])
        assert report["awa100"] == pytest.approx(report["awa"])

    def test_run_and_evaluate_add_their_own_variables(self, analyse, open_sea):
        analysis = analyse(open_sea, options={}, variables=["tws_gust"])
        report = analysis.run(solve=False, solver_options=MUMPS, variables={"wind": "tws"})
        evaluation = analysis.evaluate(report, variables=["aws_gust"])

        assert {"tws_gust", "wind"} <= set(report) and "aws_gust" not in report
        assert report["wind"] == pytest.approx(report["tws"])
        assert {"tws_gust", "aws_gust"} <= set(evaluation) and "wind" not in evaluation
        assert analysis.variables == {"tws_gust": "tws_gust"}

    def test_variables_are_described_in_the_passage_plan(self, analyse, open_sea):
        import json

        def excess(ctx):
            return ctx["tws_gust"] - ctx["tws"]

        analysis = analyse(open_sea, variables={"tws_gust": None, "excess": excess})
        analysis.run(solve=False, solver_options=MUMPS, variables=["swh"])

        metadata = analysis.passage_plan.metadata
        assert metadata["variables"] == {"tws_gust": "tws_gust", "excess": "excess"}
        assert metadata["run"]["variables"] == {"swh": "swh"}
        json.dumps(metadata)

    @pytest.mark.parametrize(
        "variables, error, match",
        [
            (["unknown"], KeyError, "unknown"),
            (["wave.unknown"], KeyError, "unknown"),
            ({"tws": "tws_gust"}, ValueError, "already computed"),
            ({"status": "swh"}, ValueError, "reserved"),
        ],
    )
    def test_wrong_variables_are_reported(self, analyse, open_sea, variables, error, match):
        analysis = analyse(open_sea, variables=variables)

        with pytest.raises(error, match=match):
            analysis.run(solve=False, solver_options=MUMPS)


# ------------------------------------------------------------------------------
# Consumption formulations and optional vessel variables
# ------------------------------------------------------------------------------


def cubic_bhp(x):
    return POLAR_POWER_COEFFICIENT * x["stw"] ** 3


def consumption_vessel(formulation, **kwargs):
    """A vessel whose consumption is the cubic law of the fixture, in one of the formulations."""
    from architeuthis.vessel import Vessel

    vessel = Vessel(f"{formulation}_ship", verbose=False, **kwargs)
    if formulation == "bhp":
        vessel.add_function("bhp", cubic_bhp, ["stw"])
    elif formulation == "total_power":
        vessel.add_function("total_power", lambda x: cubic_bhp(x) + HOTEL_LOAD, ["stw"])
    else:
        vessel.add_function(
            "hourly_consumption",
            lambda x: (cubic_bhp(x) + HOTEL_LOAD) * SFC / 1e3 / FUEL_DENSITY,
            ["stw"],
        )
    return vessel


def evaluate_baseline(vessel, atmosphere, wave, current, topography, **kwargs):
    analysis = RoutingAnalysis(
        "analysis", vessel, make_voyage(), atmosphere, wave, current, topography, verbose=False, **kwargs,
    )
    return analysis.run(solve=False, solver_options=MUMPS)


class TestConsumption:
    @pytest.fixture
    def baseline(self, atmosphere, wave, current, open_sea):
        def _baseline(vessel, **kwargs):
            return evaluate_baseline(vessel, atmosphere, wave, current, open_sea, **kwargs)

        return _baseline

    @pytest.fixture
    def reference(self, baseline):
        return baseline(consumption_vessel("bhp", hotel_load=HOTEL_LOAD, sfoc=SFC))

    def test_the_formulations_give_the_same_fuel(self, baseline, reference):
        total = baseline(consumption_vessel("total_power", sfoc=SFC))
        hourly = baseline(consumption_vessel("hourly_consumption"))

        assert total["fuel"] == pytest.approx(reference["fuel"], rel=1e-9)
        assert hourly["fuel"] == pytest.approx(reference["fuel"], rel=1e-9)
        assert np.ravel(hourly["hourly_consumption"]) == pytest.approx(np.ravel(reference["hourly_consumption"]))

    def test_fuel_integrates_the_hourly_consumption(self, reference):
        duration_h = np.diff(np.ravel(reference["tim"])) / HOUR

        # Litres per hour over each segment, times kg/L, in tonnes.
        assert reference["fuel"] == pytest.approx(np.sum(np.ravel(reference["hourly_consumption"]) * duration_h) * FUEL_DENSITY / 1e3)

    def test_reports_hold_the_quantities_of_their_formulation(self, baseline, reference):
        total = baseline(consumption_vessel("total_power", sfoc=SFC))
        hourly = baseline(consumption_vessel("hourly_consumption"))
        segments = len(np.ravel(reference["ctim"]))

        for key in ("bhp", "hotel_load", "total_power", "sfoc", "hourly_consumption"):
            assert len(np.ravel(reference[key])) == segments
        assert np.ravel(reference["hotel_load"]) == pytest.approx(HOTEL_LOAD)
        assert np.ravel(reference["total_power"]) == pytest.approx(np.ravel(reference["bhp"]) + HOTEL_LOAD)
        assert np.ravel(reference["sfoc"]) == pytest.approx(SFC)
        assert {"total_power", "sfoc", "hourly_consumption"} <= set(total)
        assert not {"bhp", "hotel_load"} & set(total)
        assert "hourly_consumption" in hourly
        assert not {"bhp", "hotel_load", "total_power", "sfoc"} & set(hourly)

    def test_optional_vessel_variables_are_computed_when_listed(self, vessel, baseline):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            listed = baseline(vessel, variables=["max_bhp", "sails_contribution"])
            other = baseline(consumption_vessel("bhp", hotel_load=HOTEL_LOAD, sfoc=SFC, max_power=None))

        assert np.ravel(listed["max_bhp"]) == pytest.approx(np.ravel(listed["bhp"]))
        assert np.ravel(listed["sails_contribution"]) == pytest.approx(0.0)
        assert not {"max_bhp", "sails_contribution"} & set(other)

    def test_unlisted_max_bhp_and_sails_are_still_computed_until_0_4(self, vessel, baseline):
        with pytest.warns(DeprecationWarning, match="from 0.4.0") as record:
            default = baseline(vessel, variables=["max_bhp"])

        assert "sails_contribution" in str(record[0].message)
        assert "max_bhp," not in str(record[0].message)
        assert {"max_bhp", "sails_contribution"} <= set(default)

    def test_avg_bhp_is_the_deprecated_name_of_bhp(self, reference, baseline):
        import json

        from architeuthis.report import ReportCollection, RoutingReport
        from architeuthis.toolbox.json_utils import CustomEncoder

        assert "avg_bhp" not in dict(reference)
        with pytest.warns(DeprecationWarning, match="use 'bhp'"):
            assert np.ravel(reference["avg_bhp"]) == pytest.approx(np.ravel(reference["bhp"]))
        with pytest.warns(DeprecationWarning, match="use 'bhp'"):
            assert "avg_bhp" in reference
        with pytest.warns(DeprecationWarning, match="use 'bhp'"):
            assert reference.get("avg_bhp") is reference["bhp"]

        # Reports saved under the former name are read under the current one
        saved = {("avg_bhp" if key == "bhp" else key): value for key, value in reference.items()}
        loaded = ReportCollection(json.loads(json.dumps([saved], cls=CustomEncoder)))[0]
        assert isinstance(loaded, RoutingReport)
        assert "bhp" in dict(loaded) and "avg_bhp" not in dict(loaded)

        # Constraints written with the former name still work
        seen = {}

        def constraints(ctx):
            with pytest.warns(DeprecationWarning, match="use 'bhp'"):
                seen["avg_bhp"] = ctx["avg_bhp"]
            return [ctx["z"] < 0.0]

        baseline(consumption_vessel("bhp", hotel_load=HOTEL_LOAD, sfoc=SFC), constraints=constraints)
        assert "avg_bhp" in seen

    def test_a_constant_brake_power(self, baseline):
        from architeuthis.vessel import Vessel

        vessel = Vessel("constant_ship", hotel_load=HOTEL_LOAD, sfoc=SFC, verbose=False)
        vessel.add_constant("bhp", 1000.0)

        report = baseline(vessel)

        assert np.ravel(report["bhp"]) == pytest.approx(1000.0)
        assert report["fuel"] == pytest.approx((1000.0 + HOTEL_LOAD) * ETA / HOUR * SFC / 1e6)

    def test_sfoc_and_hotel_load_can_be_models(self, baseline, reference):
        vessel = consumption_vessel("bhp")
        vessel.add_constant("hotel_load", HOTEL_LOAD)
        # An sfoc curve of the engine load, constant here
        vessel.add_function("sfoc", lambda x: SFC + 0.0 * x["total_power"], ["total_power"])

        report = baseline(vessel)

        assert report["fuel"] == pytest.approx(reference["fuel"], rel=1e-9)

    def test_a_variable_model_can_take_a_consumption_quantity(self, baseline):
        vessel = consumption_vessel("bhp", hotel_load=HOTEL_LOAD, sfoc=SFC)
        vessel.add_function("load", lambda x: x["bhp"] / 1e4, ["bhp"])

        report = baseline(vessel, variables=["load"])

        assert np.ravel(report["load"]) == pytest.approx(np.ravel(report["bhp"]) / 1e4)

    def test_a_vessel_without_consumption_is_reported(self, baseline):
        from architeuthis.vessel import Vessel

        vessel = Vessel("no_consumption", sfoc=SFC, verbose=False)
        vessel.add_function("max_bhp", cubic_bhp, ["stw"])

        with pytest.raises(KeyError, match="no consumption model"):
            baseline(vessel)

    def test_a_missing_sfoc_is_zero_until_0_4(self, baseline):
        with pytest.warns(DeprecationWarning, match="no sfoc"):
            report = baseline(consumption_vessel("total_power", max_power=None))

        assert report["fuel"] == 0.0

    def test_the_power_limit_is_optional(self, analyse, open_sea):
        def count(vessel):
            analysis = analyse(open_sea, vessel=vessel)
            return len(analysis.evaluate(analysis.run(solve=False, solver_options=MUMPS))["constraint_violations"])

        assert count(consumption_vessel("bhp", sfoc=SFC, max_power=None)) == 1
        with pytest.warns(DeprecationWarning, match="max_power"):
            unset = consumption_vessel("bhp", sfoc=SFC)
        assert unset.max_power == 1e12
        assert count(unset) == 2
        assert count(consumption_vessel("bhp", sfoc=SFC, max_power=1e6)) == 2
        assert count(consumption_vessel("total_power", sfoc=SFC, max_power=1e6)) == 2
        assert count(consumption_vessel("hourly_consumption", max_power=1e6)) == 1

    def test_max_bhp_is_limited_first_when_listed(self):
        import casadi as ca
        from types import SimpleNamespace

        from architeuthis.core import default_routing_constraints

        powers = {key: ca.MX.sym(key) for key in ("max_bhp", "bhp", "total_power")}
        ctx = {"vessel": SimpleNamespace(max_power=100.0), "z": ca.MX.sym("z"), **powers}

        for key in ("max_bhp", "bhp", "total_power"):
            limit, at_sea = default_routing_constraints(ctx)
            assert ca.is_equal(limit.dep(0), powers[key])
            assert ca.is_equal(at_sea.dep(0), ctx["z"])
            del ctx[key]
        assert len(default_routing_constraints(ctx)) == 1

    @pytest.mark.integration
    def test_an_hourly_consumption_can_be_optimized(self, atmosphere, wave, current, island):
        vessel = consumption_vessel("hourly_consumption")
        analysis = RoutingAnalysis(
            "analysis", vessel, make_voyage(), atmosphere, wave, current, island, verbose=False,
        )

        baseline = analysis.run(solve=False, solver_options=MUMPS)
        optimized = analysis.run(max_iter=500, solver_options=MUMPS)

        assert optimized["status"] == 1
        assert np.max(optimized["z"]) < 1e-2
        assert np.max(baseline["z"]) > 0.0


@pytest.mark.integration
def test_a_polar_table_can_be_optimized_on_a_calm_sea(vessel, atmosphere, current, island):
    # The wave components vanish everywhere: the wave direction, an input of the
    # table, keeps a gradient only thanks to WAVE_COMPONENTS_OFFSET.
    from .conftest import uniform_forecast

    calm_sea = uniform_forecast("calm_sea", swh=0.0, uw=0.0, vw=0.0)
    analysis = RoutingAnalysis(
        "analysis", vessel, make_voyage(), atmosphere, calm_sea, current, island, verbose=False,
    )

    optimized = analysis.run(max_iter=500, solver_options=MUMPS)

    assert optimized["status"] == 1
    assert np.max(optimized["z"]) < 1e-2


class TestIncompleteEnvironment:
    def test_a_missing_source_is_calm(self, vessel, open_sea):
        analysis = RoutingAnalysis("analysis", vessel, make_voyage(), topography=open_sea, verbose=False)

        assert [analysis.atmosphere.name, analysis.wave.name, analysis.current.name] == [
            "calm_atmosphere", "calm_wave", "calm_current",
        ]

    def test_the_topography_is_required(self, vessel, atmosphere):
        with pytest.raises(TypeError, match="needs a topography"):
            RoutingAnalysis("analysis", vessel, make_voyage(), atmosphere, verbose=False)

    def test_a_missing_source_reads_as_zero_fields(self, atmosphere, current, open_sea):
        from .conftest import uniform_forecast

        vessel = consumption_vessel("bhp", hotel_load=HOTEL_LOAD, sfoc=SFC, max_power=None)
        zero_wave = uniform_forecast("wave", swh=0.0, uw=0.0, vw=0.0)

        given = evaluate_baseline(vessel, atmosphere, zero_wave, current, open_sea)
        missing = evaluate_baseline(vessel, atmosphere, None, current, open_sea)

        assert missing["fuel"] == pytest.approx(given["fuel"], rel=1e-12)
        assert np.ravel(missing["swh"]) == pytest.approx(0.0)
        # The time grid still comes from the atmosphere
        assert np.ravel(missing["ctim"]) == pytest.approx(np.ravel(given["ctim"]))

    def test_without_any_forecast_the_time_grid_is_regular(self, open_sea):
        from architeuthis.core import DEFAULT_TIME_STEP

        vessel = consumption_vessel("hourly_consumption")
        report = evaluate_baseline(vessel, None, None, None, open_sea)

        ctim = np.ravel(report["ctim"])
        assert np.diff(ctim) == pytest.approx(DEFAULT_TIME_STEP)
        assert ctim[0] == pytest.approx(DEFAULT_TIME_STEP)
        assert ctim[-1] < ETA
        for key in ("tws", "swh", "cs"):
            assert np.ravel(report[key]) == pytest.approx(0.0)
        assert np.ravel(report["sog"]) == pytest.approx(np.ravel(report["stw"]))
        assert report["model"] == "calm_atmosphere"

    @pytest.mark.integration
    def test_a_polar_table_can_be_optimized_without_environment(self, vessel, island):
        # Calm wind and flat sea: their directions have no derivative to take.
        analysis = RoutingAnalysis(
            "analysis", vessel, make_voyage(), topography=island, variables=["max_bhp"], verbose=False,
        )

        baseline = analysis.run(solve=False, solver_options=MUMPS)
        optimized = analysis.run(max_iter=500, solver_options=MUMPS)

        assert optimized["status"] == 1
        assert np.max(optimized["z"]) < 1e-2
        assert np.max(baseline["z"]) > 0.0
        assert analysis.passage_plan.metadata["atmosphere"]["name"] == "calm_atmosphere"

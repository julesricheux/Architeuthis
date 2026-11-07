"""End-to-end routing on synthetic fields. The icebergs module is stubbed in tests/conftest.py."""

import numpy as np
import pytest

from architeuthis.common import GUST_DEFAULT_RATIO
from architeuthis.core import Leg, RoutingAnalysis, Schedule, Voyage, exclusion_zones
from architeuthis.toolbox.geo_utils import distances, poly_deviated_route

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


def test_exclusion_zones_are_lat_lon_polygons():
    assert len(exclusion_zones) == 3
    assert all(np.asarray(zone).ndim == 2 and np.asarray(zone).shape[1] == 2 for zone in exclusion_zones)


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
        power = np.ravel(report["avg_bhp"]) + HOTEL_LOAD
        duration_h = np.diff(np.ravel(report["tim"])) / HOUR

        assert report["fuel"] == pytest.approx(np.sum(power * duration_h * SFC) / 1e6)

    def test_weather_is_converted_to_knots_and_degrees(self, report):
        knots_per_mps = 3600.0 / 1852.0

        assert report["tws"] == pytest.approx(np.hypot(5.0, 2.0) * knots_per_mps)
        assert report["twd"] == pytest.approx(np.degrees(np.arctan2(5.0, 2.0)) + 180.0)
        assert report["cs"] == pytest.approx(0.1 * knots_per_mps)
        assert report["cd"] == pytest.approx(90.0)
        assert report["swh"] == pytest.approx(1.5)

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

        report = route(open_sea, constraints=limit_power)

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
        for key in ("lat", "lon", "tim", "ctim", "avg_bhp", "z", "sog", "tws_gust"):
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
        heavier = Vessel("heavier", filepath="unused.nc", sfc=SFC, hotel_load=HOTEL_LOAD, verbose=False)
        heavier.data = polar.copy()
        for key in ("bhp", "max_bhp", "sails_contribution"):
            heavier.data[key] = heavier.data[key] * 2.0
            heavier.add_interpolator(key, "stw", "tws", "twa", "hs", "wa")

        evaluation = analyse(island, vessel=heavier).evaluate(analysis.passage_plan)

        assert np.ravel(evaluation["lat"]) == pytest.approx(np.ravel(report["lat"]))
        assert np.ravel(evaluation["avg_bhp"]) == pytest.approx(2.0 * np.ravel(report["avg_bhp"]), rel=1e-6)
        assert evaluation["fuel"] > report["fuel"]

    def test_constraint_violations_are_reported(self, route, analyse, open_sea, island):
        straight = analyse(open_sea)
        straight.run(solve=False, solver_options=MUMPS)

        evaluation = analyse(island).evaluate(straight.passage_plan)

        # The default constraints are max_bhp < max_power and z < 0.
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

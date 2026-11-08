"""Routes, schedules, voyages and passage plans: geometry and storage, no optimization."""

import datetime

import numpy as np
import pandas as pd
import pytest

from architeuthis.route import (
    ROUTE_SET_DIRECTORY,
    Leg,
    Route,
    RouteLibrary,
    RouteSet,
    RouteSetLibrary,
    Waypoint,
    safe_file_name,
)
from architeuthis.toolbox.geo_utils import distances, poly_deviated_route
from architeuthis.voyage import PassagePlan, PassagePlanLibrary, Schedule, Voyage

HOUR = 3600.0

MONTOIR = Waypoint(47.112, -2.405, "FRMTX")
PENMARCH = Waypoint(47.673, -4.896, "Penmarch")
CAPE_RACE = Waypoint(46.560, -53.033, "Cape Race")
SAINT_PIERRE = Waypoint(46.781, -56.091, "PMFSP")


@pytest.fixture
def crossing():
    return Route(
        "FRMTX-PMFSP",
        [MONTOIR, PENMARCH, CAPE_RACE, SAINT_PIERRE],
        divergences=[0.0, -0.5, 0.0],
        spread=[0.0, 0.4, 0.0],
        verbose=False,
    )


def path_distance_nm(points):
    return np.sum(distances(points[:, 0], points[:, 1]))


# ------------------------------------------------------------------------------
# Waypoint
# ------------------------------------------------------------------------------


def test_waypoint_behaves_like_a_lat_lon_pair():
    lat, lon = MONTOIR

    assert (lat, lon) == (47.112, -2.405)
    assert MONTOIR[0] == 47.112
    assert np.asarray(MONTOIR).tolist() == [47.112, -2.405]


@pytest.mark.parametrize("value", [[47.0, -3.0], np.array([47.0, -3.0]), {"lat": 47.0, "lon": -3.0}])
def test_waypoint_accepts_pairs_and_dicts(value):
    assert Waypoint.coerce(value) == Waypoint(47.0, -3.0)


def test_waypoint_refuses_an_invalid_latitude():
    with pytest.raises(ValueError):
        Waypoint(95.0, 0.0)


# ------------------------------------------------------------------------------
# Route geometry
# ------------------------------------------------------------------------------


def test_route_has_one_leg_per_segment(crossing):
    legs = crossing.legs

    assert [leg.name for leg in legs] == ["FRMTX-Penmarch", "Penmarch-Cape Race", "Cape Race-PMFSP"]
    assert crossing.distance == pytest.approx(sum(leg.distance for leg in legs))
    assert isinstance(legs[0], Leg)


def test_route_end_points(crossing):
    assert crossing.departure.tolist() == [MONTOIR.lat, MONTOIR.lon]
    assert crossing.arrival.tolist() == [SAINT_PIERRE.lat, SAINT_PIERRE.lon]


def test_route_path_passes_through_the_waypoints(crossing):
    lat, lon = crossing.ortho(np.array([0.0, 1.0]))

    assert [lat[0], lon[0]] == pytest.approx(list(MONTOIR))
    assert [lat[1], lon[1]] == pytest.approx(list(SAINT_PIERRE))


def test_a_divergence_lengthens_the_path(crossing):
    straight = crossing.sample(500, divergences=np.zeros(3))
    curved = crossing.sample(500)

    assert path_distance_nm(curved) > path_distance_nm(straight)


def test_spread_builds_the_minus_and_plus_routes(crossing):
    s = np.linspace(0.3, 0.7, 5)

    assert np.allclose(crossing.minus(s), crossing.path([0.0, -0.9, 0.0])(s))
    assert np.allclose(crossing.plus(s), crossing.path([0.0, -0.1, 0.0])(s))


def test_scalar_spread_applies_to_every_segment():
    route = Route("route", [MONTOIR, PENMARCH, CAPE_RACE], spread=0.2, verbose=False)

    assert route.spread.tolist() == [0.2, 0.2]


def test_route_checks_the_number_of_divergences():
    with pytest.raises(ValueError, match="one per segment"):
        Route("route", [MONTOIR, PENMARCH, CAPE_RACE], divergences=[0.1], verbose=False)


@pytest.mark.parametrize("waypoints", [[MONTOIR], [MONTOIR, MONTOIR]])
def test_route_refuses_degenerate_waypoints(waypoints):
    with pytest.raises(ValueError):
        Route("route", waypoints, verbose=False)


# ------------------------------------------------------------------------------
# Reversal
# ------------------------------------------------------------------------------


def test_reversed_route_swaps_the_name_and_waypoints(crossing):
    reverse = crossing.reversed()

    assert reverse.name == "PMFSP-FRMTX"
    assert [waypoint.name for waypoint in reverse.waypoints] == ["PMFSP", "Cape Race", "Penmarch", "FRMTX"]
    assert reverse.distance == pytest.approx(crossing.distance)


def test_reversed_route_follows_the_same_path(crossing):
    s = np.linspace(0.0, 1.0, 301)
    forward = crossing.sample(301)
    backward = crossing.reversed().sample(301)[::-1]

    # Same curve sailed backwards: the abscissas match because segment lengths do.
    assert np.allclose(forward, backward, atol=1e-6)
    # Divergence and spread signs are relative to the travel direction, so sides swap.
    assert np.allclose(crossing.reversed().plus(1 - s), crossing.minus(s), atol=1e-6)


def test_reversing_twice_gives_back_the_route(crossing):
    twice = crossing.reversed().reversed()

    assert twice.name == crossing.name
    assert twice.waypoints == crossing.waypoints
    assert twice.divergences.tolist() == crossing.divergences.tolist()


# ------------------------------------------------------------------------------
# Restarting from a position at sea
# ------------------------------------------------------------------------------


def test_from_position_keeps_the_remaining_waypoints(crossing):
    at_sea = crossing.sample(101)[40]

    rest = crossing.from_position(at_sea)

    assert [waypoint.name for waypoint in rest.waypoints] == ["position", "Cape Race", "PMFSP"]
    assert rest.departure == pytest.approx(at_sea)
    assert rest.arrival == pytest.approx(crossing.arrival)
    assert rest.divergences.tolist() == [0.0, 0.0]
    assert rest.spread.tolist() == [0.4, 0.0]
    assert rest.distance < crossing.distance


def test_from_position_skips_a_waypoint_already_reached(crossing):
    near_penmarch = [PENMARCH.lat + 0.01, PENMARCH.lon - 0.01]

    rest = crossing.from_position(near_penmarch, tolerance=5.0)

    assert [waypoint.name for waypoint in rest.waypoints] == ["position", "Cape Race", "PMFSP"]


def test_from_position_never_skips_the_arrival(crossing):
    rest = crossing.from_position([SAINT_PIERRE.lat, SAINT_PIERRE.lon + 0.05])

    assert [waypoint.name for waypoint in rest.waypoints] == ["position", "PMFSP"]


def test_from_position_accepts_an_explicit_next_waypoint(crossing):
    rest = crossing.from_position([47.5, -4.0], next_waypoint="Cape Race")

    assert [waypoint.name for waypoint in rest.waypoints] == ["position", "Cape Race", "PMFSP"]
    assert crossing.from_position([47.5, -4.0], next_waypoint=1).waypoints[1] == PENMARCH


def test_from_position_warns_when_far_from_the_route(crossing, capsys):
    crossing.from_position([30.0, -30.0])

    assert "away from route" in capsys.readouterr().out


# ------------------------------------------------------------------------------
# Storage
# ------------------------------------------------------------------------------


def test_route_survives_a_json_round_trip(crossing, tmp_path):
    path = crossing.save(str(tmp_path / "crossing.json"))
    loaded = Route.load(path, verbose=False)

    assert loaded.name == crossing.name
    assert loaded.waypoints == crossing.waypoints
    assert loaded.divergences.tolist() == crossing.divergences.tolist()
    assert loaded.spread.tolist() == crossing.spread.tolist()


def test_route_library_stores_routes_by_name(crossing, tmp_path):
    library = RouteLibrary(str(tmp_path), verbose=False)
    library.save(crossing)
    library.save(crossing.reversed())

    assert sorted(library.names()) == ["FRMTX-PMFSP", "PMFSP-FRMTX"]
    assert "PMFSP-FRMTX" in library
    assert library.load("PMFSP-FRMTX").waypoints[0] == SAINT_PIERRE
    assert len(library) == 2


def test_route_library_does_not_overwrite_silently(crossing, tmp_path):
    library = RouteLibrary(str(tmp_path), verbose=False)
    library.save(crossing)

    with pytest.raises(FileExistsError):
        library.save(crossing)
    library.save(crossing, overwrite=True)


def test_route_library_reports_missing_routes_and_removes(crossing, tmp_path):
    library = RouteLibrary(str(tmp_path), verbose=False)
    library.save(crossing)
    library.remove("FRMTX-PMFSP")

    with pytest.raises(KeyError):
        library.load("FRMTX-PMFSP")


def test_route_library_defaults_to_the_data_folder():
    assert RouteLibrary().directory.endswith("route_library")


def test_file_names_are_sanitized():
    assert safe_file_name("FRMTX - PMFSP / via Cape Race") == "FRMTX_-_PMFSP_via_Cape_Race"


# ------------------------------------------------------------------------------
# Schedule and voyage
# ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "etd",
    [
        1767268800.0,
        "2026-01-01T12:00",
        pd.Timestamp("2026-01-01 12:00"),
        datetime.datetime(2026, 1, 1, 12),
        datetime.datetime(2026, 1, 1, 13, tzinfo=datetime.timezone(datetime.timedelta(hours=1))),
        np.datetime64("2026-01-01T12:00"),
    ],
)
def test_schedule_converts_dates_to_epoch_seconds(etd):
    schedule = Schedule("schedule", etd=etd, eta="2026-01-02T12:00", verbose=False)

    assert schedule.etd == 1767268800.0
    assert schedule.transit_time == 24 * HOUR


def test_schedule_refuses_an_arrival_before_departure():
    with pytest.raises(ValueError):
        Schedule("schedule", etd=10.0, eta=5.0, verbose=False)


def test_voyage_on_a_route_uses_its_distance_and_paths(crossing):
    voyage = Voyage("voyage", etd=0.0, eta=240 * HOUR, route=crossing, verbose=False)
    s = np.linspace(0.0, 1.0, 11)

    assert voyage.distance == pytest.approx(crossing.distance)
    assert voyage.transit_sog == pytest.approx(crossing.distance / 240.0)
    assert np.allclose(voyage.route_plus(s), crossing.plus(s))
    assert voyage.departure == pytest.approx(crossing.departure)


def test_voyage_refuses_end_points_that_contradict_the_route(crossing):
    with pytest.raises(ValueError, match="departure"):
        Voyage("voyage", etd=0.0, eta=HOUR, departure=[0.0, 0.0], route=crossing, verbose=False)


def test_voyage_needs_a_route_or_end_points():
    with pytest.raises(ValueError):
        Voyage("voyage", etd=0.0, eta=HOUR, verbose=False)


def test_voyage_accepts_routes_as_references(crossing):
    alternative = Route("south", [MONTOIR, CAPE_RACE, SAINT_PIERRE], verbose=False)
    voyage = Voyage("voyage", etd=0.0, eta=HOUR, route=crossing, route_minus=alternative, verbose=False)
    s = np.linspace(0.0, 1.0, 11)

    assert np.allclose(voyage.route_minus(s), alternative.ortho(s))


def test_voyage_from_position_keeps_the_arrival_time(crossing):
    voyage = Voyage("voyage", etd="2026-02-05T12:00", eta="2026-02-17T06:00", route=crossing, verbose=False)

    rest = voyage.from_position([47.0, -20.0], time="2026-02-09T10:00")

    assert rest.etd == pd.Timestamp("2026-02-09T10:00", tz="UTC").timestamp()
    assert rest.eta == voyage.eta
    assert rest.departure.tolist() == [47.0, -20.0]
    assert rest.route.waypoints[1:] == crossing.waypoints[2:]


def test_voyage_from_position_restarts_route_references(crossing, capsys):
    alternative = Route("south", [MONTOIR, CAPE_RACE, SAINT_PIERRE], verbose=False)
    voyage = Voyage(
        "voyage",
        etd=0.0,
        eta=240 * HOUR,
        route=crossing,
        route_minus=alternative,
        route_plus=lambda s: crossing.plus(s),
        verbose=False,
    )

    rest = voyage.from_position([47.0, -20.0], time=48 * HOUR)

    assert rest._references["minus"].departure.tolist() == [47.0, -20.0]
    assert "route_plus is a function" in capsys.readouterr().out


# ------------------------------------------------------------------------------
# Passage plans
# ------------------------------------------------------------------------------


@pytest.fixture
def plan(crossing):
    tim = np.linspace(0.0, 240 * HOUR, 6)
    points = crossing.sample(6)
    return PassagePlan(
        "plan",
        route=crossing,
        schedule=Schedule("schedule", 0.0, 240 * HOUR, verbose=False),
        tim=tim,
        lat=points[:, 0],
        lon=points[:, 1],
        metadata={"vessel": {"name": "ship"}, "fuel": np.float64(12.5)},
        verbose=False,
    )


def test_plan_samples_weather_at_segment_midpoints_by_default(plan):
    assert plan.ctim.tolist() == pytest.approx((np.arange(5) + 0.5) * 48 * HOUR)


def test_plan_interpolates_its_position_in_time(plan):
    assert plan.at(0.0) == pytest.approx(plan.positions[0])
    assert plan.at(24 * HOUR) == pytest.approx((plan.positions[0] + plan.positions[1]) / 2)


def test_plan_checks_its_arrays(crossing):
    schedule = Schedule("schedule", 0.0, HOUR, verbose=False)

    with pytest.raises(ValueError):
        PassagePlan("plan", crossing, schedule, tim=[0.0, HOUR], lat=[47.0], lon=[-3.0, -4.0])
    with pytest.raises(ValueError):
        PassagePlan("plan", crossing, schedule, tim=[HOUR, 0.0], lat=[47.0, 46.0], lon=[-3.0, -4.0])


def test_plan_survives_a_json_round_trip(plan, tmp_path):
    loaded = PassagePlan.load(plan.save(str(tmp_path / "plan.json")), verbose=False)

    assert loaded.tim.tolist() == plan.tim.tolist()
    assert loaded.lat.tolist() == plan.lat.tolist()
    assert loaded.ctim.tolist() == plan.ctim.tolist()
    assert loaded.route.waypoints == plan.route.waypoints
    assert loaded.etd == plan.etd and loaded.eta == plan.eta
    assert loaded.metadata == {"vessel": {"name": "ship"}, "fuel": 12.5}


def test_plan_library(plan, tmp_path):
    library = PassagePlanLibrary(str(tmp_path), verbose=False)
    library.save(plan)

    assert library.names() == ["plan"]
    assert library.load("plan").lon.tolist() == plan.lon.tolist()


def test_plan_converts_to_a_route_through_its_nodes(plan):
    route = plan.to_route()

    assert len(route.waypoints) == 6
    assert route.waypoints[0].name == "FRMTX"
    assert route.waypoints[-1].name == "PMFSP"


def test_plan_gives_back_its_voyage(plan, crossing):
    voyage = plan.voyage()

    assert voyage.route is crossing
    assert (voyage.etd, voyage.eta) == (0.0, 240 * HOUR)


def test_plan_from_a_report(crossing):
    report = {
        "etd": 0.0,
        "eta": 2 * HOUR,
        "tim": np.array([0.0, HOUR, 2 * HOUR]),
        "ctim": np.array([0.5 * HOUR, 1.5 * HOUR]),
        "lat": np.array([47.1, 47.0, 46.9]),
        "lon": np.array([-2.4, -3.0, -3.5]),
        "fuel": np.float64(1.5),
        "status": 1,
    }

    plan = PassagePlan.from_report(report, route=crossing, name="plan", metadata={"model": "ifs"}, verbose=False)

    assert plan.lat.tolist() == [47.1, 47.0, 46.9]
    assert plan.metadata == {"fuel": 1.5, "status": 1, "model": "ifs"}


def test_a_route_is_called_like_a_path_function(crossing):
    s = np.linspace(0.0, 1.0, 11)

    assert np.array_equal(crossing(s), crossing.ortho(s))
    assert np.array_equal(
        crossing(s),
        poly_deviated_route(list(crossing.lats), list(crossing.lons), [0.0, -0.5, 0.0])(s),
    )


# ------------------------------------------------------------------------------
# Route sets
# ------------------------------------------------------------------------------


@pytest.fixture
def route_set(crossing):
    north = Route(
        "north",
        [MONTOIR, Waypoint(49.0, -30.0, "North"), SAINT_PIERRE],
        verbose=False,
    )
    south = Route(
        "south",
        [MONTOIR, Waypoint(44.0, -30.0, "South"), SAINT_PIERRE],
        verbose=False,
    )
    return RouteSet("crossing", ortho=crossing, minus=north, plus=south, verbose=False)


def test_route_set_defaults_its_sides_to_the_ortho_route(crossing):
    routes = RouteSet("crossing", ortho=crossing, verbose=False)

    assert routes.minus is crossing
    assert routes.plus is crossing
    assert routes.routes == {"minus": crossing, "ortho": crossing, "plus": crossing}


def test_reversed_route_set_swaps_the_sides(route_set):
    back = route_set.reversed()

    assert back.name == "crossing_reversed"
    assert list(back.ortho.departure) == list(route_set.ortho.arrival)
    assert [waypoint.name for waypoint in back.minus.waypoints] == ["PMFSP", "South", "FRMTX"]
    assert [waypoint.name for waypoint in back.plus.waypoints] == ["PMFSP", "North", "FRMTX"]
    assert route_set.reversed("back").name == "back"


def test_restarted_route_set_starts_at_the_position(route_set):
    position = [46.5, -30.0]

    restart = route_set.from_position(position)

    assert restart.name == "crossing_restart"
    for route in restart.routes.values():
        assert list(route.departure) == pytest.approx(position)
        assert list(route.arrival) == pytest.approx(list(SAINT_PIERRE))


def test_route_set_survives_a_json_round_trip(route_set, tmp_path):
    loaded = RouteSet.load(route_set.save(str(tmp_path / "routes.json")), verbose=False)

    assert loaded.name == route_set.name
    for key, route in route_set.routes.items():
        assert loaded.routes[key].to_dict() == route.to_dict()


def test_route_set_library_stores_sets_by_name(route_set, tmp_path):
    library = RouteSetLibrary(str(tmp_path), verbose=False)

    library.save(route_set)

    assert library.names() == ["crossing"]
    assert library.load("crossing").plus.to_dict() == route_set.plus.to_dict()
    with pytest.raises(FileExistsError):
        library.save(route_set)


def test_route_set_library_defaults_to_the_data_folder():
    assert RouteSetLibrary().directory == ROUTE_SET_DIRECTORY
    assert ROUTE_SET_DIRECTORY.endswith("route_sets")


def test_voyage_from_routes_uses_the_three_routes(route_set):
    voyage = Voyage.from_routes(route_set, etd=0.0, eta=240.0 * HOUR, verbose=False)
    direct = Voyage(
        name="crossing",
        route=route_set.ortho,
        route_minus=route_set.minus,
        route_ortho=route_set.ortho,
        route_plus=route_set.plus,
        etd=0.0,
        eta=240.0 * HOUR,
        verbose=False,
    )

    assert voyage.name == "crossing"
    assert voyage.route is route_set.ortho
    assert list(voyage.departure) == pytest.approx(list(direct.departure))
    abscissa = np.linspace(0.0, 1.0, 20)
    for reference in ("route_minus", "route_ortho", "route_plus"):
        np.testing.assert_allclose(getattr(voyage, reference)(abscissa), getattr(direct, reference)(abscissa))


def test_voyage_from_routes_can_be_named(route_set):
    assert Voyage.from_routes(route_set, etd=0.0, eta=240.0 * HOUR, name="other", verbose=False).name == "other"


def test_voyage_from_routes_can_restart_at_sea(route_set):
    position = [46.5, -30.0]
    voyage = Voyage.from_routes(route_set, etd=0.0, eta=240.0 * HOUR, verbose=False)

    restart = voyage.from_position(position, 10.0 * HOUR)

    assert list(restart.departure) == pytest.approx(position)
    np.testing.assert_allclose(restart.route_minus(0.0), position, atol=1e-6)
    np.testing.assert_allclose(restart.route_plus(1.0), list(SAINT_PIERRE), atol=1e-6)

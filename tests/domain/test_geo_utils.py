import casadi as ca
import numpy as np
import pytest

from architeuthis.toolbox.geo_utils import (
    distances,
    great_circle_route,
    headings,
    lonlat_to_web_mercator,
    midpoints,
    poly_deviated_route,
    resample_coordinates,
)

NAUTICAL_MILES_PER_DEGREE = 3440.065 * np.pi / 180.0


def evaluate_symbolically(function, lats, lons):
    """Run a geographic function on CasADi symbols, as the routing problem does."""
    lat = ca.MX.sym("lat", len(lats))
    lon = ca.MX.sym("lon", len(lons))
    outputs = function(lat, lon)
    if not isinstance(outputs, tuple):
        outputs = (outputs,)
    evaluated = ca.Function("f", [lat, lon], list(outputs))(lats, lons)
    if isinstance(evaluated, tuple):
        return tuple(np.asarray(value).ravel() for value in evaluated)
    return np.asarray(evaluated).ravel()


def test_distances_along_meridian_and_equator():
    lats = np.array([0.0, 1.0, 1.0])
    lons = np.array([0.0, 0.0, 1.0])

    result = distances(lats, lons)

    assert result[0] == pytest.approx(NAUTICAL_MILES_PER_DEGREE)
    assert result[1] == pytest.approx(NAUTICAL_MILES_PER_DEGREE * np.cos(np.radians(1.0)), rel=1e-3)


@pytest.mark.parametrize(
    "lats, lons, expected",
    [
        ([0.0, 1.0], [0.0, 0.0], 0.0),
        ([0.0, 0.0], [0.0, 1.0], 90.0),
        ([1.0, 0.0], [0.0, 0.0], 180.0),
        ([0.0, 0.0], [1.0, 0.0], 270.0),
    ],
)
def test_headings_cardinal_points(lats, lons, expected):
    assert headings(np.array(lats), np.array(lons))[0] == pytest.approx(expected)


def test_headings_account_for_meridian_convergence():
    assert headings(np.array([60.0, 61.0]), np.array([0.0, 1.0]))[0] == pytest.approx(
        np.degrees(np.arctan2(np.cos(np.radians(60.0)), 1.0))
    )


@pytest.mark.parametrize("function", [distances, headings])
def test_symbolic_and_numeric_evaluations_agree(function):
    lats = np.array([46.0, 47.5, 49.0])
    lons = np.array([-50.0, -40.0, -30.0])

    assert evaluate_symbolically(function, lats, lons) == pytest.approx(function(lats, lons))


def test_midpoints():
    assert midpoints(np.array([0.0, 2.0, 6.0])) == pytest.approx([1.0, 4.0])


def test_resample_coordinates_adds_nodes_between_points():
    lats = np.array([0.0, 4.0, 8.0])
    lons = np.array([10.0, 14.0, 18.0])

    lat, lon = evaluate_symbolically(lambda a, b: resample_coordinates(a, b, n=3), lats, lons)

    assert lat == pytest.approx(np.arange(0.0, 9.0))
    assert lon == pytest.approx(np.arange(10.0, 19.0))


def test_resample_coordinates_without_points_returns_the_input():
    lats, lons = np.array([0.0, 1.0]), np.array([2.0, 3.0])

    lat, lon = resample_coordinates(lats, lons, n=0)

    assert lat is lats
    assert lon is lons


def test_great_circle_route_includes_ends_on_request():
    p1, p2 = (45.0, -50.0), (50.0, -20.0)

    lats, lons, distance = great_circle_route(p1, p2, nPoints=10)
    inner_lats, _, _ = great_circle_route(p1, p2, nPoints=10, include_ends=False)

    assert (lats[0], lons[0]) == p1
    assert (lats[-1], lons[-1]) == p2
    assert lats.size == 10
    assert inner_lats.size == 8
    assert distance == pytest.approx(distances(np.array([45.0, 50.0]), np.array([-50.0, -20.0]))[0], rel=5e-3)


def test_great_circle_bulges_poleward():
    lats, _, _ = great_circle_route((50.0, -50.0), (50.0, -10.0), nPoints=11)

    assert lats[5] > 50.0


def test_poly_deviated_route_hits_all_waypoints():
    route = poly_deviated_route([45.0, 48.0, 50.0], [-50.0, -30.0, -10.0], [0.0, 0.0])

    lat, lon = route(np.array([0.0, 1.0]))

    assert lat == pytest.approx([45.0, 50.0])
    assert lon == pytest.approx([-50.0, -10.0])


def test_poly_deviated_route_defaults_to_no_divergence():
    route = poly_deviated_route([45.0, 50.0], [-50.0, -10.0])
    explicit = poly_deviated_route([45.0, 50.0], [-50.0, -10.0], [0.0])
    curvilinear_abscissa = np.linspace(0.0, 1.0, 7)

    assert route(curvilinear_abscissa)[0] == pytest.approx(explicit(curvilinear_abscissa)[0])


def test_divergence_sign_moves_the_route_to_opposite_sides():
    lats, lons = [45.0, 45.0], [-50.0, -10.0]
    middle = np.array([0.5])

    reference = poly_deviated_route(lats, lons, [0.0])(middle)[0][0]
    plus = poly_deviated_route(lats, lons, [0.5])(middle)[0][0]
    minus = poly_deviated_route(lats, lons, [-0.5])(middle)[0][0]

    assert (plus - reference) * (minus - reference) < 0.0


def test_divergence_keeps_the_end_points():
    route = poly_deviated_route([45.0, 50.0], [-50.0, -10.0], [0.5])

    lat, lon = route(np.array([0.0, 1.0]))

    assert lat == pytest.approx([45.0, 50.0])
    assert lon == pytest.approx([-50.0, -10.0])


def test_web_mercator_origin_and_scale():
    x, y = lonlat_to_web_mercator(np.array(180.0), np.array(0.0))

    assert x == pytest.approx(np.pi * 6378137.0)
    assert y == pytest.approx(0.0, abs=1e-6)

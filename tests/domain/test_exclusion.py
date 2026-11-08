"""Exclusion zones: the objects, their storage, the routing and the layers of the UI."""

import json
import os
import sys

import numpy as np
import pytest
import xarray as xr

import architeuthis.core as core
from architeuthis.exclusion import (
    BRITTANY_POLYGON,
    DEFAULT_ZONE_COLOR,
    NORTH_AMERICA_POLYGON,
    ExclusionZone,
    ExclusionZoneLibrary,
    brittany_zone,
    default_exclusion_zones,
    iceberg_zone,
    merge_exclusion_zones,
    north_america_zone,
)
from architeuthis.forecast import Topography
from architeuthis.icebergs import berg_zone
from architeuthis.wrappers.leaflet_wrapper import exclusion_zone_overlay, exclusion_zone_overlays

SQUARE = [[0.5, 0.5], [0.5, 2.5], [3.5, 2.5], [3.5, 0.5], [0.5, 0.5]]


@pytest.fixture
def zone():
    return ExclusionZone(
        "safety",
        SQUARE,
        label="Safety margin",
        color="#00ff00",
        outline=SQUARE[:3],
        visible=False,
        description="Added by the master",
        verbose=False,
    )


# ------------------------------------------------------------------------------
# The zone
# ------------------------------------------------------------------------------


def test_defaults():
    zone = ExclusionZone("safety", SQUARE)

    assert zone.label == "safety"
    assert zone.color == DEFAULT_ZONE_COLOR
    assert zone.outline == SQUARE
    assert zone.visible is True
    assert zone.description == ""


def test_zone_reads_like_its_list_of_points(zone):
    assert len(zone) == 5
    assert zone[0] == SQUARE[0]
    assert zone[:2] == SQUARE[:2]
    assert list(zone) == SQUARE
    np.testing.assert_array_equal(np.asarray(zone), np.asarray(SQUARE))


def test_points_can_be_any_sequence():
    assert ExclusionZone("zone", np.array(SQUARE)).polygon == SQUARE
    assert ExclusionZone("zone", tuple(map(tuple, SQUARE))).polygon == SQUARE


@pytest.mark.parametrize("points", [[1.0, 2.0, 3.0], [[1.0, 2.0, 3.0]], [[[1.0, 2.0]]]])
def test_invalid_points_are_refused(points):
    with pytest.raises(ValueError, match=r"\[lat, lon\]"):
        ExclusionZone("zone", points)


def test_outline_is_only_what_is_drawn(zone):
    assert zone.outline == SQUARE[:3]
    assert zone.polygon == SQUARE


@pytest.mark.parametrize("points", [[], SQUARE[:2]])
def test_too_few_points_make_an_empty_zone(points):
    empty = ExclusionZone("zone", points)

    assert empty.is_empty
    assert not empty.contains([1.0], [1.0]).any()


def test_contains_uses_lat_lon_order():
    # A wide box: latitudes from 0 to 1, longitudes from 0 to 10.
    box = ExclusionZone("box", [[0.0, 0.0], [0.0, 10.0], [1.0, 10.0], [1.0, 0.0]])

    assert box.contains([0.5, 5.0], [5.0, 0.5]).tolist() == [True, False]


# ------------------------------------------------------------------------------
# Storage
# ------------------------------------------------------------------------------


def assert_same_zone(first, second):
    assert first.to_dict() == second.to_dict()


def test_zone_survives_a_json_round_trip(zone, tmp_path):
    path = zone.save(str(tmp_path / "zone.json"))

    assert_same_zone(zone, ExclusionZone.load(path))


def test_zone_without_outline_keeps_following_its_polygon(tmp_path):
    zone = ExclusionZone("zone", SQUARE)

    assert ExclusionZone.load(zone.save(str(tmp_path / "zone.json")))._outline is None


def test_minimal_file_is_accepted(tmp_path):
    path = tmp_path / "zone.json"
    path.write_text(json.dumps({"name": "zone", "polygon": SQUARE}))

    zone = ExclusionZone.load(str(path))

    assert zone.label == "zone"
    assert zone.visible is True


def test_library_stores_zones_by_name(zone, tmp_path):
    library = ExclusionZoneLibrary(str(tmp_path), verbose=False)

    assert len(library) == 0
    library.save(zone)

    assert "safety" in library
    assert library.names() == ["safety"]
    assert_same_zone(zone, library.load("safety"))
    assert [item.name for item in library] == ["safety"]


def test_library_does_not_overwrite_silently(zone, tmp_path):
    library = ExclusionZoneLibrary(str(tmp_path), verbose=False)
    library.save(zone)

    with pytest.raises(FileExistsError):
        library.save(zone)

    library.save(ExclusionZone("safety", SQUARE[:4], verbose=False), overwrite=True)
    assert len(library.load("safety")) == 4


def test_library_defaults_to_the_data_folder():
    from architeuthis.common import _HOME

    assert ExclusionZoneLibrary().directory == os.path.join(_HOME, "exclusion_zones")


def test_zone_from_geojson(tmp_path):
    ring = [[lon, lat] for lat, lon in SQUARE]
    path = tmp_path / "zones.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": "a",
                        "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                    },
                ],
            }
        )
    )

    zone = ExclusionZone.from_geojson(str(path), "a", name="zone", label="Zone")

    assert zone.name == "zone"
    assert zone.label == "Zone"
    assert zone.polygon == SQUARE


def test_missing_geojson_feature_is_reported(tmp_path):
    path = tmp_path / "zones.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": []}))

    with pytest.raises(KeyError, match="missing"):
        ExclusionZone.from_geojson(str(path), "missing")


# ------------------------------------------------------------------------------
# Zones used by default
# ------------------------------------------------------------------------------


def test_default_zones_are_in_the_former_order():
    zones = default_exclusion_zones(verbose=False)

    assert [zone.name for zone in zones] == ["north_america", "brittany", "iceberg_limit"]
    assert [zone.label for zone in zones] == ["North America", "Brittany", "Iceberg limit"]


def test_default_polygons_are_unchanged():
    assert north_america_zone().polygon == NORTH_AMERICA_POLYGON
    assert brittany_zone().polygon == BRITTANY_POLYGON
    assert len(NORTH_AMERICA_POLYGON) == 60
    assert len(BRITTANY_POLYGON) == 23
    assert NORTH_AMERICA_POLYGON[0] == [46.6475507, -53.0879974]
    assert BRITTANY_POLYGON[0] == [47.234906794905456, -2.298894594711654]


def test_iceberg_zone_comes_from_the_bulletin():
    zone = iceberg_zone(verbose=False)

    assert zone.polygon == berg_zone
    assert zone.label == "Iceberg limit"
    assert zone.outline == berg_zone[:-3]


def test_scripts_keep_reading_the_zones_from_core():
    zones = core.exclusion_zones

    assert len(zones) == 3
    # The scripts leave out the iceberg limit with exclusion_zones[:-1].
    assert [zone.name for zone in zones[:-1]] == ["north_america", "brittany"]
    assert core.berg_zone == berg_zone


def test_core_refuses_unknown_attributes():
    with pytest.raises(AttributeError):
        core.not_an_attribute


def test_merge_keeps_the_order_and_lets_a_later_zone_replace_an_earlier_one():
    first = ExclusionZone("a", SQUARE, label="first")
    other = ExclusionZone("b", SQUARE)
    second = ExclusionZone("a", SQUARE, label="second")

    merged = merge_exclusion_zones([first, other], [second])

    assert [zone.name for zone in merged] == ["a", "b"]
    assert merged[0].label == "second"


# ------------------------------------------------------------------------------
# Routing
# ------------------------------------------------------------------------------


def half_land_grid():
    elevation = np.full((5, 10), -100.0)
    elevation[:, 5:] = 50.0
    return xr.Dataset(
        {"z": (("lat", "lon"), elevation)},
        coords={"lat": np.arange(5.0), "lon": np.arange(10.0)},
    )


def distance_field(**kwargs):
    topography = Topography("topography", verbose=False, **kwargs)
    topography.data = half_land_grid()
    topography._convert_data()
    return topography.data["distance_to_iso0"].values


def test_topography_gives_the_same_field_with_a_zone_or_its_points():
    with_zone = distance_field(exclusion_zones=[ExclusionZone("zone", SQUARE)])

    np.testing.assert_array_equal(with_zone, distance_field(exclusion_zones=[SQUARE]))
    assert with_zone[2, 1] > 0.0
    assert with_zone[2, 3] < 0.0


def test_topography_accepts_a_mix_of_zones_and_points():
    mixed = distance_field(exclusion_zones=[ExclusionZone("zone", SQUARE), []])

    np.testing.assert_array_equal(mixed, distance_field(exclusion_zones=[SQUARE]))


def test_topography_skips_an_empty_zone_and_names_it(capsys):
    empty = ExclusionZone("iceberg_limit", [])
    topography = Topography("topography", verbose=True, exclusion_zones=[empty])
    topography.data = half_land_grid()

    topography._convert_data()

    expected = distance_field()
    np.testing.assert_array_equal(topography.data["distance_to_iso0"].values, expected)
    assert "iceberg_limit" in capsys.readouterr().out


def test_hidden_zone_still_applies_to_the_routing():
    hidden = ExclusionZone("zone", SQUARE, visible=False)

    np.testing.assert_array_equal(
        distance_field(exclusion_zones=[hidden]),
        distance_field(exclusion_zones=[SQUARE]),
    )


def test_analysis_describes_the_zones_of_its_topography(vessel, atmosphere, wave, current):
    from architeuthis.core import RoutingAnalysis

    topography = Topography("topography", verbose=False, exclusion_zones=[ExclusionZone("zone", SQUARE), SQUARE])
    analysis = RoutingAnalysis("analysis", vessel, None, atmosphere, wave, current, topography, verbose=False)

    assert analysis.describe()["exclusion_zones"][0] == "zone"
    assert len(analysis.describe()["exclusion_zones"]) == 2


# ------------------------------------------------------------------------------
# Layers of the UI
# ------------------------------------------------------------------------------


def test_overlay_can_be_hidden_under_the_label_of_the_zone(zone):
    overlay = exclusion_zone_overlay(zone)

    assert overlay.name == "Safety margin"
    assert overlay.checked is False


def test_overlay_is_shown_at_first_by_default():
    assert exclusion_zone_overlay(ExclusionZone("zone", SQUARE)).checked is True


def test_label_is_written_on_the_map(zone):
    line = exclusion_zone_overlay(zone).children
    tooltip = line.children

    assert tooltip.children == "Safety margin"
    assert tooltip.permanent is True
    assert tooltip.className == "exclusion-zone-label"


def test_overlay_draws_the_outline_in_the_color_of_the_zone(zone):
    line = exclusion_zone_overlay(zone).children

    assert line.positions == SQUARE[:3]
    assert line.color == "#00ff00"
    assert line.fill is False
    assert line.id == "exclusion-zone-safety"


@pytest.mark.parametrize(
    "zone",
    [
        ExclusionZone("zone", [], label="Iceberg limit"),
        ExclusionZone("zone", SQUARE[:1], label="Iceberg limit"),
    ],
)
def test_zone_without_data_stays_listed_as_unavailable(zone):
    overlay = exclusion_zone_overlay(zone)

    assert overlay.name == "Iceberg limit (unavailable)"
    assert overlay.checked is False


def test_iceberg_limit_without_a_bulletin_is_listed_as_unavailable(monkeypatch):
    monkeypatch.setattr(sys.modules["architeuthis.icebergs"], "berg_zone", [])

    assert exclusion_zone_overlay(iceberg_zone(verbose=False)).name == "Iceberg limit (unavailable)"


def test_one_overlay_per_zone():
    overlays = exclusion_zone_overlays(default_exclusion_zones(verbose=False))

    assert [overlay.name for overlay in overlays] == ["North America", "Brittany", "Iceberg limit"]
    assert all(overlay.checked for overlay in overlays)

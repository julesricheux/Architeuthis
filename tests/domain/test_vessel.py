import numpy as np
import pytest

from architeuthis.vessel import POLAR_KEYS, Vessel

POLAR_DIMS = ("stw", "tws", "twa", "hs", "wa")
POLAR_POWER_COEFFICIENT = 1.2  # as built by the `polar` fixture


def test_numeric_loads_become_callables():
    vessel = Vessel("ship", filepath="polar.nc", hotel_load=100.0, sfc=224)

    assert vessel.hotel_load(1234.0) == 100.0
    assert vessel.sfc(1234.0) == 224


def test_callable_loads_are_kept():
    def sfc(power):
        return 200.0 + power / 100.0

    vessel = Vessel("ship", filepath="polar.nc", sfc=sfc)

    assert vessel.sfc is sfc


def test_max_power_stays_a_raw_value():
    assert Vessel("ship", filepath="polar.nc", max_power=3100.0).max_power == 3100.0


def test_missing_polar_file_is_reported():
    vessel = Vessel("ship", filepath="does_not_exist.nc")

    with pytest.raises(AssertionError, match="does not exist"):
        vessel.load_data()


def test_load_polar_from_netcdf_and_query_it(tmp_path, polar):
    path = tmp_path / "polar.nc"
    polar.to_netcdf(path)
    vessel = Vessel("ship", filepath=str(path))

    vessel.load_data()
    vessel.add_interpolator("bhp", *POLAR_DIMS)
    result = vessel("bhp", np.array([[6.0, 15.0, 60.0, 4.1, 60.0], [8.0, 15.0, 60.0, 1.0, 60.0]]))
    vessel.data.close()

    expected = [POLAR_POWER_COEFFICIENT * 6.0**3, POLAR_POWER_COEFFICIENT * 8.0**3]
    assert np.asarray(result).ravel() == pytest.approx(expected)


def test_interpolator_accepts_a_custom_key_and_slices(polar):
    vessel = Vessel("ship", filepath="polar.nc")
    vessel.data = polar

    vessel.add_interpolator("bhp", *POLAR_DIMS, var_key="power", stw_slice=slice(None, None, 5))

    assert vessel.var_keys == {"power"}
    # stw = 5 stays on the 5-knot subgrid, so the cubic law holds exactly there.
    query = np.array([[5.0, 0.0, 0.0, 0.0, 0.0]])
    assert float(vessel("power", query)) == pytest.approx(POLAR_POWER_COEFFICIENT * 5.0**3)


@pytest.mark.parametrize(
    "path, label",
    [
        ("C:/data/polars/neoliner_origin_v2-2-0_mc0_sc0_35up_28down_7buff_5m_eff45.nc", "eff45"),
        ("polars/ship_eff100.nc", "eff100"),
        ("polars/ship.nc", "ship"),
        ("ship_eff45_old.nc", "ship_eff45_old"),
    ],
)
def test_label_comes_from_the_polar_file(path, label):
    assert Vessel("ship", filepath=path).label == label


def test_label_can_be_given():
    assert Vessel("ship", filepath="polars/ship_eff45.nc", label="hybrid").label == "hybrid"


def test_add_interpolators_adds_what_routing_requires(polar):
    vessel = Vessel("ship", filepath="polar.nc", verbose=False)
    vessel.data = polar

    vessel.add_interpolators()

    assert set(vessel.interpolators) == set(POLAR_KEYS)
    query = np.array([[5.0, 0.0, 0.0, 0.0, 0.0]])
    assert float(vessel("bhp", query)) == pytest.approx(POLAR_POWER_COEFFICIENT * 5.0**3)


def test_add_interpolators_takes_its_variables(polar):
    vessel = Vessel("ship", filepath="polar.nc", verbose=False)
    vessel.data = polar

    vessel.add_interpolators(keys=["bhp"])

    assert set(vessel.interpolators) == {"bhp"}

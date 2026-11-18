import numpy as np
import pytest

from architeuthis.vessel import POLAR_KEYS, Vessel

POLAR_DIMS = ("stw", "tws", "twa", "hs", "wa")
POLAR_POWER_COEFFICIENT = 1.2  # as built by the `polar` fixture


def test_numeric_loads_become_callables():
    vessel = Vessel("ship", filepath="polar.nc", hotel_load=100.0, sfoc=224)

    assert vessel.hotel_load(1234.0) == 100.0
    assert vessel.sfoc(1234.0) == 224


def test_callable_loads_are_kept():
    def sfoc(power):
        return 200.0 + power / 100.0

    vessel = Vessel("ship", filepath="polar.nc", sfoc=sfoc)

    assert vessel.sfoc is sfoc


def test_max_power_stays_a_raw_value():
    assert Vessel("ship", filepath="polar.nc", max_power=3100.0).max_power == 3100.0


def test_no_power_limit_and_no_sfoc_by_default():
    vessel = Vessel("ship", verbose=False)

    assert vessel.max_power is None
    assert vessel.sfoc is None


def test_sfc_is_the_deprecated_name_of_sfoc():
    with pytest.warns(DeprecationWarning, match="sfoc"):
        vessel = Vessel("ship", sfc=224.0, verbose=False)
    assert vessel.sfoc(0.0) == 224.0

    with pytest.warns(DeprecationWarning, match="sfoc"):
        assert vessel.sfc(0.0) == 224.0
    with pytest.warns(DeprecationWarning, match="sfoc"):
        vessel.sfc = 190.0
    assert vessel.sfoc(0.0) == 190.0

    with pytest.warns(DeprecationWarning), pytest.raises(TypeError, match="sfoc only"):
        Vessel("ship", sfc=224.0, sfoc=190.0, verbose=False)


def cubic(x):
    return POLAR_POWER_COEFFICIENT * x["stw"] ** 3


QUERY = {"stw": np.array([10.0, 5.0])}
BHP = POLAR_POWER_COEFFICIENT * QUERY["stw"] ** 3


def values(quantities):
    return {key: np.ravel(np.asarray(value, dtype=float)) for key, value in quantities.items()}


def test_consumption_of_a_brake_power():
    vessel = Vessel("ship", hotel_load=200.0, sfoc=180.0, verbose=False)
    vessel.add_function("bhp", cubic, ["stw"])

    consumption = values(vessel.consumption(QUERY))

    assert vessel.consumption_model == "bhp"
    assert vessel.consumption_keys() == ["bhp"]
    assert list(consumption) == vessel.consumption_quantities()
    assert list(consumption) == ["bhp", "hotel_load", "total_power", "sfoc", "hourly_consumption"]
    assert consumption["total_power"] == pytest.approx(BHP + 200.0)
    assert consumption["hourly_consumption"] == pytest.approx((BHP + 200.0) * 180.0 / 1e3)


def test_consumption_of_a_total_power():
    vessel = Vessel("ship", hotel_load=1e6, sfoc=lambda power: 150.0 + power / 100.0, verbose=False)
    vessel.add_function("total_power", cubic, ["stw"])

    consumption = values(vessel.consumption(QUERY))

    # The hotel load is part of the total power
    assert list(consumption) == ["total_power", "sfoc", "hourly_consumption"]
    assert consumption["sfoc"] == pytest.approx(150.0 + BHP / 100.0)
    assert consumption["hourly_consumption"] == pytest.approx(BHP * (150.0 + BHP / 100.0) / 1e3)


def test_an_hourly_consumption_needs_no_sfoc():
    vessel = Vessel("ship", verbose=False)
    vessel.add_function("hourly_consumption", cubic, ["stw"])

    consumption = values(vessel.consumption(QUERY))

    assert vessel.consumption_keys() == ["hourly_consumption"]
    assert list(consumption) == ["hourly_consumption"]
    assert consumption["hourly_consumption"] == pytest.approx(BHP)


def test_the_first_consumption_model_is_used():
    vessel = Vessel("ship", sfoc=180.0, verbose=False)
    vessel.add_function("bhp", cubic, ["stw"])
    assert vessel.consumption_model == "bhp"

    vessel.add_constant("total_power", 500.0)
    assert vessel.consumption_model == "total_power"

    vessel.add_constant("hourly_consumption", 90.0)
    assert vessel.consumption_model == "hourly_consumption"
    assert values(vessel.consumption(QUERY))["hourly_consumption"] == pytest.approx(90.0)


def test_models_of_hotel_load_and_sfoc_take_precedence():
    vessel = Vessel("ship", hotel_load=1e6, sfoc=1e6, verbose=False)
    vessel.add_function("bhp", cubic, ["stw"])
    vessel.add_function("hotel_load", lambda x: 0.1 * x["bhp"], ["bhp"])
    vessel.add_function("sfoc", lambda x: 150.0 + x["total_power"] / 100.0, ["total_power"])

    consumption = values(vessel.consumption(QUERY))

    assert vessel.consumption_keys() == ["bhp", "hotel_load", "sfoc"]
    assert consumption["total_power"] == pytest.approx(1.1 * BHP)
    assert consumption["sfoc"] == pytest.approx(150.0 + 1.1 * BHP / 100.0)


def test_a_constant_model_takes_no_input():
    vessel = Vessel("ship", hotel_load=100.0, sfoc=200.0, verbose=False)
    vessel.add_constant("bhp", 900.0)

    assert vessel.input_names("bhp") == []
    assert float(vessel("bhp", {"stw": 12.0})) == 900.0
    assert float(vessel.consumption({})["hourly_consumption"]) == pytest.approx(1000.0 * 200.0 / 1e3)


def test_a_vessel_without_consumption_model_is_reported():
    vessel = Vessel("ship", sfoc=180.0, verbose=False)
    vessel.add_function("max_bhp", cubic, ["stw"])

    assert vessel.consumption_model is None
    with pytest.raises(KeyError, match="no consumption model"):
        vessel.consumption(QUERY)


def test_a_missing_sfoc_is_reported():
    vessel = Vessel("ship", verbose=False)
    vessel.add_function("bhp", cubic, ["stw"])

    with pytest.raises(ValueError, match="needs sfoc"):
        vessel.consumption(QUERY)


def test_consumption_is_differentiable():
    import casadi as ca

    stw = ca.MX.sym("stw")
    vessel = Vessel("ship", hotel_load=200.0, sfoc=180.0, verbose=False)
    vessel.add_function("bhp", cubic, ["stw"])

    rate = vessel.consumption({"stw": stw})["hourly_consumption"]
    gradient = ca.Function("gradient", [stw], [ca.jacobian(rate, stw)])

    assert float(gradient(10.0)) == pytest.approx(3.0 * POLAR_POWER_COEFFICIENT * 100.0 * 180.0 / 1e3)


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


def test_polars_are_queried_by_their_axes(polar):
    vessel = Vessel("ship", filepath="polar.nc")
    vessel.data = polar
    vessel.add_interpolator("bhp", *POLAR_DIMS)
    query = {"stw": np.array([6.0, 8.0]), "tws": 15.0, "twa": 60.0, "hs": 1.0, "wa": 60.0}

    assert vessel.input_names("bhp") == list(POLAR_DIMS)
    expected = [POLAR_POWER_COEFFICIENT * 6.0**3, POLAR_POWER_COEFFICIENT * 8.0**3]
    assert np.asarray(vessel("bhp", query)).ravel() == pytest.approx(expected)


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


def semi_empirical_power(x, p):
    return p["k"] * x["stw"] ** 3


def test_vessel_without_polar_file_takes_functions():
    vessel = Vessel("function_ship", verbose=False)
    vessel.add_function("bhp", semi_empirical_power, inputs=["stw"], args={"p": {"k": POLAR_POWER_COEFFICIENT}})

    assert vessel.path is None
    assert vessel.label == "function_ship"
    assert float(vessel("bhp", {"stw": 10.0})) == pytest.approx(POLAR_POWER_COEFFICIENT * 1e3)


def test_vessel_without_polar_file_has_nothing_to_load():
    with pytest.raises(AssertionError, match="no polar file"):
        Vessel("function_ship", verbose=False).load_data()

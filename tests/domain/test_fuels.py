import pytest

from architeuthis.core import _describe
from architeuthis.fuels import FUEL_ALIASES, FUELS, GWP_CH4, GWP_N2O, Fuel, fuel_key, get_fuel
from architeuthis.vessel import Vessel


def test_every_fuel_is_physical():
    for key, fuel in FUELS.items():
        assert 0.05 < fuel.density < 1.1, key
        assert 15.0 < fuel.lcv < 125.0, key
        assert 0.0 <= fuel.cf_co2 < 3.3, key
        assert 0.0 <= fuel.methane_slip < 5.0, key
        assert fuel.label and fuel.source, key


def test_every_alias_names_a_fuel():
    assert set(FUEL_ALIASES.values()) <= set(FUELS)
    assert not set(FUEL_ALIASES) & set(FUELS)


def test_fuels_are_found_by_key_alias_or_case():
    assert get_fuel("HFO") is FUELS["hfo"]
    assert get_fuel("Gas oil") is FUELS["mgo"]
    assert get_fuel("gasoline") is FUELS["unleaded"]
    assert fuel_key("petrol") == "unleaded"
    own = Fuel("Blend", density=0.9, lcv=41.5, cf_co2=3.15)
    assert get_fuel(own) is own and fuel_key(own) is None
    with pytest.raises(KeyError, match="Unknown fuel type"):
        get_fuel("kerosene")


def test_heavy_fuel_oil_has_the_fueleu_intensities():
    hfo = FUELS["hfo"]
    burnt = 3.114 + GWP_CH4 * 0.00005 + GWP_N2O * 0.00018

    assert hfo.ttw_intensity == pytest.approx(burnt / 0.0405)
    assert hfo.wtw_intensity == pytest.approx(13.5 + burnt / 0.0405)
    assert hfo.wtw_intensity == pytest.approx(91.74, abs=0.01)


def test_methane_slip_weighs_on_lng():
    otto, diesel = FUELS["lng"], FUELS["lng_diesel"]

    assert otto.ttw_intensity > diesel.ttw_intensity
    burnt = 2.750 + GWP_N2O * 0.00011
    assert otto.ttw_intensity == pytest.approx((0.969 * burnt + 0.031 * GWP_CH4) / 0.0491)


def test_biogenic_carbon_and_unknown_production_are_told_apart():
    fame = FUELS["fame"]

    assert fame.biogenic
    assert fame.ttw_intensity < 2.0  # its CH4 and N2O only
    assert fame.wtw_intensity is None and fame.ghg(10.0) is None
    assert FUELS["hydrogen"].ttw_intensity == 0.0


def test_emissions_of_a_voyage():
    mdo = FUELS["mdo"]

    assert mdo.co2(10.0) == pytest.approx(32.06)
    # 10 t of fuel is 427 GJ.
    assert mdo.ghg(10.0, well_to_wake=False) == pytest.approx(427e3 * mdo.ttw_intensity / 1e6)
    assert mdo.ghg(10.0) > mdo.ghg(10.0, well_to_wake=False)
    assert mdo.energy_density == pytest.approx(0.85 * 42.7)


def test_the_plan_metadata_tells_the_fuel():
    vessel = Vessel("ship", fuel_type="hfo", fuel_density=0.99, max_power=None, verbose=False)

    description = _describe(vessel)

    assert description["fuel_type"] == "hfo"
    assert description["fuel_density"] == 0.99

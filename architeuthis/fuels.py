# -*- coding: utf-8 -*-
"""
Fuels: density, heating value and greenhouse gas factors.

`FUELS` gives, for each fuel type, the density that turns the
consumption of a vessel, in L/h, into the mass of its voyage, in
tonnes, and the factors of its emissions. `Vessel(fuel_type=...)`
takes its density from it.

Factors of marine fuels are the default values of FuelEU Maritime
(Regulation (EU) 2023/1805, Annex II), consistent with the IMO
guidelines (MEPC.364(79)): lower heating value, emission factors of
CO2, CH4 and N2O per mass of fuel, methane slip and well-to-tank
intensity. Road fuels take the IPCC 2006 values (Volume 2,
chapters 1 and 3). Densities are typical values at 15 deg C, liquid
for gases, within the limits of their standard: a bunker delivery
note gives the actual one, which `Vessel(fuel_density=...)` takes.
`None` marks a factor that these sources leave open, counted as zero
by the intensities. Check the values against the regulation in force
before any regulatory use.

Created on Mon Nov 23 2026

@author: jrich
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

# Global warming potentials over 100 years, those of FuelEU Maritime
# (Annex I), in g CO2 equivalent per g.
GWP_CH4 = 25.0
GWP_N2O = 298.0


@dataclass(frozen=True)
class Fuel:
    """
    A fuel type and its factors.

    Args:
        label: Name of the fuel, with its standard.
        density: Typical density at 15 deg C, liquid, in kg/L.
        lcv: Lower calorific (heating) value, in MJ/kg.
        cf_co2: CO2 emitted by burning it, in g/g of fuel.
        cf_ch4: CH4 emitted by burning it, in g/g of fuel, or None.
        cf_n2o: N2O emitted by burning it, in g/g of fuel, or None.
        methane_slip: Fuel escaping unburnt, in % of its mass.
        wtt: Well-to-tank intensity, in g CO2 equivalent per MJ, or
            None when it depends on the production pathway.
        biogenic: Whether its carbon is biogenic: FuelEU counts the
            CO2 of its combustion as zero when it is sustainable.
        source: Where the factors come from.

    Example:
        >>> FUELS["hfo"].wtw_intensity
        91.74...
    """

    label: str
    density: float
    lcv: float
    cf_co2: float
    cf_ch4: Optional[float] = None
    cf_n2o: Optional[float] = None
    methane_slip: float = 0.0
    wtt: Optional[float] = None
    biogenic: bool = False
    source: str = "FuelEU Maritime, Annex II"

    @property
    def energy_density(self) -> float:
        """
        Energy per volume, in MJ/L.
        """
        return self.density * self.lcv

    @property
    def ttw_intensity(self) -> float:
        """
        Tank-to-wake intensity, in g CO2 equivalent per MJ.

        As FuelEU Maritime: the CO2, CH4 and N2O of the fuel burnt,
        weighted by their GWP, plus the methane slip, per MJ of fuel.
        The CO2 of a biogenic fuel counts as zero, and an unknown
        factor too.
        """
        burnt = (0.0 if self.biogenic else self.cf_co2) + GWP_CH4 * (self.cf_ch4 or 0.0) + GWP_N2O * (self.cf_n2o or 0.0)
        slip = self.methane_slip / 100.0
        return ((1.0 - slip) * burnt + slip * GWP_CH4) / (self.lcv / 1e3)

    @property
    def wtw_intensity(self) -> Optional[float]:
        """
        Well-to-wake intensity, in g CO2 equivalent per MJ, or None.
        """
        return None if self.wtt is None else self.wtt + self.ttw_intensity

    def co2(self, fuel: float) -> float:
        """
        CO2 emitted by burning a mass of this fuel.

        Args:
            fuel: Mass of fuel, in tonnes, as the `fuel` of a report.

        Returns:
            Tank-to-wake CO2, in tonnes.
        """
        return fuel * self.cf_co2

    def ghg(self, fuel: float, well_to_wake: bool = True) -> Optional[float]:
        """
        Greenhouse gases of a mass of this fuel, in CO2 equivalent.

        Args:
            fuel: Mass of fuel, in tonnes.
            well_to_wake: Whether to include its production, else only
                its combustion (tank-to-wake).

        Returns:
            Tonnes of CO2 equivalent, or None when the well-to-tank
            intensity is unknown.
        """
        intensity = self.wtw_intensity if well_to_wake else self.ttw_intensity
        return None if intensity is None else fuel * self.lcv * intensity / 1e3


_OIL = {"cf_ch4": 0.00005, "cf_n2o": 0.00018}
_IPCC = "IPCC 2006, Volume 2"

# Fuel types by key: marine fuels oils (ISO 8217), gases, alcohols,
# carbon-free fuels, biofuels and road fuels.
FUELS = {
    # Marine distillates and residual fuels, ISO 8217
    "mdo": Fuel("Marine diesel oil (ISO 8217 DMB)", density=0.85, lcv=42.7, cf_co2=3.206, wtt=14.4, **_OIL),
    "mgo": Fuel("Marine gas oil (ISO 8217 DMA)", density=0.85, lcv=42.7, cf_co2=3.206, wtt=14.4, **_OIL),
    "lfo": Fuel("Light fuel oil (ISO 8217 RMA-RMD)", density=0.93, lcv=41.0, cf_co2=3.151, wtt=13.2, **_OIL),
    "hfo": Fuel("Heavy fuel oil (ISO 8217 RME-RMK)", density=0.985, lcv=40.5, cf_co2=3.114, wtt=13.5, **_OIL),
    "vlsfo": Fuel("Very low sulphur fuel oil, 0.5 % S (residual)", density=0.94, lcv=40.5, cf_co2=3.114, wtt=13.5, **_OIL),
    # Liquefied gases: methane slip of the engine type, FuelEU Annex II
    "lng": Fuel("LNG, Otto dual fuel medium speed engine", density=0.45, lcv=49.1, cf_co2=2.750, cf_ch4=0.0, cf_n2o=0.00011, methane_slip=3.1, wtt=18.5),
    "lng_otto_slow": Fuel("LNG, Otto dual fuel slow speed engine", density=0.45, lcv=49.1, cf_co2=2.750, cf_ch4=0.0, cf_n2o=0.00011, methane_slip=1.7, wtt=18.5),
    "lng_diesel": Fuel("LNG, diesel dual fuel slow speed engine", density=0.45, lcv=49.1, cf_co2=2.750, cf_ch4=0.0, cf_n2o=0.00011, methane_slip=0.2, wtt=18.5),
    "lng_lbsi": Fuel("LNG, lean burn spark ignited engine", density=0.45, lcv=49.1, cf_co2=2.750, cf_ch4=0.0, cf_n2o=0.00011, methane_slip=2.6, wtt=18.5),
    "lpg_propane": Fuel("LPG, propane", density=0.51, lcv=46.0, cf_co2=3.000, wtt=7.8),
    "lpg_butane": Fuel("LPG, butane", density=0.58, lcv=46.0, cf_co2=3.030, wtt=7.8),
    # Alcohols
    "methanol": Fuel("Methanol from natural gas", density=0.792, lcv=19.9, cf_co2=1.375, wtt=31.3),
    "ethanol": Fuel("Ethanol", density=0.789, lcv=26.8, cf_co2=1.913, source="IMO MEPC.364(79)"),
    # Carbon-free fuels, from natural gas (grey)
    "ammonia": Fuel("Ammonia from natural gas, liquid at -33 deg C", density=0.682, lcv=18.6, cf_co2=0.0, cf_ch4=0.0, wtt=121.0),
    "hydrogen": Fuel("Hydrogen from natural gas, liquid at -253 deg C", density=0.071, lcv=120.0, cf_co2=0.0, cf_ch4=0.0, cf_n2o=0.0, wtt=132.0),
    # Biofuels: their well-to-tank intensity depends on the feedstock
    "fame": Fuel("Biodiesel, FAME (EN 14214)", density=0.88, lcv=37.2, cf_co2=2.834, biogenic=True, **_OIL),
    "hvo": Fuel("Hydrotreated vegetable oil (EN 15940)", density=0.78, lcv=44.0, cf_co2=3.115, biogenic=True, **_OIL),
    # Road fuels
    "diesel": Fuel("Road diesel (EN 590)", density=0.835, lcv=43.0, cf_co2=3.186, source=_IPCC),
    "unleaded": Fuel("Unleaded petrol (EN 228)", density=0.745, lcv=44.3, cf_co2=3.070, source=_IPCC),
}

# Other names of the fuel types.
FUEL_ALIASES = {
    "dmb": "mdo",
    "dma": "mgo",
    "gas_oil": "mgo",
    "gasoil": "mgo",
    "ifo": "hfo",
    "ifo380": "hfo",
    "rmg": "hfo",
    "lsfo": "vlsfo",
    "lpg": "lpg_propane",
    "propane": "lpg_propane",
    "butane": "lpg_butane",
    "nh3": "ammonia",
    "h2": "hydrogen",
    "biodiesel": "fame",
    "petrol": "unleaded",
    "gasoline": "unleaded",
}


def get_fuel(fuel: Union[str, Fuel]) -> Fuel:
    """
    A fuel type of `FUELS`, by key or alias, whatever its case.

    Args:
        fuel: A key of `FUELS` or `FUEL_ALIASES`, or a `Fuel`, given
            back as it is.

    Returns:
        The `Fuel`.

    Example:
        >>> get_fuel("HFO").density
        0.985
    """
    if isinstance(fuel, Fuel):
        return fuel
    key = str(fuel).strip().lower().replace("-", "_").replace(" ", "_")
    key = FUEL_ALIASES.get(key, key)
    if key not in FUELS:
        raise KeyError(f"Unknown fuel type {fuel!r}: one of {sorted(FUELS)}, or a Fuel.")
    return FUELS[key]


def fuel_key(fuel: Union[str, Fuel]) -> Optional[str]:
    """
    The key of a fuel type in `FUELS`, or None for another `Fuel`.

    Args:
        fuel: A key, an alias or a `Fuel`.
    """
    found = get_fuel(fuel)
    return next((key for key, value in FUELS.items() if value is found), None)

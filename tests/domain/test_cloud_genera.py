"""The table of the ten WMO cloud genera, `architeuthis/data/cloud_genera.json`."""

import json
from importlib import resources

import pytest

GENERA = {
    "Ci": "Cirrus",
    "Cc": "Cirrocumulus",
    "Cs": "Cirrostratus",
    "Ac": "Altocumulus",
    "As": "Altostratus",
    "Ns": "Nimbostratus",
    "Sc": "Stratocumulus",
    "St": "Stratus",
    "Cu": "Cumulus",
    "Cb": "Cumulonimbus",
}
ETAGES = {"Ci": "high", "Cc": "high", "Cs": "high", "Ac": "middle", "As": "middle", "Ns": "middle"}
CHARACTERS = {"none", "intermittent", "continuous", "showery"}
INTENSITIES = {"none", "light", "moderate", "heavy"}
FORMS = {"cirriform", "stratiform", "stratocumuliform", "cumuliform"}
COMPOSITIONS = {"ice", "water", "mixed"}
# Mother clouds that are not genera (Table 2): human activity, forests, waterfalls, fires.
SPECIAL_MOTHERS = {"homo", "silva", "cataracta", "flamma"}


@pytest.fixture(scope="module")
def table():
    with (resources.files("architeuthis") / "data" / "cloud_genera.json").open(encoding="utf-8") as stream:
        return json.load(stream)


def test_lists_the_ten_genera_in_atlas_order(table):
    assert [(genus["abbreviation"], genus["name"]) for genus in table["genera"]] == list(GENERA.items())


def test_etages_follow_the_atlas(table):
    for genus in table["genera"]:
        assert genus["etage"] == ETAGES.get(genus["abbreviation"], "low")
        assert genus["etage"] in genus["spans"]
        assert set(genus["spans"]) <= set(table["etages"])

    for etage in table["etages"].values():
        for bottom, top in etage["height_km"].values():
            assert 0 <= bottom < top


def test_fields_use_the_controlled_vocabulary(table):
    for genus in table["genera"]:
        precipitation = genus["precipitation"]

        assert genus["form"] in FORMS
        assert genus["composition"] in COMPOSITIONS
        assert precipitation["character"] in CHARACTERS
        assert precipitation["intensity"] in INTENSITIES
        assert (precipitation["character"] == "none") == (precipitation["intensity"] == "none")
        assert (precipitation["character"] == "none") == (not precipitation["forms"])
        assert genus["appearance"] and genus["significance"]


def test_mother_clouds_are_genera_or_special_clouds(table):
    for genus in table["genera"]:
        for mother in genus["genitus"] + genus["mutatus"]:
            assert mother in GENERA.values() or mother in SPECIAL_MOTHERS
        assert genus["name"] not in genus["genitus"] + genus["mutatus"]

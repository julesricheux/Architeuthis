"""
Session-wide test isolation: no real home directory, credentials, GUI or network.

The environment is set here, at import time, because `architeuthis.common` reads it as
soon as it is imported during collection.
"""

import os
import shutil
import sys
import tempfile
import types

_temporary_home = tempfile.mkdtemp(prefix="architeuthis-tests-")
os.makedirs(os.path.join(_temporary_home, "data"))

os.environ["HOME"] = _temporary_home
os.environ["USERPROFILE"] = _temporary_home
os.environ["MPLBACKEND"] = "Agg"

for credential in ("CDS_API_KEY", "CMEMS_USER", "CMEMS_PWD", "EUMDAC_USER", "EUMDAC_PWD"):
    os.environ.pop(credential, None)

# architeuthis.icebergs downloads the IIP bulletin and shapefiles when its data is first
# used, by the default exclusion zones for example. Replace it so that tests never depend
# on that server. tests/domain/test_icebergs.py loads the real source.
_icebergs_stub = types.ModuleType("architeuthis.icebergs")
_icebergs_stub.polygon = [
    [50.0, -40.0],
    [50.0, -39.0],
    [49.0, -39.0],
    [48.0, -40.0],
    [48.0, -45.0],
    [50.0, -45.0],
    [50.0, -40.0],
]
_icebergs_stub.berg_zone = _icebergs_stub.polygon
_icebergs_stub.berg_geojson = {"type": "FeatureCollection", "features": []}
sys.modules["architeuthis.icebergs"] = _icebergs_stub


def pytest_unconfigure(config):
    shutil.rmtree(_temporary_home, ignore_errors=True)

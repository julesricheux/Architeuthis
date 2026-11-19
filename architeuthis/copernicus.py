# -*- coding: utf-8 -*-
"""
Access to the Copernicus Marine Service (CMEMS).

Shared by the forecasts (`forecast.CopernicusForecast`) and the
satellite observations (`satellite.CopernicusSatelliteData`): the
subsetting on the server with the `copernicusmarine` toolbox, and the
credentials it needs.

Created on Thu Nov 19 2026

@author: jrich
"""

import os
import logging

import copernicusmarine

from typing import Optional, Sequence
from architeuthis.common import _USER_HOME
from architeuthis.credentials import require_credentials


logging.getLogger("copernicusmarine").handlers.clear()


def copernicusmarine_credentials_file() -> str:
    """
    The file written by `copernicusmarine login`.

    Returns:
        Its path, which may not exist.
    """
    directory = (
        os.environ.get("COPERNICUSMARINE_CREDENTIALS_DIRECTORY")
        or os.path.join(_USER_HOME, ".copernicusmarine")
    )
    return os.path.join(directory, ".copernicusmarine-credentials")


class CopernicusMarineData:
    """
    Mixin of the data downloaded from Copernicus Marine.

    Combined with a data class, before it in the bases, it adds
    `_subset`, which downloads a subset of a dataset over the domain of
    the object (`min_lon`, `max_lon`, `min_lat`, `max_lat`) to its
    `output_path`, and reports progress if its `verbose` is True.

    Credentials come from `CMEMS_USER` and `CMEMS_PWD`, read from the
    environment or the credential store when downloading (see
    `architeuthis.credentials`), else from `copernicusmarine login`.
    They are never kept on the object.
    """

    def _subset(
        self,
        dataset: str,
        variables: Sequence[str],
        start,
        end,
        min_depth: Optional[float] = None,
        max_depth: Optional[float] = None,
        compression_level: int = 1,
        selection: str = "strict-inside",
    ) -> str:
        """
        Download a subset of a dataset, unless already downloaded.

        Args:
            dataset: Identifier of the CMEMS dataset.
            variables: Variables to download.
            start: Start of the period; the toolbox takes a naive
                date as local time.
            end: End of the period.
            min_depth: Shallowest depth, in m, None for a dataset
                without depth.
            max_depth: Deepest depth, in m.
            compression_level: Compression level of the NetCDF file.
            selection: `coordinates_selection_method` of the toolbox:
                "strict-inside" refuses a request beyond the dataset,
                "inside" clips it to the dataset.

        Returns:
            Path of the NetCDF file.

        Raises:
            MissingCredentialError: If the credentials are missing.
        """
        # Read here and not kept on the object, so that it can be copied,
        # pickled or inspected without exposing the credentials.
        username, password = require_credentials(
            "CMEMS_USER",
            "CMEMS_PWD",
            provider="Copernicus Marine",
            fallback_files=[copernicusmarine_credentials_file()],
        )
        depth = {}
        if min_depth is not None:
            depth = {"minimum_depth": min_depth, "maximum_depth": max_depth}

        request = copernicusmarine.subset(
            username=username,
            password=password,
            dataset_id=dataset,
            variables=variables,
            minimum_longitude=self.min_lon,
            maximum_longitude=self.max_lon,
            minimum_latitude=self.min_lat,
            maximum_latitude=self.max_lat,
            start_datetime=start,
            end_datetime=end,
            coordinates_selection_method=selection,
            netcdf_compression_level=compression_level,
            disable_progress_bar=not self.verbose,
            output_directory=self.output_path,
            skip_existing=True,  # do not download a file again
            **depth,
        )
        return request.file_path

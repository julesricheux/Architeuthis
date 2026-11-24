# -*- coding: utf-8 -*-
"""
Display and user experience: graphical reporting and route sharing.

`share` writes routes, forecasts and zones as one HTML file that opens
offline in any browser, on a globe; it needs nothing beyond the
dependencies of Architeuthis. `ui` is the analyst's page that previews
and downloads that file, and `json_wrapper` and `leaflet_wrapper` build
the GeoJSON and map layers of the former Leaflet map. These need Dash,
installed with the `dux` extra:

    pip install architeuthis[dux]

Importing this package imports none of its modules, so it has no side
effect and needs no extra dependency.

Created on Fri Nov 20 2026

@author: jrich
"""

from contextlib import contextmanager

EXTRA = "dux"
INSTALL_HINT = f'pip install "architeuthis[{EXTRA}]"'


class MissingExtraError(ImportError):
    """
    A dependency of the `dux` extra is not installed.
    """


@contextmanager
def require_extra():
    """
    Turn a missing dependency into an error naming the `dux` extra.

    Wraps the imports of a module that needs Dash or Flask, so that
    without them it fails with the command that installs them.

    Example:
        >>> with require_extra():
        ...     import dash
    """
    try:
        yield
    except ModuleNotFoundError as error:
        raise MissingExtraError(
            f"{error.name} is missing: the display tools of Architeuthis need the "
            f"{EXTRA!r} extra. Install it with: {INSTALL_HINT}",
            name=error.name,
        ) from error

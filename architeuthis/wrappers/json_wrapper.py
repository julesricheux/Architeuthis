# -*- coding: utf-8 -*-
"""
Former place of `architeuthis.dux.json_wrapper`, kept until 0.4.0.

Importing it warns and gives the module of `architeuthis.dux`, which
needs the `dux` extra.
"""

import importlib
import sys
import warnings

warnings.warn(
    "architeuthis.wrappers.json_wrapper moved to architeuthis.dux.json_wrapper, "
    "installed with the 'dux' extra; the former name will be removed in 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = importlib.import_module("architeuthis.dux.json_wrapper")

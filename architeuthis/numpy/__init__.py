### Import everything from NumPy

"""
This module relies on Peter D. Sharpe's awesome work on AeroSandbox.

AeroSandbox
Author: Peter D. Sharpe
Repository: https://github.com/peterdsharpe/AeroSandbox
Version used: 4.2.9
Date retrieved: 2026-03-02

AeroSandbox is distributed under its original MIT license.
All credit for the underlying methods and implementations belongs to the original author.
"""

from numpy import *

### Overwrite some functions
from architeuthis.numpy.array import *
from architeuthis.numpy.arithmetic_monadic import *
from architeuthis.numpy.arithmetic_dyadic import *
from architeuthis.numpy.calculus import *
from architeuthis.numpy.conditionals import *
from architeuthis.numpy.finite_difference_operators import *
from architeuthis.numpy.integrate import *
from architeuthis.numpy.interpolate import *
from architeuthis.numpy.linalg_top_level import *
import architeuthis.numpy.linalg as linalg
from architeuthis.numpy.logicals import *
from architeuthis.numpy.rotations import *
from architeuthis.numpy.spacing import *
from architeuthis.numpy.surrogate_model_tools import *
from architeuthis.numpy.trig import *

### Force-overwrite built-in Python functions.

from numpy import round  # TODO check that min, max are properly imported

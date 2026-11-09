# -*- coding: utf-8 -*-
"""
Marine weather routing for hybrid sailing ships.

Created on Thu Jan 15 17:01:59 2026

@author: jrich

                  ▄▄                               ▄▄
                  ██    ▀▀  ██                ██   ██    ▀▀
 ▀▀█▄ ████▄ ▄████ ████▄ ██ ▀██▀▀ ▄█▀█▄ ██ ██ ▀██▀▀ ████▄ ██  ▄█▀▀▀
▄█▀██ ██ ▀▀ ██    ██ ██ ██  ██   ██▄█▀ ██ ██  ██   ██ ██ ██  ▀███▄
▀█▄██ ██    ▀████ ██ ██ ██▄ ██   ▀█▄▄▄ ▀██▀█  ██   ██ ██ ██▄ ▄▄▄█▀

🦑 An open-source marine weather and decision-making framework for
hybrid sailing ships. It couples mesh-free, fully differentiable
methods in a unified optimization environment to compute optimal
routes under real-world constraints.
"""

__author__ = "Jules Richeux"
__company__ = "NEOLINE"
__version__ = "0.2.0"

__meet_Architeuthis__ = "https://en.wikipedia.org/wiki/Giant_squid"
__documentation__ = None # TODO

from architeuthis.optimization import Opti, OptiSol
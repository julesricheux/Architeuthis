# -*- coding: utf-8 -*-
"""
Created on Thu Jan 15 11:06:09 2026

@author: jrich
"""

from __future__ import annotations

import datetime

from typing import Sequence, Tuple, Optional
from architeuthis.common import ArchiteuthisObject


class Route(ArchiteuthisObject):

    def __init__(
        self,
        waypoints: Sequence[Tuple[float, float]],
        etd: Optional[datetime.datetime] = None,
        eta: Optional[datetime.datetime] = None,
        timestamps: Sequence[float, float] = None,
        name: str = None,
        verbose: bool = True,
    ):
        super().__init__(name, verbose)
        
        self.waypoints = waypoints
        self.eta = eta
        self.etd = etd
        self.timestamps = timestamps
        
        self.lat = None
        self.lon = None

    def length(self) -> float:
        """
        Return total route length.
        """
        raise NotImplementedError("Route.length must be implemented")




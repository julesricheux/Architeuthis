# -*- coding: utf-8 -*-
"""
Results of a routing: `RoutingReport` and `ReportCollection`.

A `RoutingReport` is the dict returned by `RoutingAnalysis.run` and
`evaluate`, with the same keys and the same JSON file format as before,
and helpers for tables, GPX export and plots. A `ReportCollection` is a
list of reports that can be selected, tabulated, saved and reloaded.
Both can still be used as a plain dict and a plain list.

The UI (`ui.py`) displays the most recent file of `~/data/routes/`, as
written by `ReportCollection.save`.
"""

from __future__ import annotations

import json
import os

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as onp
import pandas as pd

from architeuthis.common import _HOME, status
from architeuthis.toolbox.json_utils import CustomEncoder, custom_decoder


ROUTES_DIRECTORY = os.path.join(_HOME, "routes")

DEFAULT_TABLE_VARIABLES = ("sog", "cog", "avg_bhp", "twa")
DEFAULT_QUANTILES = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)


def routes_to_table(
    frame: pd.DataFrame,
    mask=None,
    variables: Sequence[str] = DEFAULT_TABLE_VARIABLES,
) -> pd.DataFrame:
    """
    A table of several routes against time.

    It has a `timestamp` column and, for each selected row `I` of
    `frame`, one column `{variable}_{I}` per variable. Times missing
    from a route are left empty.

    Args:
        frame: One report per row, as given by `ReportCollection.frame`.
        mask: Rows to keep, any `frame.loc` selector. All of them by
            default.
        variables: Report entries with one value per segment.
    """
    rows = frame if mask is None else frame.loc[mask]

    if len(rows) == 0:
        raise ValueError("routes_to_table: no report selected.")

    tables = []

    for I, row in rows.iterrows():

        data = {
            "timestamp": pd.to_datetime(row["tim"][:-1], unit="s")
        }

        for VAR in variables:
            data[f"{VAR}_{I}"] = onp.asarray(row[VAR])

        tables.append(pd.DataFrame(data))

    table = tables[0]

    for t in tables[1:]:
        table = table.merge(t, on="timestamp", how="outer")

    table = table.sort_values("timestamp")

    return table


class RoutingReport(dict):
    """
    The result of a routing.

    It is a dict of numeric arrays and scalars, in float epoch seconds.
    """

    @property
    def etd_time(self) -> pd.Timestamp:
        """
        The departure time, as a timestamp.
        """
        return pd.to_datetime(self["etd"], unit="s")

    @property
    def eta_time(self) -> pd.Timestamp:
        """
        The arrival time, as a timestamp.
        """
        return pd.to_datetime(self["eta"], unit="s")

    def summary(self) -> dict:
        """
        The key figures of this route.

        They form a row of `ReportCollection.summary`.
        """
        return {
            "etd": self.etd_time,
            "eta": self.eta_time,
            "model": self.get("model"),
            "vessel": self.get("vessel"),
            "member": self.get("member"),
            "init_fac": self.get("init_fac"),
            "solve": self.get("solve"),
            "status": self.get("status"),
            "dist": self["dist"],
            "extra_dist_%": (self["dist_rel"] - 1.) * 100.,
            "stw": float(onp.mean(self["stw"])),
            "sog": float(onp.mean(self["sog"])),
            "fuel": self["fuel"],
            "fuel_per_day": self["fuel"] / self["transit_time"] * 24.,
            "max_z": float(onp.max(self["z"])),
        }

    def steps(self, quantity: str):
        """
        Times and values of a per-segment quantity, to plot it as steps.

        See `plot_utils.get_steps`.
        """
        from architeuthis.toolbox.plot_utils import get_steps

        return get_steps(self, quantity)

    def table(self, variables: Sequence[str] = DEFAULT_TABLE_VARIABLES) -> pd.DataFrame:
        """
        A table of this route against time.

        It has a `timestamp` column and one column per variable.
        """
        data = {"timestamp": pd.to_datetime(onp.ravel(self["tim"])[:-1], unit="s")}
        for variable in variables:
            data[variable] = onp.asarray(self[variable])
        return pd.DataFrame(data)

    def to_gpx(self, filename: Optional[str] = None, track_name: Optional[str] = None) -> str:
        """
        Write the track as a GPX file and return its name.

        The default name is `track_<MODEL>_<vessel>_<ETD date>.gpx`, in
        the working directory, and the default track name is
        `track_<MODEL>`.
        """
        from architeuthis.toolbox.os_utils import save_gpx

        model = str(self.get("model", "route")).upper()
        if filename is None:
            filename = f"track_{model}_{self.get('vessel', 'vessel')}_{self.etd_time:%Y%m%d}.gpx"
        if track_name is None:
            track_name = f"track_{model}"

        save_gpx(
            onp.ravel(self["lat"]),
            onp.ravel(self["lon"]),
            onp.ravel(self["tim"]),
            filename,
            track_name=track_name,
        )
        return filename

    def plot(self, save_as: Optional[str] = None, show: bool = True, **kwargs):
        """
        The A4 page of this report.

        See `plot_utils.plot_report` for the options.
        """
        from architeuthis.toolbox.plot_utils import plot_report

        return plot_report(self, save_as=save_as, show=show, **kwargs)


class ReportCollection(list):
    """
    A list of `RoutingReport`.

    Example:
        >>> reports = ReportCollection()
        >>> reports.append(analysis.run(tags={"model": "ifs"}))
        >>> reports.save()  # displayed by ui.py
        >>> for report in reports.select(vessel="eff60", solve=1):
        ...     report.plot()
    """

    def __init__(self, reports=()):
        super().__init__(
            report if isinstance(report, RoutingReport) else RoutingReport(report)
            for report in reports
        )

    def append(self, report: dict) -> None:
        """
        Add a report, converted to a `RoutingReport` if needed.
        """
        super().append(report if isinstance(report, RoutingReport) else RoutingReport(report))

    def __getitem__(self, index):
        """
        A report, or a `ReportCollection` for a slice.
        """
        selected = super().__getitem__(index)
        return ReportCollection(selected) if isinstance(index, slice) else selected

    def select(self, slicing: Optional[Callable[[dict], bool]] = None, **criteria) -> "ReportCollection":
        """
        The reports matching a condition and some criteria.

        These are the reports for which `slicing(report)` is true and
        whose entries equal `criteria`.

        Example:
            >>> reports.select(vessel="eff45", model="ifs")
            >>> reports.select(lambda r: r["fuel"] < 100., solve=1)
        """
        return ReportCollection(
            report
            for report in self
            if (slicing is None or slicing(report))
            and all(report.get(key) == value for key, value in criteria.items())
        )

    def frame(self) -> pd.DataFrame:
        """
        One row per report, one column per entry.
        """
        return pd.DataFrame(self)

    def summary(self) -> pd.DataFrame:
        """
        One row of key figures per report.

        The figures are the schedule, tags, `status`, distance in nm and
        above the reference in %, mean `stw` and `sog` in kt, `fuel` in
        t, in t per day, and `max_z` in nm, positive when the route
        touches land or an exclusion zone.
        """
        return pd.DataFrame([report.summary() for report in self])

    def table(self, variables: Sequence[str] = DEFAULT_TABLE_VARIABLES, mask=None) -> pd.DataFrame:
        """
        A table of the routes against time. See `routes_to_table`.
        """
        return routes_to_table(self.frame(), mask, variables)

    def quantiles(self, variable: str, quantiles: Sequence[float] = DEFAULT_QUANTILES) -> dict:
        """
        Quantiles of a per-segment quantity over the reports.

        They are given at each segment: `{q: array}`.
        """
        if len(self) == 0:
            raise ValueError("ReportCollection.quantiles: no report selected.")
        values = onp.array([report[variable] for report in self], dtype=float)
        return {q: onp.quantile(values, q, axis=0) for q in quantiles}

    def to_gpx(self, track_name: Optional[str] = None) -> list:
        """
        Write one GPX file per report.

        The files have the default names of `RoutingReport.to_gpx`.
        """
        return [report.to_gpx(track_name=track_name) for report in self]

    # --------------------------------------------------------------------------
    # Storage
    # --------------------------------------------------------------------------

    def save(self, path: Optional[str] = None) -> str:
        """
        Write the reports as JSON and return the path.

        The default path, `~/data/routes/output_<today>.json`, is the
        one that `ui.py` displays.
        """
        if path is None:
            path = os.path.join(ROUTES_DIRECTORY, f"output_{datetime.now():%Y-%m-%d}.json")

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as file:
            json.dump(self, file, cls=CustomEncoder, indent=2)

        status(f"➕ {len(self)} reports saved to {path}.")
        return path

    @classmethod
    def load(cls, path: str) -> "ReportCollection":
        """
        Read reports from a file.

        The file was written by `save`, or by `json.dump(reports, f,
        cls=CustomEncoder)`.
        """
        with open(path, "r") as file:
            return cls(json.load(file, object_hook=custom_decoder))

    @classmethod
    def latest(cls, directory: Optional[str] = None) -> "ReportCollection":
        """
        The reports of the most recently modified file.

        The file is searched in `directory`, by default
        `~/data/routes/`.
        """
        return cls.load(latest_report_file(directory))


def latest_report_file(directory: Optional[str] = None) -> Path:
    """
    The most recently modified JSON file of `directory`.

    `directory` is by default `~/data/routes/`.
    """
    json_files = list(Path(directory if directory is not None else ROUTES_DIRECTORY).glob("*.json"))

    if not json_files:
        raise FileNotFoundError("No JSON files found in routes directory.")

    return max(json_files, key=lambda file: file.stat().st_mtime)

# -*- coding: utf-8 -*-
"""
Created on Tue Feb 24 20:55:28 2026

@author: jrich
"""

import re
from typing import List, Tuple, Optional


def _split_top_level_or(pattern: str) -> List[str]:
    """
    Splits a regex pattern on | only when not inside parentheses.
    """
    parts = []
    depth = 0
    current = []

    for char in pattern:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            continue

        current.append(char)

    parts.append("".join(current))
    return parts


def _expand_non_capturing_groups(expr: str) -> List[str]:
    """
    Expands simple flat groups of form (?:A|B|C)
    """

    pattern = r"\(\?:([^)]+)\)"
    match = re.search(pattern, expr)

    if not match:
        return [expr]

    options = match.group(1).split("|")
    prefix = expr[:match.start()]
    suffix = expr[match.end():]

    expanded = []
    for opt in options:
        expanded.extend(
            _expand_non_capturing_groups(prefix + opt + suffix)
        )

    return expanded


def _extract_variable_and_level(expr: str) -> Optional[Tuple[str, Optional[str]]]:
    """
    Extracts (variable, level)
    """

    expr = expr.strip()

    # VARIABLE:LEVEL
    m = re.match(r"^([A-Za-z0-9_]+)\s*:\s*([^:]+)$", expr)
    if m:
        return m.group(1), m.group(2).strip()

    # :variable:
    m = re.match(r"^:([A-Za-z0-9_]+):$", expr)
    if m:
        return m.group(1), None

    # VARIABLE
    m = re.match(r"^([A-Za-z0-9_]+)$", expr)
    if m:
        return m.group(1), None

    return None


def parse_forecast_regex(
    pattern: str
) -> List[Tuple[str, Optional[str]]]:
    """
    Parses forecast-style regex and returns list of
    (variable, level)
    """

    results = []

    # Correct splitting
    parts = _split_top_level_or(pattern)

    for part in parts:
        expanded = _expand_non_capturing_groups(part)

        for expr in expanded:
            parsed = _extract_variable_and_level(expr)
            if parsed:
                results.append(parsed)

    return results


# -------------------
# Test
# -------------------
if __name__ == "__main__":

    examples = [
        r"(?:U|V)GRD:10 m",
        r"(?:U|V)GRD:AGL-10m",
        r":swh:|:mwd:",
    ]

    for ex in examples:
        print(f"\nPattern: {ex}")
        print(parse_forecast_regex(ex))
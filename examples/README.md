# Examples

Each script is self-contained. Its settings are at the top and it runs from the repository root, cell by cell (`#%%`, in Spyder for example) or as a whole with `python examples/simple_routing.py`. The routing examples need your own polar files, in `~/data/polars/` by default, and the docstring of each script gives the data and credentials it needs.

| To learn | Read |
| --- | --- |
| A first routing, in the fewest lines | [`post_leg_rewind.py`](post_leg_rewind.py) |
| Every step of a study: presets, routes, runs, reports, `ui.py`, open-loop evaluation, figures, GPX, A4 page | [`simple_routing.py`](simple_routing.py) |
| Testing a plan with another model, positions unchanged | [`ifs_route_tested_with_gfs.py`](ifs_route_tested_with_gfs.py) |
| Stored routes and passage plans, restarting from a position at sea, routing without credentials | [`passage_planning.py`](passage_planning.py) |
| Several starting routes, and the spread of an ensemble along a route | [`long_term_routing.py`](long_term_routing.py) |
| One optimization per ensemble member, and a fuel consumption that depends on the power | [`ensemble_routing.py`](ensemble_routing.py) |
| High-resolution wind on a short leg | [`short_term_routing.py`](short_term_routing.py) |
| Querying forecasts directly, to compare them with satellite observations | [`comparison_ascat_models.py`](comparison_ascat_models.py) |

[`reference_data.py`](reference_data.py) is not an example: it lists usual positions, iceberg limit waypoints, past schedules, polars and alternative settings, to copy into the settings of a script.

## How a routing script reads

```python
vessel = presets.vessel(polar_file, sfc=220., hotel_load=194., max_power=4100.)
atmosphere = presets.atmosphere("ifs", domain, date=forecast_date, fxx=steps)
wave = presets.wave("ifs", domain, date=forecast_date, fxx=steps)
current = presets.current_mercator(domain, date=forecast_date)
topography = presets.topography(domain)

route = Route("crossing", [departure, cape_race, arrival])
voyage = Voyage("crossing", etd="2026-11-06T08:40", eta="2026-11-15T04:00", route=route)

analysis = RoutingAnalysis("analysis", vessel, voyage, atmosphere, wave, current, topography)
report = analysis.run()

reports = ReportCollection([report])
print(reports.summary())
reports.save()                 # run ui.py to display the latest file
plot_report(report)            # the A4 page
```

The [user guide](../docs/user_guide.md) documents the data sources, the reports, the figures and the exclusion zones.

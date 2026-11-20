# Examples

Each script is self-contained. Its settings are at the top and it runs from the repository root, cell by cell (`#%%`, in Spyder for example) or as a whole with `python examples/simple_routing.py`. Polar files are your own, read from `~/data/polars/` by default, and the docstring of each script details the data it needs. To get a credential, see the [README](../README.md#-credentials-and-settings).

**🆓 Nothing to set up**: start here if you have no polar file and no account.

| To learn | Read |
| --- | --- |
| A polar written as functions, with no file, on the wind at 10 m and 100 m and the air temperature; gusts and wave slope computed as additional variables | [`function_polar_routing.py`](function_polar_routing.py) |
| A routing in the wind alone: the waves and the current left out read as zero | [`wind_only_routing.py`](wind_only_routing.py) |
| The ways of defining the consumption of a vessel, compared on a short-sea leg: brake power as a function or a table, sfoc curve, total power, hourly consumption | [`vessel_definitions.py`](vessel_definitions.py) |
| The clouds along a route, from IFS and GFS side by side, without routing | [`sky_along_route.py`](sky_along_route.py) |
| Cloud images from Meteosat and GOES-East joined into one layer over the North Atlantic: infrared and visible, Windy colour scales, a smooth zoom, a map and an animation | [`cloud_imagery.py`](cloud_imagery.py) |

**🚢 With your polar file**

| To learn | Read | Also needs |
| --- | --- | --- |
| A first routing, in the fewest lines | [`post_leg_rewind.py`](post_leg_rewind.py) | Copernicus Marine |
| Every step of a study: data sources, zones, routes, runs, reports, `ui.py`, open-loop evaluation, figures, GPX, A4 page | [`simple_routing.py`](simple_routing.py) | Copernicus Marine |
| Stored routes and passage plans, restarting from a position at sea | [`passage_planning.py`](passage_planning.py) | |
| Testing a plan with another model, positions unchanged | [`ifs_route_tested_with_gfs.py`](ifs_route_tested_with_gfs.py) | Copernicus Marine |
| Several starting routes, and the spread of an ensemble along a route | [`long_term_routing.py`](long_term_routing.py) | Copernicus Marine |
| One optimization per ensemble member, and a fuel consumption that depends on the power | [`ensemble_routing.py`](ensemble_routing.py) | Copernicus Marine |
| High-resolution wind on a short leg | [`short_term_routing.py`](short_term_routing.py) | Copernicus Marine |

**🛰️ Satellite observations**

| To learn | Read | Needs |
| --- | --- | --- |
| ASCAT winds from EUMETSAT or Copernicus Marine: the default source with its fallback, one source only, each source with its options, and both compared on the same passes | [`ascat_sources.py`](ascat_sources.py) | EUMETSAT and/or Copernicus Marine |
| Querying forecasts directly, to compare them with ASCAT winds | [`comparison_ascat_models.py`](comparison_ascat_models.py) | EUMETSAT |

Their commented lines are alternatives that were used in past studies: other polars, domains, positions, waypoints, schedules, constraints and figure settings. Each script keeps them next to what they replace, and the settings of the former figures are in a cell of their own. The schedules follow the latest forecasts, with the dates of past studies left as comments.

## How a routing script reads

```python
vessel = Vessel("vessel", filepath=polar_file, sfoc=220., hotel_load=194., max_power=4100.)
vessel.load_data()
for key in ("bhp", "max_bhp", "sails_contribution"):
    vessel.add_interpolator(key, "stw", "tws", "twa", "hs", "wa", method="linear")

atmosphere = DeterministicHerbieForecast("wind", model="ifs", product="oper", regex=r":10[u|v]:", fxx=steps, date=forecast_date, **domain)
atmosphere.load_data()
atmosphere.add_interpolator("u10", "valid_time", "latitude", "longitude")
atmosphere.add_interpolator("v10", "valid_time", "latitude", "longitude")

wave = DeterministicHerbieForecast("wave", model="ifs", product="wave", regex=r":swh:|:mwd:", fxx=steps, date=forecast_date, **domain)
wave.load_data()
wave.add_wave_components()  # the direction is interpolated through its components
wave.add_interpolator("swh", "valid_time", "latitude", "longitude")
wave.add_interpolator("uw", "valid_time", "latitude", "longitude")
wave.add_interpolator("vw", "valid_time", "latitude", "longitude")

current = CopernicusForecast("current", dataset="cmems_mod_glo_phy_anfc_0.083deg_PT1H-m", variables=["uo", "vo"], date=forecast_date, **domain)
current.load_data()
current.add_interpolator("uo", "valid_time", "latitude", "longitude")
current.add_interpolator("vo", "valid_time", "latitude", "longitude")

topography = Topography("topography", exclusion_zones=my_zones, **domain)
topography.load_data()
topography.add_interpolator("distance_to_iso0", "lat", "lon", var_key="z")

route = Route("crossing", [departure, cape_race, arrival])
voyage = Voyage("crossing", etd="2026-11-06T08:40", eta="2026-11-15T04:00", route=route)

analysis = RoutingAnalysis("analysis", vessel, voyage, atmosphere, wave, current, topography, variables=["max_bhp", "sails_contribution"])
report = analysis.run()

reports = ReportCollection([report])
print(reports.summary())
reports.save()                 # run ui.py to display the latest file
plot_report(report)            # the A4 page
```

The [user guide](../docs/user_guide.md) documents the data sources, the reports, the figures and the exclusion zones.

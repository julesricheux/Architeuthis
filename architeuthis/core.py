# -*- coding: utf-8 -*-
"""
Created on Mon Jan 19 15:54:06 2026

@author: jrich
"""


import architeuthis.numpy as np

from abc import abstractmethod
from typing import Sequence, Union
from architeuthis.vessel import Vessel
from architeuthis.common import _banner
from architeuthis.optimization import Opti
from architeuthis.icebergs import berg_zone
from architeuthis.forecast import Forecast, Topography
from architeuthis.common import ArchiteuthisObject, Datetime
from architeuthis.toolbox.geo_utils import great_circle_route, distances, midpoints, headings, poly_deviated_route


# Useful for broadcasting with matrices later.
def tall(array):
    return np.reshape(array, (-1, 1))


def wide(array):
    return np.reshape(array, (1, -1))


def added_wave_load(hs):
    a = 3.951610803604126 / 100. # regression 11/12/2025
    
    return a*hs

def sigmoid(x):
    return 2*np.arctan(x)/np.pi


def transform(x, delta):
    # return x
    # return 2 * (np.sigmoid(x) - 0.5) * delta
    return (sigmoid(x)) * tall(delta)


DEFAULT_SOLVER_OPTIONS = {
    "ipopt":{
        # "tol": 1e-3,
        "acceptable_tol": 1e9,

        # 'linear_solver': 'mumps',
        'linear_solver': 'spral',
        
        "hessian_approximation": "limited-memory",
    },
}

SOLVED = {
    "Solve_Succeeded",
    "Solved_To_Acceptable_Level",
}

exclusion_zones = [
    [
        [46.6475507, -53.0879974],
        [47.1448975, -52.6904297],
        [47.8057761, -52.6574707],
        [48.7272088, -53.0310059],
        [52.2547088, -55.5688477],
        [57.0646303, -61.6992188],
        [59.1759282, -64.0283203],
        [60.5221575, -64.8193359],
        [62.0833149, -66.2255859],
        [63.5485522, -70.3125000],
        [64.4348920, -73.6083984],
        [64.8862654, -77.3876953],
        [66.0715465, -86.4404297],
        [64.1681069, -92.1093750],
        [59.4450751, -96.6796875],
        [56.2677611, -95.9765625],
        [46.1950421, -92.7246094],
        [41.0793511, -87.6708984],
        [35.3532161, -75.9814453],
        [37.7620299, -77.0141602],
        [38.3761154, -76.9454956],
        [38.9935721, -76.8273926],
        [39.2577782, -76.3659668],
        [38.3416562, -75.9594727],
        [37.2980904, -75.9979248],
        [37.1121458, -75.9539795],
        [37.6164071, -75.5804443],
        [38.0351124, -75.2563477],
        [38.4084061, -75.0723267],
        [38.7883454, -75.0860596],
        [39.2705372, -74.6026611],
        [39.7747695, -74.1137695],
        [40.3904888, -73.9984131],
        [41.2881262, -70.7794189],
        [41.2365112, -69.9746704],
        [41.2943173, -69.9362183],
        [41.8347815, -69.9307251],
        [42.0615286, -70.0708008],
        [42.6440611, -70.5844116],
        [43.4130287, -70.4553223],
        [43.8345268, -68.8623047],
        [44.6881828, -67.1539307],
        [44.2412638, -66.3958740],
        [43.3930737, -66.0305786],
        [43.3850899, -65.6268311],
        [43.5007524, -65.2807617],
        [44.4631908, -63.5641479],
        [45.2555553, -60.9851074],
        [46.0045933, -59.6667480],
        [47.0252060, -60.3918457],
        [47.5394554, -59.2053223],
        [47.2549999, -55.9616089],
        [46.9146271, -55.9780884],
        [46.8414071, -55.8050537],
        [46.8733358, -55.3738403],
        [46.8188578, -54.1873169],
        [46.6098279, -53.5720825],
        [46.6263348, -53.1614685],
        [46.6484934, -53.0879974],
        [46.6475507, -53.0879974]
    ],
    # [
    #     [47.234906794905456, -2.298894594711654],
    #     [47.25856998567288, -2.4325583888579034],
    #     [47.29283375261824, -2.547348407391687],
    #     [47.472965041672204, -3.132757632163045],
    #     [47.643448179530274, -3.2076668170178877],
    #     [47.700395091200015, -3.368297468536256],
    #     [47.69636166917016, -3.4548323100507234],
    #     [47.79791598030666, -3.8522262539473218],
    #     [47.85365939763104, -3.980613066215874],
    #     [47.84328834623138, -4.041571653262067],
    #     [47.79730758529769, -4.187810231946969],
    #     [47.7951034723181, -4.380102394509618],
    #     [48.04251441805747, -4.732749036488459],
    #     [48.271675251256646, -4.616214170859991],
    #     [48.33235206326594, -4.766668801789211],
    #     [48.51970337432375, -4.781458461018697],
    #     [48.67589361128423, -4.353382869976883],
    #     [48.75347516979233, -4.009457823390732],
    #     [48.84141631708758, -3.5046081884123716],
    #     [48.89654815888168, -3.0605321526173523],
    #     [48.560105723588045, -2.671292321902763],
    #     [48.685993556279584, -2.318443857961514],
    #     [47.234906794905456, -2.298894594711654],
    # ],
    berg_zone,
]


#%%

class ArchiteuthisAnalysis(ArchiteuthisObject):
    
    @abstractmethod
    def __init__(
        self,
        name: str,
        verbose: bool = True,
    ):
        self.status = 0 # 0: not solved, 1: solved, 2: not converged
        
        super().__init__(name, verbose)
        
        
class Leg(ArchiteuthisObject):
    
    def __init__(
        self,
        name: str,
        departure: Sequence[float],
        arrival: Sequence[float],
        verbose: bool = True,
    ):
        self.departure = departure
        self.arrival = arrival
        
        self.distance = distances(
            np.asarray([departure[0], arrival[0]]),
            np.asarray([departure[1], arrival[1]]),
        )[0]
        
        super().__init__(name, verbose)
        
        
class Schedule(ArchiteuthisObject):
    
    def __init__(
        self,
        name: str,
        etd: Union[Datetime, list[Datetime]],
        eta: Union[Datetime, list[Datetime]],
        verbose: bool = True,
    ):
        self.etd = etd
        self.eta = eta
        
        self.transit_time = eta - etd
        
        super().__init__(name, verbose)
        
        
class Voyage(ArchiteuthisObject):
    
    def __init__(
        self,
        name: str,
        etd: Union[Datetime, list[Datetime]],
        eta: Union[Datetime, list[Datetime]],
        departure: Sequence[float],
        arrival: Sequence[float],
        verbose: bool = True,
        
        route_minus = None,
        route_ortho = None,
        route_plus = None,
    ):
        
        self.leg = Leg(f"{name}_leg", departure, arrival, verbose)
        self.schedule = Schedule(f"{name}_schedule", etd, eta, verbose)
        
        self.transit_time = (eta-etd)/3600.
        self.transit_sog = self.leg.distance * 3600 / (eta-etd)
        
        _default_route_function = poly_deviated_route(
            [self.departure[0], self.arrival[0]],
            [self.departure[1], self.arrival[1]],
            [0.])
        
        if route_minus is None:
            route_minus = _default_route_function
        if route_ortho is None:
            route_ortho = _default_route_function
        if route_plus is None:
            route_plus = _default_route_function
        
        self.route_minus = route_minus
        self.route_ortho = route_ortho
        self.route_plus = route_plus
        
        super().__init__(name, verbose)
        
    @property
    def departure(self):
        return self.leg.departure
        
    @property
    def arrival(self):
        return self.leg.arrival
        
    @property
    def distance(self):
        return self.leg.distance
    
    @property
    def etd(self):
        return self.schedule.etd
    
    @property
    def eta(self):
        return self.schedule.eta
        

# TODO find a name for the method?
class RoutingAnalysis(ArchiteuthisAnalysis):
    
    def __init__(
        self,
        name: str,
        vessel: Vessel,
        voyage: Voyage,
        # environment: Environment, # TODO rather use the Environment object? Find a way to handle the layers
        atmosphere: Forecast,
        wave: Forecast,
        current: Forecast,
        topography: Topography,
        atmosphere_member: float = None,
        wave_member: float = None,
        verbose: bool = True,
    ):
        self.vessel = vessel
        self.voyage = voyage
        # self.env = environment
        self.atmosphere = atmosphere
        self.wave = wave
        self.current = current
        self.topography = topography
        
        self.atmosphere_member = atmosphere_member
        self.wave_member = wave_member
        
        super().__init__(name, verbose)
        
    
    def check_valid_time(self):
        for forecast in [self.atmosphere, self.wave, self.current]:
            f00 = forecast.data["valid_time"].values[0]
            f99 = forecast.data["valid_time"].values[-3]
        
            if self.voyage.etd < f00:
                print(f"⚠️ Warning: ETD sooner than earliest {forecast.name.upper()} forecast valid time.")
            if self.voyage.eta > f99:
                print(f"⚠️ Warning: ETA later than furthest {forecast.name.upper()} forecast valid time.")
    
    def run(
        self,
        init_fac: float = 0.,
        vary_fac: bool = False,
        skip_tim: int = 0,
        max_iter: int = 1000,
        solver_options: dict = DEFAULT_SOLVER_OPTIONS,
        solve: bool = True,
    ):
            
        etd = self.voyage.etd
        eta = self.voyage.eta
        departure = self.voyage.departure
        arrival = self.voyage.arrival
        
        dist0 = self.voyage.distance
        
        transit_time = self.voyage.transit_time
        
        self.check_valid_time()
            
        # f00 = self.atmosphere.data["valid_time"].values[0] # earliest wind forecast
        # fxx = np.asarray(steps) * 3600 + f00 # TODO adapt steps to each analysis
        fxx = self.atmosphere.data.valid_time.values
        # f99 = self.atmosphere.data["valid_time"].values[-3] # latest actual wind forecast
        
        ctim0 = fxx[(fxx>etd) * (fxx<eta)][skip_tim::1+skip_tim]
        
        # assert (ctim0[-1] < f99), "ETA later than furthest forecast"
        
        tim0 = np.concatenate((
            [etd], 
            midpoints(ctim0),
            [eta], 
        ))
        
        npts = len(tim0)
        
        curv_abc = (tim0 - etd)/(eta - etd)
        
        print((departure, arrival, npts))
        _, _, dist0 = great_circle_route(departure, arrival, npts) # TODO initialize a sea route rather than a great circle route
        
        # TODO should port and starboard limits rather than loxo/ortho
        
        sog0 = self.voyage.transit_sog
        
        # TODO determine how much data can be handled at a time
        
        # xn = np.linspace(0, np.pi, npts)[1:-1]
        xn = np.linspace(0, 1., npts)[1:-1]
        
        delta = 4 * xn * (1-xn) * 1. #
        
        # initializing opti
        opti = Opti()
        
        if vary_fac and solve:
            deviation_fac = opti.variable(init_guess=init_fac)#, lower_bound=0., upper_bound=2.)
        else:
            deviation_fac = opti.parameter(init_fac)
            
        # init minus
        lat0minus, lon0minus = self.voyage.route_minus(curv_abc)
        
        # init ortho
        lat0ortho, lon0ortho = self.voyage.route_ortho(curv_abc)
        
        # init plus
        lat0plus, lon0plus = self.voyage.route_plus(curv_abc)
            
        lat0 = np.fmax(deviation_fac, 0) * lat0plus + (1-np.abs(deviation_fac)) * lat0ortho - np.fmin(deviation_fac, 0.) * lat0minus
        lon0 = np.fmax(deviation_fac, 0) * lon0plus + (1-np.abs(deviation_fac)) * lon0ortho - np.fmin(deviation_fac, 0.) * lon0minus
        
        # # init ortho
        # lat0ortho, lon0ortho = great_circle_path_points(departure, arrival, curv_abc)
        
        # # init loxo
        # lat0loxo = departure[0] * (1-curv_abc) + arrival[0] * curv_abc
        # lon0loxo = departure[1] * (1-curv_abc) + arrival[1] * curv_abc
        
        # lat0 = deviation_fac * lat0loxo + (1-deviation_fac) * lat0ortho
        # lon0 = deviation_fac * lon0loxo + (1-deviation_fac) * lon0ortho
        
        # TODO is it okay to have these uncontrained?
        if solve:
            vlon = opti.variable(n_vars=npts-2, init_guess=0.,)
            vlat = opti.variable(n_vars=npts-2, init_guess=0.,)
            # vlon = np.array([
            #    opti.variable(
            #         init_guess=0.,
            #         # lower_bound=-dist0/60/2*delta[i-1],
            #         # upper_bound=+dist0/60/2*delta[i-1],
            #     ) for i in range(1, npts-1)
            # ])
            # vlat = np.array([
            #    opti.variable(
            #         init_guess=0.,
            #         # lower_bound=-dist0/60/2*delta[i-1],
            #         # upper_bound=+dist0/60/2*delta[i-1],
            #     ) for i in range(1, npts-1)
            # ])
        else:
            vlon = 0.
            vlat = 0.
        
        tim = opti.parameter(n_params=npts)
        opti.set_value(tim, tim0)
        
        ctim = opti.parameter(n_params=npts-1)
        opti.set_value(ctim, ctim0)
        
        lon = np.concatenate((lon0[:1], lon0[1:-1] + vlon, lon0[-1:]))
        lat = np.concatenate((lat0[:1], lat0[1:-1] + vlat, lat0[-1:]))
        
        clon = midpoints(lon)
        clat = midpoints(lat)
        
        # TODO for backup
        environment_query = np.concatenate([
            ctim, clat, clon,
        ], axis=1)
        
        if self.atmosphere_member is not None:
            atm_mb = opti.parameter(n_params=npts-1)
            opti.set_value(atm_mb, self.atmosphere_member)
            atmosphere_query = np.concatenate([
                ctim, atm_mb, clat, clon,
            ], axis=1)
        else:
            atmosphere_query = environment_query
            
        if self.wave_member is not None:
            wav_mb = opti.parameter(n_params=npts-1)
            opti.set_value(wav_mb, self.wave_member)
            wave_query = np.concatenate([
                ctim, wav_mb, clat, clon,
            ], axis=1)
        else:
            wave_query = environment_query
            
        # environment_query = {
        #     "valid_time": ctim,
        #     "latitude": clat,
        #     "longitude": clon,
        # }
        
        # if self.atmosphere_member is not None:
        #     atm_mb = opti.parameter(n_params=npts-1)
        #     opti.set_value(atm_mb, self.atmosphere_member)
        
        #     atmosphere_query = {
        #         "valid_time": ctim,
        #         "number": atm_mb,
        #         "latitude": clat,
        #         "longitude": clon,
        #     }
        # else:
        #     atmosphere_query = environment_query
        
        # if self.wave_member is not None:
        #     wav_mb = opti.parameter(n_params=npts-1)
        #     opti.set_value(wav_mb, self.wave_member)
        
        #     wave_query = {
        #         "valid_time": ctim,
        #         "number": wav_mb,
        #         "latitude": clat,
        #         "longitude": clon,
        #     }
        # else:
        #     wave_query = environment_query
        
        u10 = self.atmosphere("u10", atmosphere_query) # eastward tws10 in m/s
        v10 = self.atmosphere("v10", atmosphere_query) # northward tws10 in m/s
        
        swh = self.wave("swh", wave_query)
        mwd = self.wave("mwd", wave_query)
        
        uc = self.current("uo", environment_query) * 3600./1852. # eastward current in kts
        vc = self.current("vo", environment_query) * 3600./1852. # northward current in kts
        
        # TODO for backup
        topography_query = np.concatenate([
            # lat,
            # lon,
            # clat,
            # clon,
            np.concatenate((lat[1:-1], clat)),
            np.concatenate((lon[1:-1], clon)),
        ], axis=1) # TODO need for higher topography resolution to avoid land
        
        # topography_query = {
        #     "latitude": np.concatenate((lat[1:-1], clat)),
        #     "longitude": np.concatenate((lon[1:-1], clon)),
        # }
        
        z = self.topography("z", topography_query)
        
        tws = np.sqrt(u10**2. + v10**2.) * 3600./1852. # wind speed in kts
        twd = np.mod(np.arctan2d(u10, v10)+180., 360.) # wind direction from 0 to 360 deg
        
        # TODO find why east/north wave generates unstability
        # swh = np.sqrt(uw**2. + vw**2.)
        # mwd = np.mod(np.arctan2d(uw, vw)+180, 360.)
        
        # tcs = np.sqrt(u10**2. + v10**2.) # current speed in kts
        # tcd = np.mod(np.arctan2d(uc, vc), 360.) # current going to from 0 to 360 deg
        
        cog = headings(lat, lon)
        
        # dlat = np.diff(lat)
        # dlon = np.diff(lon) * np.cosd(clat) # local east–west distance correction
        
        twa = np.mod(twd-cog + 180., 360.) - 180
        mwa = np.mod(mwd-cog + 180., 360.) - 180
        
        # twa = np.zeros(npts-1) + 90*np.ones(npts-1)
        # mwa = np.zeros(npts-1)
        d = distances(lat, lon)
        dt = np.diff(tim) / 3600.
        sog = d/dt
        
        # cog_r = np.radians(cog)
        # tcd_r = np.radians(tcd)
        
        duog = sog * np.sind(cog) # eastward sog in kts
        dvog = sog * np.cosd(cog) # northward sog in kts
        
        # norm = np.sqrt(dlat**2. + dlon**2. + 1e-9)
        
        # duog = sog * dlat / norm
        # dvog = sog * dlon / norm
        
        dutw = duog - uc # eastward stw in kts
        dvtw = dvog - vc # northward stw in kts
        
        # TODO compute stw
        
        stw = np.sqrt(dutw**2. + dvtw**2.) # stw norm in kts
        ctw = np.mod(np.arctan2d(dutw, dvtw), 360.) # course through water from 0 to 360
        
        # stw = sog
        
        # TODO for backup
        vessel_query = np.concatenate([
            stw, tws, np.abs(twa), swh, np.abs(mwa),
        ], axis=1)
        
        # vessel_query = {
        #     "stw": stw,
        #     "tws": tws,
        #     "twa": np.abs(twa),
        #     "swh": swh,
        #     "mwa": np.abs(mwa),
        # }
        
        avg_bhp = self.vessel("bhp", vessel_query)
        max_bhp = self.vessel("max_bhp", vessel_query)
        # leeway = vessel("leeway", vessel_query)        
        sc = self.vessel("sails_contribution", vessel_query)
        
        hotel_load = self.vessel.hotel_load(avg_bhp) # kW
        
        sfc = self.vessel.sfc(avg_bhp+hotel_load) # g/kWh
        
        consumption = np.abs(avg_bhp + hotel_load) * dt # kWh
        
        fuel = np.sum(consumption * sfc) / 1e6 # tons # TODO get rid of sfc to rather have f(power) = cons
        
        cons = []
        
        # cons.append(np.max(stranded) < minDepth) # TODO constraint land
        # cons.append(lon >= minimum_longitude)
        # cons.append(lon <= maximum_longitude)
        # cons.append(lat >= minimum_latitude)
        # cons.append(lat <= maximum_latitude)
        
        # cons.append(stw <= maxSTW)
        # cons.append(swh < maxSWH)
        cons.append(max_bhp < self.vessel.max_power)
        cons.append((wide(z) @ tall(z)) == 0.)
        # cons.append(z == 0.)
        
        if solve:
            opti.subject_to(cons)
            opti.minimize(fuel)
        
        if self.verbose:
            print(_banner)
        
        sol = opti.solve(
            max_iter=max_iter,
            behavior_on_failure="return_last",
            options=solver_options,
            # callback=callback,
        )
        
        status = 1 if opti.return_status() in SOLVED else 2
        
        self.opti = opti
        self.sol = sol
        self.status = status
        
        # # reports = []
        
        return {
            "etd" : etd,
            "eta" : eta,
            "transit_sog" : sog0,
            "transit_time" : transit_time,
            "init_fac": init_fac,
            "fuel" : sol(fuel),
            "stw" : sol(stw),
            "sog" : sol(sog),
            "cog" : sol(cog),
            "ctw" : sol(ctw),
            # "leeway" : sol(leeway),
            "tws" : sol(tws),
            "twd" : sol(twd),
            "twa" : sol(twa),
            "swh" : sol(swh),
            "mwd" : sol(mwd),
            "mwa" : sol(mwa),
            "z" : sol(z),
            "avg_bhp" : sol(avg_bhp),
            "hotel_load" : sol(hotel_load),
            "sfc" : sol(sfc),
            "consumption" : sol(consumption),
            "max_bhp" : sol(max_bhp),
            "sails_contribution" : sol(sc),
            "pos": [[la, lo] for la, lo in zip(sol(lat), sol(lon))],
            "tim": sol(tim),
            "lat": sol(lat),
            "lon": sol(lon),
            "cpos": [[cla, clo] for cla, clo in zip(sol(clat), sol(clon))],
            "ctim": sol(ctim),
            "clat": sol(clat),
            "clon": sol(clon),
            # "valid_time": sol(vtim),
            "dist": sol(np.sum(d)),
            "dist_rel": sol(np.sum(d)/dist0),
            "status": status,
        }

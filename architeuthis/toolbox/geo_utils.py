# -*- coding: utf-8 -*-
"""
Created on Fri Dec 12 14:18:00 2025

@author: jrich
"""


import casadi as ca
# import jax.numpy as jnp
import architeuthis.numpy as np

from pyproj import Geod


def great_circle_route(p1, p2, nPoints):
    # use great circle formula for a perfect sphere.
    a = 6378.137 / 1.852  # semi-major axis (equatorial radius) in nmi
    b = 6356.752 / 1.852  # semi-minor axis (polar radius) in nmi
    
    lat1, lon1 = p1
    lat2, lon2 = p2
    
    # from mpl_toolkits.Basemap.drawgreatcircle method
    gc = Geod(a=a, b=b)
    az12, az21, dist = gc.inv(lon1, lat1, lon2, lat2)
    # npoints = np.ceil((dist + 0.5 * 1000. * del_s) / (1000. * del_s))
    lonlats = gc.npts(lon1, lat1, lon2, lat2, nPoints-2)
    lons = [lon1]
    lats = [lat1]
    for lon, lat in lonlats:
        lons.append(lon)
        lats.append(lat)
    lons.append(lon2)
    lats.append(lat2)
    
    return np.array(lats), np.array(lons), dist


def distances(lats, lons):
    """
    Calculate the great-circle distances between consecutive points
    on the Earth using the Haversine formula.
    
    Parameters:
    lats: Array of latitudes in decimal degrees
    lons: Array of longitudes in decimal degrees
    
    Returns:
    Array of distances between each consecutive pair of points in nautical miles
    """
    
    # Convert latitude and longitude from degrees to radians
    lats = np.radians(lats)
    lons = np.radians(lons)
    
    # Differences in latitude and longitude
    dlat = np.diff(lats)
    dlon = np.diff(lons)
    
    # Haversine formula
    a = np.sin(dlat / 2)**2 + np.cos(lats[:-1]) * np.cos(lats[1:]) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    
    # Radius of the Earth in nautical miles
    R = 3440.065 # nmi
    
    # Distance in nautical miles
    distances = R * c
    
    return distances


def headings(lats, lons):
    """
    Compute headings (0–360°) between successive geographic points.

    Parameters
    ----------
    lats : array_like
        Latitudes of the points in degrees. Must have shape (N+1,).
    lons : array_like
        Longitudes of the points in degrees. Must have shape (N+1,).

    Returns
    -------
    headings : ndarray
        Array of shape (N,) containing the heading from each point i
        to point i+1, expressed in degrees clockwise from true North,
        normalized to the [0, 360) interval.

    Notes
    -----
    • Uses a simple local Cartesian approximation:
        dx = Δlon * cos(lat)
        dy = Δlat
    • For small step-to-step distances this is sufficiently accurate.
    • If a great-circle heading is required, say so and I will provide
      a fully geodesic version.

    """

    dlat = np.diff(lats)
    dlon = np.diff(lons)

    # local east–west distance correction
    dlon_scaled = dlon * np.cos(np.radians(lats[:-1]))

    angles = np.degrees(np.arctan2(dlon_scaled, dlat))  # atan2(x_east, y_north)

    # convert from [-180,180) to [0,360)
    return np.mod(angles, 360.0)


def midpoints(pts):
    
    return (pts[:-1] + pts[1:]) / 2


def resample_coordinates(lat, lon, n):
    
    if n <= 0:
        return lat, lon

    # Calculate step fractions (e.g., for n=1: t_vals = [0.0, 0.5])
    t_vals = np.linspace(0, 1, n + 2)[:-1]
    
    new_lats = []
    new_lons = []
    
    # lat.shape[0] safely gets the length of a CasADi vector or Numpy array
    num_points = lat.shape[0]
    
    # Build the interpolation point-by-point
    for i in range(num_points - 1):
        for t in t_vals:
            new_lats.append(lat[i] * (1 - t) + lat[i+1] * t)
            new_lons.append(lon[i] * (1 - t) + lon[i+1] * t)
            
    # Append the final destination point
    new_lats.append(lat[-1])
    new_lons.append(lon[-1])
    
    return np.concatenate(new_lats), np.concatenate(new_lons)


def great_circle_path_points(
        p1,
        p2,
        abscissas,
):
    """
    Computes intermediate points along the great circle.

    abscissas : array-like in [0,1], meaning 0=first point, 1=second point.
    Returns arrays (lat_deg, lon_deg) of the same shape.
    """
    
    lat1_deg, lon1_deg = p1
    lat2_deg, lon2_deg = p2

    lat1 = np.radians(lat1_deg)
    lon1 = np.radians(lon1_deg)
    lat2 = np.radians(lat2_deg)
    lon2 = np.radians(lon2_deg)

    # Angle between the two points (central angle)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    )
    delta = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))  # central angle

    # Avoid division by zero in the degenerate case
    # Use smooth maximum (still differentiable)
    eps = 1e-12
    delta_safe = delta + eps

    # Spherical linear interpolation (slerp)
    f = np.asarray(abscissas)[..., None]  # ensure broadcasting

    sin_delta = np.sin(delta_safe)

    A = np.sin((1.0 - f) * delta_safe) / sin_delta
    B = np.sin(f * delta_safe) / sin_delta

    # Convert endpoints to 3D Cartesian vectors
    x1 = np.cos(lat1) * np.cos(lon1)
    y1 = np.cos(lat1) * np.sin(lon1)
    z1 = np.sin(lat1)

    x2 = np.cos(lat2) * np.cos(lon2)
    y2 = np.cos(lat2) * np.sin(lon2)
    z2 = np.sin(lat2)

    # Interpolated vectors
    x = A * x1 + B * x2
    y = A * y1 + B * y2
    z = A * z1 + B * z2

    # Renormalize (slerp guarantees unit vectors except for eps)
    norm = np.sqrt(x * x + y * y + z * z)
    x /= norm
    y /= norm
    z /= norm

    # Back to lat/lon
    lat = np.arctan2(z, np.sqrt(x * x + y * y))
    lon = np.arctan2(y, x)

    return np.degrees(lat.squeeze()), np.degrees(lon.squeeze())


# Earth radius in nautical miles
_R_NMI = 3440.065
_deg2rad = np.pi / 180.0
_rad2deg = 180.0 / np.pi

def _ensure_column(x):
    """Return CasADi column vector (DM or MX) for input x (np array, list, DM, MX)."""
    # numpy / list -> DM
    if isinstance(x, (list, tuple, np.ndarray)):
        xd = ca.DM(np.asarray(x).ravel())
        return ca.reshape(xd, (xd.size1(), 1))
    # DM
    if isinstance(x, ca.DM):
        return ca.reshape(x, (x.size1(), 1))
    # MX / SX / any CasADi type: try reshape to column
    # If x already column shape, this will keep it
    try:
        return ca.reshape(x, (x.size1(), 1))
    except Exception:
        # fallback: convert to DM then reshape
        xd = ca.DM(x)
        return ca.reshape(xd, (xd.size1(), 1))

def distances_casadi(lats, lons):
    """
    CasADi-compatible great-circle distances (Haversine) between successive points.

    Inputs
    ------
    lats, lons : array-like or CasADi vector
        Latitude and longitude arrays in degrees. Shape (N,) or (N,1).
    Returns
    -------
    d : CasADi column vector of length N-1
        Distances between consecutive points in nautical miles.
    """
    φ = _ensure_column(lats) * (_deg2rad)   # radians (N,1)
    λ = _ensure_column(lons) * (_deg2rad)

    φ1 = φ[:-1, 0]
    φ2 = φ[1:, 0]
    λ1 = λ[:-1, 0]
    λ2 = λ[1:, 0]

    dφ = φ2 - φ1
    dλ = λ2 - λ1

    sin_dφ2 = ca.sin(dφ/2)
    sin_dλ2 = ca.sin(dλ/2)
    a = sin_dφ2**2 + ca.cos(φ1) * ca.cos(φ2) * (sin_dλ2**2)
    # numerical safety: clamp a to [0,1] isn't necessary usually, but keep robust
    # c = 2 * atan2(sqrt(a), sqrt(1-a))
    c = 2 * ca.atan2(ca.sqrt(a), ca.sqrt(1 - a))
    d = _R_NMI * c

    # return column vector (N-1,1)
    return ca.reshape(d, (d.size1(), 1))


def headings_casadi(lats, lons):
    """
    CasADi-compatible great-circle initial bearings between successive points.

    Inputs
    ------
    lats, lons : array-like or CasADi vector
        Latitudes and longitudes in degrees. Shape (N,) or (N,1).
    Returns
    -------
    bearings : CasADi column vector of length N-1
        Initial bearing from point i to i+1 in degrees, in [0, 360).
    """
    φ = _ensure_column(lats) * (_deg2rad)   # radians (N,1)
    λ = _ensure_column(lons) * (_deg2rad)

    φ1 = φ[:-1, 0]
    φ2 = φ[1:, 0]
    λ1 = λ[:-1, 0]
    λ2 = λ[1:, 0]

    dλ = λ2 - λ1

    y = ca.sin(dλ) * ca.cos(φ2)
    x = ca.cos(φ1) * ca.sin(φ2) - ca.sin(φ1) * ca.cos(φ2) * ca.cos(dλ)

    θ = ca.atan2(y, x)               # radians in [-pi, pi]
    deg = θ * (_rad2deg)             # degrees in [-180, 180]
    # normalize to [0, 360)
    # Use fmod on positive argument: deg + 360 then fmod 360
    bearing = ca.fmod(deg + 360.0, 360.0)

    return ca.reshape(bearing, (bearing.size1(), 1))

# midpoints function: implement using CasADi so result is symbolic MX
def midpoints_casadi(x):
    # x is a column vector (npts,)
    # returns column vector with npts-1 entries
    return 0.5*(x[1:] + x[:-1])


def sph_to_cart(lat, lon):
    lat = np.radians(lat)
    lon = np.radians(lon)
    return np.array([
        np.cos(lat) * np.cos(lon),
        np.cos(lat) * np.sin(lon),
        np.sin(lat),
    ])


def cart_to_sph(v):
    """
    v: array of shape (3, N)
    returns lat, lon arrays of length N
    """
    v = v / np.linalg.norm(v, axis=0, keepdims=True)
    lat = np.degrees(np.arcsin(v[2, :]))
    lon = np.degrees(np.arctan2(v[1, :], v[0, :]))
    return lat, lon



def deviated_gc_segment(lat0, lon0, lat1, lon1, divergence):

    p0 = sph_to_cart(lat0, lon0)
    p1 = sph_to_cart(lat1, lon1)

    omega = np.arccos(np.clip(np.dot(p0, p1), -1.0, 1.0))

    # Fixed GC normal
    n = np.cross(p0, p1)
    n = n / np.linalg.norm(n)

    def f(s):
        s = np.asarray(s)

        # --- Slerp (correct) ---
        a = np.sin((1 - s) * omega) / np.sin(omega)
        b = np.sin(s * omega) / np.sin(omega)

        p = (a[:, None] * p0 + b[:, None] * p1)
        p = p / np.linalg.norm(p, axis=1)[:, None]

        # --- Local tangent along GC ---
        t = np.cross(n, p)
        t = t / np.linalg.norm(t, axis=1)[:, None]

        # --- Cross-track normal (this was missing) ---
        c = np.cross(p, t)

        # --- Sinusoidal offset ---
        delta = divergence * 0.5 * omega * np.sin(np.pi * s)

        p_dev = (
            np.cos(delta)[:, None] * p +
            np.sin(delta)[:, None] * c
        )

        lat, lon = cart_to_sph(p_dev.T)
        return lat, lon

    return f


# def poly_deviated_route(lats, lons, divergences):
#     """
#     lats, lons: length n
#     divergences: length n-1
#     """

#     assert len(lats) == len(lons)
#     assert len(divergences) == len(lats) - 1

#     segments = [
#         deviated_gc_segment(
#             lats[i], lons[i],
#             lats[i+1], lons[i+1],
#             divergences[i]
#         )
#         for i in range(len(divergences))
#     ]

#     def route(s):
#         """
#         s in [0, 1], returns lat(s), lon(s)
#         """
#         s = np.asarray(s)
#         seg_id = np.clip((s * len(segments)).astype(int), 0, len(segments) - 1)
#         local_s = s * len(segments) - seg_id

#         lat = np.empty_like(s, dtype=float)
#         lon = np.empty_like(s, dtype=float)

#         for i, seg in enumerate(segments):
#             mask = seg_id == i
#             if np.any(mask):
#                 lat[mask], lon[mask] = seg(local_s[mask])

#         return lat, lon

#     return route


def poly_deviated_route(lats, lons, divergences=None):
    
    if divergences == None:
        divergences = np.zeros(len(lats) - 1)

    assert len(lats) == len(lons)
    assert len(divergences) == len(lats) - 1

    # --- Precompute segment lengths (angular) ---
    pts = [sph_to_cart(lat, lon) for lat, lon in zip(lats, lons)]

    omegas = []
    for i in range(len(pts) - 1):
        omega = np.arccos(np.clip(np.dot(pts[i], pts[i+1]), -1.0, 1.0))
        omegas.append(omega)

    omegas = np.array(omegas)
    cumlen = np.concatenate(([0], np.cumsum(omegas)))
    total_len = cumlen[-1]
    cumlen_norm = cumlen / total_len

    # --- Build segment functions ---
    segments = [
        deviated_gc_segment(
            lats[i], lons[i],
            lats[i+1], lons[i+1],
            divergences[i]
        )
        for i in range(len(divergences))
    ]

    def route(s):

        s = np.asarray(s)

        lat = np.empty_like(s, dtype=float)
        lon = np.empty_like(s, dtype=float)

        # For each segment
        for i in range(len(segments)):

            mask = (
                (s >= cumlen_norm[i]) &
                (s <= cumlen_norm[i+1])
            )

            if not np.any(mask):
                continue

            # Local normalized parameter in segment
            local_s = (
                (s[mask] - cumlen_norm[i]) /
                (cumlen_norm[i+1] - cumlen_norm[i])
            )

            lat[mask], lon[mask] = segments[i](local_s)

        return lat, lon

    return route


def lonlat_to_web_mercator(lon, lat):
    """Convert lon/lat in degrees to Web Mercator (EPSG:3857)."""
    R = 6378137.0  # Earth radius in meters
    x = np.radians(lon) * R
    y = np.log(np.tan(np.pi/4 + np.radians(lat)/2)) * R
    return x, y
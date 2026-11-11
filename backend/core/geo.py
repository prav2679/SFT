"""Geodesic helpers.

Horizontal position errors are reported as WGS-84 ellipsoidal geodesic distances (Vincenty inverse formula),
never as differences of latitude / longitude. Vincenty fails to converge only for nearly antipodal points; in
that case the great-circle (haversine) distance is returned instead (error < 0.5 %, irrelevant for balloon flights).
Note: the preserved SFT models advance positions on a spherical Earth (R = 6 371 000 m); that is a model property
and is not altered here.
"""
from __future__ import annotations

import math

WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
WGS84_B = WGS84_A * (1 - WGS84_F)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000.0 * math.asin(min(1.0, math.sqrt(a)))


def geodesic_m(lat1, lon1, lat2, lon2) -> float:
    """WGS-84 geodesic distance in metres between two points given in decimal degrees."""
    if (lat1, lon1) == (lat2, lon2):
        return 0.0
    L = math.radians(lon2 - lon1)
    U1 = math.atan((1 - WGS84_F) * math.tan(math.radians(lat1)))
    U2 = math.atan((1 - WGS84_F) * math.tan(math.radians(lat2)))
    sU1, cU1, sU2, cU2 = math.sin(U1), math.cos(U1), math.sin(U2), math.cos(U2)
    lam = L
    for _ in range(200):
        sl, cl = math.sin(lam), math.cos(lam)
        sin_sigma = math.hypot(cU2 * sl, cU1 * sU2 - sU1 * cU2 * cl)
        if sin_sigma == 0:
            return 0.0
        cos_sigma = sU1 * sU2 + cU1 * cU2 * cl
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cU1 * cU2 * sl / sin_sigma
        cos2_alpha = 1 - sin_alpha ** 2
        cos_2sm = cos_sigma - 2 * sU1 * sU2 / cos2_alpha if cos2_alpha != 0 else 0.0
        C = WGS84_F / 16 * cos2_alpha * (4 + WGS84_F * (4 - 3 * cos2_alpha))
        lam_prev = lam
        lam = L + (1 - C) * WGS84_F * sin_alpha * (
            sigma + C * sin_sigma * (cos_2sm + C * cos_sigma * (-1 + 2 * cos_2sm ** 2)))
        if abs(lam - lam_prev) < 1e-12:
            break
    else:
        return haversine_m(lat1, lon1, lat2, lon2)           # near-antipodal: no convergence
    u2 = cos2_alpha * (WGS84_A ** 2 - WGS84_B ** 2) / WGS84_B ** 2
    A = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
    B = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))
    d_sigma = B * sin_sigma * (cos_2sm + B / 4 * (cos_sigma * (-1 + 2 * cos_2sm ** 2) - B / 6 * cos_2sm * (
        -3 + 4 * sin_sigma ** 2) * (-3 + 4 * cos_2sm ** 2)))
    return WGS84_B * A * (sigma - d_sigma)


def initial_bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0

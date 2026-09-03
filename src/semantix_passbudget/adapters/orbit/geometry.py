"""Earth geometry for the orbit contact provider.

Every constant and convention here is fixed by `docs/specs/ORBIT_VERIFICATION_CONTRACT.md`.
Nothing in this module may be changed to make a comparison pass; a change here is a change
to the verification contract and requires an entry in its amendment log.

Floating point stays inside this module and its callers at full double precision. Quantisation
to canonical microseconds happens exactly once, in the provider, on the way out -- see ADR-0001
`Numerical contract`.
"""

from __future__ import annotations

import math

# --- WGS-84 station geodesy (contract section 4) -----------------------------------------
# Defining constants of the WGS-84 datum. These are exact by definition, not measurements.
WGS84_A_M = 6_378_137.0
WGS84_INVERSE_FLATTENING = 298.257223563
WGS84_F = 1.0 / WGS84_INVERSE_FLATTENING
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)

#: Seconds of UT1 per Julian century, used by the IAU-82 GMST series.
_SECONDS_PER_DAY = 86_400.0
_JULIAN_CENTURY_DAYS = 36_525.0
#: Julian date of the J2000.0 epoch, 2000-01-01T12:00:00 TT.
_JD_J2000 = 2_451_545.0


def geodetic_to_ecef(
    latitude_deg: float, longitude_east_deg: float, ellipsoidal_height_m: float
) -> tuple[float, float, float]:
    """WGS-84 geodetic position to Earth-fixed metres.

    `ellipsoidal_height_m` is height above the WGS-84 ellipsoid. It is never an orthometric
    or mean-sea-level height: no geoid model is applied anywhere in this project, and feeding
    an MSL height in here would displace the station by tens of metres.
    """
    lat = math.radians(latitude_deg)
    lon = math.radians(longitude_east_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    # Radius of curvature in the prime vertical.
    n = WGS84_A_M / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + ellipsoidal_height_m) * cos_lat * math.cos(lon)
    y = (n + ellipsoidal_height_m) * cos_lat * math.sin(lon)
    z = (n * (1.0 - WGS84_E2) + ellipsoidal_height_m) * sin_lat
    return x, y, z


def gmst82_rad(julian_date_ut1: float) -> float:
    """Greenwich Mean Sidereal Time, IAU-82 / FK5 series, in radians.

    This is the rotation that carries TEME to the pseudo-Earth-fixed frame in the standard
    SGP4 usage. Under the verification contract UT1 equals UTC exactly, so the caller passes a
    UTC-based Julian date; that simplification is recorded in contract section 2 together with
    the accuracy it costs.
    """
    t = (julian_date_ut1 - _JD_J2000) / _JULIAN_CENTURY_DAYS
    # Vallado, "Fundamentals of Astrodynamics and Applications", GMST82 in seconds of time.
    seconds = (
        67_310.54841
        + (876_600.0 * 3600.0 + 8_640_184.812866) * t
        + 0.093104 * t * t
        - 6.2e-6 * t * t * t
    )
    # Seconds of time -> radians, wrapped to [0, 2pi).
    radians = math.radians((seconds % _SECONDS_PER_DAY) / 240.0)
    return radians % (2.0 * math.pi)


def teme_to_ecef(
    position_teme_m: tuple[float, float, float], julian_date_ut1: float
) -> tuple[float, float, float]:
    """Rotate a TEME position into the Earth-fixed frame.

    Polar motion is zero by contract, so the pseudo-Earth-fixed frame and ITRF coincide and
    this is a single rotation about the Z axis. Reintroducing polar motion would require an EOP
    table and would make the two tools disagree about the table rather than about the physics.
    """
    theta = gmst82_rad(julian_date_ut1)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    x, y, z = position_teme_m
    return (cos_t * x + sin_t * y, -sin_t * x + cos_t * y, z)


def elevation_deg(
    satellite_ecef_m: tuple[float, float, float],
    station_ecef_m: tuple[float, float, float],
    station_latitude_deg: float,
    station_longitude_east_deg: float,
) -> float:
    """Geometric elevation above the station's local geodetic horizon, in degrees.

    The horizon is the plane normal to the *ellipsoid* at the station, not the plane normal to
    the geocentric radius. The two differ by up to about 0.19 degrees at mid latitudes, which is
    several times the whole elevation tolerance budget, so the distinction is not cosmetic.

    No refraction and no light-time correction is applied; both are disabled by contract.
    """
    lat = math.radians(station_latitude_deg)
    lon = math.radians(station_longitude_east_deg)
    dx = satellite_ecef_m[0] - station_ecef_m[0]
    dy = satellite_ecef_m[1] - station_ecef_m[1]
    dz = satellite_ecef_m[2] - station_ecef_m[2]
    # Local up unit vector (the ellipsoid normal).
    up_x = math.cos(lat) * math.cos(lon)
    up_y = math.cos(lat) * math.sin(lon)
    up_z = math.sin(lat)
    range_m = math.sqrt(dx * dx + dy * dy + dz * dz)
    if range_m == 0.0:
        return 90.0
    sin_elevation = (dx * up_x + dy * up_y + dz * up_z) / range_m
    # Guard the arcsine against a value nudged outside [-1, 1] by rounding.
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_elevation))))

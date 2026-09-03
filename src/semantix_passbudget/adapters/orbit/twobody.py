"""Two-body propagation and the EME2000 to Earth-fixed frame chain.

Used by the `VIRTUAL_CIRCULAR` fixture under propagator profile `TWO_BODY_V1`
(`docs/specs/ORBIT_VERIFICATION_CONTRACT.md` §7.2, resolved by `Q-DATA-03`).

Unlike the SGP4 path, whose state is born in TEME and reaches the Earth-fixed frame by a single
sidereal rotation, an EME2000 state needs the full IAU-76/FK5 reduction: precession, nutation,
apparent sidereal time, then polar motion (zero by contract).

**Accuracy budget for the truncated nutation series.** A frame rotation error of one arcsecond
displaces a station by about 31 m, and the satellite closes on a station at roughly 6.5 km/s, so
one arcsecond is worth about 4.8 ms of pass timing. The §10.1 ceiling of 1.000 s therefore
tolerates roughly 210 arcseconds of frame error. Precession is ~1300 arcseconds over this epoch
and must be modelled in full; nutation peaks near 17 arcseconds and the terms retained below leave
a residual under 0.1 arcsecond, worth under 0.5 ms. The truncation is thus three orders of
magnitude inside the budget, and it is a bounded, stated approximation rather than a silent one.
"""

from __future__ import annotations

import math

_ARCSEC_TO_RAD = math.pi / (180.0 * 3600.0)
_JD_J2000 = 2_451_545.0
_JULIAN_CENTURY_DAYS = 36_525.0

#: Contract §7.2. Stated explicitly because tool defaults differ in the last digits.
MU_EARTH_M3_S2 = 3.986004415e14

# IAU-1980 nutation series, the terms that matter at the accuracy stated above.
# Columns: multipliers of (l, l', F, D, Omega), then dPsi coefficients (A, A_dot) and
# dEps coefficients (B, B_dot), in units of 0.0001 arcsecond and 0.0001 arcsecond/century.
_NUTATION_TERMS: tuple[tuple[int, int, int, int, int, float, float, float, float], ...] = (
    (0, 0, 0, 0, 1, -171996.0, -174.2, 92025.0, 8.9),
    (0, 0, 2, -2, 2, -13187.0, -1.6, 5736.0, -3.1),
    (0, 0, 2, 0, 2, -2274.0, -0.2, 977.0, -0.5),
    (0, 0, 0, 0, 2, 2062.0, 0.2, -895.0, 0.5),
    (0, 1, 0, 0, 0, 1426.0, -3.4, 54.0, -0.1),
    (1, 0, 0, 0, 0, 712.0, 0.1, -7.0, 0.0),
    (0, 1, 2, -2, 2, -517.0, 1.2, 224.0, -0.6),
    (0, 0, 2, 0, 1, -386.0, -0.4, 200.0, 0.0),
    (1, 0, 2, 0, 2, -301.0, 0.0, 129.0, -0.1),
    (0, -1, 2, -2, 2, 217.0, -0.5, -95.0, 0.3),
    (1, 0, 0, -2, 0, -158.0, 0.0, -1.0, 0.0),
    (0, 0, 2, -2, 1, 129.0, 0.1, -70.0, 0.0),
    (-1, 0, 2, 0, 2, 123.0, 0.0, -53.0, 0.0),
    (1, 0, 0, 0, 1, 63.0, 0.1, -33.0, 0.0),
    (0, 0, 0, 2, 0, 63.0, 0.0, -2.0, 0.0),
    (-1, 0, 2, 2, 2, -59.0, 0.0, 26.0, 0.0),
    (-1, 0, 0, 0, 1, -58.0, -0.1, 32.0, 0.0),
    (1, 0, 2, 0, 1, -51.0, 0.0, 27.0, 0.0),
    (2, 0, 0, -2, 0, 48.0, 0.0, 1.0, 0.0),
    (-2, 0, 2, 0, 1, 46.0, 0.0, -24.0, 0.0),
    (0, 0, 2, 2, 2, -38.0, 0.0, 16.0, 0.0),
    (2, 0, 2, 0, 2, -31.0, 0.0, 13.0, 0.0),
    (2, 0, 0, 0, 0, 29.0, 0.0, -1.0, 0.0),
    (1, 0, 2, -2, 2, 29.0, 0.0, -12.0, 0.0),
    (0, 0, 2, 0, 0, 26.0, 0.0, -1.0, 0.0),
    (0, 0, 2, -2, 0, -22.0, 0.0, 0.0, 0.0),
    (-1, 0, 2, 0, 1, 21.0, 0.0, -10.0, 0.0),
    (0, 2, 0, 0, 0, 17.0, -0.1, 0.0, 0.0),
    (0, 2, 2, -2, 2, -16.0, 0.1, 7.0, 0.0),
    (-1, 0, 0, 2, 1, 16.0, 0.0, -8.0, 0.0),
)


def _julian_centuries(julian_date: float) -> float:
    return (julian_date - _JD_J2000) / _JULIAN_CENTURY_DAYS


def _delaunay(t: float) -> tuple[float, float, float, float, float]:
    """The five Delaunay fundamental arguments, radians."""
    l_moon = 485866.733 + (1325.0 * 1296000.0 + 715922.633) * t + 31.310 * t * t + 0.064 * t**3
    lp = 1287099.804 + (99.0 * 1296000.0 + 1292581.224) * t - 0.577 * t * t - 0.012 * t**3
    f = 335778.877 + (1342.0 * 1296000.0 + 295263.137) * t - 13.257 * t * t + 0.011 * t**3
    d = 1072261.307 + (1236.0 * 1296000.0 + 1105601.328) * t - 6.891 * t * t + 0.019 * t**3
    om = 450160.280 - (5.0 * 1296000.0 + 482890.539) * t + 7.455 * t * t + 0.008 * t**3
    return tuple((x % 1296000.0) * _ARCSEC_TO_RAD for x in (l_moon, lp, f, d, om))  # type: ignore[return-value]


def nutation(t: float) -> tuple[float, float, float]:
    """IAU-1980 nutation: (dPsi, dEps, mean obliquity), all radians."""
    l_moon, lp, f, d, om = _delaunay(t)
    d_psi = 0.0
    d_eps = 0.0
    for n_l, n_lp, n_f, n_d, n_om, a, a_dot, b, b_dot in _NUTATION_TERMS:
        argument = n_l * l_moon + n_lp * lp + n_f * f + n_d * d + n_om * om
        d_psi += (a + a_dot * t) * math.sin(argument)
        d_eps += (b + b_dot * t) * math.cos(argument)
    # Coefficients are in units of 0.0001 arcsecond.
    d_psi *= 1e-4 * _ARCSEC_TO_RAD
    d_eps *= 1e-4 * _ARCSEC_TO_RAD
    mean_obliquity = (84381.448 - 46.8150 * t - 0.00059 * t * t + 0.001813 * t**3) * _ARCSEC_TO_RAD
    return d_psi, d_eps, mean_obliquity


def _rot_x(v: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    c, s = math.cos(angle), math.sin(angle)
    return (v[0], c * v[1] + s * v[2], -s * v[1] + c * v[2])


def _rot_y(v: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    c, s = math.cos(angle), math.sin(angle)
    return (c * v[0] - s * v[2], v[1], s * v[0] + c * v[2])


def _rot_z(v: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    c, s = math.cos(angle), math.sin(angle)
    return (c * v[0] + s * v[1], -s * v[0] + c * v[1], v[2])


def eme2000_to_ecef(
    position_m: tuple[float, float, float], julian_date_utc: float
) -> tuple[float, float, float]:
    """EME2000 (J2000) to Earth-fixed, via the IAU-76/FK5 reduction.

    UT1 equals UTC and polar motion is zero by contract §2, so the final step is a rotation by
    apparent sidereal time alone and the pseudo-Earth-fixed frame coincides with ITRF.
    """
    t = _julian_centuries(julian_date_utc)

    # IAU-76 precession, J2000 to mean-of-date.
    zeta = (2306.2181 * t + 0.30188 * t * t + 0.017998 * t**3) * _ARCSEC_TO_RAD
    theta = (2004.3109 * t - 0.42665 * t * t - 0.041833 * t**3) * _ARCSEC_TO_RAD
    z = (2306.2181 * t + 1.09468 * t * t + 0.018203 * t**3) * _ARCSEC_TO_RAD
    # R3(-z) R2(theta) R3(-zeta). The middle rotation is about Y, not X: theta is the
    # obliquity-like tilt of the mean equator about the node, and rotating about the wrong axis
    # leaves the in-plane angle nearly right while tilting the pole by the full precession
    # angle, which is how this was originally wrong and how the oracle caught it.
    mod = _rot_z(_rot_y(_rot_z(position_m, -zeta), theta), -z)

    # Nutation, mean-of-date to true-of-date.
    d_psi, d_eps, eps_mean = nutation(t)
    eps_true = eps_mean + d_eps
    tod = _rot_x(_rot_z(_rot_x(mod, eps_mean), -d_psi), -eps_true)

    # Apparent sidereal time. The equation of the equinoxes is what separates GAST from GMST;
    # omitting it would leave up to about 1.1 arcseconds, which is small but free to include.
    from .geometry import gmst82_rad

    equation_of_equinoxes = d_psi * math.cos(eps_true)
    gast = gmst82_rad(julian_date_utc) + equation_of_equinoxes
    return _rot_z(tod, gast)


def propagate_two_body(
    position_m: tuple[float, float, float],
    velocity_m_s: tuple[float, float, float],
    elapsed_s: float,
    mu: float = MU_EARTH_M3_S2,
) -> tuple[float, float, float]:
    """Kepler propagation of an inertial state by `elapsed_s`, returning position only.

    Solved through the classical elements rather than by numerical integration: the two-body
    problem has a closed-form solution, so integrating it would add truncation error to a
    fixture whose whole purpose is to have none.
    """
    r = math.sqrt(sum(component * component for component in position_m))
    v2 = sum(component * component for component in velocity_m_s)
    energy = v2 / 2.0 - mu / r
    a = -mu / (2.0 * energy)

    # Eccentricity vector and the orbit's orientation.
    rv_dot = sum(p * q for p, q in zip(position_m, velocity_m_s, strict=True))
    e_vec = tuple(
        (v2 - mu / r) * position_m[i] / mu - rv_dot * velocity_m_s[i] / mu for i in range(3)
    )
    e = math.sqrt(sum(component * component for component in e_vec))

    n = math.sqrt(mu / (a * a * a))

    # Eccentric anomaly now, from the radial distance and the sign of the radial velocity.
    cos_ecc = (1.0 - r / a) / e if e > 1e-12 else 0.0
    cos_ecc = max(-1.0, min(1.0, cos_ecc))
    ecc_anomaly = math.acos(cos_ecc)
    if rv_dot < 0.0:
        ecc_anomaly = 2.0 * math.pi - ecc_anomaly
    mean_anomaly = ecc_anomaly - e * math.sin(ecc_anomaly) + n * elapsed_s

    # Kepler's equation. Newton converges in a handful of steps for a near-circular orbit.
    ecc_new = mean_anomaly
    for _ in range(60):
        delta = (ecc_new - e * math.sin(ecc_new) - mean_anomaly) / (1.0 - e * math.cos(ecc_new))
        ecc_new -= delta
        if abs(delta) < 1e-14:
            break

    # Lagrange f and g coefficients carry the state forward in its own plane.
    f = 1.0 - a / r * (1.0 - math.cos(ecc_new - ecc_anomaly))
    g = elapsed_s - math.sqrt(a**3 / mu) * (
        (ecc_new - ecc_anomaly) - math.sin(ecc_new - ecc_anomaly)
    )
    return tuple(f * position_m[i] + g * velocity_m_s[i] for i in range(3))  # type: ignore[return-value]


def circular_state_from_elements(
    semi_major_axis_m: float,
    inclination_deg: float,
    raan_deg: float,
    argument_of_perigee_deg: float,
    true_anomaly_deg: float,
    eccentricity: float = 0.0,
    mu: float = MU_EARTH_M3_S2,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Classical elements to an EME2000 position and velocity."""
    i = math.radians(inclination_deg)
    raan = math.radians(raan_deg)
    argp = math.radians(argument_of_perigee_deg)
    nu = math.radians(true_anomaly_deg)

    p = semi_major_axis_m * (1.0 - eccentricity * eccentricity)
    r = p / (1.0 + eccentricity * math.cos(nu))

    # Perifocal frame.
    r_pqw = (r * math.cos(nu), r * math.sin(nu), 0.0)
    v_pqw = (
        -math.sqrt(mu / p) * math.sin(nu),
        math.sqrt(mu / p) * (eccentricity + math.cos(nu)),
        0.0,
    )

    def to_inertial(v: tuple[float, float, float]) -> tuple[float, float, float]:
        # Perifocal to EME2000: R3(-raan) R1(-i) R3(-argp).
        return _rot_z(_rot_x(_rot_z(v, -argp), -i), -raan)

    return to_inertial(r_pqw), to_inertial(v_pqw)

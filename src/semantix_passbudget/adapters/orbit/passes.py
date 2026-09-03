"""Pass finding for the orbit contact provider.

Implements the event definitions in `docs/specs/ORBIT_VERIFICATION_CONTRACT.md` sections 8
and 9 on top of an SGP4 propagator. Everything here is deterministic: no randomness, no
wall-clock reads, no environment reads, no filesystem access.

Design note. This module deliberately does not import anything from `domain/` or
`application/`. It is a pure geometry service, so the provider that adapts it to
`ContactProvider` can be thin and the architecture test can keep proving that the domain
never sees an orbit library. See ADR-0004.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sgp4.api import Satrec

from .geometry import elevation_deg, geodetic_to_ecef, teme_to_ecef
from .twobody import eme2000_to_ecef, propagate_two_body

_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
#: Julian date of the Unix epoch, used to turn UTC seconds into the (jd, fr) pair SGP4 wants.
_JD_UNIX_EPOCH = 2_440_587.5
_SECONDS_PER_DAY = 86_400.0

#: Contract section 8.3. Coarse enough to be cheap, fine enough that no pass can hide inside
#: one step: the shortest geometrically possible 5-degree-mask pass for a LEO orbit is on the
#: order of a minute.
BRACKET_STEP_S = 10.0
#: Contract section 8.1. Three orders of magnitude below the acceptance ceiling, so the solver
#: cannot be what the delta table is measuring.
CROSSING_TOLERANCE_S = 1e-6
#: Peak location only. The peak *value* converges quadratically faster than its time, because
#: dE/dt vanishes there -- which is also why the contract allows a looser ceiling on peak time.
PEAK_TOLERANCE_S = 1e-4


@dataclass(frozen=True, slots=True)
class StationSite:
    """A ground station's fixed geodetic position and its constant elevation mask."""

    station_key: str
    latitude_deg: float
    longitude_east_deg: float
    ellipsoidal_height_m: float
    minimum_elevation_deg: float


@dataclass(frozen=True, slots=True)
class PassEvent:
    """One contact, already clipped to the analysis window."""

    station_key: str
    stable_key: str
    aos: datetime
    los: datetime
    duration_s: float
    maximum_elevation_deg: float
    maximum_elevation_time: datetime
    clipped_start: bool
    clipped_end: bool

    @property
    def aos_is_true_crossing(self) -> bool:
        return not self.clipped_start

    @property
    def los_is_true_crossing(self) -> bool:
        return not self.los_clipped

    @property
    def los_clipped(self) -> bool:
        return self.clipped_end


def _to_julian(moment_s: float) -> tuple[float, float]:
    """Split UTC seconds-since-Unix-epoch into the (whole, fractional) Julian date SGP4 wants.

    Kept as two floats rather than one so that a microsecond stays resolvable: a single double
    holding a Julian date near 2.46e6 has a resolution of only about 40 microseconds.
    """
    days = moment_s / _SECONDS_PER_DAY
    jd = _JD_UNIX_EPOCH + math.floor(days)
    fr = days - math.floor(days)
    return jd, fr


class _ElevationCurve:
    """Elevation of one satellite seen from one station, as a function of UTC seconds.

    The propagator is injected as an Earth-fixed position source, so pass finding, clipping,
    peak location and ordering are written once and shared by every propagator profile. Only
    the dynamics and the frame chain differ between fixtures.
    """

    def __init__(
        self, ecef_at: Callable[[float], tuple[float, float, float]], site: StationSite
    ) -> None:
        self._ecef_at = ecef_at
        self._site = site
        self._station_ecef = geodetic_to_ecef(
            site.latitude_deg, site.longitude_east_deg, site.ellipsoidal_height_m
        )

    def __call__(self, moment_s: float) -> float:
        return elevation_deg(
            self._ecef_at(moment_s),
            self._station_ecef,
            self._site.latitude_deg,
            self._site.longitude_east_deg,
        )


def sgp4_position_source(
    tle_line_1: str, tle_line_2: str
) -> Callable[[float], tuple[float, float, float]]:
    """Earth-fixed position from SGP4, for the `GP_TLE` fixture."""
    satellite = Satrec.twoline2rv(tle_line_1, tle_line_2)

    def at(moment_s: float) -> tuple[float, float, float]:
        jd, fr = _to_julian(moment_s)
        error, position_km, _velocity = satellite.sgp4(jd, fr)
        if error != 0:
            raise OrbitPropagationError(error)
        position_m = (position_km[0] * 1000.0, position_km[1] * 1000.0, position_km[2] * 1000.0)
        return teme_to_ecef(position_m, jd + fr)

    return at


def two_body_position_source(
    epoch_s: float,
    position_eme2000_m: tuple[float, float, float],
    velocity_eme2000_m_s: tuple[float, float, float],
    mu: float,
) -> Callable[[float], tuple[float, float, float]]:
    """Earth-fixed position from Kepler propagation, for the `VIRTUAL_CIRCULAR` fixture."""

    def at(moment_s: float) -> tuple[float, float, float]:
        inertial = propagate_two_body(
            position_eme2000_m, velocity_eme2000_m_s, moment_s - epoch_s, mu
        )
        jd, fr = _to_julian(moment_s)
        return eme2000_to_ecef(inertial, jd + fr)

    return at


class OrbitPropagationError(RuntimeError):
    """SGP4 refused to propagate. Carries the library's numeric code, never a host path."""

    def __init__(self, code: int) -> None:
        super().__init__(f"SGP4 propagation failed with code {code}")
        self.code = code


def _refine_crossing(curve: _ElevationCurve, mask: float, low: float, high: float) -> float:
    """Bisect to the mask crossing bracketed by [low, high].

    Bisection rather than a faster root finder on purpose: the bracket is guaranteed by a sign
    change, bisection cannot leave it, and 10 s down to 1 microsecond is only about 24
    evaluations. A secant-family method could step outside the bracket near a tangent pass,
    which is precisely the case this fixture is built to exercise.
    """
    f_low = curve(low) - mask
    while high - low > CROSSING_TOLERANCE_S:
        middle = 0.5 * (low + high)
        f_middle = curve(middle) - mask
        if (f_low > 0.0) == (f_middle > 0.0):
            low, f_low = middle, f_middle
        else:
            high = middle
    return 0.5 * (low + high)


def _locate_peak(curve: _ElevationCurve, low: float, high: float) -> tuple[float, float]:
    """Golden-section search for the maximum elevation on [low, high].

    Elevation over a single pass is unimodal, so golden section is safe. When the true peak
    lies outside a clipped interval the function is monotonic there and the search converges
    to the correct endpoint, which is exactly the clipped-pass reading the contract specifies
    in section 8.2.
    """
    invphi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = low, high
    c = b - invphi * (b - a)
    d = a + invphi * (b - a)
    f_c, f_d = curve(c), curve(d)
    while b - a > PEAK_TOLERANCE_S:
        if f_c > f_d:
            b, d, f_d = d, c, f_c
            c = b - invphi * (b - a)
            f_c = curve(c)
        else:
            a, c, f_c = c, d, f_d
            d = a + invphi * (b - a)
            f_d = curve(d)
    # The interval endpoints are candidates too: a clipped pass peaks at its boundary.
    best = max((low, curve(low)), (high, curve(high)), (c, f_c), (d, f_d), key=lambda p: p[1])
    return best


def _as_datetime(moment_s: float) -> datetime:
    """Quantise to whole microseconds, half-even, exactly once, on the way out.

    ADR-0001's numerical contract: float precision is kept inside the adapter and the canonical
    result is quantised only at the boundary. `round` on a Python float is half-even, matching
    `time_quantization_revision = UTC_US_HALF_EVEN_V1`.
    """
    microseconds = round(moment_s * 1_000_000.0)
    return _UNIX_EPOCH + timedelta(microseconds=microseconds)


def _stable_key(fixture_id: str, station_key: str, aos: datetime) -> str:
    """Contract section 9: derived only from fixed inputs, so it is stable across machines."""
    return f"ORB-{fixture_id}-{station_key}-{aos.strftime('%Y%m%dT%H%M%S%f')}"


def find_passes(
    position_source: Callable[[float], tuple[float, float, float]],
    sites: tuple[StationSite, ...],
    window_start: datetime,
    window_end: datetime,
    fixture_id: str,
) -> tuple[PassEvent, ...]:
    """Every contact in `[window_start, window_end)`, clipped and ordered per the contract.

    A station with no contact contributes no rows; the caller is responsible for recording
    that station as an explicit zero-contact result rather than omitting it (section 8.6).
    """
    start_s = (window_start - _UNIX_EPOCH).total_seconds()
    end_s = (window_end - _UNIX_EPOCH).total_seconds()

    events: list[PassEvent] = []
    for site in sites:
        curve = _ElevationCurve(position_source, site)
        mask = site.minimum_elevation_deg
        events.extend(_passes_for_site(curve, site, mask, start_s, end_s, fixture_id))

    # Contract section 9. Sorting by the same key the synthetic provider uses means swapping
    # providers cannot reorder a result.
    events.sort(key=lambda e: (e.aos, e.los, e.station_key, e.stable_key))
    return tuple(events)


def _passes_for_site(
    curve: _ElevationCurve,
    site: StationSite,
    mask: float,
    start_s: float,
    end_s: float,
    fixture_id: str,
) -> list[PassEvent]:
    events: list[PassEvent] = []
    above_at_start = curve(start_s) > mask
    # A pass already in progress when the window opens is clipped, not discarded.
    open_aos: float | None = start_s if above_at_start else None
    open_clipped_start = above_at_start

    previous_t = start_s
    previous_f = curve(start_s) - mask
    t = start_s + BRACKET_STEP_S
    while previous_t < end_s:
        t = min(t, end_s)
        f = curve(t) - mask
        if previous_f <= 0.0 < f:
            open_aos = _refine_crossing(curve, mask, previous_t, t)
            open_clipped_start = False
        elif previous_f > 0.0 >= f and open_aos is not None:
            los = _refine_crossing(curve, mask, previous_t, t)
            events.append(_build(curve, site, open_aos, los, open_clipped_start, False, fixture_id))
            open_aos = None
            open_clipped_start = False
        if t >= end_s:
            break
        previous_t, previous_f = t, f
        t += BRACKET_STEP_S

    # Still above the mask when the window closes: clip at the boundary rather than drop it.
    if open_aos is not None:
        events.append(_build(curve, site, open_aos, end_s, open_clipped_start, True, fixture_id))
    return events


def _build(
    curve: _ElevationCurve,
    site: StationSite,
    aos_s: float,
    los_s: float,
    clipped_start: bool,
    clipped_end: bool,
    fixture_id: str,
) -> PassEvent:
    peak_t, peak_value = _locate_peak(curve, aos_s, los_s)
    aos = _as_datetime(aos_s)
    los = _as_datetime(los_s)
    return PassEvent(
        station_key=site.station_key,
        stable_key=_stable_key(fixture_id, site.station_key, aos),
        aos=aos,
        los=los,
        duration_s=los_s - aos_s,
        maximum_elevation_deg=peak_value,
        maximum_elevation_time=_as_datetime(peak_t),
        clipped_start=clipped_start,
        clipped_end=clipped_end,
    )

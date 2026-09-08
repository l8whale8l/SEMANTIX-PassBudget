"""The ``ORBIT_DERIVED`` contact provider.

This adapts the verified pass-finder (`passes.py`, cross-checked against NASA GMAT under
the frozen orbit-verification setup) to the `ContactProvider` port. It is the only
production path that turns an orbit assumption and station geometry into contact windows.

Design rules it obeys:

- It is a *second* implementation of the existing port, never a mode of the synthetic provider.
- No module in `domain/` or `application/` imports it or the engine it wraps; the composition
  root selects it for ``contact_source = ORBIT_DERIVED`` and nothing else.
- No fallback. If the engine cannot propagate, the run fails with a structured error rather than
  quietly returning synthetic-looking contacts.
- Floating point stays inside the engine; every value handed back to the domain is an exact
  integer in a canonical micro-unit, quantised once at this boundary.
- The same frozen snapshot always yields the same contacts and the same hashes: nothing here reads
  the clock, the environment, the filesystem or the network.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from semantix_passbudget.domain.enums import OrbitKind
from semantix_passbudget.domain.errors import DomainValidationError, ErrorDetail
from semantix_passbudget.domain.models import ScenarioSnapshot, SyntheticContact
from semantix_passbudget.domain.time import TimeInterval, UtcInstant

from .passes import (
    OrbitPropagationError,
    PassEvent,
    StationSite,
    find_passes,
    sgp4_position_source,
    two_body_position_source,
)
from .twobody import circular_state_from_elements

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: The pass-finder revision. Bump when the bracket/solve/ordering behaviour changes meaning.
PROVIDER_REVISION = "ORB-PASS-01"
#: Event solver: 10 s bracket, bisection to 1e-6 s, golden-section peak. Mirrors `passes.py`.
EVENT_SOLVER_REVISION = "BRACKET_10S_BISECT_1E6_GOLDEN_PEAK_V1"

_MANIFEST_BY_KIND: dict[OrbitKind, dict[str, str]] = {
    OrbitKind.GP_TLE: {
        "orbit_provider_revision": PROVIDER_REVISION,
        "constants_revision": "SGP4_VALLADO_REV2_WGS72_STATION_WGS84_V1",
        "frame_transform_revision": "TEME_GMST82_TO_ITRF_V1",
        "event_solver_revision": EVENT_SOLVER_REVISION,
    },
    OrbitKind.TWO_BODY_V1: {
        "orbit_provider_revision": PROVIDER_REVISION,
        "constants_revision": "TWO_BODY_V1_MU_LITERAL_STATION_WGS84_V1",
        "frame_transform_revision": "EME2000_IAU76_80_GAST_TO_ITRF_V1",
        "event_solver_revision": EVENT_SOLVER_REVISION,
    },
}


def _instant(moment: datetime) -> UtcInstant:
    """Exact microseconds since the Unix epoch. The engine already quantised to whole µs."""
    delta = moment.astimezone(UTC) - _EPOCH
    return UtcInstant((delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds)


def _sites(snapshot: ScenarioSnapshot) -> tuple[StationSite, ...]:
    sites: list[StationSite] = []
    for station in snapshot.stations:
        site = station.site
        assert site is not None  # guaranteed by ScenarioSnapshot.validate for ORBIT_DERIVED
        sites.append(
            StationSite(
                station_key=station.stable_key,
                latitude_deg=site.latitude_udeg / 1_000_000,
                longitude_east_deg=site.longitude_east_udeg / 1_000_000,
                ellipsoidal_height_m=site.ellipsoidal_height_mm / 1_000,
                minimum_elevation_deg=site.minimum_elevation_udeg / 1_000_000,
            )
        )
    return tuple(sites)


def _position_source(snapshot: ScenarioSnapshot):  # type: ignore[no-untyped-def]
    orbit = snapshot.orbit
    assert orbit is not None  # guaranteed by ScenarioSnapshot.validate for ORBIT_DERIVED
    if orbit.kind is OrbitKind.GP_TLE:
        assert orbit.tle is not None
        return sgp4_position_source(orbit.tle.line_1, orbit.tle.line_2)
    two_body = orbit.two_body
    assert two_body is not None
    mu = float(two_body.mu_m3_per_s2)
    position, velocity = circular_state_from_elements(
        semi_major_axis_m=two_body.semi_major_axis_mm / 1_000,
        inclination_deg=two_body.inclination_udeg / 1_000_000,
        raan_deg=two_body.raan_udeg / 1_000_000,
        argument_of_perigee_deg=two_body.argument_of_perigee_udeg / 1_000_000,
        true_anomaly_deg=two_body.true_anomaly_udeg / 1_000_000,
        eccentricity=two_body.eccentricity_ppb / 1_000_000_000,
        mu=mu,
    )
    epoch_s = (two_body.epoch.microseconds) / 1_000_000
    return two_body_position_source(epoch_s, position, velocity, mu)


def _to_contact(event: PassEvent) -> SyntheticContact:
    return SyntheticContact(
        stable_key=event.stable_key,
        station_key=event.station_key,
        true_interval=TimeInterval(_instant(event.aos), _instant(event.los)),
        maximum_elevation_udeg=round(event.maximum_elevation_deg * 1_000_000),
        maximum_elevation_time=_instant(event.maximum_elevation_time),
        clipped_start=event.clipped_start,
        clipped_end=event.clipped_end,
    )


class OrbitContactProvider:
    """Generates ``ORBIT_DERIVED`` contact windows from an orbit assumption and station geometry."""

    provider_revision = PROVIDER_REVISION

    def contacts_for(self, snapshot: ScenarioSnapshot) -> tuple[SyntheticContact, ...]:
        window_start = datetime.fromisoformat(
            snapshot.analysis_window.start.isoformat().replace("Z", "+00:00")
        )
        window_end = datetime.fromisoformat(
            snapshot.analysis_window.end.isoformat().replace("Z", "+00:00")
        )
        try:
            events = find_passes(
                _position_source(snapshot),
                _sites(snapshot),
                window_start,
                window_end,
                snapshot.fixture_id,
            )
        except OrbitPropagationError as exc:
            # No fallback to synthetic contacts: a failed propagation is a failed run, and the
            # error carries the library's numeric code only, never a host path.
            raise DomainValidationError(
                ErrorDetail(
                    code="ORBIT_PROPAGATION_FAILED",
                    message=f"The orbit engine could not propagate this orbit (code {exc.code}).",
                    scope="contact",
                    field_paths=("orbit",),
                    affected_branches=("contact", "capacity", "schedule"),
                )
            ) from exc
        return tuple(_to_contact(event) for event in events)

    def manifest_overrides(self, snapshot: ScenarioSnapshot) -> Mapping[str, str]:
        orbit = snapshot.orbit
        assert orbit is not None
        return dict(_MANIFEST_BY_KIND[orbit.kind])

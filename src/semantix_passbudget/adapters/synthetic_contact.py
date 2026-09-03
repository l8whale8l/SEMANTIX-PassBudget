from collections.abc import Mapping

from semantix_passbudget.domain.models import ScenarioSnapshot, SyntheticContact


class SyntheticContactProvider:
    """Literal test/demo input; it makes no accuracy claim about any propagated trajectory."""

    provider_revision = "SYN-CONTACT-01"

    def contacts_for(self, snapshot: ScenarioSnapshot) -> tuple[SyntheticContact, ...]:
        return tuple(
            sorted(
                snapshot.contacts,
                key=lambda item: (
                    item.true_interval.start,
                    item.true_interval.end,
                    item.station_key,
                    item.stable_key,
                ),
            )
        )

    def manifest_overrides(self, snapshot: ScenarioSnapshot) -> Mapping[str, str]:
        """No propagator ran, so the base manifest's placeholders stand unchanged."""
        return {}

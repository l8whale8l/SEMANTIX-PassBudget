from semantix_passbudget.domain.models import ScenarioSnapshot, SyntheticContact


class SyntheticContactProvider:
    """Literal test/demo input; it makes no orbit-accuracy claim."""

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

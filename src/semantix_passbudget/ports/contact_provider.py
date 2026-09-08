from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from semantix_passbudget.domain.models import ScenarioSnapshot, SyntheticContact


class ContactProvider(Protocol):
    provider_revision: str

    def contacts_for(self, snapshot: ScenarioSnapshot) -> tuple[SyntheticContact, ...]: ...

    def manifest_overrides(self, snapshot: ScenarioSnapshot) -> Mapping[str, str]:
        """Engine-manifest revisions this provider owns, overlaid on the base manifest.

        A provider that computes contacts from a propagator reports its real propagator, frame and
        event-solver revisions here; a provider that injects contacts directly returns an empty
        mapping, so the base ``NOT_APPLICABLE`` placeholders stand and its result hash is unchanged.
        """
        ...

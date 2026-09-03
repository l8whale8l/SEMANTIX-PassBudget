from __future__ import annotations

from typing import Protocol

from semantix_passbudget.domain.models import ScenarioSnapshot, SyntheticContact


class ContactProvider(Protocol):
    provider_revision: str

    def contacts_for(self, snapshot: ScenarioSnapshot) -> tuple[SyntheticContact, ...]: ...

from semantix_passbudget.ports.run_repository import StoredRun


class InMemoryRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, StoredRun] = {}

    def add(self, run: StoredRun) -> None:
        if run.run_id in self._runs:
            raise ValueError("run IDs are immutable and may not be overwritten")
        self._runs[run.run_id] = run

    def get(self, run_id: str) -> StoredRun | None:
        return self._runs.get(run_id)

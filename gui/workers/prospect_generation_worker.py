"""Sequential worker for prospect generation queues."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from gui.services.prospect_generation import ProspectGenerationService


class ProspectGenerationWorker(QObject):
    progress = Signal(str, str)  # job_id, status
    finished = Signal(object)  # list[ProspectGenerationJob]
    failed = Signal(str)

    def __init__(self, service: ProspectGenerationService, job_ids: list[str]) -> None:
        super().__init__()
        self._service = service
        self._job_ids = list(job_ids)

    def run(self) -> None:
        results = []
        try:
            for job_id in self._job_ids:
                self.progress.emit(job_id, "RUNNING")
                job = self._service.run_job(job_id)
                self.progress.emit(job_id, job.status)
                results.append(job)
            self.finished.emit(results)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
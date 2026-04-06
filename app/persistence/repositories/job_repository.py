from sqlalchemy.orm import Session

from app.persistence.models.background_job import BackgroundJob
from app.persistence.models.background_job import claimable_jobs


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, job_id):
        return self.session.get(BackgroundJob, job_id)

    def add(self, job: BackgroundJob) -> BackgroundJob:
        self.session.add(job)
        self.session.flush()
        return job

    def claim_next_batch(self, batch_size: int = 10) -> list[BackgroundJob]:
        return claimable_jobs(self.session, batch_size)

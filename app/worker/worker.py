from app.persistence.repositories.job_repository import JobRepository


class Worker:
    def __init__(self, job_repository: JobRepository) -> None:
        self.job_repository = job_repository

    def run_once(self, batch_size: int = 10):
        return self.job_repository.claim_next_batch(batch_size=batch_size)

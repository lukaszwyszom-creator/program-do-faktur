from sqlalchemy.orm import Session


class IdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

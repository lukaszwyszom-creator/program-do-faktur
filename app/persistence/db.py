from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def create_db_engine() -> Engine:
	kwargs: dict = {
		"echo": settings.database_echo,
		"future": True,
		"pool_pre_ping": True,
	}
	if not settings.database_url.startswith("sqlite"):
		kwargs["pool_size"] = settings.database_pool_size
		kwargs["max_overflow"] = settings.database_max_overflow
	return create_engine(settings.database_url, **kwargs)


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
	session = SessionLocal()
	try:
		yield session
	finally:
		session.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
	session = SessionLocal()
	try:
		yield session
		session.commit()
	except Exception:
		session.rollback()
		raise
	finally:
		session.close()


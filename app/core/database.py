import logging
import time
from collections.abc import Generator

import psycopg2
from psycopg2 import OperationalError as PsycopgOperationalError
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _connect_psycopg2_with_retry():
    """Abre conexión a Postgres con reintentos (útil con RDS remoto desde local)."""
    last_error: Exception | None = None
    retries = max(settings.db_connect_retries, 1)
    delay = settings.db_connect_retry_delay_seconds
    timeout = settings.db_connect_timeout

    for attempt in range(1, retries + 1):
        try:
            return psycopg2.connect(
                settings.database_url,
                connect_timeout=timeout,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=5,
            )
        except PsycopgOperationalError as exc:
            last_error = exc
            if attempt >= retries:
                logger.error("DB connection failed after %s attempts: %s", retries, exc)
                raise
            logger.warning(
                "DB connection attempt %s/%s failed (%s). Retrying in %ss...",
                attempt,
                retries,
                exc,
                delay,
            )
            time.sleep(delay)

    assert last_error is not None
    raise last_error


engine = create_engine(
    "postgresql+psycopg2://",
    creator=_connect_psycopg2_with_retry,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=300,
    pool_timeout=settings.db_pool_timeout,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

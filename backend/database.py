import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DATABASE_URL = os.environ.get(
    "FRAMEFLEET_DATABASE_URL",
    "postgresql+psycopg://framefleet:framefleet@database:5432/framefleet",
)


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_database_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
